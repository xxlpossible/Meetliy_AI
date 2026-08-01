from pathlib import Path
from typing import Any

import chromadb
import requests
from loguru import logger

from settings import settings

# 默认持久化路径：backend/chroma_db/（与本文件所在 utils/ 目录同级）
_DEFAULT_PERSIST_DIR = Path(__file__).resolve().parent.parent / "chroma_db"


# 硅基流动嵌入模型工具类
class SiliconFlowEmbeddingTool:
    def __init__(
            self,
    ):
        embeddings = settings.get_embeddings_config()
        self.api_key = embeddings.get('api_key', None)
        self.model_name = embeddings.get('model', "BAAI/bge-large-zh-v1.5")
        self.url = embeddings.get('base_url', "https://api.siliconflow.cn/v1/embeddings")

    def get_embeddings(self, texts: list[str]) -> list[list[float]]:
        """调用 API 将一组文本转换为向量"""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.model_name,
            "input": texts
        }

        try:
            response = requests.post(self.url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
            # 提取向量并保持顺序
            return [item['embedding'] for item in data['data']]
        except Exception as e:
            logger.error(f"调用 SiliconFlowEmbedding 获取 Embedding 失败: {e}")
            raise


# ==========================================
# 工具类 2: ChromaDB 管理工具类
# ==========================================
class ChromaDBManager:
    def __init__(
            self,
            embedding_tool: SiliconFlowEmbeddingTool = SiliconFlowEmbeddingTool(),
            persist_path: str | None = None,
    ):
        """
        初始化 ChromaDB
        :param embedding_tool: 上面定义的硅基流动工具类实例
        :param persist_path: 数据库持久化存储路径，默认 backend/chroma_db/
        """
        if persist_path is None:
            persist_path = str(_DEFAULT_PERSIST_DIR)
        self.embedding_tool = embedding_tool
        # 确保持久化目录存在
        Path(persist_path).mkdir(parents=True, exist_ok=True)
        # 初始化持久化客户端（数据会存到硬盘）
        self.client = chromadb.PersistentClient(path=persist_path)

    def get_or_create_collection(self, name: str):
        """获取或创建集合"""
        return self.client.get_or_create_collection(
            name=name,
            metadata={"hnsw:space": "cosine"}
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

    def add_documents(
            self,
            collection_name: str,
            documents: list[str],
            metadatas: list[dict] | None = None,
            ids: list[str] | None = None
    ):
        """
        存储文档及其向量
        """
        if ids is None:
            import uuid
            ids = [str(uuid.uuid4()) for _ in documents]

        # 1. 先通过硅基流动工具类获取向量
        embeddings = self.embedding_tool.get_embeddings(documents)

        collection = self.get_or_create_collection(collection_name)

        # 2. 将文档、向量、元数据一并存入 ChromaDB
        collection.add(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas
        )
        logger.info(f"成功往向量库中存入 {len(documents)} 条文档")

    def search(
        self,
        collection_name: str,
        query_text: str,
        n_results: int = 5,
        where: dict | None = None
    ) -> dict[str, Any]:
        """
        向量查询
        
        Args:
            collection_name: 集合名称
            query_text: 查询文本
            n_results: 返回结果数量
            where: 可选， metadata 过滤条件（ChromaDB where 语法）
                   例如 {"session_id": "xxx"} 或 {"$or": [{"role": "user"}, {"role": "assistant"}]}
        """
        # 1. 将查询词转换为向量
        query_embedding = self.embedding_tool.get_embeddings([query_text])[0]

        collection = self.get_or_create_collection(collection_name)

        # 2. 在 ChromaDB 中进行向量搜索
        query_params = {
            "query_embeddings": [query_embedding],
            "n_results": n_results,
            "include": ["documents", "metadatas", "distances"]
        }
        # 如果有 where 条件，加入查询参数
        if where is not None:
            query_params["where"] = where
            
        results = collection.query(**query_params)
        return results

    def get_by_file_id_and_knowledge_id(self, file_id: str, knowledge_id: str):
        collection_name = f"collection_kb_{knowledge_id}"
        collection = self.get_or_create_collection(collection_name)
        # 先获取集合总数，再用 where 条件过滤
        total = collection.count()
        if total == 0:
            logger.info(f"集合 {collection_name} 为空")
            return {"ids": [], "documents": [], "metadatas": []}
        results = collection.get(
            where={"file_id": {"$eq": file_id}},
            include=["documents", "metadatas"]
        )
        logger.info(f"已从集合 {collection_name} 查询文件片段: {file_id}, 结果数: {len(results.get('ids', []))}")
        return results

    def get_by_chunk_index_range(
        self,
        collection_name: str,
        start_index: int,
        end_index: int,
    ) -> list[str]:
        """
        按 chunk_index 范围查询文档（用于相邻扩展，不依赖向量相似度）。

        Args:
            collection_name: 集合名称
            start_index: 起始 chunk_index（包含）
            end_index: 结束 chunk_index（不包含）

        Returns:
            匹配的文档文本列表
        """
        try:
            collection = self.client.get_collection(collection_name)
            results = collection.get(
                where={
                    "$and": [
                        {"chunk_index": {"$gte": start_index}},
                        {"chunk_index": {"$lt": end_index}},
                    ]
                },
                include=["documents", "metadatas"]
            )
            docs = results.get("documents", []) or []
            metadatas = results.get("metadatas", []) or []

            # 按 chunk_index 排序返回
            indexed: list[tuple[int, str]] = []
            for doc, meta in zip(docs, metadatas):
                if doc and meta:
                    idx = meta.get("chunk_index", -1)
                    if idx >= 0:
                        indexed.append((idx, str(doc)))

            indexed.sort(key=lambda x: x[0])
            return [doc for _, doc in indexed]
        except Exception as e:
            logger.warning(f"按 chunk_index 范围查询失败 (collection={collection_name}): {e}")
            return []

    def delete_by_file_id(self, knowledge_id: str, file_id: str):
        """
        根据 file_id 删除指定知识库中的所有相关向量片段
        """
        collection_name = f"collection_kb_{knowledge_id}"
        # 获取集合（如果集合不存在，get_or_create 也没问题，但通常删除时集合应该存在）
        try:
            collection = self.client.get_collection(collection_name)
        except Exception:
            # 如果集合都不存在，说明肯定没数据，直接返回即可
            logger.warning(f"集合 {collection_name} 不存在，跳过 Chroma 删除步骤")
            return

        # 使用 where 条件直接删除
        collection.delete(
            where={"file_id": {"$eq": file_id}}
        )
        logger.info(f"已从集合 {collection_name} 中删除 file_id={file_id} 的所有向量")

    def delete_by_session_id(self, user_id: int, session_id: str):
        """
        根据 session_id 删除指定用户聊天记忆集合中的相关向量。
        
        Args:
            user_id: 用户ID，用于定位集合 chat_memory_{user_id}
            session_id: 会话ID，作为 metadata 过滤条件
        """
        collection_name = f"chat_memory_{user_id}"
        try:
            collection = self.client.get_collection(collection_name)
        except Exception:
            logger.warning(f"集合 {collection_name} 不存在，跳过 Chroma 删除步骤")
            return

        # 使用 where 条件删除 session_id 匹配的文档
        collection.delete(
            where={"session_id": {"$eq": session_id}}
        )
        logger.info(f"已从集合 {collection_name} 中删除 session_id={session_id} 的所有向量")


db_manager = ChromaDBManager()

# if __name__ == "__main__":
#     # 2. 实例化 ChromaDB 管理类
#     db_manager = ChromaDBManager()
#
#     # 3. 存储数据
#     test_docs = [
#         "硅基流动提供高性能的嵌入模型服务。",
#         "ChromaDB 是一个轻量级的向量数据库。",
#         "人工智能正在改变世界。"
#     ]
#     t_id = "123456"
#     collection_name = f"collection_{t_id}"
#     test_metas = [{"source": "news"}, {"source": "tech"}, {"source": "philosophy"}]
#     db_manager.add_documents(collection_name=collection_name, documents=test_docs, metadatas=test_metas)
#
#     # 4. 查询数据
#     query = "硅基流动好用吗？"
#     search_results = db_manager.search(collection_name, query, n_results=1)
#
#     print("\n查询结果:")
#     for i in range(len(search_results['ids'][0])):
#         print(f"ID: {search_results['ids'][0][i]}")
#         print(f"文档内容: {search_results['documents'][0][i]}")
#         print(f"相似度距离: {search_results['distances'][0][i]}")
#         print(f"元数据: {search_results['metadatas'][0][i]}")