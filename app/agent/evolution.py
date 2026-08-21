"""M8 进化层：Reflexion 反思 + Voyager 技能库 + JIT 技能检索
设计依据：docs/M8-DESIGN.md（论文原文 + probe_evolve 实测）
三条论文硬约束的落地：
- 反思/技能入库必须有外部验证信号（用户反馈触发，模型自评永不直接入库）
- 技能只增不改（Voyager 原则）；容量硬限是护栏（超限报错交模型，不替它合并）
- 独立 collection 存储（reflections/skills），不污染用户记忆
"""
import hashlib
import re
import time
import uuid
from datetime import datetime
from pathlib import Path
from app.config import DATA_DIR

import chromadb
from pydantic_ai import Agent

from app.memory.vector import aembed

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
REFLECTIONS_FILE = DATA_DIR / "memory" / "reflections.md"
SKILLS_FILE = DATA_DIR / "memory" / "skills.md"
CHROMA_DIR = DATA_DIR / "data" / "vector_evolve"

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
        _client = chromadb.PersistentClient(path=str(CHROMA_DIR))
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
    不调用 LLM（向量距离是确定性计算）；失败保守返回 None（宁可不拒，不误伤）。"""
    try:
        col = _get_collection(collection)
        if col.count() == 0:
            return None
        vec = (await aembed([new_block]))[0]
        res = col.query(query_embeddings=[vec], n_results=3)
        docs = (res.get("documents") or [[]])[0]
        dists = (res.get("distances") or [[]])[0]
        for doc, dist in zip(docs, dists):
            sim = 1.0 - dist  # cosine space: distance = 1 - similarity
            if sim >= DUP_THRESHOLD:
                return doc[:80]
    except Exception:
        pass
    return None


def _entry_id(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def _blocks(file: Path) -> list[str]:
    """解析块文件：按行首 '## [时间戳]' 分块（内容里的 '### ' 子标题不会被误拆）"""
    if not file.exists():
        return []
    text = file.read_text(encoding="utf-8")
    parts = re.split(r"(?m)^## \[", text)
    return ["## [" + p.strip() for p in parts if p.strip()]


def _remove_block(file: Path, content: str, collection: str) -> bool:
    """按内容匹配删除一个块（文件 + 向量）"""
    blocks = _blocks(file)
    kept = [b for b in blocks if content not in b]
    if len(kept) == len(blocks):
        return False
    file.write_text("\n\n".join(kept) + ("\n\n" if kept else ""), encoding="utf-8")
    for b in blocks:
        if content in b:
            try:
                _get_collection(collection).delete(ids=[_entry_id(b)])
            except Exception:
                pass
    return True


def list_reflections() -> list[dict]:
    """M5 人可审：反思列表 [{id, date, content}]"""
    out = []
    for b in _blocks(REFLECTIONS_FILE):
        lines = b.splitlines()
        date = lines[0][lines[0].find("[") + 1 : lines[0].find("]")] if "[" in lines[0] else ""
        out.append({"id": _entry_id(b), "date": date, "content": b})
    return out


def list_skills() -> list[dict]:
    """M5 人可审：技能列表 [{id, date, content}]"""
    out = []
    for b in _blocks(SKILLS_FILE):
        lines = b.splitlines()
        date = lines[0][lines[0].find("[") + 1 : lines[0].find("]")] if "[" in lines[0] else ""
        out.append({"id": _entry_id(b), "date": date, "content": b})
    return out


def delete_item(kind: str, content: str) -> str:
    """M5 人可删：kind=reflection|skill，按内容匹配删除"""
    if kind == "reflection":
        return "已删除" if _remove_block(REFLECTIONS_FILE, content, "reflections") else "未找到匹配的反思"
    if kind == "skill":
        return "已删除" if _remove_block(SKILLS_FILE, content, "skills") else "未找到匹配的技能"
    return "未知类型"


async def reindex_evolution() -> str:
    """从源文件重建反思/技能向量索引（源文件权威，索引可重建——与 kb_reindex 同模式）。
    背景：chroma 删库/损坏后若不重灌，search_skills/反思检索永远为空（"没存过讲法"假象）。"""
    from app.memory.vector import aembed as _aembed

    rebuilt = []
    for name, file in (("reflections", REFLECTIONS_FILE), ("skills", SKILLS_FILE)):
        blocks = _blocks(file)
        if not blocks:
            continue
        col = _get_collection(name)
        old = col.get(include=[])["ids"]
        if old:
            col.delete(ids=old)
        for b in blocks:
            col.upsert(ids=[_entry_id(b)], documents=[b], embeddings=[(await _aembed([b]))[0]])
        rebuilt.append(f"{name}×{len(blocks)}")
    return f"已重建: {', '.join(rebuilt)}" if rebuilt else "(无源条目可重建)"


# ---------- 反思（Reflexion）----------

async def reflect_teaching(context: str) -> str:
    """用户对讲解不满意（没听懂/太快/讲错）时调用：生成三段式反思入库改进。context=刚才发生什么"""
    context = (context or "").strip()
    if not context:
        return "(反思内容为空，请重试)"
    if _count_lines(REFLECTIONS_FILE) >= CAP_LIMIT:
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
    _append(REFLECTIONS_FILE, block)
    _get_collection("reflections").upsert(
        ids=[_entry_id(block)],
        documents=[block],
        embeddings=[(await aembed([block]))[0]],
    )
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
                return s[len(prefix):].strip()[:100]
        else:
            return s[:100]
    return block[:100]


def _blocks(path) -> list[str]:
    """按块头切分（## [时间] 块级标题；不误切 ### 子标题——用 \n## 前缀匹配）。"""
    import re

    text = path.read_text(encoding="utf-8") if path.exists() else ""
    return [b.strip() for b in re.split(r"\n## ", "\n" + text) if b.strip()]


def recent_pair(limit: int = 1) -> str:
    """注入用：最近经验摘要（S2 截短，2026-08-19，参考 DeepTutor render_skills_manifest——
    摘要清单注入 + 需要完整时工具查，850 字/轮 → ~230 字/轮）。
    反思/技能各只留首行摘要（何时用），完整讲法模型自己 search_skills 查。"""
    parts = []
    # 失败教训：最近反思首行
    rblocks = _blocks(REFLECTIONS_FILE)
    if rblocks:
        head = _block_first_line(rblocks[-1])
        parts.append(f"【最近教训】{head}（完整讲法用 search_skills）")
    # 成功讲法：最近技能描述行（何时用）
    sblocks = _blocks(SKILLS_FILE)
    if sblocks:
        desc = _block_first_line(sblocks[-1], prefix="描述：")
        parts.append(f"【最近讲法】{desc}（完整讲法用 search_skills）")
    if not parts:
        return "(暂无教训与讲法)"
    return "\n".join(parts)


# ---------- 技能（Voyager）----------

async def save_skill(description: str, method: str) -> str:
    """用户对讲法满意时，把"讲法"存进技能库。描述=何时用；方法=怎么讲。确信有复用价值才调"""
    description = (description or "").strip()
    method = (method or "").strip()
    if not description or not method:
        return "(技能描述和方法都不能为空)"
    if _count_lines(SKILLS_FILE) >= CAP_LIMIT:
        return f"(技能库已满 {CAP_LIMIT} 条，请先让我整理合并旧的技能)"
    ts = datetime.now().strftime("%Y-%m-%dT%H:%M")
    sid = uuid.uuid4().hex[:6]
    block = f"## [{ts}] 技能 #{sid}\n描述：{description}\n方法：{method}"
    # 语义查重（2026-08-19 P1 复盘缺陷3）：与库内已有技能高度相似 → 拒写防堆积
    dup = await _is_duplicate("skills", block)
    if dup:
        return f"(已有相似技能，不重复写入——库内: {dup[:40]}…)"
    _append(SKILLS_FILE, block)
    _get_collection("skills").upsert(
        ids=[_entry_id(block)],
        documents=[block],
        embeddings=[(await aembed([block]))[0]],
    )
    return f"技能已入库（#{sid}）。遇到类似情境我会想起它。"


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
        items = []
        for doc, d in zip(docs, dists):
            lines = doc.splitlines()
            head = lines[0].strip() if lines else "(技能)"
            desc = next((l.split("描述：", 1)[1].strip() for l in lines if l.startswith("描述：")), "")
            items.append(f"[相似度 {1 - d:.2f}] {head} | 描述：{desc}")
        return "\n".join(items) + "\n（需要某条技能的完整讲法时，用 read_document 读 memory/skills.md 对应条目）"
    except Exception as e:
        return f"(技能检索失败：{e})"
