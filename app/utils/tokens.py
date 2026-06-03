"""Authentication helpers — token generation for email verification & password reset."""
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired


def _get_serializer(salt: str) -> URLSafeTimedSerializer:
    from flask import current_app
    return URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt=salt)


def generate_email_token(email: str) -> str:
    s = _get_serializer('email-confirm')
    return s.dumps(email)


def verify_email_token(token: str, max_age: int = 86400) -> str | None:
    """Return the email if valid, else None. max_age in seconds (default 24h)."""
    s = _get_serializer('email-confirm')
    try:
        email = s.loads(token, max_age=max_age)
        return email
    except (BadSignature, SignatureExpired):
        return None


def generate_reset_token(user_id: int) -> str:
    s = _get_serializer('password-reset')
    return s.dumps(str(user_id))


def verify_reset_token(token: str, max_age: int = 3600) -> int | None:
    """Return user_id if valid, else None. max_age in seconds (default 1h)."""
    s = _get_serializer('password-reset')
    try:
        user_id = int(s.loads(token, max_age=max_age))
        return user_id
    except (BadSignature, SignatureExpired, ValueError):
        return None
