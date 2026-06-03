"""LION response parser — extracted from AIService.

Handles _preprocess_lion, _parse_lion, _parse_issues, and _handle_mentor_response.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from lib.lion import loads as lion_loads, strip_markdown_fences

logger = logging.getLogger('bpmtutor.lion_parser')

_SEVERITY_RANK: Dict[str, int] = {'syntax': 0, 'semantic': 1, 'info': 2}

_SCALAR_KEY_RE = re.compile(
    r'^(\s*)(message|phase|title|details|shortDesc|longDesc)\s*:\s*(.+)$'
)
_KEY_DELIMITER_RE = re.compile(
    r'^\s*(?:message|phase|issues|complete|'
    r'title|details|shortDesc|longDesc|elementId|severity|category)\s*[:(]'
)


class LIONParser:
    """Parse LLM responses in the LION format."""

    # ── Pre-processing ────────────────────────────────────────────────────────

    @staticmethod
    def preprocess(text: str) -> str:
        """Auto-quote unquoted string values for known scalar LION keys."""
        close_re = re.compile(r'^\s*[}\]]\s*,?\s*$')
        num_re = re.compile(r'^-?\d')

        lines = text.split('\n')
        result: List[str] = []
        i = 0
        while i < len(lines):
            line = lines[i]
            m = _SCALAR_KEY_RE.match(line)
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
                    if _KEY_DELIMITER_RE.match(nxt) or close_re.match(nxt):
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

    # ── Parsing ───────────────────────────────────────────────────────────────

    @classmethod
    def parse(cls, content: str) -> Optional[Dict[str, Any]]:
        """Parse a LION-formatted LLM response into a Python dict."""
        content = strip_markdown_fences(content)
        content = cls.preprocess(content)
        try:
            return lion_loads(content)
        except Exception as exc:
            logger.warning('[LIONParser] Parse error: %s', exc)
            logger.debug('[LIONParser] Raw content: %s', content)
            return None

    # ── Issue normalisation ───────────────────────────────────────────────────

    @classmethod
    def parse_issues(cls, raw_issues: List[Any]) -> List[Dict[str, Any]]:
        """Normalise raw issue entries and keep only the highest-severity per element."""
        _severity_map = {
            'critical': 'syntax',
            'warning': 'semantic',
            'major': 'semantic',
            'minor': 'info',
        }
        all_issues: List[Dict[str, Any]] = []
        for item in raw_issues:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                issue: Dict[str, Any] = {
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

            sev = issue.get('severity', 'info')
            sev = _severity_map.get(sev, sev)
            if sev not in ('syntax', 'semantic', 'info'):
                sev = 'info'

            all_issues.append({
                'elementId': issue.get('elementId', ''),
                'severity': sev,
                'category': issue.get('category', 'general'),
                'shortDesc': issue.get('shortDesc', issue.get('message', 'Issue detected')),
                'longDesc': issue.get('longDesc', issue.get('message', 'No details available')),
            })

        # Keep only highest-severity issue per element
        best: Dict[str, Dict[str, Any]] = {}
        for iss in all_issues:
            eid = iss['elementId']
            if eid not in best or (_SEVERITY_RANK.get(iss['severity'], 9) <
                                    _SEVERITY_RANK.get(best[eid]['severity'], 9)):
                best[eid] = iss
        return list(best.values())

    # ── Response handling ─────────────────────────────────────────────────────

    @classmethod
    def handle_mentor_response(cls, content: str) -> Dict[str, Any]:
        """Parse a Mentor/Colleague/Supervisor LION response into a structured dict."""
        parsed = cls.parse(content)

        if not parsed or 'phase' not in parsed:
            logger.warning('[LIONParser] Response not in expected LION format')
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

        issues: List[Dict[str, Any]] = []
        if phase == 'ANALYSIS' or parsed.get('issues'):
            raw_issues = parsed.get('issues', [])
            if isinstance(raw_issues, list):
                issues = cls.parse_issues(raw_issues)

        bpmn_ops: List[Dict[str, Any]] | dict = []
        raw_ops = parsed.get('bpmn_ops', [])
        if isinstance(raw_ops, dict):
            # New grouped format: {rename: [...], draw: [...], ...}
            # Pass the dict directly — JS normalizeOps() will expand it client-side.
            bpmn_ops = raw_ops
        elif isinstance(raw_ops, list):
            for op in raw_ops:
                if isinstance(op, (list, tuple)) and len(op) >= 2:
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

        logger.debug('[LIONParser] Phase=%s issues=%d bpmn_ops=%d complete=%s',
                     phase, len(issues), len(bpmn_ops), is_complete)

        return {
            'message': message,
            'phase': phase,
            'issues': issues,
            'bpmn_ops': bpmn_ops,
            'complete': is_complete,
        }
