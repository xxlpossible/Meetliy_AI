import httpx
from typing import List, Optional
from settings import settings


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

        payload = {
            "model": self.model,
            "query": question,
            "documents": flat_docs,
            "top_n": top_k,
            "return_documents": True
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}"
        }

        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(self.rerank_url, json=payload, headers=headers)
            if r.status_code != 200:
                raise RuntimeError(f"Rerank 调用失败: {r.status_code} - {r.text}")

            data = r.json()

        rerank_results = data.get("results", [])
        # 按相关性得分降序排序（虽然 API 通常已排序，但显式处理更安全）
        rerank_results.sort(key=lambda x: x['relevance_score'], reverse=True)

        return [item["document"] for item in rerank_results[:top_k]]


rerank = RerankService()
