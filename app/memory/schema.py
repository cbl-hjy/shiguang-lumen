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
# 画像硬限（Claude Code 25KB 量级，我们更严：常驻注入必须瘦）
PROFILE_LIMIT = 1000

WRITE_RULES = "记忆写入规范：一条一事实；可验证可执行；未来有用才写；时间转绝对日期；同事实不重复；反思类需外部验证才写"


@dataclass
class MemoryEntry:
    """8 字段记忆条目（importance 由模型打，代码不设默认判断）
    verification_status 已删：从未消费的沉睡字段（反思/技能走独立 chroma + 外部验证信号）"""
    content: str            # 单条原子断言
    created_at: str         # YYYY-MM-DD
    source: str = "user"    # user/agent（用户原话 vs 转述/推断）
    importance: int = 5     # 1-10，模型打
    category: str = "note"  # 偏好/目标/进度/错误记录/学习记录
    metadata: dict = field(default_factory=dict)
    updated_at: str = ""
    entry_id: str = ""

    def to_line(self) -> str:
        meta = " ".join(f"{k}={v}" for k, v in self.metadata.items())
        parts = [
            self.created_at,
            f"src={self.source}",
            f"imp={self.importance}",
            f"cat={self.category}",
            self.content,
        ]
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
            if "=" in s and s.split("=", 1)[0] in ("src", "imp", "cat", "id", "upd", "ver"):
                # ver= 是已删除字段的旧数据残留：解析掉但不消费（避免污染 content）
                k, v = s.split("=", 1)
                kv[k] = v
            else:
                content_parts.append(s)
        return cls(
            content=" | ".join(content_parts),
            created_at=created,
            source=kv.get("src", "user"),
            importance=int(kv.get("imp", 5)),
            category=kv.get("cat", "note"),
            entry_id=kv.get("id", ""),
            updated_at=kv.get("upd", ""),
        )
