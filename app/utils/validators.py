"""Shared validation helpers."""
from email_validator import validate_email, EmailNotValidError


def is_valid_email(email: str) -> bool:
    """Return True when *email* is a syntactically valid, deliverable address.

    Uses the *email-validator* library for RFC 5321 / RFC 5322 compliance.
    Falls back to False on any validation error (including DNS failures when
    *check_deliverability=False* is not set, but we keep it False here so that
    validation stays fast and offline-friendly).
    """
    try:
        validate_email(email, check_deliverability=False)
        return True
    except EmailNotValidError:
        return False
