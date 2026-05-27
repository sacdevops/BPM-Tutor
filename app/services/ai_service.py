import logging
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests

import config
from lib.bpmn.validator import BPMNValidator
from app.services.prompts import get_system_prompt as _get_sys_prompt
from app.services import task_tracker
from lib.lion import loads as lion_loads, dumps as lion_dumps, strip_markdown_fences

logger = logging.getLogger('bpmtutor.ai')


def _load_agent_prompt(prompt_type: str, lang: str) -> str | None:
    """Load a prompt from the default DB agent. Returns None if unavailable."""
    try:
        from app.models.agent import AIAgent
        agent = AIAgent.get_default()
        if agent:
            return agent.get_prompt(prompt_type, lang)
    except Exception:
        pass
    return None


class AIServiceError(Exception):
    """Structured error with type for user-facing messages."""
    def __init__(self, message: str, error_type: str = 'unknown'):
        super().__init__(message)
        self.error_type = error_type


class AIService:

    _BPMN_NS = {
        'bpmn': 'http://www.omg.org/spec/BPMN/20100524/MODEL',
        'bpmndi': 'http://www.omg.org/spec/BPMN/20100524/DI',
        'dc': 'http://www.omg.org/spec/DD/20100524/DC',
        'di': 'http://www.omg.org/spec/DD/20100524/DI',
    }
    _TASK_TAGS = frozenset({
        'task', 'userTask', 'serviceTask', 'sendTask', 'receiveTask',
        'manualTask', 'businessRuleTask', 'scriptTask',
    })
    _EVENT_TAGS = frozenset({
        'startEvent', 'endEvent', 'intermediateCatchEvent',
        'intermediateThrowEvent', 'boundaryEvent',
    })
    _GATEWAY_TAGS = frozenset({
        'exclusiveGateway', 'parallelGateway', 'inclusiveGateway',
        'eventBasedGateway', 'complexGateway',
    })
    _EVENT_DEF_TAGS = frozenset({
        'messageEventDefinition', 'timerEventDefinition', 'signalEventDefinition',
        'errorEventDefinition', 'conditionalEventDefinition', 'terminateEventDefinition',
        'escalationEventDefinition', 'compensateEventDefinition',
    })
    _BPMN_NS_TAG = '{http://www.omg.org/spec/BPMN/20100524/MODEL}'

    _LION_SCALAR_KEY_RE = re.compile(
        r'^(\s*)(message|phase|title|details|shortDesc|longDesc)\s*:\s*(.+)$'
    )
    _LION_KEY_DELIMITER_RE = re.compile(
        r'^\s*(?:message|phase|issues|complete|'
        r'title|details|shortDesc|longDesc|elementId|severity|category)\s*[:(]'
    )

    @classmethod
    def _chat_completion(cls, api_key: str, model: str, messages: list,
                         base_url: str = '') -> dict:
        """Call the chat completions endpoint (OpenAI-compatible)."""
        effective_base = (base_url.rstrip('/') if base_url else None) or config.CAMPUS_KI_BASE_URL.rstrip('/')
        url = f"{effective_base}/v1/chat/completions"
        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
        }
        payload = {
            'model': model,
            'messages': messages,
            'stream': False,
        }
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=300, stream=False)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.Timeout:
            raise AIServiceError(
                'Request timed out. The AI service may be overloaded.',
                error_type='timeout',
            )
        except requests.exceptions.ChunkedEncodingError:
            raise AIServiceError(
                'The AI service closed the connection before sending a complete response. '
                'Please try again.',
                error_type='connection',
            )
        except requests.exceptions.ConnectionError:
            raise AIServiceError(
                'Cannot connect to the AI service. Please check your internet connection.',
                error_type='connection',
            )
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else 500
            if status in (401, 403):
                raise AIServiceError(
                    'Invalid or expired API key. Please check your settings.',
                    error_type='auth',
                )
            if status in (429,):
                raise AIServiceError(
                    'Rate limit exceeded. Please wait a moment and try again.',
                    error_type='rate_limit',
                )
            if status in (500, 502, 503, 504):
                raise AIServiceError(
                    'The AI service is temporarily unavailable. Please try again later.',
                    error_type='service_down',
                )
            raise AIServiceError(
                f'API error (HTTP {status}).',
                error_type='api_error',
            )

    def __init__(self, task_id: str = 'unknown', session_id: str = '',
                 api_key: str = '', model: str = '', lang: str = 'en',
                 tracker_key: str = '', base_url: str = '',
                 agent_id: str = ''):
        self.api_key = api_key
        self.model = model
        self.lang = lang
        self.task_id = task_id
        self.session_id = session_id
        self.tracker_key = tracker_key or task_id
        self.base_url = base_url
        self._agent = None
        self._agent_id = agent_id

    def _get_agent(self):
        """Lazily load the agent for this session (by id, or default)."""
        if self._agent is not None:
            return self._agent
        try:
            from app.models.agent import AIAgent
            if self._agent_id:
                self._agent = AIAgent.query.get(self._agent_id)
            if not self._agent:
                self._agent = AIAgent.get_default()
        except Exception:
            pass
        return self._agent

    def _get_prompt(self, prompt_type: str) -> str:
        """Return the prompt string for prompt_type (greeting/analysis/reaction) from the session agent."""
        from app.services.prompts import get_prompt_with_standards as _resolve
        agent = self._get_agent()
        if agent:
            p = agent.get_prompt(prompt_type, self.lang)
            if p:
                return _resolve(p, self.lang)
        # Built-in system-agent prompt — already resolved at import time, but
        # re-resolve at runtime so DB-overridden bpmn_standards are respected.
        base = _get_sys_prompt(agent.agent_type if agent else 'mentor', prompt_type, self.lang)
        if base:
            return _resolve(base, self.lang)
        return _resolve(_get_sys_prompt('mentor', prompt_type, self.lang) or '', self.lang)

    def _log_llm_io(self, label: str, messages: list, response_content: str):
        if not getattr(config, 'LOG_LLM_IO', False):
            return

        log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'llm_logs')
        os.makedirs(log_dir, exist_ok=True)

        sid = f'_{self.session_id}' if self.session_id else ''
        log_file = os.path.join(log_dir, f'{self.task_id}_mentor{sid}.md')

        interaction_num = 1
        if os.path.exists(log_file):
            with open(log_file, 'r', encoding='utf-8') as f:
                interaction_num = sum(1 for line in f if '## Interaction ' in line) + 1

        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        with open(log_file, 'a', encoding='utf-8') as f:
            if interaction_num == 1:
                f.write(f'# LLM Log: {self.task_id}\n')
                f.write(f'- **AI Type:** Mentor\n')
                f.write(f'- **Model:** {self.model}\n')
                f.write(f'- **Started:** {timestamp}\n\n')
                f.write(f'---\n\n')

            f.write(f'## Interaction {interaction_num} -- {label}\n')
            f.write(f'**Time:** {timestamp}\n\n')

            f.write(f'### Input\n\n')
            for msg in messages:
                role = msg.get('role', 'unknown').upper()
                content = msg.get('content', '')
                f.write(f'**[{role}]**\n```\n{content}\n```\n\n')

            f.write(f'### Output\n\n')
            f.write(f'```\n{response_content}\n```\n\n')
            f.write(f'---\n\n')

    def _parse_issues(self, raw_issues: List[Any]) -> List[Dict[str, Any]]:
        """Convert raw issues into normalized issue dicts, keeping only the highest-severity issue per element."""
        _SEVERITY_RANK = {'syntax': 0, 'semantic': 1, 'info': 2}
        all_issues = []
        for item in raw_issues:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                issue = {
                    'elementId': str(item[0]),
                    'severity': str(item[1]) if len(item) > 1 else 'info',
                    'category': str(item[2]) if len(item) > 2 else 'general',
                    'shortDesc': str(item[3]) if len(item) > 3 else 'Issue detected',
                    'longDesc': str(item[4]) if len(item) > 4 else 'No details available',
                }
            elif isinstance(item, dict):
                issue = item
            else:
                continue

            if 'elementId' not in issue:
                continue

            severity = issue.get('severity', 'info')
            # Map old severity names to new ones
            severity_map = {
                'critical': 'syntax',
                'warning': 'semantic',
                'major': 'semantic',
                'minor': 'info',
            }
            severity = severity_map.get(severity, severity)
            if severity not in ('syntax', 'semantic', 'info'):
                severity = 'info'

            all_issues.append({
                'elementId': issue.get('elementId', ''),
                'severity': severity,
                'category': issue.get('category', 'general'),
                'shortDesc': issue.get('shortDesc', issue.get('message', 'Issue detected')),
                'longDesc': issue.get('longDesc', issue.get('message', 'No details available')),
            })

        # Deduplicate: keep only highest-severity issue per element
        best: Dict[str, Dict[str, Any]] = {}
        for iss in all_issues:
            eid = iss['elementId']
            if eid not in best or _SEVERITY_RANK.get(iss['severity'], 9) < _SEVERITY_RANK.get(best[eid]['severity'], 9):
                best[eid] = iss
        return list(best.values())

    def _bpmn_xml_to_lion(self, xml: str) -> Dict[str, Any]:
        if not xml:
            return {}

        try:
            root = ET.fromstring(xml)
            ns = self._BPMN_NS

            bounds_map: Dict[str, Dict[str, int]] = {}
            for shape in root.findall('.//bpmndi:BPMNShape', ns):
                bpmn_elem = shape.get('bpmnElement', '')
                bounds = shape.find('dc:Bounds', ns)
                if bpmn_elem and bounds is not None:
                    bounds_map[bpmn_elem] = {
                        'x': int(float(bounds.get('x', '0'))),
                        'y': int(float(bounds.get('y', '0'))),
                        'width': int(float(bounds.get('width', '0'))),
                        'height': int(float(bounds.get('height', '0')))
                    }

            proc_to_participant: Dict[str, str] = {}

            model: Dict[str, Any] = {
                'pools': [],
                'lanes': [],
                'tasks': [],
                'events': [],
                'gateways': [],
                'flows': []
            }

            pool_expanded_map: Dict[str, bool] = {}
            for shape in root.findall('.//bpmndi:BPMNShape', ns):
                shape_elem = shape.get('bpmnElement', '')
                is_exp_attr = shape.get('isExpanded', None)
                if is_exp_attr is not None:
                    pool_expanded_map[shape_elem] = is_exp_attr.lower() != 'false'

            expanded_processes: set = set()
            for proc in root.findall('.//bpmn:process', ns):
                for child in proc:
                    tag = child.tag.replace(self._BPMN_NS_TAG, '')
                    if tag not in ('documentation', 'laneSet', 'extensionElements'):
                        expanded_processes.add(proc.get('id', ''))
                        break

            for participant in root.findall('.//bpmn:participant', ns):
                p_id = participant.get('id', '')
                p_name = participant.get('name', '')
                process_ref = participant.get('processRef', '')
                if process_ref:
                    proc_to_participant[process_ref] = p_id
                b = bounds_map.get(p_id, {})

                if p_id in pool_expanded_map:
                    is_expanded = pool_expanded_map[p_id]
                elif process_ref and process_ref in expanded_processes:
                    is_expanded = True
                else:
                    is_expanded = False
                model['pools'].append({
                    'id': p_id,
                    'name': p_name,
                    'expanded': is_expanded,
                    'x': b.get('x', 0),
                    'y': b.get('y', 0),
                    'width': b.get('width', 0),
                    'height': b.get('height', 0)
                })

            for process in root.findall('.//bpmn:process', ns):
                process_id = process.get('id', '')
                pool_id = proc_to_participant.get(process_id, '')

                lane_members: Dict[str, str] = {}
                for lane_set in process.findall('bpmn:laneSet', ns):
                    for lane in lane_set.findall('.//bpmn:lane', ns):
                        lane_id = lane.get('id', '')
                        lane_name = lane.get('name', '')
                        b = bounds_map.get(lane_id, {})
                        model['lanes'].append({
                            'id': lane_id,
                            'name': lane_name,
                            'pool_id': pool_id,
                            'x': b.get('x', 0),
                            'y': b.get('y', 0),
                            'width': b.get('width', 0),
                            'height': b.get('height', 0)
                        })
                        for ref in lane.findall('bpmn:flowNodeRef', ns):
                            if ref.text:
                                lane_members[ref.text.strip()] = lane_id

                for elem in process:
                    tag = elem.tag.replace(self._BPMN_NS_TAG, '')
                    elem_id = elem.get('id', '')
                    elem_name = elem.get('name', '')
                    b = bounds_map.get(elem_id, {})
                    parent_id = lane_members.get(elem_id, pool_id)

                    if tag == 'sequenceFlow':
                        model['flows'].append({
                            'id': elem_id,
                            'source': elem.get('sourceRef', ''),
                            'target': elem.get('targetRef', ''),
                            'type': 'sequenceFlow',
                            'name': elem.get('name', '')
                        })

                    elif tag in self._TASK_TAGS:
                        model['tasks'].append({
                            'id': elem_id,
                            'name': elem_name,
                            'type': tag,
                            'parent': parent_id,
                            'x': b.get('x', 0),
                            'y': b.get('y', 0),
                            'width': b.get('width', 100),
                            'height': b.get('height', 80)
                        })

                    elif tag in self._EVENT_TAGS:
                        event_def = ''
                        for child in elem:
                            child_tag = child.tag.replace(self._BPMN_NS_TAG, '')
                            if child_tag in self._EVENT_DEF_TAGS:
                                event_def = child_tag
                                break
                        model['events'].append({
                            'type': tag,
                            'id': elem_id,
                            'name': elem_name,
                            'parent': parent_id,
                            'eventDefinition': event_def,
                            'x': b.get('x', 0),
                            'y': b.get('y', 0),
                            'width': b.get('width', 36),
                            'height': b.get('height', 36)
                        })

                    elif tag in self._GATEWAY_TAGS:
                        model['gateways'].append({
                            'id': elem_id,
                            'name': elem_name,
                            'type': tag,
                            'parent': parent_id,
                            'x': b.get('x', 0),
                            'y': b.get('y', 0),
                            'width': b.get('width', 50),
                            'height': b.get('height', 50)
                        })

            for mf in root.findall('.//bpmn:messageFlow', ns):
                model['flows'].append({
                    'id': mf.get('id', ''),
                    'source': mf.get('sourceRef', ''),
                    'target': mf.get('targetRef', ''),
                    'type': 'messageFlow',
                    'name': mf.get('name', '')
                })

            return model

        except ET.ParseError as e:
            logger.warning("[BPMN Parser] XML Parse Error: %s", e)
            return {}

    def _format_memory(self, messages: List[Dict[str, str]]) -> List[str]:
        """Extract text messages for memory."""
        SKIP_SIGNALS = {'[INITIAL_GREETING]'}
        memory = []
        for msg in messages:
            content = msg.get('content', '')
            if content.strip() in SKIP_SIGNALS:
                continue
            if content.strip():
                memory.append(content)
        return memory

    def _build_context(
        self,
        task: str,
        user_input: Optional[str],
        instruction: str,
        memory: List[Dict[str, str]],
        bpmn_model: Dict[str, Any],
        validation_results: str = '',
        previous_issues: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        context = {
            'task': task,
            'instruction': instruction,
            'user_input': user_input or '',
            'memory': self._format_memory(memory) if memory else [],
            'bpmn_model': bpmn_model or {
                'pools': [], 'lanes': [], 'tasks': [],
                'events': [], 'gateways': [], 'flows': [],
            },
        }
        if previous_issues:
            context['previous_issues'] = [
                {
                    'elementId': iss.get('elementId', ''),
                    'severity': iss.get('severity', ''),
                    'shortDesc': iss.get('shortDesc', ''),
                }
                for iss in previous_issues
            ]
        lion_str = lion_dumps(context, pretty=True)
        if validation_results:
            lion_str += '\n\n' + validation_results
        return lion_str

    def _handle_mentor_response(self, content: str) -> Dict[str, Any]:
        """Parse Mentor response -- phase, message, optional issues and bpmn_ops."""
        parsed = self._parse_lion(content)

        if not parsed or 'phase' not in parsed:
            logger.warning("[Mentor] Response not in expected LION format")

            fallback_message = ''
            quoted = re.search(r'message\s*:\s*"((?:[^"\\]|\\.)*)"', content, re.DOTALL)
            if quoted:
                fallback_message = quoted.group(1).replace('\\n', '\n').replace('\\"', '"')
            else:
                unquoted = re.search(r'message\s*:\s*([^\n,}{\[\]]+)', content)
                if unquoted:
                    fallback_message = unquoted.group(1).strip()
            if not fallback_message:
                fallback_message = content if isinstance(content, str) else str(content)
            return {
                'message': fallback_message,
                'phase': 'FEEDBACK',
                'issues': [],
                'bpmn_ops': [],
                'complete': False,
            }

        message = parsed.get('message', '')
        if not isinstance(message, str):
            message = str(message) if message is not None else ''

        phase = parsed.get('phase', 'FEEDBACK')
        if isinstance(phase, str):
            phase = phase.upper()

        issues = []
        if phase == 'ANALYSIS' or parsed.get('issues'):
            raw_issues = parsed.get('issues', [])
            if isinstance(raw_issues, list):
                issues = self._parse_issues(raw_issues)

        # Parse AI-generated BPMN operations (for modeling agents)
        bpmn_ops = []
        raw_ops = parsed.get('bpmn_ops', [])
        if isinstance(raw_ops, list):
            for op in raw_ops:
                if isinstance(op, (list, tuple)) and len(op) >= 2:
                    # LION parametric form: bpmn_ops(op, type, id, x, y, name): [...]
                    bpmn_ops.append({
                        'op': str(op[0]) if len(op) > 0 else 'create',
                        'type': str(op[1]) if len(op) > 1 else 'task',
                        'id': str(op[2]) if len(op) > 2 else '',
                        'x': int(op[3]) if len(op) > 3 else 200,
                        'y': int(op[4]) if len(op) > 4 else 200,
                        'name': str(op[5]) if len(op) > 5 else '',
                        'source': str(op[6]) if len(op) > 6 else '',
                        'target': str(op[7]) if len(op) > 7 else '',
                    })
                elif isinstance(op, dict):
                    bpmn_ops.append(op)

        is_complete = parsed.get('complete', False)

        logger.debug("[Mentor] Phase=%s issues=%d bpmn_ops=%d complete=%s",
                     phase, len(issues), len(bpmn_ops), is_complete)

        return {
            'message': message,
            'phase': phase,
            'issues': issues,
            'bpmn_ops': bpmn_ops,
            'complete': is_complete,
        }

    def get_mentor_response(
        self,
        task_description: str,
        instruction: str,
        memory: List[Dict[str, str]],
        current_bpmn_state: Optional[str] = None,
        user_message: Optional[str] = None,
        phase_hint: str = 'REACTION',
        previous_issues: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Call the AI agent for analysis or conversation."""
        bpmn_model = {}
        validation_text = ''
        if current_bpmn_state:
            bpmn_model = self._bpmn_xml_to_lion(current_bpmn_state)
            try:
                validator = BPMNValidator()
                validator.validate(current_bpmn_state)
                validation_text = validator.format_for_prompt(self.lang)
            except Exception as e:
                logger.warning('[Validator] Error: %s', e)

        # Determine modeling_mode from the session agent
        modeling_mode = 'none'
        agent = self._get_agent()
        if agent:
            modeling_mode = getattr(agent, 'modeling_mode', 'none') or 'none'

        # Augment instruction with modeling capability notice
        effective_instruction = instruction
        if modeling_mode != 'none':
            _modeling_hint_de = (
                '\n\nDu hast die Berechtigung, das BPMN-Diagramm zu modellieren. '
                'Wenn du Elemente erstellen, verschieben, verbinden oder löschen möchtest, '
                'füge ein Feld "bpmn_ops" in deine LION-Antwort ein.\n'
                'Unterstützte Operationen:\n'
                '  participate (Pool): {op: participate, type: Participant, x: 100, y: 50, width: 800, height: 200, name: "Lieferant", id: PoolLieferant}\n'
                '  draw (Element in Pool): {op: draw, type: UserTask, x: 300, y: 130, name: "Bestellung prüfen", id: Task1, parentId: PoolLieferant, connectTo: [Start1]}\n'
                '  connect: {op: connect, source: Task1, target: EndEvent1}\n'
                '  delete: {op: delete, id: Element1}\n'
                '  rename: {op: rename, id: Element1, name: "Neuer Name"}\n'
                '  move: {op: move, id: Element1, x: 400, y: 300}\n'
                '  resize: {op: resize, id: Pool1, width: 1000, height: 250}\n'
                'Hinweis: connectTo in draw erstellt automatisch SequenceFlows. '
                'eventDefinition nur bei Events: MessageEventDefinition, TimerEventDefinition, SignalEventDefinition.'
            )
            _modeling_hint_en = (
                '\n\nYou have permission to modify the BPMN diagram. '
                'When you want to create, move, connect, or delete elements, '
                'include a "bpmn_ops" field in your LION response.\n'
                'Supported operations:\n'
                '  participate (Pool): {op: participate, type: Participant, x: 100, y: 50, width: 800, height: 200, name: "Vendor", id: PoolVendor}\n'
                '  draw (Element in Pool): {op: draw, type: UserTask, x: 300, y: 130, name: "Review order", id: Task1, parentId: PoolVendor, connectTo: [Start1]}\n'
                '  connect: {op: connect, source: Task1, target: EndEvent1}\n'
                '  delete: {op: delete, id: Element1}\n'
                '  rename: {op: rename, id: Element1, name: "New name"}\n'
                '  move: {op: move, id: Element1, x: 400, y: 300}\n'
                '  resize: {op: resize, id: Pool1, width: 1000, height: 250}\n'
                'Note: connectTo in draw automatically creates SequenceFlows. '
                'eventDefinition only for events: MessageEventDefinition, TimerEventDefinition, SignalEventDefinition.'
            )
            effective_instruction += (_modeling_hint_de if self.lang == 'de' else _modeling_hint_en)

        lion_context = self._build_context(
            task=task_description,
            user_input=user_message or '',
            instruction=effective_instruction,
            memory=memory,
            bpmn_model=bpmn_model,
            validation_results=validation_text,
            previous_issues=previous_issues or [],
        )

        system_prompt = self._get_prompt('analysis' if phase_hint == 'ANALYSIS' else 'reaction')
        api_messages = [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': lion_context},
        ]

        _RETRY_HINT = (
            'Your previous response could not be parsed as valid LION. '
            'Please respond again, strictly following the LION format. '
            'The response must include the "phase" and "message" fields at the top level.'
        )

        content = None
        for attempt in range(2):
            try:
                result = self._chat_completion(self.api_key, self.model, api_messages,
                                                base_url=self.base_url)
                content = result['choices'][0]['message']['content']
                usage = result.get('usage')
                if usage:
                    task_tracker.record_llm_call(
                        self.tracker_key,
                        usage.get('prompt_tokens', 0),
                        usage.get('completion_tokens', 0),
                    )
                self._log_llm_io('mentor_response', api_messages, content)

                parsed = self._parse_lion(content)
                if parsed is not None and ('phase' in parsed or 'issues' in parsed):
                    break

                if attempt == 0:
                    logger.debug("[Mentor] Invalid LION on attempt 1, retrying")
                    api_messages = api_messages + [
                        {'role': 'assistant', 'content': content},
                        {'role': 'user', 'content': _RETRY_HINT},
                    ]

            except AIServiceError:
                raise
            except Exception as e:
                logger.error("[Mentor] API Error: %s", e)
                return {
                    'message': f"Mentor error: {e}",
                    'phase': 'FEEDBACK',
                    'issues': [],
                    'complete': False,
                    'error': str(e),
                }

        return self._handle_mentor_response(content)

    @staticmethod
    def _preprocess_lion(text: str) -> str:
        """Auto-quote unquoted string values for known scalar LION keys."""
        scalar_re = AIService._LION_SCALAR_KEY_RE
        delim_re  = AIService._LION_KEY_DELIMITER_RE
        close_re  = re.compile(r'^\s*[}\]]\s*,?\s*$')
        num_re    = re.compile(r'^-?\d')

        lines  = text.split('\n')
        result = []
        i = 0
        while i < len(lines):
            line = lines[i]
            m = scalar_re.match(line)
            if m:
                indent, key, first = m.group(1), m.group(2), m.group(3).rstrip()
                stripped = first.strip()

                if (
                    stripped.startswith('"') or
                    stripped.startswith('{') or
                    stripped.startswith('[') or
                    stripped in ('true', 'false', 'null') or
                    num_re.match(stripped)
                ):
                    result.append(line)
                    i += 1
                    continue

                parts = [stripped]
                i += 1
                while i < len(lines):
                    nxt = lines[i]
                    if delim_re.match(nxt) or close_re.match(nxt):
                        break
                    parts.append(nxt.strip())
                    i += 1
                combined = ' '.join(p for p in parts if p)
                combined = combined.rstrip(',')
                combined = combined.replace('\\', '\\\\').replace('"', '\\"')
                result.append(f'{indent}{key}: "{combined}"')
            else:
                result.append(line)
                i += 1
        return '\n'.join(result)

    def _parse_lion(self, content: str) -> Optional[Dict[str, Any]]:
        content = strip_markdown_fences(content)
        content = self._preprocess_lion(content)
        try:
            return lion_loads(content)
        except Exception as e:
            logger.warning("[LION Parser] Error: %s", e)
            logger.debug("[LION Parser] Raw LLM response: %s", content)
            return None

    def generate_greeting(self, task_description: str) -> Dict[str, Any]:
        """Generate initial greeting adapted to the active agent type."""
        agent = self._get_agent()
        agent_type = getattr(agent, 'agent_type', 'mentor') if agent else 'mentor'
        system_prompt = self._get_prompt('greeting')

        if self.lang == 'de':
            if agent_type == 'colleague':
                greeting_prompt = f"""Du bist der BPMN-Kollege und startest eine gemeinsame Modellierungssitzung.

Aufgabe:
{task_description}

Analysiere die Aufgabenstellung und schreibe eine kollegiale Begrüßungsnachricht, die:
1. Dich kurz als gleichberechtigten Partner vorstellt
2. Die Pools/Bereiche der Aufgabe konkret identifiziert (z. B. Kunde, Verwaltung, Lieferant)
3. Einen fairen Aufgabenteilungsvorschlag macht -- du übernimmst etwa die Hälfte
   (berücksichtige Komplexität; Blackbox-Pools zählen weniger)
4. Den Studierenden um Zustimmung oder Gegenvorschlag bittet

Verwende Markdown (**fett**, Listen). Sei kollegial und partnerschaftlich.
Gib nur den Nachrichtentext aus -- kein JSON, keine LION-Schlüssel."""
            elif agent_type == 'supervisor':
                greeting_prompt = f"""Du bist der BPMN-Supervisor und beginnst eine neue Bewertungssitzung.

Aufgabe:
{task_description}

Schreibe eine professionelle Begrüßungsnachricht (3-4 Sätze), die:
1. Dich als Supervisor vorstellt
2. Erklärt, dass du die Qualität der Modellierung überwachst
3. Erklärt, dass der Studierende deine Kriterien erfüllen muss, um die Aufgabe abzuschließen
4. Den Studierenden auffordert, mit der Modellierung zu beginnen

Verwende Markdown. Sei professionell und klar.
Gib nur den Nachrichtentext aus -- kein JSON, keine LION-Schlüssel."""
            elif agent_type == 'assistant':
                greeting_prompt = f"""Du bist der BPMN-Assistent und beginnst eine neue Modellierungssitzung.

Aufgabe:
{task_description}

Schreibe eine freundliche Begrüßungsnachricht (2-3 Sätze), die:
1. Dich als hilfreichen Assistenten vorstellt
2. Erklärt, dass du bei Fragen und Problemen zur Verfügung stehst
3. Den Studierenden ermutigt, selbstständig mit der Modellierung zu beginnen

Verwende Markdown. Sei freundlich und zugänglich.
Gib nur den Nachrichtentext aus -- kein JSON, keine LION-Schlüssel."""
            else:  # mentor, delegant, or custom
                greeting_prompt = f"""Ein Studierender beginnt gleich mit einer BPMN-Modellierungsaufgabe.

Aufgabe: {task_description}

Schreibe eine kurze Begrüßung (2-3 Sätze), die:
1. Dich kurz als BPMN-Begleiter vorstellt
2. Den Studierenden ermutigt, mit der Modellierung zu beginnen
3. Ihn daran erinnert, dass er jederzeit um Hilfe bitten kann

Verwende Markdown. Sei knapp. Antworte auf Deutsch."""
        else:
            if agent_type == 'colleague':
                greeting_prompt = f"""You are the BPMN Colleague starting a joint modeling session.

Task:
{task_description}

Analyze the task and write a collegial greeting that:
1. Briefly introduces yourself as an equal partner
2. Concretely identifies the pools/areas in the task (e.g., Customer, Administration, Vendor)
3. Makes a fair split proposal -- you take about half
   (consider complexity; blackbox pools count less)
4. Asks the student to agree or suggest an alternative

Use Markdown (**bold**, lists). Be collegial and equal.
Output only the message text -- no JSON, no LION keys."""
            elif agent_type == 'supervisor':
                greeting_prompt = f"""You are the BPMN Supervisor starting a new evaluation session.

Task:
{task_description}

Write a professional greeting (3-4 sentences) that:
1. Introduces yourself as the Supervisor
2. Explains you will monitor the quality of the modeling
3. States the student must meet your criteria before completing the task
4. Invites the student to start modeling

Use Markdown. Be professional and clear.
Output only the message text -- no JSON, no LION keys."""
            elif agent_type == 'assistant':
                greeting_prompt = f"""You are the BPMN Assistant starting a new modeling session.

Task:
{task_description}

Write a friendly greeting (2-3 sentences) that:
1. Introduces yourself as a helpful Assistant
2. Explains you are available for questions and problems
3. Encourages the student to start modeling independently

Use Markdown. Be friendly and approachable.
Output only the message text -- no JSON, no LION keys."""
            else:  # mentor, delegant, or custom
                greeting_prompt = f"""A student is about to start a BPMN modeling task.

Task: {task_description}

Write a very short greeting (2-3 sentences) that:
1. Introduces yourself as the BPMN guide
2. Encourages the student to start modeling
3. Reminds them they can ask for help anytime

Use Markdown. Be concise."""

        try:
            result = self._chat_completion(
                self.api_key,
                self.model,
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": greeting_prompt}
                ],
                base_url=self.base_url,
            )
            content = result['choices'][0]['message']['content'].strip()
            usage = result.get('usage')
            if usage:
                task_tracker.record_llm_call(
                    self.tracker_key,
                    usage.get('prompt_tokens', 0),
                    usage.get('completion_tokens', 0),
                )
            self._log_llm_io('mentor_greeting', [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": greeting_prompt}
            ], content)

            parsed = self._parse_lion(content)
            if isinstance(parsed, dict) and isinstance(parsed.get('message'), str):
                content = parsed['message']

            return {'message': content}

        except Exception as e:
            logger.error("[Mentor] Greeting error: %s", e)
            if self.lang == 'de':
                return {
                    'message': "Hallo! Ich bin dein BPMN-Mentor. Beginne mit der Modellierung deines Prozesses und frag mich jederzeit um Hilfe!"
                }
            return {
                'message': "Hello! I'm your BPMN Mentor. Start modeling your process, and feel free to ask me for help anytime!"
            }

    # ── AI auto-grading ───────────────────────────────────────────────────────

    def generate_grade_suggestion(
        self,
        task_description: str,
        bpmn_xml: str,
        grading_type: str = 'pass_fail',
        max_points: float = 100,
    ) -> dict:
        """Ask the LLM to evaluate a student BPMN submission.

        Returns a dict with:
          grade_value (float|None), grade_passed (bool|None),
          comment (str), annotations (list[dict])
        """
        prompt_lines = [
            "Du bist ein Experte für BPMN-Prozessmodellierung und bewertest eine Studentenabgabe.",
            "",
            f"Aufgabenstellung: {task_description}",
            "",
            "BPMN-XML der Abgabe:",
            bpmn_xml[:6000] if bpmn_xml else "(kein Modell vorhanden)",
            "",
        ]
        if grading_type == 'points':
            prompt_lines += [
                f"Bewertungsskala: 0 – {max_points} Punkte.",
                "Gib im JSON-Format zurück: "
                '{"grade_value": <float>, "grade_passed": <bool>, '
                '"comment": "<ausführliche Begründung>", '
                '"annotations": [{"element_id": "<id>", "comment": "<text>", "type": "error|warning|ok"}]}',
            ]
        else:
            prompt_lines += [
                "Bewertungsskala: bestanden / nicht bestanden.",
                "Gib im JSON-Format zurück: "
                '{"grade_value": null, "grade_passed": <bool>, '
                '"comment": "<ausführliche Begründung>", '
                '"annotations": [{"element_id": "<id>", "comment": "<text>", "type": "error|warning|ok"}]}',
            ]
        prompt_lines += [
            "",
            "Antworte NUR mit dem JSON-Objekt, kein Markdown, kein Text davor/danach.",
        ]

        prompt = "\n".join(prompt_lines)
        messages = [{"role": "user", "content": prompt}]
        try:
            resp = self._chat_completion(self.api_key, self.model, messages, self.base_url)
            raw = resp.get('choices', [{}])[0].get('message', {}).get('content', '{}')
            # Strip markdown fences if present
            raw = strip_markdown_fences(raw)
            import json as _json
            data = _json.loads(raw)
            return {
                'grade_value': data.get('grade_value'),
                'grade_passed': data.get('grade_passed'),
                'comment': data.get('comment', ''),
                'annotations': data.get('annotations', []),
            }
        except Exception as exc:
            logger.error("[AIService] generate_grade_suggestion failed: %s", exc)
            return {
                'grade_value': None,
                'grade_passed': None,
                'comment': f'KI-Bewertung fehlgeschlagen: {exc}',
                'annotations': [],
            }

