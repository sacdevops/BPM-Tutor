from .encoder import LionEncoder, dumps
from .decoder import LionDecoder, loads


def strip_markdown_fences(content: str) -> str:
    """Strip leading/trailing markdown code fences from LLM output."""
    content = content.strip()
    if content.startswith('```'):
        lines = content.split('\n')
        if len(lines) >= 2:
            lines = lines[1:]
            if lines and lines[-1].strip() == '```':
                lines = lines[:-1]
            content = '\n'.join(lines).strip()
    return content


# ---------------------------------------------------------------------------
# LION action schema — maps short abbreviated keys to full property names
# used by the encoder/decoder when translating LION instructions.
# ---------------------------------------------------------------------------
SCHEMA_MAPPINGS: dict[str, dict[str, str]] = {
    'participate': {
        'x': 'x', 'y': 'y', 'w': 'width', 'h': 'height',
        'label': 'label', 'id': 'elementId', 'expanded': 'isExpanded',
        'lanes': 'lanes',
    },
    'draw': {
        'type': 'elementType', 'x': 'x', 'y': 'y', 'label': 'label',
        'id': 'elementId', 'parent': 'parentId', 'connectTo': 'connectTo',
        'eventDef': 'eventDefinition',
    },
    'connect': {'src': 'sourceId', 'tgt': 'targetId', 'label': 'label'},
    'rename': {'id': 'elementId', 'label': 'label'},
    'move': {'id': 'elementId', 'x': 'x', 'y': 'y'},
    'resize': {'id': 'elementId', 'w': 'width', 'h': 'height'},
    'update': {'id': 'elementId', 'prop': 'property', 'val': 'value'},
}

ACTION_ORDER: list[str] = [
    'delete', 'resize', 'move', 'participate', 'draw', 'rename', 'update', 'connect',
]


__version__ = "0.1.0"
__all__ = [
    "LionEncoder", "LionDecoder", "dumps", "loads", "strip_markdown_fences",
    "SCHEMA_MAPPINGS", "ACTION_ORDER",
]
