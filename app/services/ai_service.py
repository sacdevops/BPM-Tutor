"""app.services.ai_service — re-exports from app.ai_service (canonical)."""
from app.ai_service import AIService, AIServiceError  # noqa: F401

__all__ = ['AIService', 'AIServiceError']
