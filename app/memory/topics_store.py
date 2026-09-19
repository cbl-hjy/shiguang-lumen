"""主题动态演化存储层（P1，2026-08-19）——纯 harness 层，不约束模型。

设计依据：docs/TOPIC-EVOLUTION-DESIGN.md
- topics.json 是【索引层不是真相源】：删了可从记忆重建（真相源永远是 user_memory.md）
- 状态是派生的：active/dormant/archived 不存字段，读取时按 last_active 计算——
  永不过期、无定时任务、完全符合"状态再生"（记忆持久，状态再生）
- 候选池门槛：同概念 ≥CREATE_THRESHOLD 次（或用户显式命名，P3）才建主题——防一次闲聊污染
- 相对静止哲学：主题集宏观稳定（门槛+归并），微观活跃（每会话 touch 更新 last_active）
"""

import json
import os
import stat
from datetime import date
from pathlib import Path

from app.memory.schema import memory_dir

_TOPICS_OVERRIDE: Path | None = None  # 测试注入点（2026-08-28：存量测试从模块常量注入迁移）


def TOPICS_FILE() -> Path:
    return _TOPICS_OVERRIDE if _TOPICS_OVERRIDE is not None else memory_dir() / "topics.json"

# 生命周期阈值（设计文档确认：沉寂 30 天 / 归档 1 年）
DORMANT_DAYS = 30
ARCHIVE_DAYS = 365
# 创建门槛（设计修正 2026-08-19：三重——意图=new + 观察期 7 天 ≥2 次 + 用户显式命名豁免）
CREATE_THRESHOLD = 2
OBSERVATION_DAYS = 7

# 主题内容域（2026-08-30 双轨地基）：kind 决定这个主题走哪条轨——
#   knowledge=知识轨（出题-批改-正确率，有标准答案）
#   skill/habit=实践轨（设计一次真实实践 → 复盘自述 → 存证据，没有标准答案）
# 与 status 的取舍相反：kind 存字段，stage 不存。
#   理由：kind 是主题的属性（随主题长期稳定，是内容判断，真相源就是这一句）；
#   stage 是派生量（真相源是 ledger 原始记录），存了就成第二个真相源——两份数据必然打架。
KIND_VOCAB = ("knowledge", "skill", "habit")
DEFAULT_KIND = "knowledge"

# 种子主题（P3，2026-08-19）——harness 的手工初始认知（识别工具，不是层级判断）：
# 由原 hub.TOPIC_KEYWORDS 迁移而来，seed 时写入 topics.json（幂等，文件已有时不覆盖）。
# 关键区别（用户否静态树时划的线）：种子只给 name+aliases（识别用），parent 留空——
# 层级是知识判断，必须等模型演化输出（正则化属于深度学习这种判断不归 harness）。
SEED_TOPICS: list[dict] = [
    {
        "name": "正则化",
        "aliases": ["正则", "L2", "L1", "过拟合", "weight decay", "权重衰减", "dropout", "弹性网"],
    },
    {"name": "梯度下降", "aliases": ["梯度下降", "动量", "SGD", "adam", "optimizer", "学习率"]},
    {
        "name": "Transformer",
        "aliases": ["transformer", "注意力", "attention", "self-attention", "位置编码", "多头"],
    },
    {
        "name": "集成学习",
        "aliases": ["xgboost", "lightgbm", "随机森林", "adaboost", "bagging", "boosting"],
    },
    {
        "name": "深度学习基础",
        "aliases": [
            "激活函数",
            "relu",
            "softmax",
            "交叉熵",
            "反向传播",
            "BP",
            "神经网络",
            "sigmoid",
        ],
    },
    {
        "name": "职业发展",
        "aliases": ["面试", "笔试", "offer", "HR", "求职", "职业规划"],
    },
    {
        "name": "项目开发",
        "aliases": ["拾光", "agent", "mcp", "fastapi", "llamaindex", "rag", "chroma", "pydantic"],
    },
]

DEFAULT_TOPICS = {"topics": [], "candidates": [], "unclassified_count": 0}


def _default() -> dict:
    return json.loads(json.dumps(DEFAULT_TOPICS))


def seed_topics(force: bool = False) -> int:
    """种子初始化（P3）：topics.json 无主题时写入 SEED_TOPICS（parent 留空等模型演化）。
    幂等：已有主题则不重复写（force=True 清空旧主题重建——索引层可重建特性）。返回种子数。"""
    data = load_topics()
    if not force and data.get("topics"):
        return 0
    today = date.today().isoformat()
    data["topics"] = [
        {
            "name": s["name"],
            "aliases": [a for a in s.get("aliases", []) if a != s["name"]],
            "parent": "",
            "related_to": [],
            "created_at": today,
            "last_active": today,
        }
        for s in SEED_TOPICS
    ]
    data["candidates"] = []  # force 重建时候选池一并清空
    save_topics(data)
    return len(SEED_TOPICS)


def load_topics() -> dict:
    """读取主题索引（含候选池）。文件缺失/损坏 → 空索引（不崩）。"""
    if not TOPICS_FILE().exists():
        return _default()
    try:
        d = json.loads(TOPICS_FILE().read_text(encoding="utf-8"))
        return {**DEFAULT_TOPICS, **d}
    except Exception:
        return _default()


def save_topics(data: dict):
    """原子写（2026-08-30）：同目录固定名 tmp → os.replace。

    原来直接 write_text 到目标文件——写入中途进程被杀 = 文件截断 =
    用户主题图不可逆丢失（topics.json 是真实用户数据，不是缓存）。

    - tmp 用固定名（不随机）：临时文件零堆积，同一次运行内反复覆盖同一个 tmp
    - os.replace 在同目录内是原子的（POSIX rename / Windows ReplaceFile）
    - Windows 老坑：目标文件带只读属性时 os.replace 抛 PermissionError——先摘只读
    - 任何异常都清 tmp，绝不留下半截文件

    签名与语义不变：create/touch/merge/split/seed 全部无感受益。"""
    p = TOPICS_FILE()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        if p.exists() and not os.access(p, os.W_OK):
            os.chmod(p, stat.S_IWRITE | stat.S_IREAD)  # 只读 → os.replace 会 PermissionError
        os.replace(tmp, p)
    except Exception:
        # 清理失败必须可见（ruff S110 于 08-28 引入，立意就是"静默吞异常 = 故障不可见"）。
        # 但绝不能让它盖掉原始异常——只报告，不抛出。
        # 走 safe_cleanup：守卫拒删时抛的是 SystemExit（BaseException），
        # `except Exception` 接不住，会顶掉下面 raise 的原始异常。
        from app.utils.safe_cleanup import try_unlink

        try_unlink(tmp, context="memory/topics_store")
        raise


def _derive_status(last_active: str) -> str:
    """状态派生（不存字段，读取时计算）：≤30 天活跃 / ≤365 沉寂 / 更久归档。
    归档不删只藏——记忆持久，时光机可唤醒（touch 更新 last_active 自动回 active）。"""
    if not last_active:
        return "active"
    try:
        days = (date.today() - date.fromisoformat(last_active[:10])).days
    except Exception:
        return "active"
    if days > ARCHIVE_DAYS:
        return "archived"
    if days > DORMANT_DAYS:
        return "dormant"
    return "active"


def _kind_of(t: dict) -> str:
    """读取侧兜底：老主题没有 kind 字段 → knowledge（存量主题的行为全部属于知识轨）。
    非法值同样回落——与 status 一样在读取时归一，不写回文件。"""
    k = (t or {}).get("kind")
    return k if k in KIND_VOCAB else DEFAULT_KIND


def view_topics() -> list[dict]:
    """主题视图（供 API/前端）：带派生 status + kind 兜底 + 关联字段，按 last_active 倒序。"""
    data = load_topics()
    topics = []
    for t in data.get("topics", []):
        topics.append(
            {**t, "status": _derive_status(t.get("last_active", "")), "kind": _kind_of(t)}
        )
    topics.sort(key=lambda t: t.get("last_active", ""), reverse=True)
    return topics


def find_topic(name: str) -> dict | None:
    """按 name 或 aliases 精确查找（快、准、无歧义——归拢第一通道）。"""
    name = (name or "").strip()
    if not name:
        return None
    for t in load_topics().get("topics", []):
        if t.get("name") == name or name in (t.get("aliases") or []):
            return t
    return None


def create_topic(
    name: str,
    parent: str = "",
    aliases: list[str] | None = None,
    related_to: list[str] | None = None,
) -> dict:
    """正式建主题（候选池达标或用户显式命名时调用）。幂等：已存在则只 touch。"""
    name = (name or "").strip()
    if not name:
        raise ValueError("主题名不能为空")
    data = load_topics()
    existing = find_topic(name)
    if existing:
        return touch_topic(name, parent=parent, aliases=aliases, related_to=related_to)
    topic = {
        "name": name,
        "aliases": [a for a in (aliases or []) if a and a != name],
        "parent": parent or "",
        "related_to": [r for r in (related_to or []) if r and r != name],
        "created_at": date.today().isoformat(),
        "last_active": date.today().isoformat(),
    }
    data["topics"].append(topic)
    # 从候选池移除（已建成）
    data["candidates"] = [c for c in data.get("candidates", []) if c.get("name") != name]
    save_topics(data)
    return topic


def touch_topic(
    name: str,
    parent: str = "",
    aliases: list[str] | None = None,
    related_to: list[str] | None = None,
) -> dict | None:
    """主题被提及：更新 last_active（活跃/唤醒）+ 合并 aliases/related。不存在返回 None。"""
    data = load_topics()
    t = next((x for x in data.get("topics", []) if x.get("name") == name), None)
    if t is None:
        return None
    t["last_active"] = date.today().isoformat()  # 状态派生自动回 active（时光机唤醒）
    t.pop(
        "shelved_at", None
    )  # 2026-08-21 修复：唤醒=告别解除（farewell 残留不清 → 同主题既活跃又搁置，状态仲裁自相矛盾）
    for a in aliases or []:
        if a and a != name and a not in t.get("aliases", []):
            t.setdefault("aliases", []).append(a)
    for r in related_to or []:
        if r and r != name and r not in t.get("related_to", []):
            t.setdefault("related_to", []).append(r)
    if parent and not t.get("parent"):
        t["parent"] = parent
    save_topics(data)
    return t


def register_candidate(name: str, parent: str = "", explicit: bool = False) -> dict:
    """候选主题注册（三重门槛，2026-08-19 设计修正）：
    ① 意图=new（调用方保证，模型判断）
    ② 观察期：7 天内重复 ≥2 次才建（超窗重置——防"一年后随口再提"也算数）
    ③ 用户显式命名（explicit=True）→ 一次即建，豁免计数
    返回 {created, topic, count, reason}。"""
    name = (name or "").strip()
    if not name:
        return {"created": False, "topic": None, "count": 0, "reason": "空名"}
    existing = find_topic(name)
    if existing:
        touch_topic(name, parent=parent)
        return {"created": False, "topic": existing, "count": 0, "reason": "已存在"}
    if explicit:
        topic = create_topic(name, parent=parent)
        return {"created": True, "topic": topic, "count": 1, "reason": "用户显式命名"}
    data = load_topics()
    today = date.today()
    cand = next((c for c in data.get("candidates", []) if c.get("name") == name), None)
    if cand:
        # 观察期窗口检查：超 7 天未再提 → 重置计数（防陈旧候选）
        try:
            first = date.fromisoformat(cand.get("first_seen", today.isoformat())[:10])
            stale = (today - first).days > OBSERVATION_DAYS
        except Exception:
            stale = False
        if stale:
            cand["count"] = 1
            cand["first_seen"] = today.isoformat()
        else:
            cand["count"] = int(cand.get("count", 0)) + 1
        cand["last_seen"] = today.isoformat()
        if cand["count"] >= CREATE_THRESHOLD:
            save_topics(data)
            topic = create_topic(name, parent=parent)
            return {"created": True, "topic": topic, "count": cand["count"]}
        save_topics(data)
        return {"created": False, "topic": None, "count": cand["count"]}
    data.setdefault("candidates", []).append(
        {
            "name": name,
            "parent": parent,
            "count": 1,
            "first_seen": today.isoformat(),
            "last_seen": today.isoformat(),
        }
    )
    save_topics(data)
    return {"created": False, "topic": None, "count": 1}


def mark_farewell(name: str) -> bool:
    """用户告别主题（intent=farewell，2026-08-19 意图驱动）：
    不 touch（last_active 保持旧值 → 自然沉寂/归档），返回是否命中已有主题。
    告别≠激活：用户提"不学正则化了"不能让正则化变活跃（体验关键）。"""
    data = load_topics()
    t = next((x for x in data.get("topics", []) if x.get("name") == name), None)
    if t is None:
        return False
    # 记录告别标记（可观测：前端可显示"用户已告别"），但不更新 last_active
    t.setdefault("shelved_at", date.today().isoformat())
    save_topics(data)
    return True


def set_status(name: str, status: str) -> bool:
    """主题状态落盘（2026-08-21 状态细粒度归模型——模型收尾输出的 status 字段）。
    仅三态：done=完成 / stuck=卡住 / shelved=搁置；覆盖旧值 + status_at 时间戳（可观测最新判断时点）。
    不存在返回 False（防静默：候选主题等正式建立后再落状态）。"""
    if status not in ("done", "stuck", "shelved"):
        return False
    data = load_topics()
    t = next((x for x in data.get("topics", []) if x.get("name") == name), None)
    if t is None:
        return False
    t["status"] = status
    t["status_at"] = date.today().isoformat()
    save_topics(data)
    return True


def set_kind(name: str, kind: str) -> bool:
    """主题内容域落盘（与 set_status 同模式：先读后写 + 值域白名单校验）。

    仅三值：knowledge / skill / habit；覆盖旧值 + kind_at 时间戳（可观测最新判断时点）。
    非法值或主题不存在 → False（防静默：候选主题等正式建立后再落内容域）。"""
    if kind not in KIND_VOCAB:
        return False
    data = load_topics()
    t = next((x for x in data.get("topics", []) if x.get("name") == name), None)
    if t is None:
        return False
    t["kind"] = kind
    t["kind_at"] = date.today().isoformat()
    save_topics(data)
    return True


def topic_count() -> int:
    """主题总数（统计用）"""
    return len(load_topics().get("topics", []))


def rename_topic(old: str, new: str) -> dict:
    """用户纠错·改名（P3）：名字改 + 旧名进 aliases——归拢是读取端算的，改索引零迁移（记忆文件不动）。
    返回 {ok, msg, topic}；旧名自动成为别名，旧记忆归拢继续命中。"""
    old = (old or "").strip()
    new = (new or "").strip()
    if not old or not new:
        return {"ok": False, "msg": "新旧名字都不能为空"}
    if find_topic(new):
        return {"ok": False, "msg": f"已有主题叫「{new}」，如需合并请用合并操作"}
    data = load_topics()
    t = next((x for x in data.get("topics", []) if x.get("name") == old), None)
    if t is None:
        return {"ok": False, "msg": f"未找到主题「{old}」"}
    # 旧名进 aliases（防旧名失效），新名替换
    if old not in t.get("aliases", []):
        t.setdefault("aliases", []).append(old)
    t["name"] = new
    save_topics(data)
    return {"ok": True, "msg": f"已改名：{old} → {new}", "topic": t}


def split_topic(source: str, new_name: str, aliases: list[str] | None = None) -> dict:
    """用户纠错·拆分（P3）：从 source 拆出独立新主题 B（new_name + aliases）。
    零迁移：记忆文件不动——读取端归拢按关键词命中，B 的词自然把相关记忆带走。
    关键正确性：从 source 的 aliases 移除 B 的名字与别名——_match_topic 按 dict 顺序
    第一个命中即归，若 A 还留着 B 的词，A 在前会抢走 B 的记忆（拆了白拆）。
    返回 {ok, msg, topic, removed_aliases}。"""
    source = (source or "").strip()
    new_name = (new_name or "").strip()
    if not source or not new_name:
        return {"ok": False, "msg": "源主题与新主题名字都不能为空"}
    if source == new_name:
        return {"ok": False, "msg": "新主题不能与源主题同名"}
    existing = find_topic(new_name)
    if existing and existing.get("name") != source:
        return {"ok": False, "msg": f"已有主题叫「{new_name}」，如需合并请用合并操作"}
    # 注：existing 命中 source 的别名（如从「深度学习」拆出别名「Transformer」）→ 允许——这是最常见的拆分场景
    data = load_topics()
    t = next((x for x in data.get("topics", []) if x.get("name") == source), None)
    if t is None:
        return {"ok": False, "msg": f"未找到主题「{source}」"}
    # ① 从源主题 aliases 移除 B 的名字 + B 的别名（防 A 抢 B——拆分的核心不变量）
    b_terms = {a for a in (aliases or []) if a and a.strip()} | {new_name}
    removed = []
    old_aliases = t.get("aliases", [])
    kept = []
    for a in old_aliases:
        if a.strip() in b_terms:
            removed.append(a)
        else:
            kept.append(a)
    if removed:
        t["aliases"] = kept
    # ② 新建 B（独立顶级，不继承 A 的 parent——分家即独立；aliases 去重去 B 名）
    b_aliases = [a.strip() for a in (aliases or []) if a and a.strip() and a.strip() != new_name]
    b = {
        "name": new_name,
        "aliases": b_aliases,
        "parent": "",
        "related_to": [source],
        "created_at": date.today().isoformat(),
        "last_active": date.today().isoformat(),
    }
    data["topics"].append(b)
    save_topics(data)
    return {
        "ok": True,
        "msg": f"已拆分：{source} → {new_name}（含 {len(b_aliases)} 个别名）",
        "topic": b,
        "removed_aliases": removed,
    }


def merge_topics(from_name: str, to_name: str) -> dict:
    """用户纠错·合并（P3）：from 并入 to——from 删除，from 的 aliases/parent 并入 to。
    零迁移：记忆无显式主题归属，归拢时 from 的记忆自动归到 to（to 的 aliases 覆盖 from 的词）。
    返回 {ok, msg, merged_aliases}。"""
    from_name = (from_name or "").strip()
    to_name = (to_name or "").strip()
    if not from_name or not to_name or from_name == to_name:
        return {"ok": False, "msg": "合并双方不能为空且不能相同"}
    data = load_topics()
    f = next((x for x in data.get("topics", []) if x.get("name") == from_name), None)
    t = next((x for x in data.get("topics", []) if x.get("name") == to_name), None)
    if f is None:
        return {"ok": False, "msg": f"未找到主题「{from_name}」"}
    if t is None:
        return {"ok": False, "msg": f"未找到目标主题「{to_name}」"}
    merged = []
    for a in f.get("aliases", []) + [from_name]:
        if a and a != to_name and a not in t.get("aliases", []):
            t.setdefault("aliases", []).append(a)
            merged.append(a)
    # from 的 parent 若 to 没有则继承（保守：不覆盖 to 已有 parent）
    if f.get("parent") and not t.get("parent"):
        t["parent"] = f["parent"]
    # 删除 from
    data["topics"] = [x for x in data.get("topics", []) if x.get("name") != from_name]
    save_topics(data)
    return {"ok": True, "msg": f"已合并：{from_name} → {to_name}", "merged_aliases": merged}
