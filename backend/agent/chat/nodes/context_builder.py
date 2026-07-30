"""ChatAgent - 上下文构建 + 降级判定节点。"""

from loguru import logger

from agent.chat.prompts.fallback import determine_fallback_level
from rag.memory import get_recent_history


async def _context_builder_node(state: dict) -> dict:
    """汇合三路检索结果，判定降级等级，生成用户提示语。"""
    session_id = state.get('session_id', '')
    has_meeting = len(state.get('meeting_content', []) or []) > 0
    has_kb = bool(state.get('kb_snippets', ''))
    has_memory = len(state.get('memory_content', []) or []) > 0

    recent_history = get_recent_history(session_id)
    has_history = bool(recent_history)

    fallback_level, user_notice = determine_fallback_level(
        has_meeting=has_meeting,
        has_kb=has_kb,
        has_memory=has_memory,
        has_history=has_history,
    )

    logger.info(
        f"[context_builder] session={session_id}, "
        f"fallback_level={fallback_level}, "
        f"meeting={has_meeting}, kb={has_kb}, "
        f"memory={has_memory}, history={has_history}"
    )

    return {
        "fallback_level": fallback_level,
        "user_notice": user_notice or "",
    }
