"""Shared validation helpers."""
import re

_EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


def is_valid_email(email: str) -> bool:
    return bool(_EMAIL_RE.match(email))
