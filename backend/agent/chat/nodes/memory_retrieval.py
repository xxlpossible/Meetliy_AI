"""ChatAgent - 记忆检索节点。"""

from loguru import logger

from rag.memory import retrieve_past_memory
from rag.rerank import rerank


async def _memory_retrieval_node(state: dict) -> dict:
    """从 Chroma 记忆库中检索过往对话记忆，逐个 keyword 检索后合并去重。"""
    question = state.get('question', '')
    session_id = state.get('session_id', '')
    user_id = state.get('user_id', 0)
    turn_index = state.get('turn_index', 0)
    router_result = state.get('router_result') or {}

    keywords: list[str] = router_result.get("keywords", [])
    queries: list[str] = list(keywords) + [question] if keywords else [question]

    memory_content: list[str] = []
    seen: set[str] = set()
    try:
        n_per_query = max(2, 6 // len(queries))
        for q in queries:
            results = retrieve_past_memory(
                user_id=user_id,
                question=q,
                session_id=session_id,
                n_results=n_per_query,
                current_turn_index=turn_index,
            )
            for r in results:
                if r.strip() not in seen:
                    seen.add(r.strip())
                    memory_content.append(r.strip())

        if memory_content:
            try:
                memory_content = await rerank.rerank_context(
                    question, [memory_content], top_k=5
                )
            except Exception as e:
                logger.warning(f"[memory_retrieval] rerank 失败: {e}")

        logger.info(
            f"[memory_retrieval] session={session_id}, "
            f"queries={len(queries)}, "
            f"results={len(memory_content)}"
        )
    except Exception as e:
        logger.error(f"[memory_retrieval] 检索失败: {e}")

    return {"memory_content": memory_content}
