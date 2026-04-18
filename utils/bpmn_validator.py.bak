"""Validates BPMN XML models for correctness and completeness."""
from typing import Dict, List, Any, Optional, Tuple
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
    
    def __init__(self):
        self.issues: List[ValidationIssue] = []
        self.elements: Dict[str, ET.Element] = {}
        self.flows: Dict[str, Tuple[str, str]] = {}
    
    def validate(self, bpmn_xml: str) -> List[ValidationIssue]:
        """Validate a BPMN XML string and return found issues."""
        self.issues = []
        self.elements = {}
        self.flows = {}
        
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
        self._validate_events(root)
        self._validate_gateways(root)
        self._validate_tasks(root)
        self._validate_sequence_flows(root)
        self._validate_message_flows(root)
        
        return self.issues
    
    def _index_elements(self, root: ET.Element):
        for elem in root.iter():
            elem_id = elem.get('id')
            if elem_id:
                self.elements[elem_id] = elem
            
            if elem.tag.endswith('sequenceFlow'):
                source = elem.get('sourceRef')
                target = elem.get('targetRef')
                if elem_id and source and target:
                    self.flows[elem_id] = (source, target)
    
    def _validate_pools(self, root: ET.Element):
        participants = root.findall('.//bpmn:participant', self.BPMN_NS)
        processes = root.findall('.//bpmn:process', self.BPMN_NS)
        
        for participant in participants:
            pid = participant.get('id', 'unknown')
            name = participant.get('name', '')
            process_ref = participant.get('processRef')
            
            if not name:
                self.issues.append(ValidationIssue(
                    element_id=pid,
                    element_type="Participant",
                    severity=Severity.MINOR,
                    message="Pool has no name/label",
                    category="naming",
                    suggestion="Add a descriptive name to the pool"
                ))
            
            if process_ref:
                process = root.find(f".//bpmn:process[@id='{process_ref}']", self.BPMN_NS)
                if process is not None:
                    start_events = process.findall('.//bpmn:startEvent', self.BPMN_NS)
                    end_events = process.findall('.//bpmn:endEvent', self.BPMN_NS)
                    
                    if not start_events:
                        self.issues.append(ValidationIssue(
                            element_id=pid,
                            element_type="Participant",
                            severity=Severity.CRITICAL,
                            message=f"Pool '{name or pid}' has no Start Event",
                            category="structure",
                            suggestion="Add a Start Event to the pool"
                        ))
                    
                    if not end_events:
                        self.issues.append(ValidationIssue(
                            element_id=pid,
                            element_type="Participant",
                            severity=Severity.CRITICAL,
                            message=f"Pool '{name or pid}' has no End Event",
                            category="structure",
                            suggestion="Add an End Event to the pool"
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
                    suggestion="Add a Timer, Message, or Signal event definition"
                ))
    
    def _validate_gateways(self, root: ET.Element):
        gateway_types = [
            'exclusiveGateway', 'parallelGateway', 
            'inclusiveGateway', 'eventBasedGateway'
        ]
        
        for gtype in gateway_types:
            for gateway in root.findall(f'.//bpmn:{gtype}', self.BPMN_NS):
                gid = gateway.get('id', 'unknown')
                name = gateway.get('name', '')
                
                incoming = gateway.findall('bpmn:incoming', self.BPMN_NS)
                outgoing = gateway.findall('bpmn:outgoing', self.BPMN_NS)
                
                total_flows = len(incoming) + len(outgoing)
                
                if total_flows <= 2:
                    self.issues.append(ValidationIssue(
                        element_id=gid,
                        element_type=gtype,
                        severity=Severity.MAJOR,
                        message=f"Gateway has only {total_flows} flows (needs > 2)",
                        category="structure",
                        suggestion="A gateway should have multiple incoming or outgoing flows"
                    ))
                
                if gtype in ['exclusiveGateway', 'inclusiveGateway'] and len(outgoing) > 1:
                    if not name:
                        self.issues.append(ValidationIssue(
                            element_id=gid,
                            element_type=gtype,
                            severity=Severity.MINOR,
                            message="Decision gateway has no label/question",
                            category="naming",
                            suggestion="Add a decision question (e.g., 'Request approved?')"
                        ))
    
    def _validate_tasks(self, root: ET.Element):
        task_types = [
            'task', 'userTask', 'serviceTask', 'sendTask',
            'receiveTask', 'manualTask', 'businessRuleTask', 'scriptTask'
        ]
        
        for ttype in task_types:
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
    
    def _validate_sequence_flows(self, root: ET.Element):
        for flow in root.findall('.//bpmn:sequenceFlow', self.BPMN_NS):
            fid = flow.get('id', 'unknown')
            source = flow.get('sourceRef')
            target = flow.get('targetRef')
            
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
    
    def _validate_message_flows(self, root: ET.Element):
        for flow in root.findall('.//bpmn:messageFlow', self.BPMN_NS):
            fid = flow.get('id', 'unknown')
            source = flow.get('sourceRef')
            target = flow.get('targetRef')
            
            source_elem = self.elements.get(source)
            target_elem = self.elements.get(target)
            
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
