# -*- coding: utf-8 -*-
"""星阁注册表（M3 Step 1：星阁正式化）

data/sages/index.json 是星阁的索引真相源（星笺本身仍是 data/sages/<id>.json）。
职责：列出 / 读取 / 人审确认 / 注册新星宿。领域(domain)是注册表元数据，不写进星笺。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from app.config import DATA_DIR
from app.council.models import SageCard

SAGES_DIR = DATA_DIR / "data" / "sages"
INDEX_FILE = SAGES_DIR / "index.json"
TRASH_DIR = SAGES_DIR / "trash"  # 删除回收站（2026-08-20 治理权：个人数据不真删，移走可恢复）

# 领域标注（注册表元数据，按星宿 id 维护；未知默认"未分类"）
_DOMAIN = {
    "influence": "行为 / 心理",
    "poor": "决策 / 思维",
    "descartes": "哲学 / 方法",
    "bacon": "哲学 / 方法",  # 2026-08-19 入库：与笛卡尔同领域，解锁同源深挖
}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def load_index() -> dict:
    if INDEX_FILE.exists():
        try:
            return json.loads(INDEX_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"sages": [], "updated": _now()}


def _scan_cards() -> list[dict]:
    """从 data/sages/*.json（排除 index.json）扫描星笺，生成注册条目（幂等，不覆盖已确认字段）"""
    existing = {s["id"]: s for s in load_index().get("sages", [])}
    entries = []
    for p in sorted(SAGES_DIR.glob("*.json")):
        if p.name == "index.json":
            continue
        try:
            card = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        sid = card.get("id") or p.stem
        old = existing.get(sid, {})
        entries.append(
            {
                "id": sid,
                "name": card.get("name", sid),
                "stance": (card.get("stance") or "")[:80],
                "domain": _DOMAIN.get(sid, old.get("domain", "未分类")),
                "distill_method": card.get("audit", {}).get("tool", "未知"),
                # 真相源=卡文件 audit.user_confirmed（confirm_sage 每次确认都写卡文件；索引旧值会卡住状态
                # ——用户实测"确认没反应/待审黄点一直亮"根因，2026-08-20）
                "confirmed": card.get("audit", {}).get("user_confirmed", old.get("confirmed", False)),
                "claims_count": len(card.get("core_claims", [])),
                "created": old.get("created", _now()),
            }
        )
    return entries


def list_sages() -> list[dict]:
    entries = _scan_cards()
    idx = load_index()
    idx["sages"] = entries
    idx["updated"] = _now()
    # B9 兜底（2026-08-20）：索引是缓存非真相源（真相源=卡文件）——写失败不影响返回内存结果
    try:
        INDEX_FILE.write_text(json.dumps(idx, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"[sages] 索引缓存写入失败（不影响读取）: {e}", flush=True)
    return entries


def get_sage(sage_id: str) -> SageCard:
    p = SAGES_DIR / f"{sage_id}.json"
    if not p.exists():
        raise FileNotFoundError(f"星宿不存在：{sage_id}")
    return SageCard.model_validate(json.loads(p.read_text(encoding="utf-8")))


def confirm_sage(sage_id: str, confirmed: bool = True) -> dict:
    """人审确认：星笺 audit.user_confirmed 置位 + 注册表同步"""
    p = SAGES_DIR / f"{sage_id}.json"
    if not p.exists():
        raise FileNotFoundError(f"星宿不存在：{sage_id}")
    card = json.loads(p.read_text(encoding="utf-8"))
    card.setdefault("audit", {})["user_confirmed"] = confirmed
    card["audit"]["confirmed_at"] = _now()
    p.write_text(json.dumps(card, ensure_ascii=False, indent=2), encoding="utf-8")
    list_sages()  # 刷新注册表
    return {"id": sage_id, "confirmed": confirmed}


def register_sage(card: SageCard, distill_method: str = "") -> dict:
    """蒸馏完成后注册新星宿（写卡 + 刷注册表）"""
    p = SAGES_DIR / f"{card.id}.json"
    data = card.model_dump()
    data.setdefault("audit", {})
    if distill_method:
        data["audit"]["tool"] = distill_method
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"id": card.id, "registered": True}


# ---------- 星阁治理权（2026-08-20 最小落地清单②，六件套：列表/查看/确认/删除/删观点/改元信息）----------
def trash_sage(sage_id: str) -> dict:
    """删除 → 移回收站 trash/（不真删，防误删可恢复）"""
    p = SAGES_DIR / f"{sage_id}.json"
    if not p.exists():
        raise FileNotFoundError(f"星宿不存在：{sage_id}")
    TRASH_DIR.mkdir(parents=True, exist_ok=True)
    dest = TRASH_DIR / f"{sage_id}.json"
    if dest.exists():
        dest = TRASH_DIR / f"{sage_id}.{_now().replace(':', '-')}.json"
    p.rename(dest)
    list_sages()  # 刷注册表（index.json 中条目自然消失）
    return {"id": sage_id, "trashed": True, "restorable": True}


def delete_claim(sage_id: str, idx: int) -> dict:
    """删观点（重写卡，quote 锚点其余不动——忠实度不变量）；越界/非法 idx 报错"""
    p = SAGES_DIR / f"{sage_id}.json"
    if not p.exists():
        raise FileNotFoundError(f"星宿不存在：{sage_id}")
    card = json.loads(p.read_text(encoding="utf-8"))
    claims = card.get("core_claims", [])
    if not isinstance(idx, int) or idx < 0 or idx >= len(claims):
        raise ValueError(f"观点索引越界：{idx}（共 {len(claims)} 条）")
    removed = claims.pop(idx)
    card["core_claims"] = claims
    card.setdefault("audit", {})["claims_count"] = len(claims)
    p.write_text(json.dumps(card, ensure_ascii=False, indent=2), encoding="utf-8")
    list_sages()
    return {"id": sage_id, "removed_title": removed.get("title", ""), "claims_left": len(claims)}


def update_sage_meta(sage_id: str, name: str | None = None, stance: str | None = None) -> dict:
    """改元信息（name/stance——用户有发言权；claim/quote 不可改=忠实度锚点不变量）"""
    p = SAGES_DIR / f"{sage_id}.json"
    if not p.exists():
        raise FileNotFoundError(f"星宿不存在：{sage_id}")
    card = json.loads(p.read_text(encoding="utf-8"))
    if name is not None:
        name = name.strip()
        if not name:
            raise ValueError("名字不能为空")
        card["name"] = name[:60]
    if stance is not None:
        card["stance"] = stance.strip()[:200]
    card.setdefault("audit", {})["meta_updated_at"] = _now()
    p.write_text(json.dumps(card, ensure_ascii=False, indent=2), encoding="utf-8")
    list_sages()
    return {"id": sage_id, "name": card.get("name"), "stance": card.get("stance")}
