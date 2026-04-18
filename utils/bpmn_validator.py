"""Validates BPMN XML models for correctness and completeness."""
from typing import Dict, List, Any, Optional, Tuple, Set
from dataclasses import dataclass
from enum import Enum
import xml.etree.ElementTree as ET


class Severity(Enum):
    CRITICAL = "critical"
    MAJOR = "major"
    MINOR = "minor"


@dataclass
class ValidationIssue:
    element_id: str
    element_type: str
    severity: Severity
    message: str
    category: str
    suggestion: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "elementId": self.element_id,
            "elementType": self.element_type,
            "severity": self.severity.value,
            "message": self.message,
            "category": self.category,
            "suggestion": self.suggestion
        }


class BPMNValidator:

    BPMN_NS = {
        'bpmn': 'http://www.omg.org/spec/BPMN/20100524/MODEL',
        'bpmndi': 'http://www.omg.org/spec/BPMN/20100524/DI',
        'dc': 'http://www.omg.org/spec/DD/20100524/DC',
        'di': 'http://www.omg.org/spec/DD/20100524/DI'
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
    _FLOW_NODE_TAGS = _TASK_TAGS | _EVENT_TAGS | _GATEWAY_TAGS

    def __init__(self):
        self.issues: List[ValidationIssue] = []
        self.elements: Dict[str, ET.Element] = {}
        self.element_tags: Dict[str, str] = {}
        self.flows: Dict[str, Tuple[str, str]] = {}
        self.incoming: Dict[str, List[str]] = {}
        self.outgoing: Dict[str, List[str]] = {}
        self.process_elements: Dict[str, Set[str]] = {}
        self.element_process: Dict[str, str] = {}
        self.participant_process: Dict[str, str] = {}
        self.process_participant: Dict[str, str] = {}
        self.lane_members: Dict[str, str] = {}

    def validate(self, bpmn_xml: str) -> List[ValidationIssue]:
        """Validate a BPMN XML string and return found issues."""
        self.issues = []
        self.elements = {}
        self.element_tags = {}
        self.flows = {}
        self.incoming = {}
        self.outgoing = {}
        self.process_elements = {}
        self.element_process = {}
        self.participant_process = {}
        self.process_participant = {}
        self.lane_members = {}

        if not bpmn_xml or not bpmn_xml.strip():
            return self.issues

        try:
            root = ET.fromstring(bpmn_xml)
        except ET.ParseError as e:
            self.issues.append(ValidationIssue(
                element_id="document",
                element_type="XML",
                severity=Severity.CRITICAL,
                message=f"XML parsing error: {str(e)}",
                category="syntax"
            ))
            return self.issues

        self._index_elements(root)

        self._validate_pools(root)
        self._validate_lanes(root)
        self._validate_events(root)
        self._validate_gateways(root)
        self._validate_tasks(root)
        self._validate_sequence_flows(root)
        self._validate_message_flows(root)
        self._validate_reachability(root)

        return self.issues

    def _index_elements(self, root: ET.Element):
        """Build element index and flow maps."""
        for participant in root.findall('.//bpmn:participant', self.BPMN_NS):
            pid = participant.get('id', '')
            proc_ref = participant.get('processRef', '')
            if pid:
                self.elements[pid] = participant
                self.element_tags[pid] = 'participant'
            if proc_ref:
                self.participant_process[pid] = proc_ref
                self.process_participant[proc_ref] = pid

        for process in root.findall('.//bpmn:process', self.BPMN_NS):
            proc_id = process.get('id', '')
            if not proc_id:
                continue
            self.process_elements[proc_id] = set()

            for lane_set in process.findall('bpmn:laneSet', self.BPMN_NS):
                for lane in lane_set.findall('.//bpmn:lane', self.BPMN_NS):
                    lane_id = lane.get('id', '')
                    if lane_id:
                        self.elements[lane_id] = lane
                        self.element_tags[lane_id] = 'lane'
                    for ref in lane.findall('bpmn:flowNodeRef', self.BPMN_NS):
                        if ref.text:
                            self.lane_members[ref.text.strip()] = lane_id

            for elem in process:
                tag = elem.tag.replace(self._BPMN_NS_TAG, '')
                elem_id = elem.get('id', '')
                if not elem_id:
                    continue

                self.elements[elem_id] = elem
                self.element_tags[elem_id] = tag
                self.process_elements[proc_id].add(elem_id)
                self.element_process[elem_id] = proc_id

                if tag == 'sequenceFlow':
                    source = elem.get('sourceRef', '')
                    target = elem.get('targetRef', '')
                    self.flows[elem_id] = (source, target)
                    self.outgoing.setdefault(source, []).append(elem_id)
                    self.incoming.setdefault(target, []).append(elem_id)

        for elem in root.iter():
            elem_id = elem.get('id')
            if elem_id and elem_id not in self.elements:
                self.elements[elem_id] = elem
                tag = elem.tag.replace(self._BPMN_NS_TAG, '')
                self.element_tags[elem_id] = tag

    def _is_expanded_pool(self, root: ET.Element, participant_id: str) -> bool:
        """Check if a pool is expanded (has a process with flow nodes)."""
        proc_ref = self.participant_process.get(participant_id, '')
        if not proc_ref:
            return False

        for shape in root.findall('.//bpmndi:BPMNShape', self.BPMN_NS):
            if shape.get('bpmnElement') == participant_id:
                is_exp = shape.get('isExpanded', None)
                if is_exp is not None:
                    return is_exp.lower() != 'false'

        elements = self.process_elements.get(proc_ref, set())
        for eid in elements:
            tag = self.element_tags.get(eid, '')
            if tag in self._FLOW_NODE_TAGS:
                return True
        return False

    def _validate_pools(self, root: ET.Element):
        participants = root.findall('.//bpmn:participant', self.BPMN_NS)

        for participant in participants:
            pid = participant.get('id', 'unknown')
            name = participant.get('name', '')
            process_ref = participant.get('processRef', '')

            if not name:
                self.issues.append(ValidationIssue(
                    element_id=pid,
                    element_type="Participant",
                    severity=Severity.MINOR,
                    message="Pool has no name/label",
                    category="naming",
                    suggestion="Add a descriptive name to the pool"
                ))

            is_expanded = self._is_expanded_pool(root, pid)

            if is_expanded and process_ref:
                process = root.find(f".//bpmn:process[@id='{process_ref}']", self.BPMN_NS)
                if process is not None:
                    start_events = process.findall('.//bpmn:startEvent', self.BPMN_NS)
                    end_events = process.findall('.//bpmn:endEvent', self.BPMN_NS)

                    if not start_events:
                        self.issues.append(ValidationIssue(
                            element_id=pid,
                            element_type="Participant",
                            severity=Severity.CRITICAL,
                            message=f"Expanded pool '{name or pid}' has no Start Event",
                            category="structure",
                            suggestion="Every expanded pool must have exactly one Start Event"
                        ))
                    elif len(start_events) > 1:
                        self.issues.append(ValidationIssue(
                            element_id=pid,
                            element_type="Participant",
                            severity=Severity.MAJOR,
                            message=f"Expanded pool '{name or pid}' has {len(start_events)} Start Events (should have exactly 1)",
                            category="structure",
                            suggestion="An expanded pool should have exactly one Start Event"
                        ))

                    if not end_events:
                        self.issues.append(ValidationIssue(
                            element_id=pid,
                            element_type="Participant",
                            severity=Severity.CRITICAL,
                            message=f"Expanded pool '{name or pid}' has no End Event",
                            category="structure",
                            suggestion="Every expanded pool must have at least one End Event"
                        ))

            elif not is_expanded and process_ref:
                process = root.find(f".//bpmn:process[@id='{process_ref}']", self.BPMN_NS)
                if process is not None:
                    flow_nodes = []
                    for child in process:
                        tag = child.tag.replace(self._BPMN_NS_TAG, '')
                        if tag in self._FLOW_NODE_TAGS:
                            flow_nodes.append(child)
                    if flow_nodes:
                        self.issues.append(ValidationIssue(
                            element_id=pid,
                            element_type="Participant",
                            severity=Severity.CRITICAL,
                            message=f"Collapsed pool '{name or pid}' contains internal elements ({len(flow_nodes)})",
                            category="structure",
                            suggestion="A collapsed (blackbox) pool must not contain any internal elements"
                        ))

    def _validate_lanes(self, root: ET.Element):
        for process in root.findall('.//bpmn:process', self.BPMN_NS):
            proc_id = process.get('id', '')
            for lane_set in process.findall('bpmn:laneSet', self.BPMN_NS):
                lanes = lane_set.findall('.//bpmn:lane', self.BPMN_NS)
                if len(lanes) == 1:
                    pool_id = self.process_participant.get(proc_id, proc_id)
                    pool_name = ''
                    if pool_id in self.elements:
                        pool_name = self.elements[pool_id].get('name', '')
                    self.issues.append(ValidationIssue(
                        element_id=lanes[0].get('id', 'unknown'),
                        element_type="Lane",
                        severity=Severity.MAJOR,
                        message=f"Pool '{pool_name or pool_id}' has only 1 lane (must have 0 or >=2)",
                        category="structure",
                        suggestion="A pool should have either no lanes or at least 2 lanes"
                    ))

                for lane in lanes:
                    lane_id = lane.get('id', 'unknown')
                    lane_name = lane.get('name', '')
                    if not lane_name:
                        self.issues.append(ValidationIssue(
                            element_id=lane_id,
                            element_type="Lane",
                            severity=Severity.MINOR,
                            message="Lane has no name/label",
                            category="naming",
                            suggestion="Add a role or department name to the lane"
                        ))

    def _validate_events(self, root: ET.Element):
        for event in root.findall('.//bpmn:startEvent', self.BPMN_NS):
            eid = event.get('id', 'unknown')

            outgoing = event.findall('bpmn:outgoing', self.BPMN_NS)
            if not outgoing:
                self.issues.append(ValidationIssue(
                    element_id=eid,
                    element_type="StartEvent",
                    severity=Severity.CRITICAL,
                    message="Start Event has no outgoing sequence flow",
                    category="flow",
                    suggestion="Connect the Start Event to the next element"
                ))

            incoming = event.findall('bpmn:incoming', self.BPMN_NS)
            if incoming:
                self.issues.append(ValidationIssue(
                    element_id=eid,
                    element_type="StartEvent",
                    severity=Severity.CRITICAL,
                    message="Start Event must not have incoming sequence flows",
                    category="flow",
                    suggestion="Start Events begin the process — no element should flow into them"
                ))

            name = event.get('name', '')
            if not name:
                self.issues.append(ValidationIssue(
                    element_id=eid,
                    element_type="StartEvent",
                    severity=Severity.MINOR,
                    message="Start Event has no label",
                    category="naming",
                    suggestion="Label it with the trigger state (e.g., 'Order received')"
                ))

        for event in root.findall('.//bpmn:endEvent', self.BPMN_NS):
            eid = event.get('id', 'unknown')

            incoming = event.findall('bpmn:incoming', self.BPMN_NS)
            if not incoming:
                self.issues.append(ValidationIssue(
                    element_id=eid,
                    element_type="EndEvent",
                    severity=Severity.CRITICAL,
                    message="End Event has no incoming sequence flow",
                    category="flow",
                    suggestion="Connect a previous element to this End Event"
                ))

            outgoing = event.findall('bpmn:outgoing', self.BPMN_NS)
            if outgoing:
                self.issues.append(ValidationIssue(
                    element_id=eid,
                    element_type="EndEvent",
                    severity=Severity.CRITICAL,
                    message="End Event must not have outgoing sequence flows",
                    category="flow",
                    suggestion="End Events terminate the process — nothing should follow them"
                ))

            name = event.get('name', '')
            if not name:
                self.issues.append(ValidationIssue(
                    element_id=eid,
                    element_type="EndEvent",
                    severity=Severity.MINOR,
                    message="End Event has no label",
                    category="naming",
                    suggestion="Label it with the end state (e.g., 'Process completed')"
                ))

        for event in root.findall('.//bpmn:intermediateCatchEvent', self.BPMN_NS):
            eid = event.get('id', 'unknown')

            has_definition = any([
                event.find('bpmn:timerEventDefinition', self.BPMN_NS),
                event.find('bpmn:messageEventDefinition', self.BPMN_NS),
                event.find('bpmn:signalEventDefinition', self.BPMN_NS),
                event.find('bpmn:conditionalEventDefinition', self.BPMN_NS)
            ])

            if not has_definition:
                self.issues.append(ValidationIssue(
                    element_id=eid,
                    element_type="IntermediateCatchEvent",
                    severity=Severity.MAJOR,
                    message="Intermediate Catch Event has no event definition",
                    category="specification",
                    suggestion="Add a Timer, Message, Signal, or Conditional event definition"
                ))

            incoming = event.findall('bpmn:incoming', self.BPMN_NS)
            outgoing = event.findall('bpmn:outgoing', self.BPMN_NS)
            if not incoming:
                self.issues.append(ValidationIssue(
                    element_id=eid,
                    element_type="IntermediateCatchEvent",
                    severity=Severity.CRITICAL,
                    message="Intermediate Catch Event has no incoming flow",
                    category="flow",
                    suggestion="Connect a previous element to this event"
                ))
            if not outgoing:
                self.issues.append(ValidationIssue(
                    element_id=eid,
                    element_type="IntermediateCatchEvent",
                    severity=Severity.CRITICAL,
                    message="Intermediate Catch Event has no outgoing flow",
                    category="flow",
                    suggestion="Connect this event to the next element"
                ))

        for event in root.findall('.//bpmn:intermediateThrowEvent', self.BPMN_NS):
            eid = event.get('id', 'unknown')

            has_definition = any([
                event.find('bpmn:messageEventDefinition', self.BPMN_NS),
                event.find('bpmn:signalEventDefinition', self.BPMN_NS),
            ])

            if not has_definition:
                self.issues.append(ValidationIssue(
                    element_id=eid,
                    element_type="IntermediateThrowEvent",
                    severity=Severity.MAJOR,
                    message="Intermediate Throw Event has no event definition",
                    category="specification",
                    suggestion="Add a Message or Signal event definition"
                ))

            incoming = event.findall('bpmn:incoming', self.BPMN_NS)
            outgoing = event.findall('bpmn:outgoing', self.BPMN_NS)
            if not incoming:
                self.issues.append(ValidationIssue(
                    element_id=eid,
                    element_type="IntermediateThrowEvent",
                    severity=Severity.CRITICAL,
                    message="Intermediate Throw Event has no incoming flow",
                    category="flow",
                    suggestion="Connect a previous element to this event"
                ))
            if not outgoing:
                self.issues.append(ValidationIssue(
                    element_id=eid,
                    element_type="IntermediateThrowEvent",
                    severity=Severity.CRITICAL,
                    message="Intermediate Throw Event has no outgoing flow",
                    category="flow",
                    suggestion="Connect this event to the next element"
                ))

    def _validate_gateways(self, root: ET.Element):
        gateway_types = [
            'exclusiveGateway', 'parallelGateway',
            'inclusiveGateway', 'eventBasedGateway'
        ]

        parallel_gateways_by_process: Dict[str, List[Tuple[str, int, int]]] = {}

        for gtype in gateway_types:
            for gateway in root.findall(f'.//bpmn:{gtype}', self.BPMN_NS):
                gid = gateway.get('id', 'unknown')
                name = gateway.get('name', '')

                incoming = gateway.findall('bpmn:incoming', self.BPMN_NS)
                outgoing = gateway.findall('bpmn:outgoing', self.BPMN_NS)

                n_in = len(incoming)
                n_out = len(outgoing)
                total_flows = n_in + n_out

                if total_flows <= 2:
                    self.issues.append(ValidationIssue(
                        element_id=gid,
                        element_type=gtype,
                        severity=Severity.MAJOR,
                        message=f"Gateway has only {total_flows} flows (needs > 2)",
                        category="structure",
                        suggestion="A gateway should split or merge multiple paths"
                    ))

                if not incoming:
                    self.issues.append(ValidationIssue(
                        element_id=gid,
                        element_type=gtype,
                        severity=Severity.CRITICAL,
                        message="Gateway has no incoming sequence flow",
                        category="flow",
                        suggestion="Connect a previous element to this gateway"
                    ))

                if not outgoing:
                    self.issues.append(ValidationIssue(
                        element_id=gid,
                        element_type=gtype,
                        severity=Severity.CRITICAL,
                        message="Gateway has no outgoing sequence flow",
                        category="flow",
                        suggestion="Connect this gateway to the next element(s)"
                    ))

                # Decision gateways need labels when splitting
                if gtype in ('exclusiveGateway', 'inclusiveGateway') and n_out > 1:
                    if not name:
                        self.issues.append(ValidationIssue(
                            element_id=gid,
                            element_type=gtype,
                            severity=Severity.MINOR,
                            message="Decision gateway has no label/question",
                            category="naming",
                            suggestion="Add a decision question ending with '?' (e.g., 'Request approved?')"
                        ))

                    # Check that outgoing flows are labeled
                    for out_ref in outgoing:
                        flow_id = out_ref.text.strip() if out_ref.text else ''
                        if flow_id and flow_id in self.elements:
                            flow_elem = self.elements[flow_id]
                            flow_name = flow_elem.get('name', '')
                            if not flow_name:
                                self.issues.append(ValidationIssue(
                                    element_id=flow_id,
                                    element_type="SequenceFlow",
                                    severity=Severity.MINOR,
                                    message=f"Outgoing flow from decision gateway '{name or gid}' has no label",
                                    category="naming",
                                    suggestion="Label each branch (e.g., 'Yes', 'No')"
                                ))

                # Parallel/EventBased gateways should NOT be labeled
                if gtype in ('parallelGateway', 'eventBasedGateway') and name:
                    self.issues.append(ValidationIssue(
                        element_id=gid,
                        element_type=gtype,
                        severity=Severity.MINOR,
                        message=f"{gtype} should not have a label",
                        category="naming",
                        suggestion="Remove the label — parallel and event-based gateways are unlabeled"
                    ))

                # EventBasedGateway: only IntermediateCatchEvents may follow
                if gtype == 'eventBasedGateway' and n_out > 0:
                    for out_ref in outgoing:
                        flow_id = out_ref.text.strip() if out_ref.text else ''
                        if flow_id and flow_id in self.flows:
                            _, target_id = self.flows[flow_id]
                            target_tag = self.element_tags.get(target_id, '')
                            if target_tag not in ('intermediateCatchEvent', 'receiveTask'):
                                self.issues.append(ValidationIssue(
                                    element_id=gid,
                                    element_type=gtype,
                                    severity=Severity.MAJOR,
                                    message=f"EventBasedGateway has invalid successor '{target_tag}'",
                                    category="structure",
                                    suggestion="Only IntermediateCatchEvents or ReceiveTasks may follow an EventBasedGateway"
                                ))

                # Track parallel gateways for matching check
                if gtype == 'parallelGateway':
                    proc_id = self.element_process.get(gid, '')
                    if proc_id:
                        parallel_gateways_by_process.setdefault(proc_id, []).append(
                            (gid, n_in, n_out)
                        )

        # Check for unmatched parallel gateway splits
        for proc_id, pgateways in parallel_gateways_by_process.items():
            splits = [g for g in pgateways if g[2] > 1]  # outgoing > 1 = split
            joins = [g for g in pgateways if g[1] > 1]   # incoming > 1 = join
            if len(splits) > len(joins):
                for gid, _, n_out in splits:
                    if n_out > 1:
                        self.issues.append(ValidationIssue(
                            element_id=gid,
                            element_type="parallelGateway",
                            severity=Severity.MAJOR,
                            message="Parallel split gateway may be missing a matching join gateway",
                            category="structure",
                            suggestion="Every parallel split should have a corresponding parallel join to synchronize paths"
                        ))

    def _validate_tasks(self, root: ET.Element):
        for ttype in self._TASK_TAGS:
            for task in root.findall(f'.//bpmn:{ttype}', self.BPMN_NS):
                tid = task.get('id', 'unknown')
                name = task.get('name', '')

                if not name:
                    self.issues.append(ValidationIssue(
                        element_id=tid,
                        element_type=ttype,
                        severity=Severity.MAJOR,
                        message="Task has no name/label",
                        category="naming",
                        suggestion="Add a descriptive name (Verb + Noun)"
                    ))

                incoming = task.findall('bpmn:incoming', self.BPMN_NS)
                outgoing = task.findall('bpmn:outgoing', self.BPMN_NS)

                if not incoming:
                    self.issues.append(ValidationIssue(
                        element_id=tid,
                        element_type=ttype,
                        severity=Severity.CRITICAL,
                        message=f"Task '{name or tid}' has no incoming flow",
                        category="flow",
                        suggestion="Connect a previous element to this task"
                    ))

                if not outgoing:
                    self.issues.append(ValidationIssue(
                        element_id=tid,
                        element_type=ttype,
                        severity=Severity.CRITICAL,
                        message=f"Task '{name or tid}' has no outgoing flow",
                        category="flow",
                        suggestion="Connect this task to the next element"
                    ))

                # SendTask / ReceiveTask should have message flows
                if ttype == 'sendTask':
                    has_msg_flow = False
                    for mf in root.findall('.//bpmn:messageFlow', self.BPMN_NS):
                        if mf.get('sourceRef') == tid:
                            has_msg_flow = True
                            break
                    if not has_msg_flow:
                        self.issues.append(ValidationIssue(
                            element_id=tid,
                            element_type=ttype,
                            severity=Severity.MAJOR,
                            message=f"SendTask '{name or tid}' has no outgoing message flow",
                            category="flow",
                            suggestion="A SendTask should have a message flow to another pool"
                        ))

                if ttype == 'receiveTask':
                    has_msg_flow = False
                    for mf in root.findall('.//bpmn:messageFlow', self.BPMN_NS):
                        if mf.get('targetRef') == tid:
                            has_msg_flow = True
                            break
                    if not has_msg_flow:
                        self.issues.append(ValidationIssue(
                            element_id=tid,
                            element_type=ttype,
                            severity=Severity.MAJOR,
                            message=f"ReceiveTask '{name or tid}' has no incoming message flow",
                            category="flow",
                            suggestion="A ReceiveTask should have a message flow from another pool"
                        ))

    def _validate_sequence_flows(self, root: ET.Element):
        for flow in root.findall('.//bpmn:sequenceFlow', self.BPMN_NS):
            fid = flow.get('id', 'unknown')
            source = flow.get('sourceRef', '')
            target = flow.get('targetRef', '')

            if source and source not in self.elements:
                self.issues.append(ValidationIssue(
                    element_id=fid,
                    element_type="SequenceFlow",
                    severity=Severity.CRITICAL,
                    message=f"Source element '{source}' not found",
                    category="reference"
                ))

            if target and target not in self.elements:
                self.issues.append(ValidationIssue(
                    element_id=fid,
                    element_type="SequenceFlow",
                    severity=Severity.CRITICAL,
                    message=f"Target element '{target}' not found",
                    category="reference"
                ))

            # Check sequence flow stays within same process
            if source and target:
                source_proc = self.element_process.get(source, '')
                target_proc = self.element_process.get(target, '')
                if source_proc and target_proc and source_proc != target_proc:
                    self.issues.append(ValidationIssue(
                        element_id=fid,
                        element_type="SequenceFlow",
                        severity=Severity.CRITICAL,
                        message="Sequence flow crosses pool boundaries",
                        category="flow",
                        suggestion="Use message flows to communicate between pools, not sequence flows"
                    ))

    def _validate_message_flows(self, root: ET.Element):
        for flow in root.findall('.//bpmn:messageFlow', self.BPMN_NS):
            fid = flow.get('id', 'unknown')
            source = flow.get('sourceRef', '')
            target = flow.get('targetRef', '')

            if source and source not in self.elements:
                self.issues.append(ValidationIssue(
                    element_id=fid,
                    element_type="MessageFlow",
                    severity=Severity.CRITICAL,
                    message=f"Message flow source '{source}' not found",
                    category="reference"
                ))

            if target and target not in self.elements:
                self.issues.append(ValidationIssue(
                    element_id=fid,
                    element_type="MessageFlow",
                    severity=Severity.CRITICAL,
                    message=f"Message flow target '{target}' not found",
                    category="reference"
                ))

            # Check that message flow goes between different pools
            if source and target:
                source_proc = self.element_process.get(source, '')
                target_proc = self.element_process.get(target, '')

                source_tag = self.element_tags.get(source, '')
                target_tag = self.element_tags.get(target, '')
                if source_tag == 'participant':
                    source_proc = self.participant_process.get(source, source)
                if target_tag == 'participant':
                    target_proc = self.participant_process.get(target, target)

                if source_proc and target_proc and source_proc == target_proc:
                    self.issues.append(ValidationIssue(
                        element_id=fid,
                        element_type="MessageFlow",
                        severity=Severity.CRITICAL,
                        message="Message flow connects elements within the same pool",
                        category="flow",
                        suggestion="Message flows are only for communication between different pools. Use sequence flows within a pool"
                    ))

    def _validate_reachability(self, root: ET.Element):
        """Check that every flow node is reachable from a Start Event."""
        for proc_id, elem_ids in self.process_elements.items():
            flow_nodes: Set[str] = set()
            start_events = []
            for eid in elem_ids:
                tag = self.element_tags.get(eid, '')
                if tag in self._FLOW_NODE_TAGS:
                    flow_nodes.add(eid)
                if tag == 'startEvent':
                    start_events.append(eid)

            if not start_events or not flow_nodes:
                continue

            visited: Set[str] = set()
            queue = list(start_events)
            while queue:
                current = queue.pop(0)
                if current in visited:
                    continue
                visited.add(current)
                for flow_id in self.outgoing.get(current, []):
                    if flow_id in self.flows:
                        _, target = self.flows[flow_id]
                        if target not in visited:
                            queue.append(target)

            unreachable = flow_nodes - visited
            for eid in unreachable:
                tag = self.element_tags.get(eid, '')
                name = self.elements[eid].get('name', '') if eid in self.elements else ''
                self.issues.append(ValidationIssue(
                    element_id=eid,
                    element_type=tag,
                    severity=Severity.CRITICAL,
                    message=f"Element '{name or eid}' is not reachable from any Start Event",
                    category="flow",
                    suggestion="Ensure all elements are connected and reachable from the Start Event"
                ))

    def get_issues_for_element(self, element_id: str) -> List[ValidationIssue]:
        return [i for i in self.issues if i.element_id == element_id]

    def get_issues_by_severity(self, severity: Severity) -> List[ValidationIssue]:
        return [i for i in self.issues if i.severity == severity]

    def has_critical_issues(self) -> bool:
        return any(i.severity == Severity.CRITICAL for i in self.issues)

    def get_summary(self) -> Dict[str, int]:
        return {
            "critical": len(self.get_issues_by_severity(Severity.CRITICAL)),
            "major": len(self.get_issues_by_severity(Severity.MAJOR)),
            "minor": len(self.get_issues_by_severity(Severity.MINOR)),
            "total": len(self.issues)
        }

    def format_for_prompt(self, lang: str = 'en') -> str:
        """Format validation issues as plain text for injection into LLM prompts."""
        if not self.issues:
            return ''

        severity_map = {
            Severity.CRITICAL: 'syntax',
            Severity.MAJOR: 'semantic',
            Severity.MINOR: 'info',
        }

        if lang == 'de':
            header = "--- Ergebnisse der strukturellen Validierung (automatisiert) ---"
            item_fmt = "- [{severity}] Element '{eid}' ({etype}): {msg}"
            note = (
                "\nHinweis: Die obigen Probleme wurden durch automatische Validierung gefunden und sind Fakten. "
                "Formuliere sie als sokratische Hinweise in deiner Antwort. "
                "Konzentriere dich zusätzlich auf semantische Probleme, die ein Validator nicht erkennen kann "
                "(z.B. falscher Aufgabentyp, fehlende Prozesspfade laut Aufgabenbeschreibung, falsche Gateway-Nutzung für das Szenario)."
            )
        else:
            header = "--- Structural Validation Results (automated) ---"
            item_fmt = "- [{severity}] Element '{eid}' ({etype}): {msg}"
            note = (
                "\nNote: The issues above were found by automated validation and are factual. "
                "Rephrase them as Socratic hints in your response. "
                "Additionally focus on semantic issues that a validator cannot detect "
                "(e.g., wrong task types, missing process paths from the task description, incorrect gateway usage for the scenario)."
            )

        lines = [header]
        # Deduplicate: keep only highest-severity issue per element
        severity_rank = {Severity.CRITICAL: 0, Severity.MAJOR: 1, Severity.MINOR: 2}
        best: Dict[str, 'ValidationIssue'] = {}
        for issue in self.issues:
            eid = issue.element_id
            if eid not in best or severity_rank.get(issue.severity, 9) < severity_rank.get(best[eid].severity, 9):
                best[eid] = issue
        for issue in best.values():
            sev = severity_map.get(issue.severity, 'info')
            lines.append(item_fmt.format(
                severity=sev,
                eid=issue.element_id,
                etype=issue.element_type,
                msg=issue.message,
            ))
        lines.append(note)
        return '\n'.join(lines)
