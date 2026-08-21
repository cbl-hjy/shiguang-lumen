"""并行 vs 串行补测（2026-08-20 简历数据口径补全）。

背景：原 bench（reports/groupB/bench_parallel_vs_serial.txt）是单次实测、脚本未保留，
简历 54% 被指口径不足（测几次/方差/基线定义）。本脚本重新补测：
- 5 个固定子任务（纯知识型，避免触发 web_search 等外部调用——测 LLM 研究调用的 I/O 并行收益）
- 串行基线 = 顺序逐个 await（for 循环），并行 = asyncio.gather
- 重复 3 次取均值/方差/中位数
用法：./.venv/Scripts/python.exe scripts/bench_parallel_rerun.py
"""
import asyncio
import statistics
import sys
import time

sys.path.insert(0, ".")

from app.agent.delegation import _build_sub_agent, _run_subtask

TASKS = [
    "用 3 句话说明向量检索和关键词检索各自的适用场景",
    "用 3 句话说明为什么长会话需要上下文压缩",
    "用 3 句话说明多 Agent 并行和串行的核心区别",
    "用 3 句话说明 RAG 检索中重排（rerank）的作用",
    "用 3 句话说明 LLM 评测中基线（baseline）的意义",
]

REPEATS = 3


async def run_serial() -> float:
    """串行基线：顺序逐个调用（for 循环 await，最朴素的基线定义）"""
    agents = [_build_sub_agent() for _ in TASKS]
    t0 = time.perf_counter()
    for a, t in zip(agents, TASKS):
        await _run_subtask(a, t)
    return time.perf_counter() - t0


async def run_parallel() -> float:
    """并行：asyncio.gather 同一批子任务"""
    agents = [_build_sub_agent() for _ in TASKS]
    t0 = time.perf_counter()
    await asyncio.gather(*[_run_subtask(a, t) for a, t in zip(agents, TASKS)])
    return time.perf_counter() - t0


async def main():
    serial_times, parallel_times = [], []
    for i in range(REPEATS):
        st = await run_serial()
        pt = await run_parallel()
        serial_times.append(st)
        parallel_times.append(pt)
        print(f"第{i+1}次: 串行 {st:.1f}s | 并行 {pt:.1f}s | 降 {(1-pt/st)*100:.0f}%", flush=True)

    sm, pm = statistics.mean(serial_times), statistics.mean(parallel_times)
    ss, ps = statistics.stdev(serial_times), statistics.stdev(parallel_times)
    med_s, med_p = statistics.median(serial_times), statistics.median(parallel_times)
    print("\n===== 补测结果（5 固定子任务 × 3 次重复）=====")
    print(f"串行: 均值 {sm:.1f}s  方差σ {ss:.2f}  中位数 {med_s:.1f}s")
    print(f"并行: 均值 {pm:.1f}s  方差σ {ps:.2f}  中位数 {med_p:.1f}s")
    print(f"耗时降低: {(1-pm/sm)*100:.1f}%（均值口径）| 中位数口径 {(1-med_p/med_s)*100:.1f}%")
    print(f"基线定义: 串行=for 循环顺序 await 同一批 5 子任务；并行=asyncio.gather 同批")


if __name__ == "__main__":
    asyncio.run(main())
