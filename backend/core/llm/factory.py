"""LLM 模型工厂 —— 统一管理各类模型的初始化。

当前管理的模型：
- chat_model:     主对话模型（ChatAgent / MeetingAgent 共用）
- router_model:   意图路由分类模型（ChatAgent Router 节点）
- rewrite_model:  查询改写模型（query_optimizer）
- embeddings:     Embedding 模型（rag/embedding）
- rerank:         重排序模型（rag/rerank）

各 Agent 和 RAG 模块通过本工厂获取模型实例，避免在各处重复从 settings 读取配置。
"""

from langchain.chat_models import init_chat_model

from settings import settings


class ModelFactory:
    """模型工厂 —— 惰性加载各模型实例。"""

    def __init__(self):
        self._chat_model = None
        self._router_model = None
        self._rewrite_model = None

    @property
    def chat_model(self):
        """主对话模型（ChatAgent / MeetingAgent 共用）。"""
        if self._chat_model is None:
            cfg = settings.get_chat_model_config()
            self._chat_model = init_chat_model(
                model=cfg.get('model', "qwen3.5-flash"),
                model_provider="openai",
                api_key=cfg.get('api_key', None),
                base_url=cfg.get('base_url', "https://dashscope.aliyuncs.com/compatible-mode/v1"),
            )
        return self._chat_model

    @property
    def router_model_config(self) -> dict:
        """Router 模型配置（含 structured_output 需求）。"""
        chat_cfg = settings.get_chat_model_config()
        router_cfg = settings.get_router_model_config()
        return {
            'model': router_cfg.get('model', "qwen3.5-flash"),
            'api_key': router_cfg.get('api_key') or chat_cfg.get('api_key'),
            'base_url': router_cfg.get('base_url') or chat_cfg.get('base_url', "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        }

    @property
    def rewrite_model(self):
        """查询改写模型。"""
        if self._rewrite_model is None:
            cfg = settings.get_rewrite_model_config()
            chat_cfg = settings.get_chat_model_config()
            self._rewrite_model = init_chat_model(
                model=cfg.get('model', "qwen3.5-flash"),
                model_provider="openai",
                api_key=cfg.get('api_key') or chat_cfg.get('api_key'),
                base_url=cfg.get('base_url') or chat_cfg.get('base_url', "https://dashscope.aliyuncs.com/compatible-mode/v1"),
            )
        return self._rewrite_model


# 全局单例
model_factory = ModelFactory()
