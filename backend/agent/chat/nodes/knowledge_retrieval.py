"""ChatAgent - 知识库检索节点。"""

from loguru import logger

from rag.embedding import db_manager
from rag.rerank import rerank


async def _knowledge_retrieval_node(state: dict) -> dict:
    """从知识库中检索相关文档，逐个 keyword 检索后合并重排序。"""
    question = state.get('question', '')
    knowledge_ids = state.get('knowledge_ids', []) or []
    session_id = state.get('session_id', '')
    router_result = state.get('router_result') or {}

    keywords: list[str] = router_result.get("keywords", [])
    queries: list[str] = list(keywords) + [question] if keywords else [question]

    kb_text = ""
    if knowledge_ids:
        try:
            collection_docs: dict[str, list[str]] = {}
            for q in queries:
                for kb_id in knowledge_ids:
                    col_name = f"collection_kb_{kb_id}"
                    try:
                        result = db_manager.search(
                            collection_name=col_name,
                            query_text=q,
                            n_results=10,
                        )
                        docs = (result.get("documents") or [[]])[0]
                        filtered = [d.strip() for d in docs if d and isinstance(d, str) and d.strip()]
                        if filtered:
                            collection_docs.setdefault(col_name, []).extend(filtered)
                    except Exception as e:
                        logger.warning(f"[knowledge_retrieval] 检索 {col_name} 失败: {e}")

            if collection_docs:
                for col in collection_docs:
                    collection_docs[col] = list(dict.fromkeys(collection_docs[col]))

                reranked, _ = await rerank.rerank_multi_collection(
                    question=question,
                    collection_docs=collection_docs,
                    top_k=5,
                )
                kb_text = "\n".join(reranked)

            logger.info(
                f"[knowledge_retrieval] session={session_id}, "
                f"kb_ids={len(knowledge_ids)}, queries={len(queries)}, "
                f"result_len={len(kb_text)}"
            )
        except Exception as e:
            logger.error(f"[knowledge_retrieval] 检索失败: {e}")
    else:
        logger.info(f"[knowledge_retrieval] session={session_id}, 无知识库 ID，跳过")

    return {"kb_snippets": kb_text}
