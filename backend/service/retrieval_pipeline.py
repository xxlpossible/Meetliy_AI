"""
检索管道：按查询类型编排多路检索。

依赖：
- query_optimizer: 查询分类 + 改写
- rerank:           统一重排序
- db_manager:       ChromaDB 向量检索 + metadata 过滤
"""

from loguru import logger

from service.query_optimizer import QueryOptimizer
from service.rerank import rerank
from utils.siliconflow_embedding import db_manager

# 全局单例
query_optimizer = QueryOptimizer()


# ---------------------------------------------------------------------------
# 相邻扩展
# ---------------------------------------------------------------------------
async def expand_adjacent_chunks(
    retrieved_docs: list[str],
    metadatas_list: list[list[dict]],
    collection_name: str,
    expand_range: int = 2,
) -> list[str]:
    """
    对检索到的 fine_chunk 进行相邻扩展。

    拉取每个命中 chunk 前后各 expand_range 个相邻 chunk，
    合并去重后返回扩展后的文档列表。

    Args:
        retrieved_docs: 检索命中的文档文本列表
        metadatas_list: 对应的 metadata 列表（格式与 ChromaDB 返回一致）
        collection_name: 集合名称
        expand_range: 左右各扩展多少个 chunk

    Returns:
        扩展后的文档文本列表（已去重）
    """
    if not metadatas_list or not retrieved_docs:
        return list(retrieved_docs)

    # 收集所有命中的 chunk_index，按集合分组
    index_ranges: dict[str, list[int]] = {}

    for batch_metas in metadatas_list:
        if not batch_metas:
            continue
        for meta in batch_metas:
            if not meta:
                continue
            chunk_index = meta.get("chunk_index")
            if chunk_index is None:
                continue
            try:
                ci = int(chunk_index)
            except (TypeError, ValueError):
                continue
            col = meta.get("collection_name", collection_name)
            index_ranges.setdefault(col, []).append(ci)

    if not index_ranges:
        return list(retrieved_docs)

    # 对每组 chunk_index，查询相邻范围
    expanded_docs: set[str] = set(retrieved_docs)

    for col_name, indices in index_ranges.items():
        if not indices:
            continue
        min_idx = max(0, min(indices) - expand_range)
        max_idx = max(indices) + expand_range + 1  # +1 因为 end 不包含

        try:
            neighbors = db_manager.get_by_chunk_index_range(
                collection_name=col_name,
                start_index=min_idx,
                end_index=max_idx,
            )
            for doc in neighbors:
                if doc and doc.strip():
                    expanded_docs.add(doc.strip())
        except Exception as e:
            logger.warning(f"[RetrievalPipeline] 相邻扩展失败 ({col_name}): {e}")

    logger.info(
        f"[RetrievalPipeline] 相邻扩展: {len(retrieved_docs)} -> {len(expanded_docs)} 条"
    )
    return list(expanded_docs)


# ---------------------------------------------------------------------------
# 检索管道
# ---------------------------------------------------------------------------
class RetrievalPipeline:
    """多路检索编排器。"""

    def __init__(self, top_k: int = 5):
        self.top_k = top_k

    async def retrieve(
        self,
        question: str,
        meeting_ids: list[str],
        knowledge_ids: list[str] | None = None,
    ) -> dict:
        """
        编排多路检索。

        Args:
            question: 用户问题
            meeting_ids: 会议 ID 列表
            knowledge_ids: 知识库 ID 列表

        Returns:
            {
                "meeting": list[str],      # 重排序后的会议内容
                "kb": str,                  # 重排序后的知识库内容
                "has_meeting": bool,
                "has_kb": bool,
                "query_type": str,
            }
        """
        knowledge_ids = knowledge_ids or []

        # Step 1: 查询分类 + 改写
        analysis = await query_optimizer.analyze_and_rewrite(question)
        query_type = analysis["query_type"]
        query_list = analysis["rewritten_queries"]
        logger.info(
            f"[RetrievalPipeline] query_type={query_type}, "
            f"method={analysis.get('method')}, "
            f"queries={len(query_list)}"
        )

        # Step 2: 按类型分路检索会议内容
        all_meeting_docs: list[str] = []
        all_meeting_metas: list[dict] = []

        if query_type == "概括性":
            # 摘要优先：用所有改写查询分别检索 summary + theme_seg
            seen: set[str] = set()
            for q in query_list:
                await self._retrieve_by_doc_types(
                    meeting_ids=meeting_ids,
                    query_text=q,
                    doc_types=["summary", "theme_seg"],
                    n_results=10,
                    doc_list=all_meeting_docs,
                    meta_list=all_meeting_metas,
                )
            # 结果不足 → 全量检索兜底（同样遍历所有改写查询）
            if len(all_meeting_docs) < self.top_k * 3:
                for q in query_list:
                    await self._retrieve_all(
                        meeting_ids=meeting_ids,
                        query_text=q,
                        n_results=15,
                        doc_list=all_meeting_docs,
                        meta_list=all_meeting_metas,
                    )

        elif query_type == "细节性":
            # 多查询融合
            seen: set[str] = set()
            for q in query_list:
                for m_id in meeting_ids:
                    collection_name = f"collection_meeting_{m_id}"
                    await self._search_and_collect(
                        collection_name=collection_name,
                        query_text=q,
                        n_results=10,
                        doc_list=all_meeting_docs,
                        meta_list=all_meeting_metas,
                        seen=seen,
                    )

        elif query_type == "行动项":
            # 定向检索 action_items
            await self._retrieve_by_doc_types(
                meeting_ids=meeting_ids,
                query_text=question,
                doc_types=["action_items"],
                n_results=5,
                doc_list=all_meeting_docs,
                meta_list=all_meeting_metas,
            )
            # 兜底：全量检索
            if len(all_meeting_docs) < self.top_k:
                await self._retrieve_all(
                    meeting_ids=meeting_ids,
                    query_text=question,
                    n_results=10,
                    doc_list=all_meeting_docs,
                    meta_list=all_meeting_metas,
                )

        else:  # 数据性 / unknown
            for m_id in meeting_ids:
                await self._search_and_collect(
                    collection_name=f"collection_meeting_{m_id}",
                    query_text=query_list[0] if query_list else question,
                    n_results=20,
                    doc_list=all_meeting_docs,
                    meta_list=all_meeting_metas,
                    seen=set(),
                )

        # Step 3: 相邻扩展（对 fine_chunk 类型文档）
        if all_meeting_docs and meeting_ids:
            # 对每个 meeting 的集合做相邻扩展
            for m_id in meeting_ids:
                expanded = await expand_adjacent_chunks(
                    retrieved_docs=all_meeting_docs,
                    metadatas_list=[all_meeting_metas],
                    collection_name=f"collection_meeting_{m_id}",
                )
                all_meeting_docs = expanded

        # Step 4: 统一 rerank
        has_meeting = len(all_meeting_docs) > 0
        reranked_meeting: list[str] = []
        if has_meeting:
            try:
                reranked_meeting = await rerank.rerank_context(
                    question, [all_meeting_docs], top_k=self.top_k
                )
            except Exception as e:
                logger.error(f"[RetrievalPipeline] 会议内容 rerank 失败: {e}")
                reranked_meeting = all_meeting_docs[:self.top_k]

        # Step 5: 知识库检索（复用现有逻辑）
        kb_text = ""
        has_kb = False
        if knowledge_ids:
            try:
                kb_text = await self._search_kb(question, knowledge_ids)
                has_kb = bool(kb_text)
            except Exception as e:
                logger.error(f"[RetrievalPipeline] 知识库检索失败: {e}")

        logger.info(
            f"[RetrievalPipeline] 检索完成: meeting={len(reranked_meeting)}, "
            f"kb={has_kb}, query_type={query_type}"
        )

        return {
            "meeting": reranked_meeting,
            "kb": kb_text,
            "has_meeting": len(reranked_meeting) > 0,
            "has_kb": has_kb,
            "query_type": query_type,
        }

    # ------------------------------------------------------------------
    # 内部检索辅助方法
    # ------------------------------------------------------------------
    @staticmethod
    async def _search_and_collect(
        collection_name: str,
        query_text: str,
        n_results: int,
        doc_list: list[str],
        meta_list: list[dict],
        seen: set[str],
    ) -> None:
        """执行单次向量检索并收集结果（去重）。"""
        try:
            result = db_manager.search(
                collection_name=collection_name,
                query_text=query_text,
                n_results=n_results,
            )
            docs = (result.get("documents") or [[]])[0]
            metas = (result.get("metadatas") or [[]])[0]
            for doc, meta in zip(docs, metas):
                if doc and isinstance(doc, str) and doc.strip() and doc.strip() not in seen:
                    seen.add(doc.strip())
                    doc_list.append(doc.strip())
                    meta_list.append(meta if meta else {})
        except Exception as e:
            logger.warning(f"[RetrievalPipeline] 搜索 {collection_name} 失败: {e}")

    @staticmethod
    async def _retrieve_by_doc_types(
        meeting_ids: list[str],
        query_text: str,
        doc_types: list[str],
        n_results: int,
        doc_list: list[str],
        meta_list: list[dict],
    ) -> None:
        """按 doc_type 过滤检索。"""
        for m_id in meeting_ids:
            try:
                result = db_manager.search(
                    collection_name=f"collection_meeting_{m_id}",
                    query_text=query_text,
                    n_results=n_results,
                    where={"doc_type": {"$in": doc_types}},
                )
                docs = (result.get("documents") or [[]])[0]
                metas = (result.get("metadatas") or [[]])[0]
                for doc, meta in zip(docs, metas):
                    if doc and isinstance(doc, str) and doc.strip():
                        doc_list.append(doc.strip())
                        meta_list.append(meta if meta else {})
            except Exception as e:
                logger.warning(
                    f"[RetrievalPipeline] doc_type 检索失败 "
                    f"(collection_meeting_{m_id}, types={doc_types}): {e}"
                )

    @staticmethod
    async def _retrieve_all(
        meeting_ids: list[str],
        query_text: str,
        n_results: int,
        doc_list: list[str],
        meta_list: list[dict],
    ) -> None:
        """全量检索（无 doc_type 过滤）。"""
        seen: set[str] = set()
        for m_id in meeting_ids:
            await RetrievalPipeline._search_and_collect(
                f"collection_meeting_{m_id}",
                query_text, n_results, doc_list, meta_list, seen,
            )

    @staticmethod
    async def _search_kb(question: str, knowledge_ids: list[str], top_k: int = 5) -> str:
        """从多个知识库集合搜索并统一重排序。"""
        if not knowledge_ids:
            return ""

        collection_docs: dict[str, list[str]] = {}
        for kb_id in knowledge_ids:
            collection_name = f"collection_kb_{kb_id}"
            try:
                result = db_manager.search(
                    collection_name=collection_name,
                    query_text=question,
                    n_results=20,
                )
                docs = (result.get("documents") or [[]])[0]
                filtered = [d.strip() for d in docs if d and isinstance(d, str) and d.strip()]
                if filtered:
                    collection_docs[collection_name] = filtered
            except Exception as e:
                logger.warning(f"[RetrievalPipeline] KB检索失败 {collection_name}: {e}")

        if not collection_docs:
            return ""

        try:
            reranked, _ = await rerank.rerank_multi_collection(
                question=question,
                collection_docs=collection_docs,
                top_k=top_k,
            )
            reranked_text = [item.get('text', '') for item in reranked]
            return "\n".join(reranked_text)
        except Exception as e:
            logger.error(f"[RetrievalPipeline] KB rerank 失败: {e}")
            all_docs: list[str] = []
            for docs in collection_docs.values():
                all_docs.extend(docs)
            return "\n".join(all_docs[:top_k])
