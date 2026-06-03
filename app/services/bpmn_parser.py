"""BPMN XML → LION-compatible dict parser.

Extracted from AIService to keep ai_service.py focused on LLM orchestration.
"""
from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from typing import Any, Dict

logger = logging.getLogger('bpmtutor.bpmn_parser')


class BPMNParser:
    """Converts a BPMN 2.0 XML document into the LION-compatible model dict
    used by the AI context builder."""

    _BPMN_NS: Dict[str, str] = {
        'bpmn': 'http://www.omg.org/spec/BPMN/20100524/MODEL',
        'bpmndi': 'http://www.omg.org/spec/BPMN/20100524/DI',
        'dc': 'http://www.omg.org/spec/DD/20100524/DC',
        'di': 'http://www.omg.org/spec/DD/20100524/DI',
    }
    _BPMN_NS_TAG = '{http://www.omg.org/spec/BPMN/20100524/MODEL}'

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

    def parse(self, xml: str) -> Dict[str, Any]:
        """Parse a BPMN XML string and return a LION-compatible model dict.

        Returns an empty dict when *xml* is falsy or cannot be parsed.
        """
        if not xml:
            return {}

        try:
            return self._parse(xml)
        except ET.ParseError as exc:
            logger.warning('[BPMNParser] XML parse error: %s', exc)
            return {}

    def _parse(self, xml: str) -> Dict[str, Any]:
        root = ET.fromstring(xml)
        ns = self._BPMN_NS
        ns_tag = self._BPMN_NS_TAG

        # ── Build bounds map ──────────────────────────────────────────────────
        bounds_map: Dict[str, Dict[str, int]] = {}
        for shape in root.findall('.//bpmndi:BPMNShape', ns):
            bpmn_elem = shape.get('bpmnElement', '')
            bounds = shape.find('dc:Bounds', ns)
            if bpmn_elem and bounds is not None:
                bounds_map[bpmn_elem] = {
                    'x': int(float(bounds.get('x', '0'))),
                    'y': int(float(bounds.get('y', '0'))),
                    'width': int(float(bounds.get('width', '0'))),
                    'height': int(float(bounds.get('height', '0'))),
                }

        proc_to_participant: Dict[str, str] = {}
        model: Dict[str, Any] = {
            'pools': [], 'lanes': [], 'tasks': [],
            'events': [], 'gateways': [], 'flows': [],
        }

        # ── Expanded pool detection ───────────────────────────────────────────
        pool_expanded_map: Dict[str, bool] = {}
        for shape in root.findall('.//bpmndi:BPMNShape', ns):
            shape_elem = shape.get('bpmnElement', '')
            is_exp_attr = shape.get('isExpanded', None)
            if is_exp_attr is not None:
                pool_expanded_map[shape_elem] = is_exp_attr.lower() != 'false'

        expanded_processes: set = set()
        for proc in root.findall('.//bpmn:process', ns):
            for child in proc:
                tag = child.tag.replace(ns_tag, '')
                if tag not in ('documentation', 'laneSet', 'extensionElements'):
                    expanded_processes.add(proc.get('id', ''))
                    break

        # ── Participants / Pools ──────────────────────────────────────────────
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
                'height': b.get('height', 0),
            })

        # ── Processes: lanes + flow nodes ─────────────────────────────────────
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
                        'height': b.get('height', 0),
                    })
                    for ref in lane.findall('bpmn:flowNodeRef', ns):
                        if ref.text:
                            lane_members[ref.text.strip()] = lane_id

            for elem in process:
                tag = elem.tag.replace(ns_tag, '')
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
                        'name': elem.get('name', ''),
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
                        'height': b.get('height', 80),
                    })
                elif tag in self._EVENT_TAGS:
                    event_def = ''
                    for child in elem:
                        child_tag = child.tag.replace(ns_tag, '')
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
                        'height': b.get('height', 36),
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
                        'height': b.get('height', 50),
                    })

        # ── Message flows ─────────────────────────────────────────────────────
        for mf in root.findall('.//bpmn:messageFlow', ns):
            model['flows'].append({
                'id': mf.get('id', ''),
                'source': mf.get('sourceRef', ''),
                'target': mf.get('targetRef', ''),
                'type': 'messageFlow',
                'name': mf.get('name', ''),
            })

        return model
