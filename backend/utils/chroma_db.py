# backend/utils/chroma_client.py
import chromadb
from chromadb.utils import embedding_functions
from typing import List, Dict, Any, Optional

from loguru import logger


class ChromaDBClient:
    def __init__(self, persist_dir: str = "./chroma_db", embedding_model: str = "bge-m3"):
        """
        初始化 ChromaDB 客户端

        :param persist_dir: 向量数据库持久化目录
        :param embedding_model: OpenAI embedding 模型名称
        """
        from settings import settings

        self.client = chromadb.PersistentClient(path=persist_dir)
        self.embedding_function = embedding_functions.OpenAIEmbeddingFunction(
            api_base="http://112.5.142.51:32251/v1-openai",
            api_key="sk-555a61c3d5034fdbba82e46bc030e7d0",
            model_name=embedding_model,
        )
        logger.info("chroma_db 初始化成功")

    def get_or_create_collection(self, name: str):
        """获取或创建集合"""
        return self.client.get_or_create_collection(
            name=name,
            embedding_function=self.embedding_function
        )

    def delete_collection(self, name: str) -> bool:
        """删除集合"""
        try:
            self.client.delete_collection(name)
            logger.info(f"集合已删除: {name}")
            return True
        except Exception as e:
            logger.error(f"删除集合失败: {e}")
            return False

    def list_collections(self) -> List[str]:
        """列出所有集合"""
        return [c.name for c in self.client.list_collections()]

    # ---------------------------------------------------------------
    # 数据操作
    # ---------------------------------------------------------------

    def add_documents(
            self,
            collection_name: str,
            documents: List[str],
            ids: Optional[List[str]] = None
    ):
        """
        向集合中添加文本，Chroma 会自动生成向量（embedding_function 已绑定）
        （为避免单次请求过大，自动将 documents 每 20 条拆分为一批）
        :param collection_name: 集合名称
        :param documents: 文本列表
        :param ids: 每条数据的唯一ID（可选）
        """
        from loguru import logger
        import math

        collection = self.get_or_create_collection(collection_name)

        if not documents or not isinstance(documents, list):
            raise ValueError("documents 必须是非空列表")

        total_docs = len(documents)

        # 自动生成ID
        if ids is None:
            ids = [f"id_{i}" for i in range(total_docs)]

        # === 分批逻辑 ===
        batch_size = 20
        num_batches = math.ceil(total_docs / batch_size)

        for batch_idx in range(num_batches):
            start = batch_idx * batch_size
            end = min(start + batch_size, total_docs)
            docs_batch = documents[start:end]
            ids_batch = ids[start:end]

            try:
                collection.add(
                    documents=docs_batch,
                    ids=ids_batch
                )
                logger.info(
                    f"✅ 集合 {collection_name} 第 {batch_idx + 1}/{num_batches} 批添加成功，共 {len(docs_batch)} 条。")
            except Exception as e:
                logger.error(f"❌ 集合 {collection_name} 第 {batch_idx + 1}/{num_batches} 批添加失败：{e}")

        logger.info(f"🎯 已向集合 {collection_name} 添加完毕，总计 {total_docs} 条数据。")

    def query(
        self,
        collection_name: str,
        query_text: str,
        n_results: int = 5
    ) -> Dict[str, Any]:
        """
        从集合中检索最相似的文本段落
        :param collection_name: 集合名
        :param query_text: 查询文本（会自动转为向量）
        :param n_results: 返回数量
        :return: 查询结果字典
        """
        collection = self.get_or_create_collection(collection_name)

        result = collection.query(
            query_texts=[query_text],
            n_results=n_results
        )
        logger.info(f"已从集合 {collection_name} 查询文本: {query_text}")
        return result


# 单例实例（方便在项目中直接导入使用）
chromadb_client = ChromaDBClient()

if __name__ == "__main__":
    chromadb_client.get_or_create_collection(name="meeting_notes")
    # 添加数据
    docs = [
        "今天我们讨论了项目上线的准备工作。",
        "开发团队已经完成了功能测试。",
        "市场部建议推迟两周发布以优化宣传策略。"
    ]
    chromadb_client.add_documents("meeting_notes", documents=docs)

    # 查询数据
    query = "会议的重点是什么？"
    result = chromadb_client.query("meeting_notes", query_text=query)
    print(result)

