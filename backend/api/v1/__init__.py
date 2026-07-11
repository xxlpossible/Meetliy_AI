from api.v1.stt import router as audio_router
from api.v1.user import router as user_router
from api.v1.chat_message import router as chat_router
from api.v1.auth import router as auth_router
from api.v1.knowledge import router as knowledge_router
from api.v1.meeting import router as meeting_router

__all__ = [
    'audio_router',
    'user_router',
    'chat_router',
    'auth_router',
    'knowledge_router',
    'meeting_router',
]
