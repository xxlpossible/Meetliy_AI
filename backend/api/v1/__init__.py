from api.v1.auth import router as auth_router
from api.v1.chat_message import router as chat_router
from api.v1.knowledge import router as kb_router
from api.v1.knowledge_file import router as knowledge_router
from api.v1.meeting import router as meeting_router
from api.v1.session import router as session_router
from api.v1.user import router as user_router

__all__ = [
    'auth_router',
    'chat_router',
    'kb_router',
    'knowledge_router',
    'meeting_router',
    'session_router',
    'user_router',
]
