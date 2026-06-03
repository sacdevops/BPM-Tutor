import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests

import config
from lib.bpmn.validator import BPMNValidator
from app.services.prompts import get_prompt_with_standards as _resolve_prompt
from app.services import task_tracker
from lib.lion import dumps as lion_dumps, strip_markdown_fences
from app.services.bpmn_parser import BPMNParser
from app.services.lion_parser import LIONParser

logger = logging.getLogger('bpmtutor.ai')


class AIServiceError(Exception):
    """Structured error with type for user-facing messages."""
    def __init__(self, message: str, error_type: str = 'unknown'):
        super().__init__(message)
        self.error_type = error_type


# Module-level requests.Session: reuses TCP connections across all AI calls,
# avoiding per-request TLS handshake overhead.
_http_session: Optional[requests.Session] = None


def _get_http_session() -> requests.Session:
    global _http_session
    if _http_session is None:
        _http_session = requests.Session()
        _http_session.headers.update({'Content-Type': 'application/json'})
    return _http_session


class AIService:

    # Delegate BPMN/LION parsing to dedicated submodules
    _bpmn_parser: BPMNParser = BPMNParser()

    @classmethod
    def _chat_completion(cls, api_key: str, model: str, messages: List[Dict[str, Any]],
                         base_url: str = '') -> Dict[str, Any]:
        """Call the chat completions endpoint (OpenAI-compatible).

        Uses a module-level requests.Session to reuse TCP connections.
        """
        effective_base = (base_url.rstrip('/') if base_url else None) or config.CAMPUS_KI_BASE_URL.rstrip('/')
        url = f"{effective_base}/v1/chat/completions"
        payload: Dict[str, Any] = {
            'model': model,
            'messages': messages,
            'stream': False,
        }
        sess = _get_http_session()
        try:
            resp = sess.post(
                url,
                json=payload,
                headers={'Authorization': f'Bearer {api_key}'},
                timeout=300,
                stream=False,
            )
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
        except requests.exceptions.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else 500
            if status in (401, 403):
                raise AIServiceError(
                    'Invalid or expired API key. Please check your settings.',
                    error_type='auth',
                )
            if status == 429:
                raise AIServiceError(
                    'Rate limit exceeded. Please wait a moment and try again.',
                    error_type='rate_limit',
                )
            if status in (500, 502, 503, 504):
                raise AIServiceError(
                    'The AI service is temporarily unavailable. Please try again later.',
                    error_type='service_down',
                )
            raise AIServiceError(f'API error (HTTP {status}).', error_type='api_error')

    def __init__(self, task_id: str = 'unknown', session_id: str = '',
                 api_key: str = '', model: str = '', lang: str = 'en',
                 tracker_key: str = '', base_url: str = '',
                 agent_id: str = '', sub_id=None):
        self.api_key = api_key
        self.model = model
        self.lang = lang
        self.task_id = task_id
        self.session_id = session_id
        self.tracker_key = tracker_key or task_id
        self.base_url = base_url
        self._agent = None
        self._agent_id = agent_id
        self.sub_id = sub_id

    def _get_agent(self):
        """Lazily load the agent for this session (by id, or default)."""
        if self._agent is not None:
            return self._agent
        try:
            from app.models.agent import AIAgent
            from app.extensions import db
            if self._agent_id:
                self._agent = db.session.get(AIAgent, self._agent_id)
            if not self._agent:
                self._agent = AIAgent.get_default()
        except Exception:
            pass
        return self._agent

    def _get_prompt(self, prompt_type: str) -> str:
        """Return the resolved prompt string for prompt_type from the session agent (DB only)."""
        agent = self._get_agent()
        if agent:
            p = agent.get_prompt(prompt_type, self.lang)
            if p:
                return _resolve_prompt(p, self.lang)
        return ''

    def _get_simple_prompt(self, prompt_type: str) -> str:
        """Read a raw interaction prompt from the agent's DB config without BPMN standards injection."""
        agent = self._get_agent()
        if agent:
            return agent.get_prompt(prompt_type, self.lang) or ''
        return ''

    def _log_llm_io(self, label: str, messages: list, response_content: str):
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # Always persist to submission llm_prompt_log if we have a sub_id
        if self.sub_id:
            try:
                import json as _json
                from app.extensions import db
                from app.models.task import TaskSubmission
                sub = db.session.get(TaskSubmission, self.sub_id)
                if sub:
                    existing = []
                    if sub.llm_prompt_log:
                        try:
                            existing = _json.loads(sub.llm_prompt_log)
                        except Exception:
                            pass
                    existing.append({
                        'ts': timestamp,
                        'label': label,
                        'messages': messages,
                        'response': response_content,
                    })
                    sub.llm_prompt_log = _json.dumps(existing, ensure_ascii=False)
                    db.session.commit()
            except Exception as _exc:
                logger.warning('[AIService] llm_prompt_log persist error: %s', _exc)

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
        return LIONParser.parse_issues(raw_issues)

    def _bpmn_xml_to_lion(self, xml: str) -> Dict[str, Any]:
        return self._bpmn_parser.parse(xml)

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

    def _build_chat_history(self, memory: List[Dict[str, str]]) -> str:
        """Return only the conversation history — previous user messages + assistant LION responses.

        This is the content injected by the {lion_context} placeholder.
        Contains no task description, no BPMN model, no validation — only the raw exchange.
        """
        SKIP_SIGNALS = {'[INITIAL_GREETING]'}
        parts = []
        for msg in memory:
            role = msg.get('role', '')
            content = msg.get('content', '').strip()
            if not content or content in SKIP_SIGNALS:
                continue
            label = 'Student' if role == 'user' else 'Assistant'
            parts.append(f'[{label}]\n{content}')
        return '\n\n'.join(parts)

    def _handle_mentor_response(self, content: str) -> Dict[str, Any]:
        return LIONParser.handle_mentor_response(content)

    @staticmethod
    def _preprocess_lion(text: str) -> str:
        return LIONParser.preprocess(text)

    def _parse_lion(self, content: str) -> Optional[Dict[str, Any]]:
        return LIONParser.parse(content)

    def get_mentor_response(
        self,
        task_description: str,
        memory: List[Dict[str, str]],
        current_bpmn_state: Optional[str] = None,
        user_message: Optional[str] = None,
        phase_hint: str = 'REACTION',
        previous_issues: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Call the AI agent for analysis or conversation.

        The system prompt and user prompt are sent exactly as configured by the admin.
        Placeholder substitution only happens when the placeholder is explicitly present
        in the configured prompt template.
        """
        # Parse BPMN to LION representation — used by {bpmn_lion} placeholder
        bpmn_model = {}
        if current_bpmn_state:
            bpmn_model = self._bpmn_xml_to_lion(current_bpmn_state)

        # Apply memory window from agent configuration
        effective_memory = memory
        _mem_agent = self._get_agent()
        if _mem_agent:
            mem_enabled = getattr(_mem_agent, 'memory_enabled', True)
            if mem_enabled is None:
                mem_enabled = True
            if not mem_enabled:
                effective_memory = []
            else:
                mem_window = getattr(_mem_agent, 'memory_window', 10) or 10
                if mem_window > 0 and len(memory) > mem_window:
                    effective_memory = memory[-mem_window:]

        # Build user message — substitute placeholders ONLY when explicitly present
        user_prompt_type = 'analysis_user' if phase_hint == 'ANALYSIS' else 'reaction_user'
        user_prompt = self._get_simple_prompt(user_prompt_type)
        if user_prompt:
            if '{user_message}' in user_prompt:
                user_prompt = user_prompt.replace('{user_message}', user_message or '')
            if '{bpmn_lion}' in user_prompt:
                bpmn_lion_str = lion_dumps(bpmn_model, pretty=True) if bpmn_model else '(no model)'
                user_prompt = user_prompt.replace('{bpmn_lion}', bpmn_lion_str)
            if '{task_description}' in user_prompt:
                user_prompt = user_prompt.replace('{task_description}', task_description or '')
            if '{lion_context}' in user_prompt:
                user_prompt = user_prompt.replace('{lion_context}', self._build_chat_history(effective_memory))
        else:
            # No template configured — fall back to the raw user message
            user_prompt = user_message or ''

        system_prompt = self._get_prompt('analysis' if phase_hint == 'ANALYSIS' else 'reaction')
        api_messages = [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': user_prompt},
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
                print(content)
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

    def generate_greeting(self, task_description: str) -> Dict[str, Any]:
        """Generate initial greeting adapted to the active agent type."""
        system_prompt = self._get_prompt('greeting')

        # Load the greeting user-message template from DB (supports {task_description} placeholder)
        template = self._get_simple_prompt('greeting_user')
        if template:
            greeting_prompt = template.replace('{task_description}', task_description)
        else:
            # Minimal fallback when no template is configured
            greeting_prompt = task_description

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

        except AIServiceError:
            raise
        except Exception as e:
            logger.error("[Mentor] Greeting error: %s", e)
            return {'message': ''}

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
        template = self._get_simple_prompt('grading')
        if not template:
            logger.error('[AIService] No grading prompt configured for agent.')
            return {
                'grade_value': None,
                'grade_passed': None,
                'comment': 'Grading prompt not configured.',
                'annotations': [],
            }

        if grading_type == 'points':
            grading_scale = (
                f'Grading scale: 0 – {max_points} points.\n'
                'Return as JSON: {"grade_value": <float>, "grade_passed": <bool>, '
                '"comment": "<detailed reasoning>", '
                '"annotations": [{"element_id": "<id>", "comment": "<text>", "type": "error|warning|ok"}]}'
            ) if self.lang != 'de' else (
                f'Bewertungsskala: 0 – {max_points} Punkte.\n'
                'Gib als JSON zurück: {"grade_value": <float>, "grade_passed": <bool>, '
                '"comment": "<ausführliche Begründung>", '
                '"annotations": [{"element_id": "<id>", "comment": "<text>", "type": "error|warning|ok"}]}'
            )
        else:
            grading_scale = (
                'Grading scale: pass / fail.\n'
                'Return as JSON: {"grade_value": null, "grade_passed": <bool>, '
                '"comment": "<detailed reasoning>", '
                '"annotations": [{"element_id": "<id>", "comment": "<text>", "type": "error|warning|ok"}]}'
            ) if self.lang != 'de' else (
                'Bewertungsskala: bestanden / nicht bestanden.\n'
                'Gib als JSON zurück: {"grade_value": null, "grade_passed": <bool>, '
                '"comment": "<ausführliche Begründung>", '
                '"annotations": [{"element_id": "<id>", "comment": "<text>", "type": "error|warning|ok"}]}'
            )

        bpmn_lion_str = lion_dumps(self._bpmn_xml_to_lion(bpmn_xml), pretty=True) if bpmn_xml else '(no model provided)'
        prompt = (
            template
            .replace('{task_description}', task_description)
            .replace('{bpmn_lion}', bpmn_lion_str)
            .replace('{grading_scale}', grading_scale)
        )
        messages = [{'role': 'user', 'content': prompt}]
        try:
            import json as _json
            resp = self._chat_completion(self.api_key, self.model, messages, self.base_url)
            raw = resp.get('choices', [{}])[0].get('message', {}).get('content', '{}')
            raw = strip_markdown_fences(raw)
            data = _json.loads(raw)
            return {
                'grade_value': data.get('grade_value'),
                'grade_passed': data.get('grade_passed'),
                'comment': data.get('comment', ''),
                'annotations': data.get('annotations', []),
            }
        except Exception as exc:
            logger.error('[AIService] generate_grade_suggestion failed: %s', exc)
            return {
                'grade_value': None,
                'grade_passed': None,
                'comment': str(exc),
                'annotations': [],
            }

