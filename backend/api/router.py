from fastapi import APIRouter

from api.v1 import (
    auth_router,
    chat_router,
    kb_router,
    knowledge_router,
    meeting_router,
    session_router,
    user_router,
)

router = APIRouter(prefix='/api/v1', )
router.include_router(user_router)
router.include_router(chat_router)
router.include_router(auth_router)
router.include_router(knowledge_router)
router.include_router(kb_router)
router.include_router(meeting_router)
router.include_router(session_router)

