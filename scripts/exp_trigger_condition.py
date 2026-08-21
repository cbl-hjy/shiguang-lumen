"""exp_trigger_condition.py —— P0-2 触发条件对照实验（2026-08-18）

问题：收尾提炼（困惑/关系/续接点）当前挂在"本会话有记忆变化"上。
假设：若用户聊了困惑但模型没写记忆（NOOP 判别），提炼不触发 = 漏记。
本实验验证三种触发方案的真实表现（漏记率/误报率/成本）：

- 方案A（现状）：记忆变化才触发 → 困惑对话若无 remember 则漏
- 方案B（会话结束必触发）：所有对话都提炼 → 闲聊是否误报？成本多高？
- 关键测量：困惑提炼函数自身的 NOOP 判别能力（返回 None = 零落库成本）

方法：3 类模拟对话 × 直接调 extract_session_confusion（绕开 consume_memory_changed 门）。
零风险：只读主库画像/状态注入，不写任何文件。
"""
import asyncio
import sys
import time

sys.path.insert(0, ".")

# 3 类模拟对话（与真实场景同构）
DIALOGUES = {
    "困惑对话_无remember": """user: 我投了几家大厂的agent岗都没过，感觉竞争特别大，我有点怀疑我选错方向了？或者我不应该以大厂为目标？先稳住中小厂？
assistant: 打住打住，先把这个归因掰扯清楚：'投了几家大厂没过'不等于'方向选错了'...
user: 那我是需要根据不同公司微调简历的吧
assistant: 要微调，但别被定制简历那套焦虑绑架""",
    "闲聊对话": """user: 今天天气不错，你那边怎么样
assistant: 哈哈我这边没有天气，不过你心情好我就开心
user: 嗯，晚上打算出去吃个饭
assistant: 好啊，放松一下也不错""",
    "正常学习对话": """user: 我们继续上次的交叉熵吧，那两道自测题我还没答
assistant: 好，猫狗押注那道先来——小狗 0.8 猫 0.2，答案是狗...
user: 懂了，那 softmax 必要性那道呢
assistant: 直接 -log(5) 当损失为什么不行？因为 logits 没有概率语义...""",
}


async def main():
    from app.agent.tutor import build_tutor_agent, _extract_confusion
    from app.agent.tutor import _extract_relation, _extract_continuation

    build_tutor_agent()  # 注册回调（懒加载）

    print("=" * 60)
    print("P0-2 触发条件实验：提炼函数在各类对话下的真实行为")
    print("=" * 60)

    results = {}
    for name, dlg in DIALOGUES.items():
        t0 = time.time()
        confusion = await _extract_confusion(dlg)
        t1 = time.time()
        relation = await _extract_relation(dlg)
        t2 = time.time()
        continuation = await _extract_continuation(dlg)
        t3 = time.time()
        results[name] = {
            "confusion": confusion,
            "relation": relation,
            "continuation": continuation,
            "conf_t": t1 - t0,
            "rel_t": t2 - t1,
            "cont_t": t3 - t2,
        }
        print(f"\n【{name}】")
        print(f"  困惑提炼({t1-t0:.1f}s): {confusion or '(None=NOOP 不落库)'}")
        print(f"  关系提炼({t2-t1:.1f}s): {relation or '(None)'}")
        print(f"  续接点({t3-t2:.1f}s): {continuation or '(None)'}")

    # 判定
    print("\n" + "=" * 60)
    print("判定（对照三种方案）")
    print("=" * 60)
    c_d = results["困惑对话_无remember"]["confusion"]
    c_x = results["闲聊对话"]["confusion"]
    c_s = results["正常学习对话"]["confusion"]

    print(f"\n① 方案A（现状：记忆变化才触发）")
    print(f"   → '困惑对话_无remember' 若模型没调 remember，提炼不触发 → 漏记")
    print(f"   实测困惑提炼函数本身能提炼出: {bool(c_d)} → 说明漏的是触发条件不是提炼能力")
    print(f"   漏记率: 该场景在方案A下 = 100%（若模型没写记忆）")

    print(f"\n② 方案B（会话结束必触发 + NOOP 判别）")
    print(f"   → 困惑对话能提炼: {bool(c_d)}（{'✅ 补上漏记' if c_d else '❌ 仍漏'})")
    print(f"   → 闲聊对话困惑= {c_x or 'None'}（{'✅ NOOP 挡住误报' if not c_x else '❌ 误报！'})")
    print(f"   → 正常学习对话困惑= {c_s or 'None'}（{'✅ 合理' if not c_s else '⚠️ 需看内容'})")
    print(f"   → 成本：每次会话 3 次 LLM 调用（困惑/关系/续接点），返回 None 的调用是'已花输入 token 但零落库'")

    # 成本估算
    total_t = sum(r["conf_t"] + r["rel_t"] + r["cont_t"] for r in results.values())
    print(f"\n③ 成本估算：3 类对话 × 3 次提炼，总耗时 {total_t:.1f}s（每次提炼 ~1-2s，输入 token 为主）")
    print(f"   按每次会话 3 次调用 × 平均 1.5s ≈ 4.5s 收尾延迟——在 SSE 流式结束后异步执行，用户无感知")


if __name__ == "__main__":
    asyncio.run(main())
