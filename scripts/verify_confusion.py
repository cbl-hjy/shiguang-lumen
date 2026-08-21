"""困惑提炼单元验证（2026-08-15）：喂真实对话样本，检查是否提炼出困惑而非事实"""
import sys
import asyncio

sys.path.insert(0, ".")

DIALOGUE = """user: 我想投agent岗位，但是投了几家大厂的agent都没通过，感觉竞争特别大，我有点怀疑我选错方向了？或者我不应该以大厂为目标？先稳住中小厂？
assistant: 打住打住，先把这个归因掰扯清楚：投了几家大厂没过不等于方向选错了...
user: 简历就没有通过，但是我让好几个ai交叉验证，都是说我的简历很好了，可以直接投，但是事实就是没有通过的。
assistant: AI说简历很好和简历能不能过筛是两个根本不互通的系统...
user: 那我应该去官网投，还是去boss投
assistant: 大厂走官网，中小厂走Boss...
user: 那我是需要根据不同公司微调简历的吧
assistant: 要微调，但别被定制简历那套焦虑绑架..."""


async def main():
    # 必须先构建 agent（注册困惑提炼回调），否则 _confusion_writer=None 直接返回 None
    from app.agent.tutor import build_tutor_agent

    build_tutor_agent()
    from app.agent.tutor import _extract_confusion

    result = await _extract_confusion(DIALOGUE)
    print("=== 困惑提炼单元验证 ===")
    print("输出:", repr(result))
    if result and ("方向" in result or "中小厂" in result or "大厂" in result):
        print("PASS: 提炼出认知困惑（方向/选择），而非'投了几家没过'的事实")
    elif result:
        print(f"WARN: 输出了内容但非困惑类: {result}")
    else:
        print("FAIL: 返回 None（真实困惑未被识别）")


if __name__ == "__main__":
    asyncio.run(main())
