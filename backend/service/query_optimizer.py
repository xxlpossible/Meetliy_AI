"""
查询优化器：分类 + 改写

核心设计：LLM 一次调用完成查询分类和改写，返回结构化 JSON。
关键词匹配仅作为 LLM 调用失败时的兜底手段。

对外接口：
    QueryOptimizer.analyze_and_rewrite(question) -> dict
"""

import json
import asyncio
import re
from typing import Any

from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage
from loguru import logger

from settings import settings

# ---------------------------------------------------------------------------
# 查询分类 Prompt
# ---------------------------------------------------------------------------
_CLASSIFY_AND_REWRITE_PROMPT = """你是一个查询分析器。分析用户的问题，完成两项任务：
1. 判断问题类型
2. 生成用于检索的改写查询

## 问题类型定义
- "概括性"：用户想了解会议整体内容、主题、结论、关键决策等全局信息
  示例："会议说了什么" / "有什么重要决定" / "这次会议达成了什么共识"
- "细节性"：用户想了解会议中某个具体话题、某人的观点、某个议题的讨论过程
  示例："张三对预算怎么看" / "关于产品发布的讨论" / "为什么选择方案A"
- "行动项"：用户想了解待办事项、任务分配、下一步计划
  示例："有哪些待办" / "下一步要做什么"
- "数据性"：用户想获取具体事实数据（时间、人数、数字）
  示例："会议开了多久" / "多少人参加" / "预算定了多少"

## 改写规则
- 概括性：生成 3-5 个具体检索查询，覆盖不同维度的会议信息
- 细节性：保留原问题 + 生成 2 个同义改写
- 行动项/数据性：不需要改写，原问题直接用于检索

## 输出格式
严格输出 JSON，不要包含其他内容：
{
  "query_type": "概括性|细节性|行动项|数据性",
  "rewritten_queries": ["查询1", "查询2", ...]
}

## 用户问题
{question}"""

# 合法的 query_type 枚举
_VALID_QUERY_TYPES = frozenset({"概括性", "细节性", "行动项", "数据性"})

# ---------------------------------------------------------------------------
# 关键词兜底规则
# ---------------------------------------------------------------------------
# 按优先级排序：(query_type, 触发词列表)
_KEYWORD_RULES: list[tuple[str, list[str]]] = [
    ("概括性", [
        "说了什么", "讲了什么", "总结", "概括", "主要内容", "会议纪要",
        "整体", "大概", "概述", "讨论了什么", "介绍了什么", "会议内容",
        "会上说了", "聊了什么", "开了什么会", "关键决策", "重要决定",
        "共识", "结论", "成果",
    ]),
    ("行动项", [
        "行动项", "待办", "任务", "下一步", "要做", "跟进",
        "action", "todo", "后续安排",
    ]),
    ("数据性", [
        "多少", "几个", "数量", "什么时候", "什么时间", "几点",
        "哪一天", "日期", "多长时间",
    ]),
    ("细节性", [
        "具体", "关于", "细节", "详细", "谁说", "怎么", "如何",
        "为什么", "方案", "预算", "看法", "观点", "意见",
    ]),
]

# 概括性兜底改写（规则生成，不调 LLM）
_OVERVIEW_FALLBACK_QUERIES = [
    "会议讨论了哪些主要议题",
    "会议中有哪些重要决定和结论",
    "会议中提到了哪些关键信息和观点",
]


class QueryOptimizer:
    """查询优化器：LLM 分类+改写（主）+ 关键词规则（兜底）。"""

    def __init__(self):
        rewrite_model = settings.get_rewrite_model_config()
        self._model = init_chat_model(
            model=rewrite_model.get('model', "Qwen/Qwen2.5-7B-Instruct"),
            model_provider="openai",
            api_key=rewrite_model.get('api_key', None),
            base_url=rewrite_model.get('base_url', "https://api.siliconflow.cn/v1"),
            temperature=0.1,
            top_p=0.8,
            model_kwargs={"enable_thinking": False},
        )
        self._llm_timeout: float = 15.0  # LLM 调用超时（秒），分类+改写需要足够的推理时间

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------
    async def analyze_and_rewrite(self, question: str) -> dict[str, Any]:
        """
        LLM 分类 + 改写，失败时自动降级到关键词兜底。

        Returns:
            {
                "query_type": "概括性" | "细节性" | "行动项" | "数据性" | "unknown",
                "rewritten_queries": ["查询1", ...],
                "method": "llm" | "keyword"     # 实际使用的方法
            }
        """
        try:
            result = await asyncio.wait_for(
                self._call_llm(question),
                timeout=self._llm_timeout,
            )
            logger.info(f"[QueryOptimizer] LLM 分类+改写成功 -> type={result['query_type']}")
            return {**result, "method": "llm"}
        except asyncio.TimeoutError:
            logger.warning("[QueryOptimizer] LLM 调用超时，降级为关键词兜底")
        except Exception as e:
            logger.warning(f"[QueryOptimizer] LLM 调用失败: {e}，降级为关键词兜底")

        # 兜底
        return self._keyword_fallback(question)

    @classmethod
    def classify_by_keyword(cls, question: str) -> str:
        """
        纯关键词分类（公开方法，用于兜底和测试）。

        Returns:
            "概括性" | "细节性" | "行动项" | "数据性" | "unknown"
        """
        for query_type, triggers in _KEYWORD_RULES:
            for token in triggers:
                if token in question:
                    return query_type
        return "unknown"

    @staticmethod
    def get_fallback_queries(query_type: str, question: str) -> list[str]:
        """按类型生成兜底改写查询（不调 LLM）。"""
        if query_type == "概括性":
            return list(_OVERVIEW_FALLBACK_QUERIES)
        elif query_type == "细节性":
            # 规则：去掉语气词 + 添加查询后缀
            cleaned = re.sub(r"[吗呢呀啊吧的]", "", question)
            return [
                question,
                f"关于{cleaned}的讨论",
                f"{cleaned}的具体内容",
            ]
        else:
            # 行动项 / 数据性 / unknown：原问题直接使用
            return [question]

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------
    async def _call_llm(self, question: str) -> dict[str, Any]:
        """调用 LLM 获取分类 + 改写结果。"""
        # 注意：不能用 .format()，因为 prompt 中的 JSON 示例包含 {query_type} 等花括号
        prompt = _CLASSIFY_AND_REWRITE_PROMPT.replace("{question}", question)
        response = None
        content = ""

        try:
            response = await self._model.ainvoke([HumanMessage(content=prompt)])
            raw = getattr(response, "content", "")

            # 防御：LangChain 某些模型返回的 content 可能是 list[dict] 而非 str
            if isinstance(raw, list):
                content = "".join(
                    block.get("text", "") if isinstance(block, dict) else str(block)
                    for block in raw
                )
            elif isinstance(raw, str):
                content = raw
            else:
                content = str(raw)

            # 尝试提取 JSON（LLM 可能在 JSON 前后附加文字）
            json_text = self._extract_json(content)

            parsed: dict = json.loads(json_text)

            # DEBUG: 打印 LLM 原始输出和解析结果，方便排查改写模型行为
            logger.debug(
                f"[QueryOptimizer] LLM 原始输出 (前800字符): {content[:800]}\n"
                f"  JSON 提取结果: {json_text[:400]}\n"
                f"  解析字段: query_type={parsed.get('query_type')!r}, "
                f"queries={parsed.get('rewritten_queries')!r}"
            )

        except json.JSONDecodeError as e:
            logger.error(
                f"[QueryOptimizer] JSON 解析失败: {e}\n"
                f"  原始 LLM 输出 (前500字符): {content[:500]}\n"
                f"  提取的 JSON 文本 (前300字符): {json_text[:300]}"
            )
            raise
        except Exception as e:
            # 捕获其他所有异常（网络错误、API 错误、类型错误等）
            content_preview = ""
            try:
                content_preview = content[:500]
            except Exception:
                content_preview = repr(content)[:500]
            raw_preview = ""
            try:
                raw_preview = str(getattr(response, "content", ""))[:300]
            except Exception:
                raw_preview = repr(response)[:300]
            logger.error(
                f"[QueryOptimizer] LLM 调用异常 ({type(e).__name__}): {e}\n"
                f"  LLM 原始响应 (前300字符): {raw_preview}\n"
                f"  处理后内容 (前500字符): {content_preview}"
            )
            raise

        query_type = parsed.get("query_type", "").strip()
        rewritten = parsed.get("rewritten_queries", [])

        # 验证 query_type 是否合法
        if query_type not in _VALID_QUERY_TYPES:
            logger.warning(
                f"[QueryOptimizer] LLM 返回非法的 query_type={query_type}，"
                f"降级为关键词分类"
            )
            raise ValueError(f"Invalid query_type: {query_type}")

        # 确保 rewritten_queries 不为空
        if not rewritten or not isinstance(rewritten, list):
            rewritten = [question]

        return {
            "query_type": query_type,
            "rewritten_queries": [q for q in rewritten if q and isinstance(q, str)],
        }

    @staticmethod
    def _extract_json(text: str) -> str:
        """
        从 LLM 响应中提取 JSON 内容，增强容错处理。

        处理以下常见非规范输出：
        - markdown 代码块包裹（```json ... ```）
        - JSON 前后附加了自然语言说明
        - 嵌套花括号（从最外层对象正确截取）
        - 尾随逗号
        - JavaScript 风格注释
        - 非法控制字符
        """
        if not text or not text.strip():
            return "{}"

        text = text.strip()

        # 1. 优先提取 markdown 代码块
        md_match = re.search(
            r'```(?:json)?\s*\n?(.*?)\n?\s*```',
            text, re.DOTALL | re.IGNORECASE,
        )
        if md_match:
            text = md_match.group(1).strip()

        # 2. 使用平衡括号匹配提取最外层 JSON 对象（正确处理嵌套和字符串内的花括号）
        json_text = QueryOptimizer._extract_balanced_braces(text)
        if not json_text:
            return "{}"

        # 3. 修复常见 JSON 语法问题
        json_text = QueryOptimizer._sanitize_json(json_text)

        return json_text

    @staticmethod
    def _extract_balanced_braces(text: str) -> str | None:
        """
        提取最外层花括号之间的内容，正确处理：
        - 嵌套 JSON 对象/数组
        - 字符串字面量内的花括号和转义字符
        """
        start = text.find("{")
        if start == -1:
            return None

        depth = 0
        in_string = False
        escape_next = False

        for i, ch in enumerate(text):
            if i < start:
                continue

            if escape_next:
                escape_next = False
                continue

            if ch == '\\' and in_string:
                escape_next = True
                continue

            if ch == '"' and not escape_next:
                in_string = not in_string
                continue

            if in_string:
                continue

            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    return text[start:i + 1]

        # 括号不匹配时 fallback 到简单查找
        end = text.rfind("}")
        if end > start:
            return text[start:end + 1]
        return None

    @staticmethod
    def _sanitize_json(text: str) -> str:
        """修复 LLM 输出中常见的非规范 JSON 语法（仅做安全修正）。"""
        # 移除尾随逗号（对象和数组中的）
        text = re.sub(r',\s*([}\]])', r'\1', text)

        # 移除 JavaScript 风格的单行注释 //
        text = re.sub(r'//[^\n]*', '', text)

        # 移除 JavaScript 风格的多行注释 /* ... */
        text = re.sub(r'/\*.*?\*/', '', text, flags=re.DOTALL)

        # 移除非法控制字符（保留常见的空白字符）
        text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', text)

        return text

    def _keyword_fallback(self, question: str) -> dict[str, Any]:
        """关键词兜底：分类 + 规则改写。"""
        query_type = self.classify_by_keyword(question)
        rewritten = self.get_fallback_queries(query_type, question)
        logger.info(
            f"[QueryOptimizer] 关键词兜底 -> type={query_type}, "
            f"queries={len(rewritten)}"
        )
        return {
            "query_type": query_type,
            "rewritten_queries": rewritten,
            "method": "keyword",
        }
