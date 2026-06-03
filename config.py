import os
from dotenv import load_dotenv

load_dotenv()


def _bool(key: str, default: bool = False) -> bool:
    """Read an environment variable as a boolean (true/1/yes → True)."""
    val = os.getenv(key, '').strip().lower()
    if not val:
        return default
    return val in ('true', '1', 'yes')


def _int(key: str, default: int) -> int:
    """Read an environment variable as an integer with a safe fallback."""
    try:
        return int(os.getenv(key, str(default)))
    except (ValueError, TypeError):
        return default


CAMPUS_KI_BASE_URL: str = os.getenv("CAMPUS_KI_BASE_URL", "https://chat.kiconnect.nrw/api")

SECRET_KEY: str = os.getenv("SECRET_KEY", "")
if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY not set in .env file")

FLASK_DEBUG: bool = _bool("FLASK_DEBUG")

AI_CONFIG: dict = {
    "max_chat_history": _int("AI_MAX_CHAT_HISTORY", 20),
}

LOG_LLM_IO: bool = _bool("LOG_LLM_IO")

DEFAULT_LANGUAGE: str = os.getenv('DEFAULT_LANGUAGE', 'en')
