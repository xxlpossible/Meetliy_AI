"""
检索管道：按查询类型编排多路检索。

依赖：
- query_optimizer: 查询分类 + 改写
- rerank:           统一重排序
- db_manager:       ChromaDB 向量检索 + metadata 过滤
"""

from loguru import logger

from rag.query_optimizer import QueryOptimizer
from rag.rerank import rerank
from rag.embedding import db_manager

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
            for q in query_list:
                await self._retrieve(
                    meeting_ids=meeting_ids,
                    query_text=q,
                    n_res_per_collection=10,
                    doc_list=all_meeting_docs,
                    meta_list=all_meeting_metas,
                    doc_types=["summary", "theme_seg"],
                )
            # 结果不足 → 全量检索兜底（同样遍历所有改写查询）
            if len(all_meeting_docs) < self.top_k * 3:
                for q in query_list:
                    await self._retrieve(
                        meeting_ids=meeting_ids,
                        query_text=q,
                        n_res_per_collection=15,
                        doc_list=all_meeting_docs,
                        meta_list=all_meeting_metas,
                    )

        elif query_type == "细节性":
            # 多查询融合
            for q in query_list:
                await self._retrieve(
                    meeting_ids=meeting_ids,
                    query_text=q,
                    n_res_per_collection=10,
                    doc_list=all_meeting_docs,
                    meta_list=all_meeting_metas,
                )

        elif query_type == "行动项":
            # 定向检索 action_items
            await self._retrieve(
                meeting_ids=meeting_ids,
                query_text=question,
                n_res_per_collection=5,
                doc_list=all_meeting_docs,
                meta_list=all_meeting_metas,
                doc_types=["action_items"],
            )
            # 兜底：全量检索
            if len(all_meeting_docs) < self.top_k:
                await self._retrieve(
                    meeting_ids=meeting_ids,
                    query_text=question,
                    n_res_per_collection=10,
                    doc_list=all_meeting_docs,
                    meta_list=all_meeting_metas,
                )

        else:  # 数据性 / unknown
            await self._retrieve(
                meeting_ids=meeting_ids,
                query_text=query_list[0] if query_list else question,
                n_res_per_collection=20,
                doc_list=all_meeting_docs,
                meta_list=all_meeting_metas,
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
    async def _retrieve(
        meeting_ids: list[str],
        query_text: str,
        n_res_per_collection: int,
        doc_list: list[str],
        meta_list: list[dict],
        doc_types: list[str] | None = None,
        score_threshold: float = 0.6,
    ) -> None:
        """统一检索：遍历所有会议集合，支持可选的 doc_type 过滤和分数过滤，带去重。

        Args:
            meeting_ids: 会议 ID 列表
            query_text: 查询文本
            n_res_per_collection: 每个集合返回的结果数
            doc_list: 结果文档列表（原地追加）
            meta_list: 结果元数据列表（原地追加）
            doc_types: 可选，按 doc_type 过滤；为 None 则不限制类型
            score_threshold: 相似度阈值 [0, 1]，低于此分数的结果会被丢弃，默认 0.6
        """
        seen: set[str] = set()
        where = {"doc_type": {"$in": doc_types}} if doc_types else None
        max_distance = 1.0 - score_threshold  # ChromaDB cosine distances: 越小越相似

        for m_id in meeting_ids:
            try:
                kwargs: dict = {
                    "collection_name": f"collection_meeting_{m_id}",
                    "query_text": query_text,
                    "n_results": n_res_per_collection,
                }
                if where:
                    kwargs["where"] = where

                result = db_manager.search(**kwargs)
                docs = (result.get("documents") or [[]])[0]
                metas = (result.get("metadatas") or [[]])[0]
                distances = (result.get("distances") or [[]])[0]
                for doc, meta, dist in zip(docs, metas, distances):
                    if dist > max_distance:
                        continue
                    if doc and isinstance(doc, str) and doc.strip() and doc.strip() not in seen:
                        seen.add(doc.strip())
                        doc_list.append(doc.strip())
                        meta_list.append(meta if meta else {})
            except Exception as e:
                logger.warning(
                    f"[RetrievalPipeline] 检索失败 "
                    f"(collection_meeting_{m_id}, types={doc_types}): {e}"
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
            # rerank_multi_collection 返回 list[str]，已排序好的文本
            return "\n".join(reranked)
        except Exception as e:
            logger.error(f"[RetrievalPipeline] KB rerank 失败: {e}")
            all_docs: list[str] = []
            for docs in collection_docs.values():
                all_docs.extend(docs)
            return "\n".join(all_docs[:top_k])
