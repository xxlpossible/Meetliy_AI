"""ChatAgent - LLM 生成节点。"""

from langchain_core.messages import HumanMessage, SystemMessage
from loguru import logger

from agent.chat.prompts.fallback import (
    FALLBACK_LEVEL_2_PROMPT,
    FALLBACK_LEVEL_3_PROMPT,
)
from agent.chat.prompts.system import ANTI_LEAK_INSTRUCTIONS, SYSTEM_ROLE_PROMPT
from rag.memory import get_recent_history


def _make_llm_generate_node(model):
    """创建 LLM 生成节点（闭包捕获 model）。"""

    async def _llm_call(state: dict) -> dict:
        question = state.get('question', '')
        session_id = state.get('session_id', '')
        user_id = state.get('user_id', 0)
        fallback_level = state.get('fallback_level', 0)

        meeting_content_list: list[str] = state.get('meeting_content', []) or []
        kb_snippets_list: list[str] = []
        kb_snippets_str = state.get('kb_snippets', '')
        if kb_snippets_str:
            kb_snippets_list = [s.strip() for s in kb_snippets_str.split('\n') if s.strip()]
        memory_content: list[str] = state.get('memory_content', []) or []
        recent_history = get_recent_history(session_id)

        messages = _build_context(
            question=question,
            meeting_content=meeting_content_list,
            kb_snippets=kb_snippets_list,
            recent_history=recent_history,
            past_memory=memory_content,
            fallback_level=fallback_level,
        )

        logger.info(
            f"[llm_call] 构建上下文完成, session_id={session_id}, "
            f"user_id={user_id}, fallback_level={fallback_level}"
        )

        llm_message = await model.ainvoke(messages)
        logger.info("[llm_call] 大模型调用完成")

        return {"messages": [llm_message]}

    return _llm_call


def _build_context(
    question: str,
    meeting_content: list[str],
    kb_snippets: list[str],
    recent_history: list[dict[str, str]],
    past_memory: list[str],
    fallback_level: int = 0,
) -> list:
    """将对话所需全部上下文按自然语言格式拼接，返回 LangChain 消息列表。"""
    system_text = SYSTEM_ROLE_PROMPT + ANTI_LEAK_INSTRUCTIONS

    if fallback_level == 2:
        system_text += FALLBACK_LEVEL_2_PROMPT
    elif fallback_level == 3:
        system_text += FALLBACK_LEVEL_3_PROMPT

    human_parts: list[str] = []

    if meeting_content:
        try:
            clean_meeting = "\n---\n".join(m for m in meeting_content if m)
        except TypeError:
            clean_meeting = "\n---\n".join(
                str(m) if not isinstance(m, str) else m for m in meeting_content if m
            )
        human_parts.append(
            "以下是本次会议的相关内容：\n---\n" f"{clean_meeting}\n---"
        )

    if kb_snippets:
        try:
            clean_kb = "\n---\n".join(s for s in kb_snippets if s)
        except TypeError:
            clean_kb = "\n---\n".join(
                str(s) if not isinstance(s, str) else s for s in kb_snippets if s
            )
        human_parts.append(
            "以下是相关知识库参考信息：\n---\n" f"{clean_kb}\n---"
        )

    context_lines: list[str] = []
    for msg in recent_history:
        role_label = "用户" if msg.get("role") == "user" else "助手"
        context_lines.append(f"{role_label}: {msg.get('content', '')}")
    for mem in past_memory:
        context_lines.append(f"记忆: {mem}")
    if context_lines:
        human_parts.append(
            "以下是最近的对话记录：\n---\n" f"{chr(10).join(context_lines)}\n---"
        )

    human_parts.append(f"用户问题：{question}")
    human_text = "\n\n".join(human_parts)

    return [
        SystemMessage(content=system_text),
        HumanMessage(content=human_text),
    ]
