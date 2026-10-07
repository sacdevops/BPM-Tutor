"""Helpers for writing long free text into Excel sheets without breaking the file."""
import json

from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE

# Excel allows 32,767 characters per cell; longer values are cut off or flag the file as corrupt.
_CELL_LIMIT = 32000


def xl_text(value, ref: str = '') -> str:
    """Return *value* as a string that is safe to put into one Excel cell.

    Control characters Excel rejects are removed and over-long text is cut with a
    marker pointing at *ref* (the sidecar file that holds the complete text).
    """
    text = '' if value is None else str(value)
    text = ILLEGAL_CHARACTERS_RE.sub('', text)
    if len(text) <= _CELL_LIMIT:
        return text
    note = f' …[TRUNCATED: {len(text)} chars' + (f'; full text in {ref}' if ref else '') + ']'
    return text[:_CELL_LIMIT - len(note)] + note


def jsonl_line(record: dict) -> str:
    return json.dumps(record, ensure_ascii=False) + '\n'
