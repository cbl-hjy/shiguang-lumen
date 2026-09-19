# -*- coding: utf-8 -*-
"""原子写入工具（2026-08-28 P0-1 止血）：不可再生数据禁止 write_text 直写。

背景：Path.write_text 内部 open(mode='w') 先截断为 0 字节再写——
中途异常/进程被杀/掉电 = 原文件永久丢失（08-28 记忆文件 44B 空化实证）。
正确做法：同目录临时文件写入 + os.replace 原子替换（POSIX rename 语义，同卷原子）。

使用铁律：
- memory/ 下所有数据文件（user_memory.md / profile.md / skills.md / reflections.md /
  topics.json / state.json 等）一律走 atomic_write_text
- 写后应调用 store.verify_entry_count() 做条目数校验（P0-2），防静默失忆
"""
import os
import tempfile
from pathlib import Path


def atomic_write_text(path: Path | str, content: str, encoding: str = "utf-8") -> None:
    """原子写文本：同目录临时文件 + fsync + os.replace。任何失败都不动原文件。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp_", suffix=".atomic")
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="\n") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())  # 防掉电半写（数据落盘而非仅进页缓存）
        os.replace(tmp, path)  # 同目录原子替换：要么旧文件完整，要么新文件完整
    except BaseException:
        # 走 safe_cleanup：这里的 os.unlink 会被外部删除守卫拦成 SystemExit，
        # 而 SystemExit 会把**原始异常**顶掉——原子写失败的真正原因就此消失。
        # 清理失败最多留一个临时文件，绝不能让它盖掉调用方要看到的那个错。
        from app.utils.safe_cleanup import try_unlink

        try_unlink(tmp, context="utils/atomic_io")
        raise
