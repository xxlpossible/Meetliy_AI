"""
上下文管理模块

将一次对话所需的全部上下文按统一格式拼接为大模型输入提示词，组成来源包括：
- 系统初始提示词（角色定位、职责）           —— [Role & Policies]
- 当前任务（用户本轮提问）                   —— [Task]
- 会议内容（从 Chroma meeting 集合检索）      —— [MEETING_CONTENT]
- 知识库片段（从 Chroma knowledge 集合检索）  —— [Evidence]
- 最近历史对话（内存中提取，仅保留近 3 轮）   —— [Context]
- 过往记忆（从 Chroma 检索，排除近 3 轮）    —— [Context]

同时负责把会话中的每条聊天记录（单条输入或输出）同步写入 MySQL 与 Chroma 向量库，
Chroma 的 metadata 中必须包含 session_id / user_id / time / role / turn_index 信息。

turn_index 计数器由 MySQL 持久化（ChatMessage 表中取 MAX），进程内缓存仅为加速，
重启后自动从 MySQL 重新播种。
"""
import uuid
from datetime import datetime
from typing import Any

from loguru import logger

from database.models.chatmessage import ChatMessage, ChatMessageDao
from utils.siliconflow_embedding import db_manager

# 系统初始提示词（角色定位、职责）—— 作为 [Role & Policies] 区块内容。
SYSTEM_ROLE_PROMPT = (
    "你是一位专业的会议与知识库智能助理。"
    "你的职责是基于提供的会议记录、知识库片段以及历史对话，准确、有据地回答用户的问题。"
    "回答应满足以下要求：1) 提供具体可行的建议；2) 解释技术原理；3) 必要时给出代码示例或结构化要点。"
    "当上下文信息不足以回答问题时应明确说明，而不是编造内容。"
)


# ---------------------------------------------------------------------------
# 内存中的最近历史对话（仅保留近 3 轮 = 6 条），按 session_id 隔离
# ---------------------------------------------------------------------------
SESSION_HISTORY: dict[str, list[dict[str, str]]] = {}
_SEEDED_SESSIONS: set = set()
# 进程内 turn_index 缓存（session_id -> 下一个待分配的 turn_index）
# 权威数据源是 MySQL，重启后通过 _seed_history_from_db 重新播种
_SESSION_TURN_COUNTERS: dict[str, int] = {}


def _seed_history_from_db(session_id: str) -> None:
    """
    首次使用该会话时，从 MySQL 加载最近 3 轮历史 + 播种 turn_index 计数器。
    保证 WS 重连 / 服务器重启后上下文连续、turn_index 单调递增。
    """
    if session_id in _SEEDED_SESSIONS:
        return
    _SEEDED_SESSIONS.add(session_id)
    try:
        rows = ChatMessageDao.get_recent_turns(session_id, turns=3)
        SESSION_HISTORY[session_id] = [
            {"role": m.role, "content": m.content} for m in rows
        ]
        # 从 MySQL 恢复 turn_index 计数器：取 session 内最大 turn_index + 1
        max_idx = ChatMessageDao.get_max_turn_index(session_id)
        _SESSION_TURN_COUNTERS[session_id] = (max_idx + 1) if max_idx is not None else 0
        logger.info(
            f"📥 加载会话历史 {session_id} 已加载：{len(rows)} 条消息，"
            f"turn_index 从 {_SESSION_TURN_COUNTERS[session_id]} 继续"
        )
    except Exception as e:
        logger.warning(f"⚠️ 加载会话 {session_id} 历史失败: {e}")
        SESSION_HISTORY[session_id] = []
        _SESSION_TURN_COUNTERS[session_id] = 0


def get_next_turn_index(session_id: str) -> int:
    """
    获取会话的下一个轮次序号（线程安全，单 WS 连接内串行调用）。
    首次调用时自动从 MySQL 播种。
    """
    _seed_history_from_db(session_id)
    idx = _SESSION_TURN_COUNTERS.get(session_id, 0)
    _SESSION_TURN_COUNTERS[session_id] = idx + 1
    return idx


def append_history(session_id: str, role: str, content: str) -> None:
    """向内存历史追加一条消息，并裁剪为最近 3 轮（6 条）。"""
    _seed_history_from_db(session_id)
    buf = SESSION_HISTORY.setdefault(session_id, [])
    buf.append({"role": role, "content": content})
    # 只保留最近 3 轮（6 条）聊天记录
    if len(buf) > 6:
        del buf[: len(buf) - 6]


def get_recent_history(session_id: str) -> list[dict[str, str]]:
    """获取内存中最近 3 轮对话（最多 6 条）。"""
    _seed_history_from_db(session_id)
    return SESSION_HISTORY.get(session_id, [])[-6:]


# ---------------------------------------------------------------------------
# Chroma 向量库：会话记忆的存储与检索
# ---------------------------------------------------------------------------
def _memory_collection(user_id: int) -> str:
    """每个用户独立的聊天记忆集合。"""
    return f"chat_memory_{user_id}"


def _estimate_tokens(text: str) -> int:
    """
    估算文本的 token 数。
    对于中文：大约 1 个字符 = 1-2 个 token
    对于英文：大约 1 个单词 = 1-1.5 个单词
    这里采用保守估算：中文字符数 + 英文单词数 * 1.5
    """
    chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    # 非中文字符按空格分词估算英文单词
    non_chinese = ''.join(c if not ('\u4e00' <= c <= '\u9fff') else ' ' for c in text)
    english_words = len(non_chinese.split())
    return chinese_chars + int(english_words * 1.5)


def _truncate_for_embedding(text: str, max_tokens: int = 8192, safety_margin: float = 0.8) -> str:
    """
    如果文本超过 embedding 模型的 token 限制，截断到安全范围内。
    
    Args:
        text: 原始文本
        max_tokens: 模型支持的最大 token 数
        safety_margin: 安全系数，默认 80%，留出余量
    
    Returns:
        截断后的文本（如果未超限则返回原文）
    """
    estimated = _estimate_tokens(text)
    limit = int(max_tokens * safety_margin)
    
    if estimated <= limit:
        return text
    
    # 按字符截断（保守策略：1 中文字符 ≈ 1 token）
    truncated = text[:limit]
    logger.warning(
        f"⚠️Embedding模型输入限制: 文本 token 超限(估计 {estimated} > {limit}), 已截断至 {limit} 字符"
    )
    return truncated


def persist_chat_message(
    session_id: str,
    user_id: int,
    role: str,
    content: str,
    turn_index: int,
) -> None:
    """
    将单条聊天记录（一个输入或输出）同步写入 MySQL 与 Chroma 向量库。

    Chroma metadata 必须包含 session_id / user_id / time / role，
    便于后续按会话、用户、时间维度检索「过往记忆」。
    
    Chroma 中存储的文档内容格式为 `[role]: content`，
    便于后续检索时能直接获取带角色标注的对话上下文。
    """
    # 1) MySQL —— 持久化权威数据源，用于历史回溯与越权隔离
    try:
        ChatMessageDao.add(
            ChatMessage(
                session_id=session_id,
                user_id=user_id,
                role=role,
                content=content,
                turn_index=turn_index,
            )
        )
    except Exception as e:
        logger.error(f"❌ MySQL 写入聊天记录失败(session={session_id}), 错误原因: {e}")

    # 2) Chroma —— 向量化存储，作为「过往记忆」供后续跨会话检索
    try:
        # 格式：[role]: content，便于检索时直接展示对话角色和内容
        formatted_content = f"[{role}]: {content}"
        
        # 检查并截断超限文本（embedding 模型限制 8192 tokens）
        safe_content = _truncate_for_embedding(formatted_content)
        
        db_manager.add_documents(
            collection_name=_memory_collection(user_id),
            documents=[safe_content],
            metadatas=[{
                "session_id": session_id,
                "user_id": str(user_id),
                "time": datetime.now().isoformat(timespec="seconds"),
                "role": role,
                "turn_index": turn_index,
            }],
            ids=[uuid.uuid4().hex],
        )
    except Exception as e:
        logger.error(f"❌ Chroma 写入聊天记忆失败(user={user_id}), 错误原因: {e}")


def retrieve_past_memory(
    user_id: int,
    question: str,
    session_id: str,
    n_results: int = 5,
    current_turn_index: int = 0,
) -> list[str]:
    """
    从 Chroma 检索当前会话的过往记忆（排除近 3 轮）。
    
    通过 where 条件直接在 ChromaDB 层过滤：
    - session_id: 只取本会话内容
    - turn_index < current_turn_index - 5: 排除近 3 轮（6 条）消息
    
    Args:
        user_id: 用户 ID
        question: 用户当前问题
        session_id: 会话 ID
        n_results: 返回结果数量
        current_turn_index: 当前用户消息的 turn_index，用于排除近 3 轮
    
    Returns:
        过往记忆文本列表
    """
    # 构建 where 条件
    # 注意：ChromaDB 多条件必须用 $and 显式组合，不支持隐式 AND
    conditions: list = [{"session_id": session_id}]
    
    # 排除近 3 轮：SESSION_HISTORY 覆盖 [cutoff, current_turn_index)
    # 所以只检索 turn_index < cutoff 的消息
    cutoff = current_turn_index - 5
    if cutoff > 0:
        conditions.append({"turn_index": {"$lt": cutoff}})
    
    where: dict[str, Any] = {"$and": conditions} if len(conditions) > 1 else conditions[0]
    
    try:
        result = db_manager.search(
            collection_name=_memory_collection(user_id),
            query_text=question,
            n_results=n_results,
            where=where,
        )
    except Exception as e:
        logger.warning(f"⚠️ 过往记忆检索失败(user={user_id}): {e}")
        return []

    metadatas = (result.get("metadatas") or [[]])[0]
    documents = (result.get("documents") or [[]])[0]

    memory_texts: list[str] = []
    for doc, meta in zip(documents, metadatas):
        if not doc:
            continue
        meta = meta or {}
        memory_texts.append(doc.strip())
    return memory_texts


def clear_session_history(session_id: str) -> None:
    """清理指定会话的内存历史（会话结束时调用，释放内存）。"""
    SESSION_HISTORY.pop(session_id, None)
    _SEEDED_SESSIONS.discard(session_id)


# ---------------------------------------------------------------------------
# 上下文拼接
# ---------------------------------------------------------------------------
def build_context(
    question: str,
    meeting_content: list[str],
    kb_snippets: list[str],
    recent_history: list[dict[str, str]],
    past_memory: list[str],
) -> str:
    """
    按统一格式拼接上下文提示词：
    [Role & Policies]
    （系统提示词）

    [Task]
    （用户问题）

    [MEETING_CONTENT]
    （从会议内容集合检索到的片段）

    [Evidence]
    （从知识库集合检索到的片段）

    [Context]
    （最近 3 轮对话 + 过往记忆）

    [Output]
    （输出要求）
    """
    # MEETING_CONTENT：会议内容片段
    if meeting_content:
        meeting_block = "\n---\n".join(m for m in meeting_content if m)
    else:
        meeting_block = "（暂无相关会议内容）"

    # Evidence：知识库片段
    if kb_snippets:
        evidence = "\n---\n".join(s for s in kb_snippets if s)
    else:
        evidence = "（暂无相关知识库片段）"

    # Context：最近历史对话 + 过往记忆
    context_parts: list[str] = []
    for msg in recent_history:
        role_label = "user" if msg.get("role") == "user" else "assistant"
        context_parts.append(f"{role_label}: {msg.get('content', '')}")
    for mem in past_memory:
        context_parts.append(f"记忆: {mem}")
    context_block = "\n".join(context_parts) if context_parts else "（暂无历史对话）"

    return (
        "[Role & Policies]\n"
        f"{SYSTEM_ROLE_PROMPT}\n\n"
        "[Task]\n"
        f"{question}\n\n"
        "[MEETING_CONTENT]\n"
        f"{meeting_block}\n\n"
        "[Evidence]\n"
        f"{evidence}\n\n"
        "[Context]\n"
        f"{context_block}\n\n"
        "[Output]\n"
        "请基于以上信息,提供准确、有据的回答。\n"
    )
