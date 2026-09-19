# -*- coding: utf-8 -*-
"""清理路径的删除包装（2026-08-30）：把 safe-delete 的三条硬事实编码成一处。

背景（三条都是实测，不是推测）：
  ① 外部删除守卫会**按轮次累计**计数，超过上限（实测 50）后本轮所有删除一律拒绝；
     计数范围是 agent 会话，不是进程也不是仓库。
  ② 被拒时它抛的是 **SystemExit（BaseException）**，`except Exception` **接不住**。
     后果：任何清理/善后逻辑都可能把整个进程干掉（pytest 下表现为 INTERNALERROR）。
  ③ 被拦下后**不重试、不绕路**：第一次被拒后后面必然继续被拒，重试只把计数刷更高。

为什么必须有这一个模块：这三条只要有一条没照顾到，后果都是"清理临时文件的代码
把调用它的功能整个干掉"——而且只在跑够久之后才发作，本地手测永远发现不了。

2026-08-30 实证：app/tools/sandbox.py 的 finally 里 unlink 临时代码文件，
全量回归跑够 50 次后第 51 次抛 SystemExit，5 个沙箱用例全红——
**红得跟代码坏了完全一样，但代码一点没坏**（单独跑该文件 8 passed in 32s）。

设计原则（对齐项目铁律「能免疫就不要只是诚实地报错」）：
  - 返回值表达"删没删掉"，**不抛、不打断调用方**。清理失败永远不该让主功能失败。
  - **第一次被拒即全局停手**（模块级 flag）：后续调用直接返回 False，不再刷计数。
  - 只吞 SystemExit，KeyboardInterrupt 必须放行（用户 Ctrl-C 不能被吃掉）。
"""

from __future__ import annotations

from pathlib import Path

# 一旦守卫拒绝过一次，本进程后续所有删除尝试都直接放弃。
# 不重试的理由见 ③：重试只会把累计计数刷得更高，让守卫更难解除。
_GUARD_TRIPPED = False


def guard_tripped() -> bool:
    """守卫是否已经拒绝过删除。调用方可据此选择降级路径（如改覆盖写）。"""
    return _GUARD_TRIPPED


def _trip(tag: str, path: Path, on_reject: str | None) -> None:
    """守卫拒绝 → 置全局停手。只有守卫拒绝才走这里，普通 OSError 不置。

    区分的理由（2026-08-30，是单元测试逼出来的）：
      - 守卫拒绝（SystemExit）：**后续必然继续被拒**，重试只是刷高计数 ⇒ 全局停手
      - 普通 OSError（文件被占用 / 权限）：可能只针对这一个文件，
        其他文件照样能删 ⇒ 不该让整批清理陪葬
    """
    global _GUARD_TRIPPED
    _GUARD_TRIPPED = True
    prefix = f"[{tag}] " if tag else ""
    print(f"{prefix}删除被守卫拒绝，本进程后续清理全部跳过：{path}", flush=True)
    if on_reject:
        print(f"{prefix}需手工处理：{on_reject}", flush=True)


def try_unlink(
    path: str | Path,
    *,
    context: str = "",
    on_reject: str | None = None,
) -> bool:
    """删除单个文件。失败（含被守卫拒绝）一律返回 False，**绝不抛给调用方**。

    - 目标不存在 → 视为目的已达成，返回 True
    - FileNotFoundError 之外的 OSError → 打印并返回 False
    - 守卫拒绝（SystemExit）→ 置全局停手 flag，打印，返回 False

    on_reject：被拒时额外提示的人工可操作建议（这时候只能靠人删）。
    """
    if _GUARD_TRIPPED:
        return False
    p = Path(path)
    try:
        p.unlink()
        return True
    except FileNotFoundError:
        return True  # 已经没了 = 清理目的达成
    except OSError as e:
        # 普通 IO 失败（占用/权限）：只影响这一个文件，不置停手 flag
        prefix = f"[{context}] " if context else ""
        print(f"{prefix}删除失败（不影响后续清理）：{p} —— {e}", flush=True)
        return False
    except BaseException as e:  # noqa: BLE001 —— 必须接 BaseException，见 ②
        if isinstance(e, KeyboardInterrupt):
            raise
        # SystemExit 是守卫的表达方式：它不是"程序要退出"，是"这个删除被拒了"
        _trip(context, p, on_reject)
        return False


def try_rmtree(
    path: str | Path,
    *,
    context: str = "",
    ignore_errors: bool = True,
) -> bool:
    """递归删除目录。语义同 try_unlink：不抛、不打断调用方。"""
    import shutil

    if _GUARD_TRIPPED:
        return False
    p = Path(path)
    if not p.exists():
        return True
    try:
        shutil.rmtree(p, ignore_errors=ignore_errors)
        return True
    except OSError as e:
        prefix = f"[{context}] " if context else ""
        print(f"{prefix}目录删除失败（不影响后续清理）：{p} —— {e}", flush=True)
        return False
    except BaseException as e:  # noqa: BLE001 —— 同 try_unlink
        if isinstance(e, KeyboardInterrupt):
            raise
        _trip(context, p, None)
        return False


def drain(paths, *, context: str = "") -> int:
    """批量清理的收拢写法：逐个删，**第一次失败立即停**，返回实际删掉的个数。

    为什么要有 batch 版：调用方写成 `for f in files: try_unlink(f)` 时，
    被拒之后循环还会继续跑几十次，白白刷高计数。收拢到这里，停手只写一遍。
    """
    n = 0
    for item in paths:
        if _GUARD_TRIPPED:
            break
        if try_unlink(item, context=context):
            n += 1
    return n


def _selfcheck() -> None:
    """模块自检（无外部依赖）：三态行为符合上面的契约。改本文件后跑一下。"""
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "x.txt"
        p.write_text("a")
        assert try_unlink(p) is True, "普通删除应成功"
        assert try_unlink(p) is True, "已不存在应视为成功"
        assert try_unlink(Path(d) / "nope") is True, "不存在的路径应视为成功"


if __name__ == "__main__":
    _selfcheck()
    print("safe_cleanup 自检通过")
