"""压力面试深度体验驱动：连续单场 30 轮（页面不刷新、情绪不重置）。
每轮：fill 台词 → Enter → 轮询流式完成（innerText 长度稳定）→ 记录回答+工具链 → 下一条。
纪律：只操作浏览器 UI（agent-browser CLI 连 daemon），零直连数据文件。
"""
import json
import re
import subprocess
import sys
import time
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent.parent / "data" / "ux_stress"
OUT.mkdir(exist_ok=True)

# Windows：agent-browser 是 shell 脚本（内部 exec node）。Python subprocess 的 'bash' 会解析到 WSL bash（无 node），
# 直接用 node + 入口 js 最稳（绕开 bash 歧义）
NODE = r"C:\Users\17680\.workbuddy\binaries\node\versions\22.22.2\node.exe"
AB_ENTRY = r"D:\work_buddy\.caches\npm-global\node_modules\agent-browser\bin\agent-browser.js"
TOOL_NAMES = {
    "remember", "search_memory", "update_profile", "forget",
    "web_search", "python_sandbox", "ocr_image", "read_document",
    "kb_search", "kb_ingest", "schedule_wakeup", "cancel_wakeup",
    "log_learning", "deleg_study", "reflect_teaching", "save_skill", "search_skills",
}

# ---------------- 30 轮剧本（方案 v2：压力面试 + 情绪注入 + 多场景） ----------------
LINES = [
    # A. 开场建立场景（3）
    "我在准备算法岗面试，咱们模拟一场面试：你当面试官出题，我回答，你可以随意追问，越严格越好",
    "先说明一下我的水平：本科学过一点机器学习，深度学习了解概念但没系统学过，大模型是最近开始自学的",
    "咱们按真实面试来，你不用客气，该追问就追问，该给压力就给压力",
    # B. 压力面试·Transformer 专题（14）
    "好，开始吧。第一个问题：讲讲注意力机制，什么是 attention",
    "Q、K、V 分别是什么？具体怎么算的？矩阵维度给我说清楚",
    "为什么除以根号 d_k？不除会怎么样？",
    "你能不能讲快点，我赶时间，直接说重点",
    "mask 是干嘛的？训练的时候和推理的时候用的 mask 一样吗？",
    "你刚才第 2 轮说的 Q 和 V 的区别，再说一遍，我有点忘了",
    "给我个具体数值例子：序列长度 3、d=512，attention 矩阵是多大？怎么算的",
    "你说的不对吧，我记得 attention 根本不用 softmax，你是不是记错了",
    "你讲的什么玩意？完全没听懂！重讲！",
    "好，现在用一句话说清楚 attention 到底在干嘛，不许用任何术语",
    "等等，回到你刚才说的 mask，还没讲完，继续",
    "你刚才说 QKV 是同一个输入乘三个矩阵得到的，那为什么叫『查询』？它查询谁？",
    "真棒，又给我背了一遍百科，谁不知道这些概念啊",
    "哎，这轮讲得不错，比前面强多了，继续保持",
    # C. 快问快答·ML 基础（5）
    "换个题：过拟合怎么判断？30 秒内说完",
    "算了，我觉得我学不会这些东西了，越学越乱",
    "L1 和 L2 正则化的区别，用类比讲",
    "softmax 的温度系数是干嘛的？和那个根号 d_k 有关系吗？",
    "别再整这些虚的了，直接告诉我面试要背哪几条结论",
    # D. 场景切换（5）
    "不面了，帮我写个 Python 函数：输入字符串列表，返回去重后的列表，保持顺序",
    "这个函数还能优化吗？用生成器写",
    "再帮我画个 RAG 检索增强的流程图",
    "帮我记一下：面试的时候要注意，讲概念先讲直觉再讲细节",
    "你面了我这么多轮，你觉得我大概什么水平？客观评价一下",
    # E. 收尾（3）
    "面了这么多，给我打个分吧，你觉得我这场表现怎么样",
    "唉，我觉得我面试肯定完蛋了，学的东西都是散的",
    "最后说说，你今天这场面试体验下来，觉得我有哪些可以改进的？",
]


def ab(args: list[str]) -> str:
    """调用 agent-browser CLI（node 直接执行入口 js），返回 stdout"""
    r = subprocess.run(
        [NODE, AB_ENTRY, *args],
        capture_output=True, text=True, encoding="utf-8", errors="ignore", timeout=120,
    )
    return r.stdout.strip()


def page_text() -> str:
    return ab(["eval", "document.querySelector('main').innerText || ''"])


def extract_tools(new_text: str) -> list[str]:
    """从新增页面文本里找工具名（工具卡片可见性）"""
    return [t for t in TOOL_NAMES if re.search(rf"\b{t}\b", new_text)]


def wait_stream_done(max_wait: int = 180) -> int:
    """轮询 main.innerText 长度，连续 2 次不变 = 流式完成。返回稳定长度"""
    last_len, stable = -1, 0
    t0 = time.time()
    while time.time() - t0 < max_wait:
        n = len(page_text())
        if n == last_len:
            stable += 1
            if stable >= 2:
                return n
        else:
            stable = 0
        last_len = n
        time.sleep(3)
    return last_len


def main():
    rows = []
    for i, line in enumerate(LINES, 1):
        t0 = time.time()
        ab(["fill", "textarea", line])
        ab(["press", "Enter"])
        wait_stream_done()
        total = page_text()
        dt = time.time() - t0
        # 本轮新增回答：取最后 ~600 字符（简化：记录总量与新增工具）
        prev = rows[-1]["total_len"] if rows else 0
        new_text = total[prev:] if len(total) > prev else ""
        tools = extract_tools(new_text)
        row = {
            "round": i,
            "line": line[:30],
            "sec": round(dt, 1),
            "total_len": len(total),
            "new_len": len(new_text),
            "tools": tools,
        }
        rows.append(row)
        print(f"[{i:>2}/30] {row['sec']}s new={row['new_len']} tools={tools} {row['line']}...", flush=True)
        (OUT / "log.jsonl").open("a", encoding="utf-8").write(json.dumps(row, ensure_ascii=False) + "\n")
    print("=== 30 轮完成 ===", flush=True)


if __name__ == "__main__":
    main()
