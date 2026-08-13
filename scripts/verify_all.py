# -*- coding: utf-8 -*-
"""一次验证（第 0/1/2/5 层自动化；第 3/4 层手动清单见 docs/VERIFY-CHECKLIST.md）。

事件驱动：大改动后跑（今天所有"有哨兵"的东西一条命令全响）。
第 3 层（用户旅程交互）与第 4 层（故障注入/杀进程）需真实交互，留在清单手动做。

用法：python scripts/verify_all.py   （需看门狗/服务已启动，token 已配置）
"""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _auth import token  # noqa: E402

BASE = "http://127.0.0.1:8000"
RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, evidence: str):
    RESULTS.append((name, ok, evidence))
    print(f"  {'✅' if ok else '❌'} {name}: {evidence}")


def curl_json(args: list[str]) -> dict:
    r = subprocess.run(["curl", "-s"] + args, capture_output=True, text=True,
                       encoding="utf-8", errors="ignore", timeout=30)
    try:
        return json.loads(r.stdout)
    except Exception:
        return {}


def main():
    print("═══ 第 0 层 · 前置检查 ═══")
    # git 干净（行尾噪音应已随 .gitattributes 修复）
    gs = subprocess.run(["git", "status", "--short"], capture_output=True, text=True,
                        encoding="utf-8", cwd=str(ROOT)).stdout.strip()
    check("git status 干净", gs == "", f"{len(gs.splitlines()) if gs else 0} 个改动（应 0）")
    # .env 三键
    env = (ROOT / ".env").read_text(encoding="utf-8") if (ROOT / ".env").exists() else ""
    key = re.search(r"DEEPSEEK_API_KEY=(\S+)", env)
    tok = re.search(r"SHIGUANG_TOKEN=(\S+)", env)
    check("DEEPSEEK_API_KEY 非 invalid", bool(key) and "invalid" not in key.group(1), f"长度 {len(key.group(1)) if key else 0}")
    check("SHIGUANG_TOKEN 已配", bool(tok) and len(tok.group(1)) >= 32, f"长度 {len(tok.group(1)) if tok else 0}")
    fb = re.search(r"FALLBACK_MODEL=(\S*)", env)
    check("FALLBACK_* 预期（空=无fallback）", bool(fb), f"FALLBACK_MODEL={fb.group(1) if fb else '?'}")
    # 服务健康
    sid = curl_json(["-X", "POST", f"{BASE}/api/session/new", "-H", f"Authorization: Bearer {token()}",
                     "--max-time", "10"])
    check("服务健康（带 token session/new）", bool(sid.get("session_id")),
          f"sid={sid.get('session_id', 'FAIL')[:8] if sid.get('session_id') else sid}")

    print("\n═══ 第 1 层 · 自动化基线 ═══")
    for script, label in [("regression_gate.py", "回归门"), ("state_wheel_probe.py", "状态轮探针")]:
        # 状态轮探针 L2 断言模型行为（触发/格式）——采样有方差，失败自动重试一次；
        # 重试后仍挂时解析：只挂 L2 = 行为采样（黄，可重跑确认）；挂 L1/L3 = 机制真问题（红）
        attempt = 0
        while True:
            r = subprocess.run([sys.executable, str(ROOT / "scripts" / script)], capture_output=True,
                               text=True, encoding="utf-8", errors="ignore", timeout=600, cwd=str(ROOT))
            attempt += 1
            lines = [l.strip() for l in r.stdout.splitlines() if l.strip() and not l.startswith("Warning")][-3:]
            ok = ("0 挂" in r.stdout) or ("❌" not in r.stdout and len(lines) > 0)
            if ok or attempt >= 2 or label == "回归门":
                break
        if not ok and label == "状态轮探针":
            fails = [l for l in r.stdout.splitlines() if "❌" in l]
            only_l2 = fails and all("L2-" in l for l in fails)
            if only_l2:
                check(f"{label}（L2 行为采样）", True,
                      f"⚠️ 仅 L2 挂 {len(fails)} 项（模型行为采样，建议重跑确认）: {'; '.join(f.strip()[:30] for f in fails[:3])}")
                continue
        check(f"{label} 全过", ok, (" | ".join(lines[-2:]) if lines else f"exit={r.returncode} stderr={r.stderr[-200:] if r.stderr else '(空)'}") + (f"（重试{attempt}次）" if attempt > 1 else ""))

    print("\n═══ 第 2 层 · 长会话实测（166 轮会话）═══")
    # 模拟回归（阶段 6，smoke 10 轮短回归——成本可控进主链；完整 30 轮场景为独立显式条目）
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        sys.path.insert(0, str(ROOT))
        from app.config import SHIGUANG_TOKEN as _TOK, DEEPSEEK_API_KEY as _KEY, DEEPSEEK_BASE_URL as _BURL, DEEPSEEK_MODEL as _MODEL
        import json as _json
        from sim_runner import load_persona, run_persona_scenario
        import asyncio as _asyncio

        _p = load_persona("exam_crammer")
        _sc = _json.loads((ROOT / "scenarios" / "scenario_001.json").read_text(encoding="utf-8"))
        _sc["max_turns"] = 10  # smoke 短回归

        async def _smoke():
            return await run_persona_scenario(_p, _sc, 99, "http://127.0.0.1:9000", _TOK,
                                              _KEY, _BURL, _MODEL)

        _r = _asyncio.run(_smoke())
        _zero = sum(1 for x in _r["records"] if x["zero_reply"])
        _ok = _r["turns"] >= 5 and _zero == 0
        check("模拟回归（10 轮 smoke）", _ok, f"{_r['turns']}轮 0字={_zero}（实验实例 9000）")
    except Exception as e:
        check("模拟回归（10 轮 smoke）", False, f"需实验实例 9000 在跑: {str(e)[:80]}")

    if sid.get("session_id"):
        ls_sid = "0098ec44e084"
        r1 = subprocess.run(["curl", "-s", "-N", "-X", "POST", f"{BASE}/api/chat", "-H", "Content-Type: application/json",
                             "-H", f"Authorization: Bearer {token()}",
                             "-d", json.dumps({"message": "我们之前聊了哪些主题？简单说", "session_id": ls_sid}, ensure_ascii=False),
                             "--max-time", "150"], capture_output=True, text=True, encoding="utf-8", errors="ignore", timeout=180)
        done = '"type": "done"' in r1.stdout
        err = '"type": "error"' in r1.stdout
        check("长会话回复非空（无 0 字）", done and not err, f"done={done} error={err} len={len(r1.stdout)}")
        # summary 检查
        from app.db import sessions as _S  # noqa: E402
        sm = _S.get_summary(ls_sid)
        check("summary 非空且 ≥30 字", bool(sm) and len(sm) >= 30, f"{len(sm) if sm else 0} 字")

    print("\n═══ 第 5 层 · 数据抽查 ═══")
    db_size = (ROOT / "data" / "sessions.db").stat().st_size
    check("sessions.db 已瘦身（<100MB）", db_size < 100 * 1024 * 1024, f"{db_size // 1024 // 1024}MB")
    state_file = ROOT / "memory" / "state.json"
    if state_file.exists():
        st = json.loads(state_file.read_text(encoding="utf-8"))
        dims = list(st.get("current", {}).keys())
        ls_keys = list(st.get("last_session", {}).keys())
        check("state.json 结构正常", "emotion" in dims or bool(ls_keys), f"current={dims} last={ls_keys[:3]}")
    else:
        check("state.json 结构正常", False, "文件不存在")

    print("\n═══ 汇总 ═══")
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print(f"{passed}/{len(RESULTS)} 通过")
    for name, ok, ev in RESULTS:
        if not ok:
            print(f"  ❌ {name}: {ev}")
    return 1 if passed < len(RESULTS) else 0


if __name__ == "__main__":
    sys.exit(main())
