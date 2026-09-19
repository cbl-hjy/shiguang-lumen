"""多用户数据目录（2026-08-28 P0，directory-per-tenant 模式）：
- 每用户独立目录 data/users/<uid>/ 下放该用户一切数据：
  sessions.db / wakeups.db / memory/ / kb/ / vector_mem/ / vector_evolve/ / mastery.jsonl / archive/
- 全局目录 data/ 仅保留非隐私/运维/缓存：trace_log.jsonl / token_usage.csv / change_log.jsonl / users.db / sages/ / debates/
  例外：llm_cache.jsonl 文件仍全局但语义上是用户私有（用户的问题+个性化回复）——
  2026-08-31 P1 起条目带 uid 字段做行级隔离（lookup 只命中同 uid 条目；无 uid 的 legacy 条目视作未登录条目，
  靠 TTL+容量自然出清）。不搬文件到 per-user 目录：搬动涉及存量迁移，行级隔离已足够
- 数据层函数一律接收 uid：uid=None 表示未登录/legacy → 回退全局路径（兼容未迁移数据）
"""
from __future__ import annotations

import shutil
from pathlib import Path

from app.config import DATA_DIR

_USERS_ROOT = DATA_DIR / "data" / "users"


def get_user_data_dir(uid: str) -> Path:
    """某用户的独立数据目录（不存在则创建）"""
    d = _USERS_ROOT / uid
    d.mkdir(parents=True, exist_ok=True)
    return d


def user_db_path(uid: str, name: str) -> Path:
    """用户目录下的数据文件路径"""
    return get_user_data_dir(uid) / name


def global_data_dir() -> Path:
    """全局数据目录（data/）"""
    return DATA_DIR / "data"


def _copy(src: Path, dst: Path) -> None:
    """复制（保留源=迁移安全冗余；不用 move——项目 safe-delete 防护会拦 move 且不可逆）"""
    if src.is_dir():
        shutil.copytree(src, dst)
    else:
        shutil.copy2(src, dst)


def migrate_user_data(uid: str) -> int:
    """首用户（管理员）注册时调用：把现有全局数据【复制】到该用户目录（源保留=安全冗余）。
    迁移内容（文件型）：sessions.db / wakeups.db / mastery.jsonl / memory/ / archive/
    —— chroma 向量目录（vector_mem/vector_evolve/kb）不复制：运行中持有锁且物理复制有一致性风险，
      向量隔离走"每用户独立 collection"方案（P1，memory_<uid>/evolve_<uid>，与物理目录无关）。
    返回迁移项数。幂等：目标已存在则跳过。
    """
    src = global_data_dir()
    dst = get_user_data_dir(uid)
    moved = 0
    for name in ["sessions.db", "wakeups.db", "mastery.jsonl", "archive"]:
        s = src / name
        d = dst / name
        if s.exists() and not d.exists():
            try:
                _copy(s, d)
                moved += 1
            except Exception as e:
                print(f"[migrate] {name} 复制失败（跳过，不影响注册）: {e}", flush=True)
    # memory/ 在 DATA_DIR 根（不在 data/ 下）
    root_memory = DATA_DIR / "memory"
    if root_memory.exists() and not (dst / "memory").exists():
        try:
            _copy(root_memory, dst / "memory")
            moved += 1
        except Exception as e:
            print(f"[migrate] memory/ 复制失败（跳过）: {e}", flush=True)
    return moved
