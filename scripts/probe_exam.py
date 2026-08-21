"""exam_crammer 学习维度纯测：验证模型是否自主 remember（不依赖困惑钩子）"""
import asyncio
import sys
import time

sys.path.insert(0, ".")
import requests

TOKEN = ""
for line in open(".env", encoding="utf-8"):
    if line.startswith("SHIGUANG_TOKEN="):
        TOKEN = line.split("=", 1)[1].strip()
BASE = "http://127.0.0.1:9000"


async def main():
    r = requests.post(f"{BASE}/api/session/new", headers={"Authorization": f"Bearer {TOKEN}"}, timeout=15)
    sid = r.json()["session_id"]
    print("会话:", sid[:8])
    msgs = [
        "我最近在准备算法岗面试，从机器学习基础开始复习",
        "今天学完了梯度下降，损失函数那块还没吃透",
        "我的目标是秋招进大厂做AI岗，在刷LeetCode",
    ]
    for i, m in enumerate(msgs, 1):
        resp = requests.post(
            f"{BASE}/api/chat",
            json={"message": m, "session_id": sid},
            headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
            stream=True, timeout=120,
        )
        lines = [ln for ln in resp.iter_lines(decode_unicode=True) if ln] if resp.status_code == 200 else []
        print(f"轮{i} HTTP={resp.status_code} 回复{len(lines)}行")
        time.sleep(1.5)
    um = open("data-experiment/memory/user_memory.md", encoding="utf-8").read()
    print("=== 记忆文件 ===")
    print(um if um.strip() else "(空——模型没有写任何记忆)")


if __name__ == "__main__":
    asyncio.run(main())
