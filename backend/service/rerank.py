"""
Rerank 重排序服务

封装 bge-reranker-v2-m3 模型调用，对 Chroma 搜索结果进行重排序。
支持单集合/多集合聚合后的统一重排序。
"""
import httpx
from typing import List, Dict, Tuple, Optional
from settings import settings
from loguru import logger


class RerankService:
    def __init__(self):
        rerank_config = settings.get_rerank_config()
        self.model = rerank_config.get('model')
        self.rerank_url = rerank_config.get('base_url')
        self.api_key = rerank_config.get('api_key')

    async def rerank_context(self, question: str, context_docs: List[List[str]], top_k: int = 5) -> List[str]:
        """
        使用 bge-reranker-v2-m3 模型对 Chroma 搜索结果重排序

        Args:
            question: 用户查询问题
            context_docs: 二维列表，Chroma 返回的文档片段 [[doc1, doc2], [doc3]]
            top_k: 返回重排序后最相关的 top_k 个文档

        Returns:
            重排序后的文档列表（长度 <= top_k）
        """
        # Flatten documents: Chroma 的结果通常是二维 list
        flat_docs = [doc for batch in context_docs for doc in batch]

        if not flat_docs:
            return []

        return await self._rerank(question, flat_docs, top_k)

    async def rerank_multi_collection(
        self,
        question: str,
        collection_docs: Dict[str, List[str]],
        top_k: int = 10
    ) -> Tuple[List[str], Dict[str, List[str]]]:
        """
        多集合统一重排序：从多个 Chroma 集合收集文档，统一重排序后返回 top_k 结果。

        Args:
            question: 用户查询问题
            collection_docs: 字典，key 为集合名称，value 为该集合检索到的文档列表
                             例如 {"collection_meeting_xxx": ["doc1", "doc2"],
                                   "collection_kb_yyy": ["doc3", "doc4"]}
            top_k: 返回重排序后最相关的 top_k 个文档

        Returns:
            (all_reranked_docs, per_collection_results)
            - all_reranked_docs: 统一重排序后的全局 top_k 文档
            - per_collection_results: 按集合分组的重排序结果
        """
        # 收集所有文档并记录归属
        all_docs = []
        doc_to_collection = {}  # doc_index -> collection_name

        for collection_name, docs in collection_docs.items():
            for doc in docs:
                if doc and isinstance(doc, str) and doc.strip():
                    idx = len(all_docs)
                    all_docs.append(doc.strip())
                    doc_to_collection[idx] = collection_name

        if not all_docs:
            return {}, {}

        # 统一重排序
        reranked_docs = await self._rerank(question, all_docs, top_k)

        # 按集合分组
        per_collection_results: Dict[str, List[str]] = {}
        for doc in reranked_docs:
            # 找出该文档属于哪个集合
            for idx, original_doc in enumerate(all_docs):
                if original_doc == doc:
                    col_name = doc_to_collection.get(idx, "unknown")
                    per_collection_results.setdefault(col_name, []).append(doc)
                    break

        logger.info(f"多集合重排序完成: 输入 {len(all_docs)} 条，输出 top_k={len(reranked_docs)} 条")
        return reranked_docs, per_collection_results

    async def _rerank(self, question: str, documents: List[str], top_k: int) -> List[str]:
        """
        内部方法：调用 rerank API 进行重排序
        """
        if not documents:
            return []

        payload = {
            "model": self.model,
            "query": question,
            "documents": documents,
            "top_n": min(top_k, len(documents)),
            "return_documents": True
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}"
        }

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                r = await client.post(self.rerank_url, json=payload, headers=headers)
                if r.status_code != 200:
                    raise RuntimeError(f"Rerank 调用失败: {r.status_code} - {r.text}")

                data = r.json()

            rerank_results = data.get("results", [])
            # 按相关性得分降序排序
            rerank_results.sort(key=lambda x: x['relevance_score'], reverse=True)

            return [item["document"] for item in rerank_results[:top_k]]

        except Exception as e:
            logger.error(f"Rerank 调用失败: {e}")
            # 失败时返回原始文档的前 top_k 条
            return documents[:top_k]


rerank = RerankService()
