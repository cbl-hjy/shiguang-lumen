"""数据恢复机制：lifespan 启动时，若 memory 文件缺失/为空且备份存在，由服务端进程重建
背景：WorkBuddy 沙箱导致"非服务端创建的文件"服务端写被锁（readonly），
恢复必须由服务端进程自己创建文件。此模块在 uvicorn lifespan 中执行（服务端进程=可写）。
备份路径：data/backup/（手动或脚本创建）
"""
import shutil
from pathlib import Path
from app.config import DATA_DIR

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
MEMORY_DIR = DATA_DIR / "memory"
BACKUP_DIR = DATA_DIR / "data" / "backup"

FILES = ["user_memory.md", "profile.md", "reflections.md", "skills.md"]


def _looks_empty(path: Path) -> bool:
    """内容有效性判断：文件缺失、或只有标题/空行（store 模块 import 时可能先建空文件）"""
    if not path.exists():
        return True
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return True
    lines = [l for l in text.splitlines() if l.strip() and not l.startswith("#")]
    return len(lines) == 0


def restore_from_backup() -> list[str]:
    """把备份恢复到 memory/（仅当目标缺失或内容为空——按条目行判断，非仅文件大小）；返回恢复的文件列表"""
    restored = []
    if not BACKUP_DIR.exists():
        return restored
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        src = BACKUP_DIR / name
        dst = MEMORY_DIR / name
        if not src.exists():
            continue
        if not _looks_empty(dst):
            continue
        shutil.copy2(src, dst)
        restored.append(name)
    return restored


def restore_kb_index() -> str:
    """知识库索引自动恢复：kb_main 集合为空但有源文件 → 从源文件重建（源文件是权威，索引可重建）。
    背景：chroma 索引删库/损坏后若不复原，kb_search 检索永远为空（"知识库里空空如也"假象）。"""
    from app.tools.kb import CHROMA_DIR, KB_DIR, kb_reindex
    import chromadb

    if not KB_DIR.exists() or not list(KB_DIR.glob("*.md")):
        return "kb: 无源文件（跳过）"
    try:
        client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        col = client.get_or_create_collection("kb_main")
        count = col.count()
        if count > 0:
            return f"kb: 索引正常（{count} 条）"
    except Exception as e:
        return f"kb: 索引检查失败 {e}"
    return "kb: " + kb_reindex()


async def restore_evolution_index() -> str:
    """进化层索引自动恢复：skills/reflections 集合为空但有源文件 → 重建（同 kb 模式）。
    背景：chroma 删库后不重灌，search_skills 永远返回空（"没存过讲法"假象）。"""
    from app.agent.evolution import CHROMA_DIR as EVO_CHROMA, REFLECTIONS_FILE, SKILLS_FILE, reindex_evolution
    import chromadb

    if not (REFLECTIONS_FILE.exists() or SKILLS_FILE.exists()):
        return "evo: 无源文件（跳过）"
    try:
        client = chromadb.PersistentClient(path=str(EVO_CHROMA))
        missing = []
        for name in ("skills", "reflections"):
            col = client.get_or_create_collection(name, metadata={"hnsw:space": "cosine"})
            if col.count() == 0:
                missing.append(name)
        if not missing:
            return "evo: 索引正常"
    except Exception as e:
        return f"evo: 索引检查失败 {e}"
    return "evo: " + await reindex_evolution()
