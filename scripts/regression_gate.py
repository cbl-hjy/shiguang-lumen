"""回归门（改前必跑，共识 2026-08-12）：改动代码前跑这组快速探针。
事件驱动：只在"改"时跑（代码改动 或 pin 模型版本变化），绝不做定期巡检。
跑法：python scripts/regression_gate.py  （需后端已启动）
"""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _auth import curl_auth, headers_json

BASE = "http://127.0.0.1:8000"
PASS, FAIL = [], []


def chat(msg: str, sid: str | None = None) -> tuple[bool, str]:
    body = {"message": msg, "session_id": sid}
    r = subprocess.run(
        ["curl", "-s", "-N", "-X", "POST", f"{BASE}/api/chat"]
        + headers_json()
        + ["-d", json.dumps(body, ensure_ascii=False), "--max-time", "90"],
        capture_output=True, text=True, encoding="utf-8", errors="ignore", timeout=100,
    )
    return '"type": "done"' in r.stdout and '"type": "error"' not in r.stdout, r.stdout


def main():
    # 0. pin 模型版本（共识定案：供应商换模型看不见，版本指纹替你看见）
    from pathlib import Path as _P
    env_path = _P(__file__).resolve().parent.parent / ".env"
    model_line = ""
    if env_path.exists():
        model_line = next(
            (l.strip() for l in env_path.read_text(encoding="utf-8").splitlines()
             if l.strip().startswith("DEEPSEEK_MODEL=")), ""
        )
    print(f"[pin] 当前模型配置: {model_line or '(未读到 .env)'}（云端版本漂移会让回归不可复现——改模型须重跑回归）")

    # 1. 服务健康 + 基础对话
    sid = json.loads(subprocess.run(
        ["curl", "-s", "-X", "POST", f"{BASE}/api/session/new"] + curl_auth() + ["--max-time", "10"],
        capture_output=True, text=True, encoding="utf-8", timeout=15,
    ).stdout)["session_id"]
    ok, _ = chat("讲一下什么是过拟合，50 字内", sid)
    (PASS if ok else FAIL).append("基础对话（过拟合）")

    # 2. 记忆闭环：记住 → 检索
    ok, _ = chat("帮我记住：回归门测试条目 GATE_1 需要被检索到", sid)
    (PASS if ok else FAIL).append("记忆写入")
    ok, out = chat("搜一下记忆里有没有 GATE_1", sid)
    (PASS if ok and "GATE_1" in out else FAIL).append("记忆检索（含 GATE_1）")

    # 3. 工具调用可见（python_sandbox）
    ok, _ = chat("用沙箱算一下 2 的 10 次方", sid)
    (PASS if ok else FAIL).append("沙箱工具调用")

    # 3.5 API 端点层探针（防"回归门盲区 × 契约变更"：2026-08-12 实锤——async 化改签名后，
    #     同步端点调 async 工具返回 coroutine，工具层测试抓不住，必须直接打端点）
    #      edit：调 async edit_memory（Bug 1 回归防线）
    try:
        r = subprocess.run(
            ["curl", "-s", "-X", "POST", f"{BASE}/api/memory/edit"]
            + headers_json()
            + ["-d", json.dumps({"old": "回归门测试条目 GATE_1", "new": "回归门测试条目 GATE_1（端点探针）"},
                                ensure_ascii=False),
             "--max-time", "30"],
            capture_output=True, text=True, encoding="utf-8", errors="ignore", timeout=40,
        )
        resp = json.loads(r.stdout)
        assert resp.get("ok") is True, f"edit 未返回 ok: {r.stdout[:100]}"
        assert "coroutine" not in r.stdout.lower(), "edit 返回 coroutine（async 契约未对齐）"
        (PASS if True else FAIL).append("API 端点 /api/memory/edit（async 契约）")
    except Exception as e:
        FAIL.append(f"API 端点 /api/memory/edit: {e}")
    #      delete：调同步 forget（顺带清理 GATE_1，每轮重新写入闭环）
    try:
        r = subprocess.run(
            ["curl", "-s", "-X", "POST", f"{BASE}/api/memory/delete"]
            + headers_json()
            + ["-d", json.dumps({"content": "回归门测试条目 GATE_1"}, ensure_ascii=False),
             "--max-time", "30"],
            capture_output=True, text=True, encoding="utf-8", errors="ignore", timeout=40,
        )
        resp = json.loads(r.stdout)
        assert resp.get("ok") is True, f"delete 未返回 ok: {r.stdout[:100]}"
        (PASS if True else FAIL).append("API 端点 /api/memory/delete")
    except Exception as e:
        FAIL.append(f"API 端点 /api/memory/delete: {e}")

    # 4. compaction 逻辑（est 计算）+ 预算语义（hint 必须基于最终链：压缩后 est 小→无 hint）
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from app.main import _budget_hint
        assert _budget_hint(82_000) is not None and _budget_hint(20_000) is None
        assert _budget_hint(5_000) is None  # 压缩后的小链 → 无 hint（防 287% 误报回归）
        (PASS if True else FAIL).append("预算分级逻辑（含压缩后无误报）")
    except Exception as e:
        FAIL.append(f"预算分级逻辑: {e}")

    # 4.5 fallback 错误分类哨兵（P0 决策点持久化：#2 单测落盘——格式漂移会让分类器静默退化为单模型）
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from app.agent.model import should_fallback

        class _E(Exception):
            pass

        assert should_fallback(_E("status_code: 401, body: Authentication Fails")) is True   # 换凭据
        assert should_fallback(_E("status_code: 400, body: bad request")) is False            # 请求问题
        assert should_fallback(_E("status_code: 503")) is True                                # 服务端
        assert should_fallback(_E("weird unknown error")) is False                            # 未知保守
        (PASS if True else FAIL).append("fallback 错误分类（401/400/5xx/未知）")
    except Exception as e:
        FAIL.append(f"fallback 错误分类: {e}")

    # 5. #6 消息去重（X-Retry 标志/时间窗口覆盖——重试不落双份）
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from app.db import sessions as _S

        _sid = _S.new_session()
        _S.save_run(_sid, "回归门去重测试", '{"t":1}')
        with _S.get_conn() as _c:
            _n1 = _c.execute("SELECT COUNT(*) c FROM messages WHERE session_id=?", (_sid,)).fetchone()["c"]
        _S.save_run(_sid, "回归门去重测试", '{"t":2}', is_retry=True)
        with _S.get_conn() as _c:
            _n2 = _c.execute("SELECT COUNT(*) c FROM messages WHERE session_id=?", (_sid,)).fetchone()["c"]
        assert _n2 == _n1, f"重试后行数 {_n1}→{_n2}（应不变）"
        (PASS if True else FAIL).append("消息去重（X-Retry 不落双份）")
    except Exception as e:
        FAIL.append(f"消息去重: {e}")

    print(f"\n=== 回归门结果: {len(PASS)} 过 / {len(FAIL)} 挂 ===")
    for p in PASS:
        print(f"  ✅ {p}")
    for f in FAIL:
        print(f"  ❌ {f}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
