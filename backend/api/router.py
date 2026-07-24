from fastapi import APIRouter
from api.v1 import audio_router
from api.v1 import user_router
from api.v1 import chat_router
from api.v1 import auth_router
from api.v1 import knowledge_router
from api.v1 import kb_router
from api.v1 import meeting_router
from api.v1 import session_router

router = APIRouter(prefix='/api/v1', )
router.include_router(audio_router)
router.include_router(user_router)
router.include_router(chat_router)
router.include_router(auth_router)
router.include_router(knowledge_router)
router.include_router(kb_router)
router.include_router(meeting_router)
router.include_router(session_router)

