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


__version__ = "0.1.0"
__all__ = ["LionEncoder", "LionDecoder", "dumps", "loads", "strip_markdown_fences"]
