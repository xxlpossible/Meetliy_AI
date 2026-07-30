"""ChatAgent - 会议检索节点。"""

from loguru import logger

from rag.retrieval_pipeline import RetrievalPipeline, expand_adjacent_chunks
from rag.rerank import rerank
from rag.embedding import db_manager


async def _meeting_retrieval_node(state: dict, retrieval_pipeline: RetrievalPipeline) -> dict:
    """会议库检索节点。利用 Router 的输出指导多路检索。"""
    question = state.get('question', '')
    meeting_ids = state.get('meeting_ids', []) or []
    router_result = state.get('router_result') or {}
    query_type = state.get('query_type', '细节性')
    session_id = state.get('session_id', '')

    if not meeting_ids:
        logger.info(f"[meeting_retrieval] session={session_id}, 无会议 ID")
        return {"meeting_content": []}

    keywords: list[str] = router_result.get("keywords", [])
    speakers: list[str] = router_result.get("speaker", [])

    query_list: list[str] = list(keywords) + [question] if keywords else [question]
    if speakers:
        for sp in speakers:
            query_list.extend([f"{sp} {q}" for q in query_list])

    all_meeting_docs: list[str] = []
    all_meeting_metas: list[dict] = []

    type_config = {
        "概括性": (["summary", "theme_seg", "fine_chunk"], True, 5, (10, 10)),
        "行动项": (["action_items", "fine_chunk"], True, 5, (10, 10)),
        "细节性": (None, True, 5, None),
    }
    doc_types, loop_queries, n_primary, fallback = type_config.get(
        query_type, (None, False, 20, None)
    )

    queries = query_list if loop_queries else [query_list[0] if query_list else question]

    for q in queries:
        await RetrievalPipeline._retrieve(
            meeting_ids=meeting_ids,
            query_text=q,
            n_res_per_collection=n_primary,
            doc_list=all_meeting_docs,
            meta_list=all_meeting_metas,
            doc_types=doc_types,
        )

    if fallback and len(all_meeting_docs) < fallback[0]:
        for q in queries:
            await RetrievalPipeline._retrieve(
                meeting_ids=meeting_ids,
                query_text=q,
                n_res_per_collection=fallback[1],
                doc_list=all_meeting_docs,
                meta_list=all_meeting_metas,
            )

    if all_meeting_docs and meeting_ids:
        for m_id in meeting_ids:
            try:
                expanded = await expand_adjacent_chunks(
                    retrieved_docs=all_meeting_docs,
                    metadatas_list=[all_meeting_metas],
                    collection_name=f"collection_meeting_{m_id}",
                )
                all_meeting_docs = expanded
            except Exception as e:
                logger.warning(f"[meeting_retrieval] 相邻扩展失败 ({m_id}): {e}")

    reranked_meeting: list[str] = []
    if all_meeting_docs:
        try:
            reranked_meeting = await rerank.rerank_context(
                question, [all_meeting_docs], top_k=retrieval_pipeline.top_k
            )
        except Exception as e:
            logger.error(f"[meeting_retrieval] rerank 失败: {e}")
            reranked_meeting = all_meeting_docs[:retrieval_pipeline.top_k]

    logger.info(
        f"[meeting_retrieval] session={session_id}, "
        f"query_type={query_type}, "
        f"final_count={len(reranked_meeting)}"
    )

    return {"meeting_content": reranked_meeting}
