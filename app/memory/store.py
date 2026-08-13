"""M2 记忆存储：git 跟踪文件 + 画像摘要 + bge-m3 向量去重/JIT 检索
设计依据：docs/M2-DESIGN.md（三层存储 / 双轨去重 / LangMem 画像 / 护栏不是规则）
"""
from datetime import date
from pathlib import Path

from app.memory import vector
from app.memory.schema import MEMORY_FILE, MEMORY_LINE_LIMIT, PROFILE_FILE, PROFILE_LIMIT, MemoryEntry

# 防循环导入：update_profile 内部要调 LLM，由 tutor 注入回调
_profile_writer = None

# D1 事件兜底标记（v0.2，2026-08-13）：本会话是否有记忆变化（remember 写入）。
# 会话收尾钩子（main.py）消费：有变化 → 机器触发画像重提炼（触发归机器，提炼归模型）。
# 粒度 = "会话结束 + 本会话有记忆变化"，不是每次 remember 立即提炼（高频压缩成本不可控）。
_session_memory_changed = False


def register_profile_writer(fn):
    """tutor 模块注册"模型压缩记忆成画像"的回调（模型驱动，应用层零规则）"""
    global _profile_writer
    _profile_writer = fn


def mark_memory_changed():
    global _session_memory_changed
    _session_memory_changed = True


def consume_memory_changed() -> bool:
    """读取并清除会话记忆变化标记（会话收尾钩子调用一次）"""
    global _session_memory_changed
    v = _session_memory_changed
    _session_memory_changed = False
    return v


def _ensure_file():
    MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not MEMORY_FILE.exists():
        MEMORY_FILE.write_text("# 用户记忆（git 跟踪，人可审）\n", encoding="utf-8")


def read_entries() -> list[MemoryEntry]:
    _ensure_file()
    entries = []
    for line in MEMORY_FILE.read_text(encoding="utf-8").splitlines():
        e = MemoryEntry.from_line(line)
        if e:
            entries.append(e)
    return entries


_CAT_TAG = {
    "偏好": "偏好", "preference": "偏好",
    "目标": "目标", "goal": "目标",
    "进度": "进度", "progress": "进度",
    "错误记录": "错误", "mistake": "错误", "error": "错误",
    "学习记录": "学习", "learning": "学习",
}

_synced = False


async def _sync_backfill():
    """首次使用时把文件里已有的记忆回填向量库（迁移 M1 旧数据，懒执行一次）"""
    global _synced
    if _synced:
        return
    _synced = True
    entries = read_entries()
    if not entries:
        return
    try:
        have = vector.existing_ids()
    except Exception:
        return
    missing = [e for e in entries if vector.entry_id(e.content) not in have]
    if not missing:
        return
    try:
        vecs = await vector.aembed([e.content for e in missing])
        for e, v in zip(missing, vecs):
            vector.upsert(vector.entry_id(e.content), e.content, v)
    except Exception:
        pass


def entries_text() -> str:
    """全量记忆文本（供 update_profile 压缩用）"""
    entries = read_entries()
    if not entries:
        return "(暂无记忆)"
    lines = []
    for e in entries:
        tag = _CAT_TAG.get(e.category, "笔记")
        lines.append(f"[{e.created_at}|{tag}|imp={e.importance}] {e.content}")
    return "\n".join(lines)


def recall_profile() -> str:
    """画像摘要（常驻注入，瘦身）——不存在则引导模型生成"""
    if PROFILE_FILE.exists():
        text = PROFILE_FILE.read_text(encoding="utf-8").strip()
        if text:
            return text
    return "(画像未生成：积累记忆后调用 update_profile 生成我的画像)"


async def remember(note: str, source: str = "user", importance: int = 5, category: str = "note") -> str:
    """记住一条用户信息（用户明确说"记住/记一下"时）。source：用户原话→user；转述/代记→agent"""
    note = note.strip()
    if not note:
        return "内容为空，不写入"
    await _sync_backfill()
    if len(read_entries()) >= MEMORY_LINE_LIMIT:
        return f"记忆已达容量上限（{MEMORY_LINE_LIMIT} 条），请先整理：用 recall_profile 看画像、确认哪些可合并/删除"

    # 三层护栏（护栏=提供信息，不是替模型做决定）：
    # ① 字面完全重复（内容哈希相同）→ 硬拒（真重复，写了无意义）
    # ② 0.85~0.97 → 写穿 + 警告（已写入，但相似记忆列表交模型自行判断是否合并）
    # ③ <0.85 → 正常写，无提示
    same_note = next((e for e in read_entries() if e.content == note), None)
    if same_note:
        return f"已存在完全相同的内容（{same_note.content[:50]}……），不重复写入。"
    similar = vector.find_similar(note, top_k=3)
    warn = ""
    if similar:
        near = [f"{old[:40]}({sim:.2f})" for _, old, sim in similar if sim >= vector.DEDUP_SOFT]
        if any(sim >= vector.DEDUP_HARD for _, _, sim in similar):
            warn = f"。注：存在近重复记忆——{ '；'.join(near[:3]) }——请自行判断是否需要合并"
    entry = MemoryEntry(
        content=note,
        created_at=date.today().isoformat(),
        source=source,
        importance=int(importance),
        category=category,
    )
    _ensure_file()
    with open(MEMORY_FILE, "a", encoding="utf-8") as f:
        f.write(entry.to_line() + "\n")
    # 落向量（id 由内容哈希定，重复 upsert 幂等）
    try:
        vec = (await vector.aembed([note]))[0]
        vector.upsert(vector.entry_id(note), note, vec)
    except Exception as e:
        return f"已写入文件，但向量索引失败：{e}（记忆仍生效，可稍后重试）"
    # D1 事件兜底：写入成功 → 标记本会话记忆变化（会话收尾钩子消费，不立即提炼）
    mark_memory_changed()
    return f"已记住（{category}，imp={importance}）{warn}"


async def search_memory(query: str, top_k: int = 5) -> str:
    """检索记忆库：需了解用户偏好/历史/进度时调用，按相关度返回"""
    try:
        await _sync_backfill()
        vec = (await vector.aembed([query]))[0]
        hits = vector.search(vec, top_k=max(1, min(top_k, 10)))
    except Exception as e:
        return f"(检索失败：{e})"
    if not hits:
        return "(没有检索到相关记忆)"
    lines = []
    for i, (_, text, sim) in enumerate(hits, 1):
        lines.append(f"[{i}] (相关度 {sim:.2f}) {text}")
    return "\n".join(lines)


async def update_profile() -> str:
    """更新用户画像摘要（内部压缩记忆重写 profile）：画像信息变化较多时调用"""
    if _profile_writer is None:
        return "画像写入器未注册，请先启动 tutor agent"
    memory_text = entries_text()
    new_profile = await _profile_writer(memory_text)
    if not new_profile or not new_profile.strip():
        return "画像生成失败（模型返回空）"
    if len(new_profile) > PROFILE_LIMIT:
        new_profile = new_profile[:PROFILE_LIMIT] + "\n(已截断)"
    PROFILE_FILE.parent.mkdir(parents=True, exist_ok=True)
    # 内容未变不重写（防 mtime 抖动 + 无意义 IO）
    if PROFILE_FILE.exists() and PROFILE_FILE.read_text(encoding="utf-8").strip() == new_profile.strip():
        return "画像无变化（内容未变，不重写）"
    PROFILE_FILE.write_text(new_profile.strip() + "\n", encoding="utf-8")
    return f"画像已更新（{len(new_profile)} 字）"


def forget(content: str) -> str:
    """删除一条记忆（用户明确要删时）。先确认再删；误删进回收站可恢复"""
    _ensure_file()
    lines = MEMORY_FILE.read_text(encoding="utf-8").splitlines()
    kept, removed, removed_lines = [], False, []
    for ln in lines:
        if content and content in ln:
            removed = True
            removed_lines.append(ln)
            # 尝试提取内容哈希删向量
            e = MemoryEntry.from_line(ln)
            if e:
                vector.delete(vector.entry_id(e.content))
        else:
            kept.append(ln)
    if not removed:
        return "未找到匹配的记忆"
    # 代码层安全垫：删除前把被删条目写入回收站（可恢复；不打断模型流程，不依赖模型自觉）
    if removed_lines:
        trash = MEMORY_FILE.parent / "trash.md"
        trash.parent.mkdir(parents=True, exist_ok=True)
        with trash.open("a", encoding="utf-8") as f:
            f.write(f"\n## {date.today()} forget 回收\n")
            f.write("\n".join(removed_lines) + "\n")
    MEMORY_FILE.write_text("\n".join(kept) + "\n", encoding="utf-8")
    return "已删除"


async def edit_memory(old: str, new: str) -> str:
    """修正一条记忆：按内容匹配行，替换内容并同步向量（人可审可改，M5）"""
    _ensure_file()
    old = old.strip()
    new = new.strip()
    if not old or not new:
        return "修正内容为空"
    lines = MEMORY_FILE.read_text(encoding="utf-8").splitlines()
    new_lines = []
    edited = False
    for ln in lines:
        e = MemoryEntry.from_line(ln)
        if e and old in e.content:
            old_content = e.content
            e.content = new
            e.updated_at = date.today().isoformat()
            new_lines.append(e.to_line())
            edited = True
            try:
                vector.delete(vector.entry_id(old_content))
                vec = (await vector.aembed([new]))[0]
                vector.upsert(vector.entry_id(new), new, vec)
            except Exception:
                pass
        else:
            new_lines.append(ln)
    if not edited:
        return "未找到匹配的记忆"
    MEMORY_FILE.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    return "已修正"
