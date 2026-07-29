"""
Graph 运行效率测试脚本

测试 Router -> 三路检索 -> Context_Builder -> LLM 的完整链路性能，
通过 mock 外部服务（LLM / 向量库 / rerank）排除网络 IO 干扰，
聚焦测量 Graph 编排本身的开销。

用法：  cd backend && .venv\Scripts\python.exe benchmark_graph.py
"""

import asyncio
import logging
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent))

# ---- 必须在 import service 之前抑制所有日志 ----
logging.getLogger('sqlalchemy.engine').setLevel(logging.ERROR)
# 延迟导入 loguru 以在服务模块导入前配置
from loguru import logger as _loguru_logger
_loguru_logger.remove()
_loguru_logger.add(sys.stderr, level="ERROR")

SEP = "=" * 60
SEP2 = "-" * 60


@dataclass
class StageTiming:
    scenario: str
    total_ms: float = 0.0


# ---------------------------------------------------------------------------
# Mock 数据工厂
# ---------------------------------------------------------------------------
def _make_search_result(n_docs: int = 5) -> dict:
    docs = [f"mock_doc_chunk_{i}: 模拟向量检索结果第{i}段." for i in range(n_docs)]
    metas = [{"chunk_index": i, "doc_type": "fine_chunk"} for i in range(n_docs)]
    return {"documents": [docs], "metadatas": [metas],
            "distances": [[0.1 + i * 0.05 for i in range(n_docs)]]}


def _make_memory_results(n: int = 3) -> list[str]:
    return [f"历史记忆_{i}: 之前讨论过相关话题。" for i in range(n)]


# ---------------------------------------------------------------------------
# 核心: 单场景 Benchmark
# ---------------------------------------------------------------------------
async def run_benchmark(
    scenario: str,
    meeting_ids: list[str] | None = None,
    need_kb: bool = False,
    knowledge_ids: list[str] | None = None,
    iterations: int = 5,
) -> StageTiming:
    """
    运行一个 Graph 场景并测量耗时。
    通过 mock 将 Router / LLM / DB / rerank 全部替换为 AsyncMock，
    仅测量 Graph 编排开销。
    """
    from service.llm_graph_service import ChatAgent
    from service.context_builder import SESSION_HISTORY
    from langchain_core.messages import AIMessage

    question = "张三在产品发布会上关于性能测试说了什么？"
    session_id = f"bm_{scenario}_{int(time.time() * 1000)}"
    SESSION_HISTORY.pop(session_id, None)

    print(f"\n{SEP}")
    print(f"  场景: {scenario}")
    print(f"  meeting_ids={meeting_ids}, need_kb={need_kb}, knowledge_ids={knowledge_ids}")
    print(f"  问题: {question}")
    print(f"  迭代: {iterations} 次")
    print(f"{SEP2}")

    timing = StageTiming(scenario=scenario)

    for run_i in range(iterations):
        agent = ChatAgent()

        # ---- 直接替换 agent 的节点方法 ----
        agent._router_node = AsyncMock(return_value={
            "router_result": {
                "intent": "detail", "speaker": ["张三"], "topic": ["产品发布"],
                "keywords": ["测试", "性能", "Graph"], "confidence": 0.92,
            },
            "query_type": "细节性",
        })
        agent._llm_call = AsyncMock(return_value={
            "messages": [AIMessage(content="[mock] 张三在发布会上重点提到性能测试...")]
        })

        # ---- 替换外部依赖 ----
        with (
            patch('utils.siliconflow_embedding.db_manager.search',
                  MagicMock(return_value=_make_search_result(8))),
            patch('service.llm_graph_service.retrieve_past_memory',
                  MagicMock(return_value=_make_memory_results(3))),
            patch('service.llm_graph_service.rerank.rerank_context',
                  AsyncMock(return_value=[f"reranked_{i}" for i in range(5)])),
            patch('service.llm_graph_service.rerank.rerank_multi_collection',
                  AsyncMock(return_value=([f"kb_reranked_{i}" for i in range(3)], {}))),
        ):
            compiled = agent._build_graph()

            initial_state = {
                "messages": [], "question": question,
                "meeting_ids": meeting_ids or [], "knowledge_ids": knowledge_ids or [],
                "session_id": session_id, "user_id": 1,
                "need_kb": need_kb, "turn_index": 0,
                "meeting_content": [], "kb_snippets": "",
                "memory_content": [], "query_type": "细节性",
                "fallback_level": 0, "router_result": None, "user_notice": "",
            }

            t0 = time.perf_counter()
            final_state = await compiled.ainvoke(initial_state)
            t1 = time.perf_counter()
            elapsed_ms = (t1 - t0) * 1000
            timing.total_ms += elapsed_ms

            has_meeting = len(final_state.get("meeting_content", [])) > 0
            has_kb = bool(final_state.get("kb_snippets", ""))
            has_memory = len(final_state.get("memory_content", [])) > 0
            print(
                f"  Run {run_i + 1}: {elapsed_ms:.1f} ms  "
                f"| meeting={has_meeting} kb={has_kb} memory={has_memory}"
            )

    timing.total_ms /= iterations
    print(f"{SEP2}")
    print(f"  >>> 平均耗时: {timing.total_ms:.1f} ms")
    print(f"{SEP}")
    return timing


# ---------------------------------------------------------------------------
# 延迟模拟: 验证并行能力
# ---------------------------------------------------------------------------
async def run_with_delay(scenario: str, delay_ms: float = 50.0,
                         need_kb: bool = False):
    """
    在 mock 中加入 asyncio.sleep 模拟真实网络 IO，
    如果三路检索是并行的，总耗时应远小于串行求和。
    """
    from service.llm_graph_service import ChatAgent
    from service.context_builder import SESSION_HISTORY
    from langchain_core.messages import AIMessage

    question = "张三在产品发布会上关于性能测试说了什么？"
    session_id = f"bm_delay_{scenario}_{int(time.time() * 1000)}"
    SESSION_HISTORY.pop(session_id, None)

    meeting_ids = ["meeting_001"]
    knowledge_ids = ["kb_001"] if need_kb else []

    async def delayed_router(state):
        await asyncio.sleep(delay_ms / 1000.0)
        return _make_router_dict()

    async def delayed_llm(state):
        await asyncio.sleep(delay_ms / 1000.0)
        return _make_llm_dict()

    async def delayed_rerank(*a, **kw):
        await asyncio.sleep(delay_ms / 1000.0)
        return [f"r_{i}" for i in range(5)]

    async def delayed_rerank_multi(*a, **kw):
        await asyncio.sleep(delay_ms / 1000.0)
        return ([f"kb_r_{i}" for i in range(3)], {})

    agent = ChatAgent()

    # Router + LLM 节点替换为带延迟的 mock
    agent._router_node = AsyncMock(side_effect=delayed_router)
    agent._llm_call = AsyncMock(side_effect=delayed_llm)

    with (
        patch('utils.siliconflow_embedding.db_manager.search',
              MagicMock(return_value=_make_search_result(8))),
        patch('service.llm_graph_service.retrieve_past_memory',
              MagicMock(return_value=_make_memory_results(3))),
        patch('service.llm_graph_service.rerank.rerank_context',
              AsyncMock(side_effect=delayed_rerank)),
        patch('service.llm_graph_service.rerank.rerank_multi_collection',
              AsyncMock(side_effect=delayed_rerank_multi)),
    ):
        compiled = agent._build_graph()

        initial_state = {
            "messages": [], "question": question,
            "meeting_ids": meeting_ids, "knowledge_ids": knowledge_ids,
            "session_id": session_id, "user_id": 1,
            "need_kb": need_kb, "turn_index": 0,
            "meeting_content": [], "kb_snippets": "",
            "memory_content": [], "query_type": "细节性",
            "fallback_level": 0, "router_result": None, "user_notice": "",
        }

        t0 = time.perf_counter()
        await compiled.ainvoke(initial_state)
        t1 = time.perf_counter()
        elapsed_ms = (t1 - t0) * 1000

    # 理论串行: router + meeting(含rerank) + memory + context + llm [+ kb(含rerank)]
    serial_calls = 5 if need_kb else 4
    serial_ms = serial_calls * delay_ms

    print(f"\n  [{scenario}] 每步延迟 {delay_ms}ms:")
    print(f"    实际耗时:       {elapsed_ms:.1f} ms")
    print(f"    理论串行耗时:   {serial_ms:.0f} ms  ({serial_calls} 步)")
    print(f"    并行增益:       {max(0, serial_ms - elapsed_ms):.1f} ms")
    return elapsed_ms


def _make_router_dict():
    return {
        "router_result": {
            "intent": "detail", "speaker": ["张三"], "topic": ["产品发布"],
            "keywords": ["测试", "性能"], "confidence": 0.85,
        },
        "query_type": "细节性",
    }


def _make_llm_dict():
    from langchain_core.messages import AIMessage
    return {"messages": [AIMessage(content="[mock] 带延迟的模拟回答。")]}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
async def main():
    print(SEP)
    print("  Graph 运行效率 Benchmark")
    print(SEP)
    print()
    print("  模式: Mock 外部依赖（排除网络/DB IO）")
    print()

    # ====== Part 1: 纯编排开销 ======
    print("\n  >>> Part 1: 纯 Graph 编排开销（零延迟 mock）\n")

    results: list[StageTiming] = []

    t = await run_benchmark(
        "A_完整三路（meeting+memory+KB）",
        meeting_ids=["meeting_001", "meeting_002"],
        need_kb=True, knowledge_ids=["kb_001"],
        iterations=5,
    )
    results.append(t)

    t = await run_benchmark(
        "B_会议+记忆（无KB）",
        meeting_ids=["meeting_001"],
        need_kb=False,
        iterations=5,
    )
    results.append(t)

    t = await run_benchmark(
        "C_无会议",
        meeting_ids=[], need_kb=False,
        iterations=5,
    )
    results.append(t)

    # ====== Part 2: 延迟模拟 ======
    print(f"\n  >>> Part 2: 模拟延迟测试（验证并行能力）\n")

    await run_with_delay("完整三路_50ms延迟", delay_ms=50, need_kb=True)
    await run_with_delay("会议+记忆_50ms延迟", delay_ms=50, need_kb=False)

    # ====== 汇总 ======
    print(f"\n\n{SEP}")
    print(f"  Benchmark 汇总（零延迟 mock）")
    print(f"{SEP}")
    print(f"  {'场景':<35} {'平均耗时':>10}")
    print(f"  {'-' * 45}")
    for r in results:
        print(f"  {r.scenario:<35} {r.total_ms:>8.1f} ms")
    print(f"{SEP}")


if __name__ == "__main__":
    asyncio.run(main())
