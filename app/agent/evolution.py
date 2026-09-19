"""M8 进化层：Reflexion 反思 + Voyager 技能库 + JIT 技能检索
设计依据：docs/M8-DESIGN.md（论文原文 + probe_evolve 实测）
三条论文硬约束的落地：
- 反思/技能入库必须有外部验证信号（用户反馈触发，模型自评永不直接入库）
- 技能只增不改（Voyager 原则）；容量硬限是护栏（超限报错交模型，不替它合并）
- 独立 collection 存储（reflections/skills），不污染用户记忆
"""

import hashlib
import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from app.config import DATA_DIR

import chromadb
from pydantic_ai import Agent

from app.memory.vector import aembed

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
from app.auth_core import get_current_user_id
from app.user_data import get_user_data_dir
from app.utils.atomic_io import atomic_write_text


def _evo_dir(uid=None):
    """技能/反思文件 + 进化向量目录（per-user；legacy 回退全局）"""
    if not uid:
        uid = get_current_user_id()
    if uid:
        return get_user_data_dir(uid)
    return DATA_DIR


# 测试覆盖钩子（2026-08-28：存量测试从模块常量注入迁移——函数化后注入会覆盖函数本身导致
# 'WindowsPath' object is not callable；钩子优先于 uid 解析，测试零侵入生产路径）
_EVO_REFLECTIONS_OVERRIDE: Path | None = None
_EVO_SKILLS_OVERRIDE: Path | None = None
_EVO_PENDING_OVERRIDE: Path | None = None
_EVO_DELTAS_OVERRIDE: Path | None = None
_EVO_GROUNDING_OVERRIDE: Path | None = None


def REFLECTIONS_FILE(uid=None):
    if _EVO_REFLECTIONS_OVERRIDE is not None:
        return _EVO_REFLECTIONS_OVERRIDE
    return _evo_dir(uid) / "memory" / "reflections.md"


def PENDING_FILE(uid=None):
    if _EVO_PENDING_OVERRIDE is not None:
        return _EVO_PENDING_OVERRIDE
    return _evo_dir(uid) / "memory" / "pending_fixes.md"


def SKILLS_FILE(uid=None):
    if _EVO_SKILLS_OVERRIDE is not None:
        return _EVO_SKILLS_OVERRIDE
    return _evo_dir(uid) / "memory" / "skills.md"


def DELTAS_FILE(uid=None):
    """ACE Curator delta 幂等 journal（playbook_deltas.jsonl）——已应用 delta 的 sha1 落盘，重放不双加"""
    if _EVO_DELTAS_OVERRIDE is not None:
        return _EVO_DELTAS_OVERRIDE
    return _evo_dir(uid) / "data" / "playbook_deltas.jsonl"


def CHROMA_DIR(uid=None):
    return _evo_dir(uid) / "data" / "vector_evolve"


def GROUNDING_FILE(uid=None):
    """技能接地台账（skill_grounding.jsonl）：每次接地 bump 一条 {event:bump, ts, sid, session, field}，
    出索引事件 {event:exit, ts, sid}。②会话注册表（_RETRIEVED，end_session 即清）的持久化延伸——
    成熟度「跨 ≥2 session 有接地」与 14 天复活窗口的数据源（设计 §2/§3，append-only 同一仪器）。"""
    if _EVO_GROUNDING_OVERRIDE is not None:
        return _EVO_GROUNDING_OVERRIDE
    return _evo_dir(uid) / "data" / "skill_grounding.jsonl"

CAP_LIMIT = 50  # 各库容量硬限（护栏：超限报错交模型处理）
INJECT_LIMIT = 2  # 反思注入上限（Reflexion 论文容量滑窗 Ω=1-3 的落地）

REFLECT_PROMPT = """你是教育反思教练。基于"发生了什么 + 用户反馈"，写一段反思，严格三段式：
1) 什么错（指出具体错误/失误点，不笼统）
2) 为什么（根因分析）
3) 下次怎么改（具体可执行的改进，至少 2 条）
结尾附一行"证据："说明触发本次反思的用户反馈/事件来源（可复核）。
只输出反思本身，不要客套。"""

SKILL_PROMPT = """你是教学经验提炼师。用户对一次教学表示满意。请把这套"讲法"提炼成可复用的技能，格式：
描述：什么情境下用（通用可复用，不绑定具体例子，一句话）
方法：具体讲法步骤（2-4 步，可执行）
只输出这两行，不要其他。"""

_client = None
_collections: dict[str, object] = {}


def _get_collection(name: str):
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(path=str(CHROMA_DIR()))
    if name not in _collections:
        _collections[name] = _client.get_or_create_collection(
            name, metadata={"hnsw:space": "cosine"}
        )
    return _collections[name]


def _build_agent(system_prompt: str) -> Agent:
    from app.agent.model import get_model

    return Agent(get_model(), system_prompt=system_prompt)


def _count_lines(file: Path) -> int:
    if not file.exists():
        return 0
    return sum(1 for ln in file.read_text(encoding="utf-8").splitlines() if ln.startswith("## ["))


def _append(file: Path, block: str):
    file.parent.mkdir(parents=True, exist_ok=True)
    with file.open("a", encoding="utf-8") as f:
        f.write(block + "\n\n")


# 反思/技能查重阈值（2026-08-19 P1 复盘缺陷3）：新块与库内已有块向量相似度 ≥ 此值 → 拒写
# 治"多而杂"在反思/技能的复发（_append 原来纯追加，同主题每会话沉淀相似内容）
DUP_THRESHOLD = 0.92


async def _is_duplicate(collection: str, new_block: str) -> str | None:
    """语义查重（harness 不变量）：new_block 与库内已有条目相似度 ≥0.92 → 返回已有条目摘要，否则 None。
    不调用 LLM（向量距离是确定性计算）；失败保守返回 None（宁可不拒，不误伤）。
    嵌入前剥离计数元数据（_strip_meta）——计数随接地信号原地递增，不参与语义比较。"""
    try:
        col = _get_collection(collection)
        if col.count() == 0:
            return None
        vec = (await aembed([_strip_meta(new_block)]))[0]
        res = col.query(query_embeddings=[vec], n_results=3)
        docs = (res.get("documents") or [[]])[0]
        dists = (res.get("distances") or [[]])[0]
        for doc, dist in zip(docs, dists, strict=True):
            sim = 1.0 - dist  # cosine space: distance = 1 - similarity
            if sim >= DUP_THRESHOLD:
                return doc[:80]
    except Exception as _e:
        print(f"[agent/evolution] 静默异常已可见化: {_e}", flush=True)
    return None


def _entry_id(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


# ---------- P0-3 失败回灌（2026-08-27，自进化闭环的失败侧） ----------
# 协同原则（模型+harness 调研）：harness 只"采集+进待审区"，模型可见可决策——绝不静默应用
# （对齐 ai-radar "不得静默应用"；模型 read_document 待审区后自主决定是否修订技能/记忆）


def collect_failure(evidence: str, target: str = "") -> str:
    """失败证据进待审区（append-only，幂等去重——同证据 24h 内不重复采集）。"""
    try:
        evidence = (evidence or "").strip()
        if not evidence:
            return ""
        PENDING_FILE().parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%dT%H:%M")
        block = f"## [{ts}] 失败证据\n目标：{target or '未定位'}\n证据：{evidence[:300]}"
        if PENDING_FILE().exists():
            cur = PENDING_FILE().read_text(encoding="utf-8")
            if evidence[:50] in cur:  # 幂等：同证据不重复
                return ""
            # 容量护栏：超 200 条截断保留最近 100
            lines = cur.split("## [")
            if len(lines) > 200:
                cur = "## [" + "## [".join(lines[-100:])
        else:
            cur = ""
        with PENDING_FILE().open("a", encoding="utf-8") as f:
            f.write(block + "\n\n")
        return "pending"
    except Exception:
        return ""


def pending_count() -> int:
    """待审区条数（动态上下文提示用）。"""
    try:
        if not PENDING_FILE().exists():
            return 0
        return PENDING_FILE().read_text(encoding="utf-8").count("## [")
    except Exception:
        return 0


def pending_clear(evidence_prefix: str) -> bool:
    """模型采纳后清除待审条目（人工/模型决策后调用——治理动作）。"""
    try:
        if not PENDING_FILE().exists():
            return False
        lines = PENDING_FILE().read_text(encoding="utf-8").split("## [")
        kept = [l for l in lines if not (evidence_prefix and evidence_prefix[:50] in l)]
        atomic_write_text(PENDING_FILE(), ("## [" + "## [".join(kept[1:])).rstrip() + "\n")
        return len(kept) < len(lines)
    except Exception:
        return False


def _remove_block(file: Path, content: str, collection: str) -> bool:
    """按内容匹配删除一个块（文件 + 向量）"""
    blocks = _blocks(file)
    kept = [b for b in blocks if content not in b]
    if len(kept) == len(blocks):
        return False
    # _blocks（:346 现行定义）切分后块不带 "## " 前缀——写回必须补回，否则损坏块文件格式
    # （2026-08-30 修复：此前 delete_item 会把整个文件揉成无块头单块；同 _bump_counter 写回模式）
    body = "\n\n".join(b if b.startswith("## ") else "## " + b for b in kept)
    atomic_write_text(file, body + ("\n\n" if kept else ""))
    for b in blocks:
        if content in b:
            try:
                # 向量定位三保险：①入库口径 id（带 "## " 前缀全文）②reindex 口径 id（无前缀块）
                # ③剥离计数的文档内容匹配——bump 改块头计数后 id 漂移，前两种会对不上，
                # 但 _strip_meta 文档不受计数变化影响（与 exit_deprecated_skills 同策略）
                full = b if b.startswith("## ") else "## " + b
                col = _get_collection(collection)
                ids = {_entry_id(full), _entry_id(b)}
                try:
                    got = col.get(include=["documents"])
                    want = _strip_meta(full).strip()
                    for i, d in zip(got.get("ids") or [], got.get("documents") or [], strict=True):
                        if (d or "").strip() == want:
                            ids.add(i)
                except Exception as _e2:
                    # 内容扫描失败不阻断——id 口径已尽力
                    print(f"[agent/evolution] 向量内容扫描失败（静默）: {_e2}", flush=True)
                col.delete(ids=list(ids))
            except Exception as _e:
                print(f"[agent/evolution] 静默异常已可见化: {_e}", flush=True)
    return True

def list_reflections() -> list[dict]:
    """M5 人可审：反思列表 [{id, date, content}]——最新在前（时间降序，2026-08-27 排序统一）"""
    out = []
    for b in _blocks(REFLECTIONS_FILE()):
        lines = b.splitlines()
        date = lines[0][lines[0].find("[") + 1 : lines[0].find("]")] if "[" in lines[0] else ""
        out.append({"id": _entry_id(b), "date": date, "content": b})
    return list(reversed(out))  # 文件追加序=旧在前 → 倒序=最新在前


def list_skills() -> list[dict]:
    """M5 人可审：技能列表 [{id, date, content, maturity, maturity_label}]——最新在前（时间降序）。
    2026-08-30 ③：附派生成熟度（draft/tested/mature/deprecated + 中文标注）——
    状态是计数器+会话覆盖的纯函数，读取时计算；信任度判断归模型/用户，信息归代码。"""
    sessions_map = _sid_grounded_sessions()
    sid_state: dict[str, str] = {}
    out = []
    for b in _blocks(SKILLS_FILE()):
        lines = b.splitlines()
        date = lines[0][lines[0].find("[") + 1 : lines[0].find("]")] if "[" in lines[0] else ""
        m = _parse_meta(b)
        if m and m["sid"] not in sid_state:
            # 成熟度是 sid（谱系）级属性：以最新版本计数为准
            lm = _latest_meta(m["sid"])
            sid_state[m["sid"]] = _maturity_state(lm, len(sessions_map.get(m["sid"], set())))
        state = sid_state.get(m["sid"], "draft") if m else "draft"
        out.append(
            {
                "id": _entry_id(b),
                "date": date,
                "content": b,
                "maturity": state,
                "maturity_label": _MATURITY_LABELS.get(state, ""),
            }
        )
    return list(reversed(out))  # 文件追加序=旧在前 → 倒序=最新在前


def edit_item(kind: str, old: str, new: str) -> str:
    """M5 人可改：替换反思/技能条目内容（文件层；向量由端点重灌 reindex）"""
    file = REFLECTIONS_FILE() if kind == "reflection" else SKILLS_FILE() if kind == "skill" else None
    if file is None:
        return "未知类型"
    blocks = _blocks(file)
    for i, b in enumerate(blocks):
        if old in b:
            blocks[i] = b.replace(old, new)
            # 同 _remove_block：写回必须补 "## " 前缀（2026-08-30 同源修复）
            body = "\n\n".join(x if x.startswith("## ") else "## " + x for x in blocks)
            atomic_write_text(file, body + ("\n\n" if blocks else ""))
            return "已更新"
    return "未找到匹配的条目"


def delete_item(kind: str, content: str) -> str:
    """M5 人可删：kind=reflection|skill，按内容匹配删除"""
    if kind == "reflection":
        return (
            "已删除"
            if _remove_block(REFLECTIONS_FILE(), content, "reflections")
            else "未找到匹配的反思"
        )
    if kind == "skill":
        return "已删除" if _remove_block(SKILLS_FILE(), content, "skills") else "未找到匹配的技能"
    return "未知类型"


async def reindex_evolution() -> str:
    """从源文件重建反思/技能向量索引（源文件权威，索引可重建——与 kb_reindex 同模式）。
    背景：chroma 删库/损坏后若不重灌，search_skills/反思检索永远为空（"没存过讲法"假象）。"""
    from app.memory.vector import aembed as _aembed

    rebuilt = []
    for name, file in (("reflections", REFLECTIONS_FILE()), ("skills", SKILLS_FILE())):
        blocks = _blocks(file)
        if not blocks:
            continue
        col = _get_collection(name)
        old = col.get(include=[])["ids"]
        if old:
            col.delete(ids=old)
        for b in blocks:
            doc = _strip_meta(b)
            col.upsert(ids=[_entry_id(b)], documents=[doc], embeddings=[(await _aembed([doc]))[0]])
        rebuilt.append(f"{name}×{len(blocks)}")
    return f"已重建: {', '.join(rebuilt)}" if rebuilt else "(无源条目可重建)"


# ---------- 反思（Reflexion）----------


async def reflect_teaching(context: str) -> str:
    """用户对讲解不满意（没听懂/太快/讲错）时调用：生成三段式反思入库改进。context=刚才发生什么"""
    context = (context or "").strip()
    if not context:
        return "(反思内容为空，请重试)"
    if _count_lines(REFLECTIONS_FILE()) >= CAP_LIMIT:
        return f"(反思库已满 {CAP_LIMIT} 条，请先让我整理合并旧的反思)"
    agent = _build_agent(REFLECT_PROMPT)
    r = await agent.run(f"发生了什么：{context}\n\n用户反馈：用户表示不满意/没听懂。")
    reflection = r.output.strip()
    if not reflection:
        return "(反思生成失败，模型返回空)"
    ts = datetime.now().strftime("%Y-%m-%dT%H:%M")
    rid = uuid.uuid4().hex[:6]
    block = f"## [{ts}] 反思 #{rid}\n{reflection}"
    # 语义查重（2026-08-19 P1 复盘缺陷3）：与库内已有反思高度相似 → 拒写防堆积
    dup = await _is_duplicate("reflections", block)
    if dup:
        return f"(已有相似反思，不重复写入——库内: {dup[:40]}…)"
    _append(REFLECTIONS_FILE(), block)
    _get_collection("reflections").upsert(
        ids=[_entry_id(block)], documents=[block], embeddings=[(await aembed([block]))[0]]
    )
    # ACE 接地计数：reflect_teaching 的调用前提 = 用户显式不满意（工具 docstring 契约）→
    # 本会话被检索过的技能 harmful+1（检索后讲解被否定，技能可疑——接地信号非模型自评）
    _mark_explicit("dissatisfied")
    _bump_session_retrieved("harmful")
    return f"已反思并入库（#{rid}）。下次遇到类似情况会按反思改进。"


def _block_first_line(block: str, prefix: str = "") -> str:
    """块的首行内容（跳过 # 标题行、### 子标题、[时间] 反思/技能标签行；技能块按 prefix 找"描述："行）。"""
    for line in block.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if "反思 #" in s or "技能 #" in s:  # [2026-08-19T10:00] 反思 #id 标签行
            continue
        if prefix:
            if s.startswith(prefix):
                return s[len(prefix) :].strip()[:100]
        else:
            return s[:100]
    return block[:100]


def _blocks(path) -> list[str]:
    """按块头切分（## [时间] 块级标题；不误切 ### 子标题——用 \n## 前缀匹配）。
    全模块唯一定义（2026-08-30 清理：曾有一个按 ^## \\[ 切分、保留 "## " 前缀的旧定义，
    被本定义遮蔽从不生效，已删除）——返回块不带 "## " 前缀，写回文件时必须补回。"""
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    return [b.strip() for b in re.split(r"\n## ", "\n" + text) if b.strip()]


def _skill_desc(block: str) -> str:
    """技能块的"何时用"摘要：优先 背景：行（五段技能包），回退 描述：行（旧格式）。"""
    for prefix in ("背景：", "描述："):
        for line in block.splitlines():
            s = line.strip()
            if s.startswith(prefix):
                return s[len(prefix):].strip()[:100]
    return _block_first_line(block)


def recent_pair(limit: int = 1) -> str:
    """注入用：最近经验摘要（S2 截短，2026-08-19，参考 DeepTutor render_skills_manifest——
    摘要清单注入 + 需要完整时工具查，850 字/轮 → ~230 字/轮）。
    反思/技能各只留首行摘要（何时用），完整讲法模型自己 search_skills 查。

    ACE playbook 升级（2026-08-30，设计 §4）：技能侧有任何非零计数（playbook 数据存在）时，
    切到排序注入——每 sid 取最新版本，按 helpful−harmful 降序取 top-2；
    harmful≥3 且 harmful>helpful 的条目降权排尾（不删——删除归模型/用户决策，判断无墙）。
    硬约束：无 playbook 计数数据（全 0/0 或无技能）→ 输出与升级前逐字节一致（有测试断言）。"""
    parts = []
    # 失败教训：最近反思首行（反思无计数器，维持原逻辑）
    rblocks = _blocks(REFLECTIONS_FILE())
    if rblocks:
        head = _block_first_line(rblocks[-1])
        parts.append(f"【最近教训】{head}（完整讲法用 search_skills）")
    # 成功讲法
    sblocks = _blocks(SKILLS_FILE())
    metas = [_parse_meta(b) for b in sblocks]
    has_counts = any(m and (m["helpful"] or m["harmful"]) for m in metas)
    if sblocks and not has_counts:
        # 无 playbook 数据 → 旧行为逐字节不变
        desc = _block_first_line(sblocks[-1], prefix="描述：")
        parts.append(f"【最近讲法】{desc}（完整讲法用 search_skills）")
    elif sblocks:
        # ACE 注入：每 sid 最新版本参与排序；无 sid 旧格式块视为 0/0 候选
        latest: dict[str, tuple] = {}  # sid → (idx, block, meta)
        cands = []  # (score, idx, block, meta|None)
        for i, (b, m) in enumerate(zip(sblocks, metas, strict=True)):
            if m is None:
                cands.append((0, i, b, None))
                continue
            cur = latest.get(m["sid"])
            if cur is None or m["version"] > _parse_meta(cur[1])["version"]:
                latest[m["sid"]] = (i, b, m)
        for i, b, m in latest.values():
            cands.append((m["helpful"] - m["harmful"], i, b, m))

        def _demoted(m) -> bool:
            return bool(m) and m["harmful"] >= 3 and m["harmful"] > m["helpful"]

        # 成熟度门控（2026-08-30 设计 §2/§4）：mature 优先排前；draft 标注「新·未验证」；
        # deprecated（=②的降权条件）排尾带警示——判断归模型，标注与排序归代码
        sessions_map = _sid_grounded_sessions()

        def _state_of(m) -> str:
            return _maturity_state(m, len(sessions_map.get(m["sid"], set()))) if m else "draft"

        ok = sorted(
            (c for c in cands if not _demoted(c[3])),
            key=lambda c: (0 if _state_of(c[3]) == "mature" else 1, -c[0], -c[1]),
        )
        bad = sorted((c for c in cands if _demoted(c[3])), key=lambda c: (-c[0], -c[1]))
        for _score, _i, b, m in (ok + bad)[: max(2, limit)]:
            desc = _skill_desc(b)
            if _demoted(m):
                parts.append(f"【讲法】{desc}（历史反馈不佳——谨慎参考；完整讲法用 search_skills）")
            elif _state_of(m) == "draft":
                parts.append(f"【讲法】{desc}（新·未验证——待接地反馈；完整讲法用 search_skills）")
            else:
                parts.append(f"【讲法】{desc}（完整讲法用 search_skills）")
    if not parts:
        return "(暂无教训与讲法)"
    return "\n".join(parts)


# ---------- 技能（Voyager）----------


def _parse_sid_v(block: str) -> tuple[str, int] | None:
    """解析技能块头 '#sid v{n}' → (sid, version)；旧格式无 v 号视为 v1。"""
    m = re.search(r"技能 #([0-9a-f]+)(?: v(\d+))?", block)
    if not m:
        return None
    return m.group(1), int(m.group(2) or 1)


# ---------- ACE playbook v2 条目格式（2026-08-30，设计 docs/2026-08-30-ACE-PLAYBOOK-DESIGN.md §2） ----------
# 块头追加计数元数据：## [ts] 技能 #sid v{n} | helpful:N harmful:M
# 向后兼容：v1 块（无计数段）解析为 0/0。计数只在接地信号下递增（论文 §5 实测失效边界：
# 无接地反馈时 ACE 上下文被污染反降——模型自评永远到不了 _bump_counter，见 on_* 钩子）。


def _parse_meta(block: str) -> dict | None:
    """解析技能块头 → {sid, version, helpful, harmful}（v2）；v1 块无计数段 → helpful/harmful=0/0。"""
    m = re.search(r"技能 #([0-9a-f]+)(?: v(\d+))?(?:\s*\|\s*helpful:(\d+)\s+harmful:(\d+))?", block)
    if not m:
        return None
    return {
        "sid": m.group(1),
        "version": int(m.group(2) or 1),
        "helpful": int(m.group(3) or 0),
        "harmful": int(m.group(4) or 0),
    }


def _strip_meta(block: str) -> str:
    """嵌入/检索用文本：剥掉块头计数元数据（| helpful:N harmful:M）。
    关键设计：计数随接地信号原地递增（bump），若计数参与嵌入则每次 bump 向量漂移、必须重嵌入；
    剥离后 bump = 纯文件重写（同步、零 LLM 零向量），向量只对内容变化（add/revise）更新。"""
    lines = block.splitlines()
    if lines:
        lines[0] = re.sub(r"\s*\|\s*helpful:\d+\s*harmful:\d+", "", lines[0])
    return "\n".join(lines)


def _latest_meta(sid: str) -> dict | None:
    """指定 sid 的最新版本元数据（从源文件读——源文件权威，向量库文档已剥计数不可信）。"""
    best = None
    for b in _blocks(SKILLS_FILE()):
        m = _parse_meta(b)
        if m and m["sid"] == sid and (best is None or m["version"] > best["version"]):
            best = m
    return best


# ---------- 技能成熟度门控（2026-08-30，设计 docs/2026-08-30-SKILL-MATURITY-DESIGN.md §2-§4） ----------
# 状态 = 计数器 + 会话覆盖的纯函数（派生，读取时计算——禁止存状态字段，写了就会和计数器脱节）。
# 三个事件点全复用现有通道：bump 重算+变迁写 change_log（store.log_change 现有 obs 通道）；
# 会话收尾扫 deprecated 超龄出向量索引（lifecycle.py demote 模式）；add 查重升级（不动）。
# 明确不做批量整理定时任务（PSN arXiv:2601.03509：在线重构 0.846 vs 离线 0.688）。

MATURE_MIN_HELPFUL = 3
MATURE_MAX_HARMFUL = 1
MATURE_MIN_SESSIONS = 2  # 跨 ≥2 session 有接地才算成熟——单会话连续好评可能是同一偏好的回音
DEPRECATED_MIN_HARMFUL = 3
EXIT_STALE_DAYS = 14  # deprecated 连续无新 helpful 超此天数 → 出向量索引（复活窗口）

_MATURITY_LABELS = {"draft": "新·未验证", "mature": "成熟", "deprecated": "历史反馈不佳"}


def _maturity_state(meta: dict | None, grounded_sessions: int = 0) -> str:
    """四态派生（纯函数，设计 §2 表格；meta=None 或无 sid 旧格式块按 0/0 处理 → draft 不误伤）：
    draft(0/0 无接地信号) / tested(helpful≥1 且 >harmful) /
    mature(helpful≥3、harmful≤1、跨≥2 session 有接地) / deprecated(harmful≥3 且 >helpful)。"""
    h = meta["helpful"] if meta else 0
    ha = meta["harmful"] if meta else 0
    if ha >= DEPRECATED_MIN_HARMFUL and ha > h:
        return "deprecated"
    if h >= MATURE_MIN_HELPFUL and ha <= MATURE_MAX_HARMFUL and grounded_sessions >= MATURE_MIN_SESSIONS:
        return "mature"
    if h >= 1 and h > ha:
        return "tested"
    return "draft"


def _grounding_events() -> list[dict]:
    """读接地台账（尾部 5000 行——成熟度派生只需近期证据；坏行跳过不崩，失败按空处理）。"""
    try:
        gf = GROUNDING_FILE()
        if not gf.exists():
            return []
        out = []
        for ln in gf.read_text(encoding="utf-8").splitlines()[-5000:]:
            try:
                rec = json.loads(ln)
            except Exception as _je:
                print(f"[evolution] 跳过坏台账行: {_je}", file=__import__('sys').stderr)
                continue
            if isinstance(rec, dict) and rec.get("sid"):
                out.append(rec)
        return out
    except Exception as _e:
        print(f"[agent/evolution] 接地台账读取失败（按空处理）: {_e}", flush=True)
        return []


def _sid_grounded_sessions() -> dict[str, set]:
    """sid → 有接地信号的 session 集合（bump 事件；无 session 的不计——无法证明跨会话）。"""
    m: dict[str, set] = {}
    for e in _grounding_events():
        if e.get("event") == "bump" and e.get("session"):
            m.setdefault(e["sid"], set()).add(e["session"])
    return m


def skill_maturity(sid: str) -> str:
    """指定 sid 的当前成熟度（最新版本计数 + 跨会话接地，派生不存）。"""
    return _maturity_state(_latest_meta(sid), len(_sid_grounded_sessions().get(sid, set())))


def _append_grounding(rec: dict) -> None:
    """接地台账落账（append-only，尽力而为——观测非主流程）。"""
    try:
        gf = GROUNDING_FILE()
        gf.parent.mkdir(parents=True, exist_ok=True)
        with gf.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as _e:
        print(f"[agent/evolution] 接地台账落盘失败（静默）: {_e}", flush=True)


def _log_maturity_change(action: str, summary: str) -> None:
    """状态变迁/出索引写 change_log（app.memory.store.log_change 现有 obs 通道，不新造）。"""
    try:
        from app.memory.store import log_change

        log_change(action, summary)
    except Exception as _e:
        print(f"[agent/evolution] change_log 写入失败（静默）: {_e}", flush=True)


def exit_deprecated_skills(now: datetime | None = None, max_exit: int = 10) -> list[str]:
    """会话收尾事件点（设计 §3-2）：deprecated 且连续 ≥14 天无新 helpful 的技能出向量索引——
    复用 lifecycle.py demote 模式：文件保留可找回（reindex_evolution/治理视图），检索不再命中；
    彻底删除归模型/用户决策（delete_item 通道，判断无墙）。渐进式每轮上限 max_exit。
    复活窗口：窗口内 helpful+1 即脱出 deprecated（状态派生，bump 即变），扫不到它。
    返回本次出索引的 sid 列表。"""
    now = now or datetime.now()
    try:
        last_helpful: dict[str, datetime] = {}
        last_bump: dict[str, datetime] = {}
        exited: dict[str, datetime] = {}

        def _rec_ts(e) -> datetime | None:
            try:
                return datetime.fromisoformat(e["ts"])
            except Exception:
                return None

        for e in _grounding_events():
            ts = _rec_ts(e)
            if ts is None:
                continue
            sid = e["sid"]
            if e.get("event") == "bump":
                if ts > last_bump.get(sid, datetime.min):
                    last_bump[sid] = ts
                if e.get("field") == "helpful" and ts > last_helpful.get(sid, datetime.min):
                    last_helpful[sid] = ts
            elif e.get("event") == "exit":
                if ts > exited.get(sid, datetime.min):
                    exited[sid] = ts
        # 按 sid 归集最新版本块
        latest: dict[str, tuple[str, dict]] = {}
        for b in _blocks(SKILLS_FILE()):
            m = _parse_meta(b)
            if m and (m["sid"] not in latest or m["version"] > latest[m["sid"]][1]["version"]):
                latest[m["sid"]] = (b, m)
        sessions_map = _sid_grounded_sessions()
        out = []
        for sid, (block, m) in latest.items():
            if len(out) >= max_exit:
                break
            if _maturity_state(m, len(sessions_map.get(sid, set()))) != "deprecated":
                continue
            # 幂等：已出索引且之后无新 bump → 跳过（文件还在，每轮扫到但不重复动作）
            if sid in exited and sid not in {s for s, t in last_bump.items() if t > exited[sid]}:
                continue
            anchor = last_helpful.get(sid)
            if anchor is None:
                # 从无 helpful：锚点 = 最新版本块时间（「连续无新 helpful」自该版本存在起算）
                try:
                    anchor = datetime.strptime(
                        block.splitlines()[0].split("[")[1].split("]")[0], "%Y-%m-%dT%H:%M"
                    )
                except Exception as _ae:
                    # 时间不可解析 → 保守不退出（绝不误伤），但必须可见（坏块=数据异常信号）
                    print(f"[evolution] 跳过时间不可解析的块: {_ae}", file=__import__('sys').stderr)
                    continue
            if (now - anchor).days < EXIT_STALE_DAYS:
                continue
            # 出索引：该 sid 全部版本出向量库（只删最新版本没用——旧版本仍会检索命中）。
            # 按文档内容定位而非 entry_id：id 是含计数块头的哈希，bump 改头后 id 漂移，
            # 入库时的旧 id 与当前块对不上（剥离计数的文档内容才稳定，且各版本都含 sid 标记）
            try:
                col = _get_collection("skills")
                all_docs = col.get(include=["documents"])
                victim_ids = [
                    i
                    for i, d in zip(all_docs.get("ids") or [], all_docs.get("documents") or [], strict=True)
                    if f"技能 #{sid} " in (d or "")
                ]
                if victim_ids:
                    col.delete(ids=victim_ids)
            except Exception as _e:
                print(f"[agent/evolution] 出索引删除失败（跳过该技能）: {_e}", flush=True)
                continue
            _append_grounding({"event": "exit", "ts": now.isoformat(timespec="seconds"), "sid": sid})
            _log_maturity_change(
                "skill_exit_index",
                f"技能 #{sid}：deprecated 且连续 {EXIT_STALE_DAYS} 天无新 helpful → 出向量索引（文件保留可找回）",
            )
            out.append(sid)
        if out:
            print(
                f"[agent/evolution] {len(out)} 条 deprecated 技能出索引（文件保留）: "
                + "、".join(f"#{s}" for s in out),
                flush=True,
            )
        return out
    except Exception as _e:
        print(f"[agent/evolution] 弃用技能退出扫描失败（不影响主流程）: {_e}", flush=True)
        return []


def _bump_counter(sid: str, field: str) -> bool:
    """计数推进器（纯代码，Curator 侧）：指定 sid 最新版本块的 helpful/harmful 原地 +1。
    只允许从接地钩子（on_* / apply_delta 的 grounded 校验通过）到达——模型自评无路可进。
    向量侧零操作（嵌入文档是 _strip_meta 版本，计数变化不影响向量）。"""
    if field not in ("helpful", "harmful"):
        return False
    try:
        file = SKILLS_FILE()
        blocks = _blocks(file)
        best_i, best_v = -1, -1
        for i, b in enumerate(blocks):
            m = _parse_meta(b)
            if m and m["sid"] == sid and m["version"] > best_v:
                best_i, best_v = i, m["version"]
        if best_i < 0:
            return False
        m = _parse_meta(blocks[best_i])
        h = m["helpful"] + (1 if field == "helpful" else 0)
        ha = m["harmful"] + (1 if field == "harmful" else 0)
        # 成熟度门控事件点（设计 §3-1）：bump 是唯一的计数变化点 → 状态变迁只在这里发生。
        # 旧状态用 bump 前的计数+会话覆盖，新状态用 bump 后的——先落台账再重算（台账即会话覆盖数据源）
        old_state = _maturity_state(m, len(_sid_grounded_sessions().get(sid, set())))
        lines = blocks[best_i].splitlines()
        header = re.sub(r"\s*\|\s*helpful:\d+\s*harmful:\d+", "", lines[0])
        lines[0] = f"{header} | helpful:{h} harmful:{ha}"
        blocks[best_i] = "\n".join(lines)
        # _blocks（现行定义）切分后块不带 "## " 前缀——写回必须补回，否则损坏块文件格式
        body = "\n\n".join(b if b.startswith("## ") else "## " + b for b in blocks)
        atomic_write_text(file, body + ("\n\n" if blocks else ""))
        _append_grounding(
            {
                "event": "bump",
                "ts": datetime.now().isoformat(timespec="seconds"),
                "sid": sid,
                "session": _cur_session(),
                "field": field,
            }
        )
        new_state = _maturity_state(
            {"helpful": h, "harmful": ha}, len(_sid_grounded_sessions().get(sid, set()))
        )
        if new_state != old_state:
            _log_maturity_change("skill_maturity", f"技能 #{sid}：{old_state} → {new_state}")
        return True
    except Exception as _e:
        print(f"[agent/evolution] 计数推进失败（静默）: {_e}", flush=True)
        return False


# ---------- ACE 接地信号注册表（2026-08-30，设计 §2/§5） ----------
# 关联窗口 = 同 session_id（与 error_loop 台账的 contextvar 同构）。理由：
# ①error_loop 台账本就按 session 归属，检索→结果的因果在会话内最近、可接地归因；
# ②跨会话归因无法区分"哪次检索导致了什么"，把无关成败记到技能头上正是论文 §5 实测的污染源
# （FiNER 无接地时 ACE 67.3 < base 70.7）——宁可漏计，不可错计。
_RETRIEVED: dict[str, list[str]] = {}  # session_id → 本会话 search_skills 命中的技能 sid（保序去重）
_VERIFY_RESULTS: dict[str, list[str]] = {}  # session_id → verify_answer 评级（consistent/partial/inconsistent）
_EXPLICIT_FB: dict[str, dict[str, int]] = {}  # session_id → {"satisfied": n, "dissatisfied": n}
_REGISTRY_CAP = 200  # FIFO 上限防泄漏（end_session 未走到的异常路径兜底）


def _reg_touch(reg: dict, key: str, default):
    if key not in reg:
        if len(reg) >= _REGISTRY_CAP:
            reg.pop(next(iter(reg)))  # 逐出最旧
        reg[key] = default
    return reg[key]


def _cur_session() -> str | None:
    try:
        from app.agent import error_loop

        return error_loop.get_current_session_id()
    except Exception:
        return None


def _record_retrieval(sids: list[str]) -> None:
    """search_skills 命中登记（关联窗口起点）。无 session 上下文 → 跳过（与 error_loop no-op 一致）。"""
    sid = _cur_session()
    if not sid:
        return
    lst = _reg_touch(_RETRIEVED, sid, [])
    for s in sids:
        if s and s not in lst:
            lst.append(s)


def _bump_session_retrieved(field: str) -> int:
    """对本会话被检索过的技能批量 bump（接地事件触发）。返回推进条数。"""
    sid = _cur_session()
    if not sid:
        return 0
    n = 0
    for s in list(_RETRIEVED.get(sid, [])):
        if _bump_counter(s, field):
            n += 1
    return n


def on_failure_sequence(session_id: str | None = None) -> None:
    """接地钩子（error_loop 失败序列收尾落台账时调用）：本会话被检索技能 harmful+1。
    设计 §2：技能被检索后 error_loop 记录失败序列 → harmful。outcome 不论 recovered/hard_stop——
    失败序列发生了即计数（恢复只是止损，不抹除失败事实）。"""
    try:
        sid = session_id or _cur_session()
        if not sid:
            return
        for s in list(_RETRIEVED.get(sid, [])):
            _bump_counter(s, "harmful")
    except Exception as _e:
        print(f"[agent/evolution] 失败序列计数钩子失败（静默）: {_e}", flush=True)


def on_verify_result(grade: str) -> None:
    """接地钩子（tutor 包装 verify_answer 调用）：consistent → 被检索技能 helpful+1；
    inconsistent → harmful+1；partial/unknown 不计（信号不纯粹，宁可漏计不污染）。"""
    sid = _cur_session()
    if not sid:
        return
    _reg_touch(_VERIFY_RESULTS, sid, []).append(grade)
    if grade == "consistent":
        _bump_session_retrieved("helpful")
    elif grade == "inconsistent":
        _bump_session_retrieved("harmful")


def _mark_explicit(kind: str) -> None:
    """用户显式反馈登记（save_skill=满意 / reflect_teaching=不满意——两工具的调用前提即显式反馈）。"""
    sid = _cur_session()
    if not sid:
        return
    fb = _reg_touch(_EXPLICIT_FB, sid, {"satisfied": 0, "dissatisfied": 0})
    fb[kind] = fb.get(kind, 0) + 1


def end_session(session_id: str | None) -> None:
    """会话收尾清理注册表（chat_hooks 收尾钩子调用）。"""
    if not session_id:
        return
    for reg in (_RETRIEVED, _VERIFY_RESULTS, _EXPLICIT_FB):
        reg.pop(session_id, None)


def _session_seq_ended(session_id: str) -> bool:
    """本会话 error_loop 台账是否有失败序列收尾事件（读 error_ledger.jsonl——同一仪器不另建）。"""
    try:
        from app.agent import error_loop

        lp = error_loop._ledger_path()
        if not lp.exists():
            return False
        for ln in lp.read_text(encoding="utf-8").splitlines()[-500:]:
            try:
                rec = json.loads(ln)
            except Exception as _je:
                print(f"[evolution] 跳过坏台账行: {_je}", file=__import__('sys').stderr)
                continue
            if rec.get("session_id") == session_id and rec.get("event") == "seq_end":
                return True
    except Exception as _e:
        print(f"[agent/evolution] 台账读取失败（静默）: {_e}", flush=True)
    return False


def session_signal_summary(session_id: str | None = None) -> str:
    """Reflector 第 7 路输入的接地信号摘要（代码侧采集，非模型生成——模型只消费不生产信号）：
    被检索技能（sid+首行）/ error_loop 失败序列 / verify 评级 / 用户显式反馈。"""
    sid = session_id or _cur_session()
    if not sid:
        return "（无 session 上下文，无接地信号）"
    lines = []
    retr = _RETRIEVED.get(sid, [])
    if retr:
        descs = []
        for s in retr:
            lm = _latest_meta(s)
            descs.append(f"#{s}（v{lm['version']} helpful:{lm['helpful']} harmful:{lm['harmful']}）" if lm else f"#{s}（已删除）")
        lines.append("本轮被检索技能：" + "；".join(descs))
    try:
        from app.agent import error_loop

        lp = error_loop._ledger_path()
        if lp.exists():
            evs = []
            for ln in lp.read_text(encoding="utf-8").splitlines()[-500:]:
                try:
                    rec = json.loads(ln)
                except Exception as _je:
                    print(f"[evolution] 跳过坏台账行: {_je}", file=__import__('sys').stderr)
                    continue
                if rec.get("session_id") == sid:
                    evs.append(rec)
            n_err = sum(1 for e in evs if e.get("event") == "error")
            seqs = [e for e in evs if e.get("event") == "seq_end"]
            if n_err:
                lines.append(
                    f"工具失败 {n_err} 次；失败序列 {len(seqs)} 段"
                    f"（{'、'.join(str(e.get('outcome', '')) for e in seqs) or '无收尾'}）"
                )
    except Exception as _e:
        print(f"[agent/evolution] 台账信号摘要失败（静默）: {_e}", flush=True)
    vf = _VERIFY_RESULTS.get(sid, [])
    if vf:
        lines.append("verify 结果：" + "、".join(vf))
    fb = _EXPLICIT_FB.get(sid, {})
    if fb.get("satisfied") or fb.get("dissatisfied"):
        lines.append(f"用户显式反馈：满意 {fb.get('satisfied', 0)} 次 / 不满意 {fb.get('dissatisfied', 0)} 次")
    return "\n".join(lines) if lines else "（本轮无接地信号：无技能检索/无工具失败/无验证/无显式反馈）"


def session_grounded_sids(session_id: str | None = None) -> dict:
    """apply_delta 的 bump 接地校验集（代码侧计算）：哪些 sid 的哪个计数有接地证据可推进。
    Reflector 提的 bump 只有落在集合内才执行——模型自评在代码层焊死（设计 §0/§5 红线）。"""
    helpful: set = set()
    harmful: set = set()
    sid = session_id or _cur_session()
    if not sid:
        return {"helpful": helpful, "harmful": harmful}
    retr = set(_RETRIEVED.get(sid, []))
    fb = _EXPLICIT_FB.get(sid, {})
    vf = _VERIFY_RESULTS.get(sid, [])
    if fb.get("satisfied") or "consistent" in vf:
        helpful = set(retr)
    if fb.get("dissatisfied") or "inconsistent" in vf or _session_seq_ended(sid):
        harmful = set(retr)
    return {"helpful": helpful, "harmful": harmful}


# ---------- ACE Curator：确定性 delta 合并（零 LLM，循环归代码） ----------
DELTA_OPS = ("add", "bump", "revise")


def parse_delta_entries(out: str) -> list[dict] | None:
    """Reflector 输出的 delta entries 解析（防御模式，对齐 _extract_* 乱 JSON 兜底）：
    乱 JSON/非数组 → None；条目逐条校验（op 白名单/字段类型/长度上限），非法条目丢弃不崩。"""
    out = (out or "").strip()
    if not out or out == "无" or "无。" in out[:4]:
        return None
    m = re.search(r"\[.*\]", out, re.DOTALL)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except Exception:
        return None
    if not isinstance(data, list):
        return None
    valid = []
    for e in data:
        if not isinstance(e, dict):
            continue
        op = str(e.get("op", "")).strip().lower()
        sid = str(e.get("id", "")).strip()
        content = str(e.get("content", "")).strip()
        if op == "add":
            if not content or len(content) > 2000 or "\n## [" in content:
                continue
            valid.append({"op": "add", "section": str(e.get("section", "讲法")).strip(), "content": content})
        elif op == "bump":
            field = str(e.get("field", "")).strip().lower()
            if not re.fullmatch(r"[0-9a-f]{4,16}", sid) or field not in ("helpful", "harmful"):
                continue
            valid.append({"op": "bump", "id": sid, "field": field})
        elif op == "revise":
            if not re.fullmatch(r"[0-9a-f]{4,16}", sid) or not content or len(content) > 2000 or "\n## [" in content:
                continue
            valid.append({"op": "revise", "id": sid, "content": content})
        # 未知 op → 丢弃
    return valid or None


async def apply_delta(entries: list[dict], grounded: dict | None = None) -> str:
    """ACE Curator 确定性合并器（零 LLM，循环归代码；设计 §3/§5）：
    - add：语义查重（_is_duplicate 0.92）→ 追加新 sid v1（0/0）
    - bump：原地递增计数——必须落在 grounded 校验集内（代码侧接地证据），否则丢弃（模型自评焊死）
    - revise：同 sid v+1（复用版本化，计数继承，旧版本保留可回滚）
    幂等：delta 整体 sha1 落 journal（playbook_deltas.jsonl），同 delta 重放不双加。"""
    if not entries:
        return "(delta 为空)"
    delta_id = hashlib.sha1(
        json.dumps(entries, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    jf = DELTAS_FILE()
    try:
        if jf.exists() and delta_id in jf.read_text(encoding="utf-8"):
            return "(该 delta 已应用过——幂等跳过)"
    except Exception as _e:
        print(f"[agent/evolution] delta journal 读取失败（按未应用继续）: {_e}", flush=True)
    n_add = n_bump = n_rev = n_drop = 0
    for e in entries:
        op = e.get("op")
        if op == "add":
            if _count_lines(SKILLS_FILE()) >= CAP_LIMIT:
                n_drop += 1
                continue
            if await _is_duplicate("skills", e["content"]):
                n_drop += 1
                continue
            sid = uuid.uuid4().hex[:6]
            ts = datetime.now().strftime("%Y-%m-%dT%H:%M")
            block = f"## [{ts}] 技能 #{sid} v1 | helpful:0 harmful:0\n{e['content']}"
            _append(SKILLS_FILE(), block)
            doc = _strip_meta(block)
            _get_collection("skills").upsert(
                ids=[_entry_id(block)], documents=[doc], embeddings=[(await aembed([doc]))[0]]
            )
            n_add += 1
        elif op == "bump":
            allow = (grounded or {}).get(e["field"]) or set()
            if e["id"] not in allow:
                n_drop += 1  # 无接地证据的 bump（模型自评）一律丢弃——论文 §5 失效边界
                continue
            if _bump_counter(e["id"], e["field"]):
                n_bump += 1
            else:
                n_drop += 1
        elif op == "revise":
            meta = _latest_meta(e["id"])
            if meta is None or _count_lines(SKILLS_FILE()) >= CAP_LIMIT:
                n_drop += 1
                continue
            ts = datetime.now().strftime("%Y-%m-%dT%H:%M")
            block = (
                f"## [{ts}] 技能 #{meta['sid']} v{meta['version'] + 1} "
                f"| helpful:{meta['helpful']} harmful:{meta['harmful']}\n{e['content']}"
            )
            _append(SKILLS_FILE(), block)
            doc = _strip_meta(block)
            _get_collection("skills").upsert(
                ids=[_entry_id(block)], documents=[doc], embeddings=[(await aembed([doc]))[0]]
            )
            n_rev += 1
        else:
            n_drop += 1
    # journal：无论部分丢弃都记录——已应用语义是"该 delta 处理过"，重放整体跳过（防双加）
    try:
        jf.parent.mkdir(parents=True, exist_ok=True)
        with jf.open("a", encoding="utf-8") as fp:
            fp.write(
                json.dumps(
                    {
                        "delta_id": delta_id,
                        "ts": datetime.now().isoformat(timespec="seconds"),
                        "add": n_add,
                        "bump": n_bump,
                        "revise": n_rev,
                        "dropped": n_drop,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    except Exception as _e:
        print(f"[agent/evolution] delta journal 落盘失败（静默）: {_e}", flush=True)
    tail = f"（丢弃 {n_drop} 条非法/无接地/重复）" if n_drop else ""
    return f"delta 已合并：add×{n_add} bump×{n_bump} revise×{n_rev}{tail}"


def _block_sid(block: str) -> str | None:
    p = _parse_sid_v(block)
    return p[0] if p else None


def _build_skill_block(description: str, method: str, sid: str, version: int,
                       helpful: int = 0, harmful: int = 0) -> str:
    """五段技能包（P0-1 2026-08-27，对齐 SkillForge：背景/步骤/案例/常见失败/参考——空字段省略）。
    描述=背景(when)；方法=主流程（自动拆 2-4 步）；案例/常见失败由失败回灌（P0-3）与后续修订填充。
    ACE v2（2026-08-30）：块头带 helpful/harmful 计数元数据（默认 0/0，只经接地信号推进）。"""
    ts = datetime.now().strftime("%Y-%m-%dT%H:%M")
    lines = [f"## [{ts}] 技能 #{sid} v{version} | helpful:{helpful} harmful:{harmful}",
             f"背景：{description}"]
    steps = [st.strip().lstrip("-*0123456789.、 ") for st in method.split("\n") if st.strip()]
    if len(steps) >= 2:
        lines.append("步骤：")
        for st in steps:
            lines.append(f"- {st}")
    else:
        lines.append(f"方法：{method.strip()}")
    return "\n".join(lines)


async def save_skill(description: str, method: str) -> str:
    """用户对讲法满意时，把"讲法"存进技能库（五段技能包，P0-1）。
    描述=何时用；方法=怎么讲。语义查重命中 → 升级为同 sid v{n+1}（修订而非拒收——自进化）；
    库内容量硬限交模型处理。"""
    description = (description or "").strip()
    method = (method or "").strip()
    if not description or not method:
        return "(技能描述和方法都不能为空)"
    # 语义查重（2026-08-19 P1 复盘缺陷3）：命中 → 同主题升级 v+1（P0-1 改为修订不拒收）
    dup = await _is_duplicate("skills", description + "\n" + method)
    if dup:
        dup_block = dup[:200]
        sid_v = _parse_sid_v(dup_block)
        if sid_v:
            sid = sid_v[0]
            # ACE v2：版本/计数以源文件最新块为准（向量文档已 _strip_meta 剥计数，不可信）；
            # 修订继承计数（ACE 语义：计数是策略谱系的元数据，随内容修订延续）
            latest = _latest_meta(sid)
            ver = latest["version"] if latest else sid_v[1]
            h = latest["helpful"] if latest else 0
            ha = latest["harmful"] if latest else 0
            new_ver = ver + 1
            block = _build_skill_block(description, method, sid, new_ver, h, ha)
            if _count_lines(SKILLS_FILE()) >= CAP_LIMIT:
                return f"(技能库已满 {CAP_LIMIT} 条——可把 #{sid} 旧版本合并后重试)"
            _append(SKILLS_FILE(), block)
            doc = _strip_meta(block)
            _get_collection("skills").upsert(
                ids=[_entry_id(block)], documents=[doc], embeddings=[(await aembed([doc]))[0]]
            )
            _mark_explicit("satisfied")
            _bump_session_retrieved("helpful")
            return f"技能 #{sid} 已升级到 v{new_ver}（修订自 v{ver}——原版本保留可回滚）。"
        # 旧格式块（无 sid）：仍拒写提示
        return f"(已有相似技能（旧格式），不重复写入——库内: {dup[:40]}…)"
    if _count_lines(SKILLS_FILE()) >= CAP_LIMIT:
        return f"(技能库已满 {CAP_LIMIT} 条，请先让我整理合并旧的技能)"
    sid = uuid.uuid4().hex[:6]
    block = _build_skill_block(description, method, sid, 1)
    _append(SKILLS_FILE(), block)
    doc = _strip_meta(block)
    _get_collection("skills").upsert(
        ids=[_entry_id(block)], documents=[doc], embeddings=[(await aembed([doc]))[0]]
    )
    # ACE 接地计数：save_skill 的调用前提 = 用户显式满意（工具 docstring 契约）→
    # 本会话被检索过的技能 helpful+1（检索→满意在同会话内成立，关联窗口见 _RETRIEVED 注释）
    _mark_explicit("satisfied")
    _bump_session_retrieved("helpful")
    return f"技能已入库（#{sid} v1）。遇到类似情境我会想起它。"


async def search_skills(query: str, top_k: int = 3) -> str:
    """查技能库：找"类似情境下怎么讲得好"的沉淀。返回名称+描述摘要；要完整讲法用 read_document 读 skills.md"""
    query = (query or "").strip()
    if not query:
        return "(查询不能为空)"
    try:
        vec = (await aembed([query]))[0]
        hits = _get_collection("skills").query(
            query_embeddings=[vec], n_results=min(top_k, 5), include=["documents", "distances"]
        )
        docs = hits["documents"][0]
        dists = hits["distances"][0]
        if not docs:
            return "(技能库还没有相关沉淀)"
        # P0-1：按 sid 去重（同技能多版本只取最新），旧格式无 sid 保留
        seen_sid: set[str] = set()
        items = []
        hit_sids: list[str] = []
        sessions_map = _sid_grounded_sessions()  # 成熟度标注用（2026-08-30 ③，设计 §4）
        for doc, d in zip(docs, dists, strict=True):
            sid = _block_sid(doc)
            if sid and sid in seen_sid:
                continue
            if sid:
                seen_sid.add(sid)
                hit_sids.append(sid)
            lines = _strip_meta(doc).splitlines()  # 计数元数据不进检索展示（兼容存量未剥离文档）
            head = lines[0].strip() if lines else "(技能)"
            # 修复（2026-08-27 测试发现）：next() 取生成器首个产出——必须用 if 过滤而非逐行产出空串
            desc = next(
                (l.split("背景：", 1)[1].strip() for l in lines if l.startswith("背景：")),
                next((l.split("描述：", 1)[1].strip() for l in lines if l.startswith("描述：")), ""),
            )
            item = f"[相似度 {1 - d:.2f}] {head} | 背景：{desc}"
            if sid:
                # 成熟度标注（计数以源文件最新块为准——向量文档已剥计数）：模型据此决定信任度
                st = _maturity_state(_latest_meta(sid), len(sessions_map.get(sid, set())))
                label = _MATURITY_LABELS.get(st)
                if label:
                    item += f"（{label}）"
            items.append(item)
        # ACE 关联窗口起点（2026-08-30）：命中 sid 登记进本会话注册表——
        # 后续接地事件（失败序列/显式反馈/verify）按此归因推进计数
        _record_retrieval(hit_sids)
        # P1-2（2026-08-27）：技能失败关联提示——pending 待审区有该技能相关失败证据时
        # 附加提示（"历史最优"信号：新版本若失败证据多，可读旧版本回滚——人工/模型决策）
        # 2026-08-30 修复：fail_hit 预初始化——pending 文件不存在时原代码 UnboundLocalError
        # （技能检索整体 500），ACE 集成测试抓出
        fail_hit = ""
        try:
            from app.agent.evolution import PENDING_FILE

            if PENDING_FILE().exists():
                pend = PENDING_FILE().read_text(encoding="utf-8")
                fail_hit = next((l for l in pend.splitlines() if "工具 " in l or "失败" in l), "")
        except Exception:
            fail_hit = ""
        tail = "\n（需要某条技能的完整讲法时，用 read_document 读 memory/skills.md 对应条目）"
        if fail_hit:
            tail += "\n⚠ 最近有失败证据（memory/pending_fixes.md）——若与某技能相关，可考虑修订或回滚旧版本"
        return "\n".join(items) + tail
    except Exception as e:
        return f"(技能检索失败：{e})"
