"""M1 记忆层：9 字段条目 + 写入规范（行格式落地；M2 接 bge-m3 去重与 JIT 检索）
设计依据：research/2026-08-10-memory-schema-format.md（Claude Code auto-memory 写入规范 + Mem0 字段）
红线：格式约束走 prompt + 硬限，不做应用层强 schema（防"替模型思考"）
"""
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from app.config import DATA_DIR

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# 记忆文件：git 跟踪（人可审/回滚/导出）
MEMORY_FILE = DATA_DIR / "memory" / "user_memory.md"

# 画像摘要文件（LangMem 范式：单文档原地更新，不新建）
PROFILE_FILE = DATA_DIR / "memory" / "profile.md"

# 容量硬限（护栏：超限报错给模型处理，不替它合并）
MEMORY_LINE_LIMIT = 200
# 容量软阈值（2026-08-18 治理权#4）：超此值注入"该整理记忆"提示——
# 提示=提供信息不是替模型决定（判断无墙）；硬限是兜底，软阈值是提前觉察
MEMORY_SOFT_LIMIT = 100
# 画像硬限（Claude Code 25KB 量级，我们更严：常驻注入必须瘦）
PROFILE_LIMIT = 1000

WRITE_RULES = "记忆写入规范：一条一事实，可验证，未来有用才写；绝对日期；重要带证据。四原语：重复不写(NOOP)/补充edit_memory(UPDATE)/矛盾forget+重写(DELETE+ADD)/全新或用户明确说的决定→立即remember(ADD)，别因先确认拖延。记困惑不记情绪：纠结→cat=困惑+开放中，想通UPDATE已解决；情绪归状态轮。学习信息必记：进度/目标/卡点/学到哪，平淡也记(画像靠它们)。闪光=用户没发现的模式/潜力/洞见（cat=闪光，收尾提炼）。类别=词汇表(学习记录/进度/目标/偏好/困惑/关系/错误记录/反思/闪光/笔记)，乱词自动归一"

# 类别词汇表（格式不变量，锁死）——模型选词自由（判断无墙），归一表兜底映射到词汇表
# 闪光（2026-08-20）：拾光=拾到我们没发现的闪光——收尾提炼的闪光记忆类别
CAT_VOCAB = ("学习记录", "进度", "目标", "偏好", "困惑", "关系", "错误记录", "反思", "闪光", "笔记")

CAT_ALIAS = {
    "learning": "学习记录", "learn": "学习记录", "study": "学习记录", "学习": "学习记录", "面试": "学习记录",
    "progress": "进度", "prog": "进度", "进展": "进度",
    "goal": "目标", "objective": "目标", "目标": "目标",
    "preference": "偏好", "pref": "偏好", "偏好": "偏好",
    "confusion": "困惑", "puzzle": "困惑", "纠结": "困惑", "困惑": "困惑",
    "relationship": "关系", "relation": "关系", "关系": "关系",
    "error": "错误记录", "mistake": "错误记录", "错误记录": "错误记录",
    "reflection": "反思", "review": "反思", "反思": "反思",
    "glint": "闪光", "闪光": "闪光", "亮点": "闪光", "洞见": "闪光",
    "note": "笔记", "笔记": "笔记", "其他": "笔记", "misc": "笔记", "memo": "笔记", "临时": "笔记",
}


def normalize_category(cat: str) -> str:
    """归一化类别到词汇表（确定性不变量）：未知名词 → 笔记兜底"""
    if not cat:
        return "笔记"
    c = cat.strip()
    if c in CAT_VOCAB:
        return c
    return CAT_ALIAS.get(c.lower(), "笔记")


def make_entry_id(content: str, created_at: str = "") -> str:
    """稳定 id（2026-08-19 meta-id-diff 前置）：sha1(content+created_at)[:12]。
    内容不变 → id 不变（diff 稳定）；编辑改内容 → id 变（旧 id 消失=触发画像更新）。
    确定性纯函数，无随机——同一记忆任何时刻生成同一 id。"""
    import hashlib

    return hashlib.sha1(f"{content}|{created_at}".encode("utf-8")).hexdigest()[:12]


@dataclass
class MemoryEntry:
    """8 字段记忆条目（importance 由模型打，代码不设默认判断）
    verification_status 已删：从未消费的沉睡字段（反思/技能走独立 chroma + 外部验证信号）
    strength（S，2026-08-18 用进废退补洞）：检索命中强度，默认 1，命中 S+1 封顶 5——
    公式 rec = e^(-days/S)（MemoryBank），S 越大遗忘越慢；旧数据无 S= 字段兜底 1"""
    content: str            # 单条原子断言
    created_at: str         # YYYY-MM-DD
    source: str = "user"    # user/agent（用户原话 vs 转述/推断）
    importance: int = 5     # 1-10，模型打
    category: str = "笔记"  # 词汇表：学习记录/进度/目标/偏好/困惑/关系/错误记录/反思/笔记
    metadata: dict = field(default_factory=dict)
    updated_at: str = ""
    entry_id: str = ""
    strength: int = 1       # S 强度（1-5），用进废退

    def to_line(self) -> str:
        meta = " ".join(f"{k}={v}" for k, v in self.metadata.items())
        parts = [
            self.created_at,
            f"src={self.source}",
            f"imp={self.importance}",
            f"cat={normalize_category(self.category)}",
            self.content,
        ]
        # 稳定 id（2026-08-19 meta-id-diff 前置）：写入时有 id 才输出（存量条目补 id 脚本处理）；
        # id = sha1(content+created_at)——内容不变 id 不变（diff 稳定），编辑改内容→id 变（触发画像更新）
        if self.entry_id:
            parts.append(f"id={self.entry_id}")
        if self.strength and self.strength != 1:
            parts.append(f"S={self.strength}")
        if meta:
            parts.append(meta)
        return "- " + " | ".join(parts)

    @classmethod
    def from_line(cls, line: str) -> "MemoryEntry | None":
        line = line.strip()
        if not line.startswith("- "):
            return None
        body = line[2:]
        segs = [s.strip() for s in body.split("|")]
        if not segs:
            return None
        created = segs[0]
        kv = {}
        content_parts = []
        for s in segs[1:]:
            if "=" in s and s.split("=", 1)[0] in ("src", "imp", "cat", "id", "upd", "ver", "S"):
                # ver= 是复查状态字段（verified/unverified，08-15 治理引入）：doc_health/memory_audit 消费，
                # MemoryEntry 不落字段（复查状态由检查器直接读文件判断，避免双真相源）
                # S= 是检索强度（2026-08-18 用进废退）：to_line 写、from_line 读回（metadata 是单向的，不能放那）
                k, v = s.split("=", 1)
                kv[k] = v
            else:
                content_parts.append(s)
        try:
            strength = int(kv.get("S", 1))
            strength = max(1, min(5, strength))  # 兜底：越界夹到 1-5
        except Exception:
            strength = 1
        return cls(
            content=" | ".join(content_parts),
            created_at=created,
            source=kv.get("src", "user"),
            importance=int(kv.get("imp", 5)),
            category=normalize_category(kv.get("cat", "笔记")),
            entry_id=kv.get("id", ""),
            updated_at=kv.get("upd", ""),
            strength=strength,
        )
