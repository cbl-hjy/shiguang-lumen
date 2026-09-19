"""子进程受限执行器：由 sandbox.py 以 subprocess 调用（父进程负责超时）
不在沙箱内做超时（Windows 无 signal.alarm），隔离到子进程才能安全终止死循环

import 白名单（2026-08-21 新增）：RestrictedPython safe_builtins 默认禁 __import__——
学习代码 80% 要 import（math/random/json 等），全禁 = "展示代码"必然失败（用户实测）。
白名单只放**纯计算/数据处理**标准库（无文件/网络/子进程/系统能力），危险模块继续禁——
安全不破（RestrictedPython guarded getattr 仍拦属性越权），实用补上。

2026-08-26 沙箱增强（用户：拾光能做的事太少）：
- numpy/pandas 放行（实测 RestrictedPython 兼容：C 扩展属性访问正常）
- 注入 chart()：算完能画图（SVG 生成到 D 盘缓存目录，返回 markdown 图片引用，对话直接显示）
- 注入 read_file()：只读白名单路径（data/uploads 等用户资料），分析用真数据
- 注入 save_result()：分析结果落盘（D 盘 sandbox_outputs），可下载/进知识库
  安全：注入函数本身是正常 Python，但用户受限代码只能**调用**它们（open/os/pathlib 均不在
  可用范围），文件路径被白名单锁死——能力增强，隔离边界不破。
"""

import pathlib
import sys
import uuid

import operator as _op

from RestrictedPython import compile_restricted_exec, safe_builtins, safe_globals
from RestrictedPython.Eval import default_guarded_getattr as _G, default_guarded_getitem
from RestrictedPython.Guards import guarded_iter_unpack_sequence, guarded_unpack_sequence


class _SharedOut:
    """共享输出收集器（2026-08-26 修复）：8.5 的 _print_ 传 PrintCollector 类（工厂）时
    顶层 print 正常但**函数内 print 的收集器实例丢失**（def f(): print() 是学习代码最高频写法，
    实测静默无输出）。改为共享实例（callable），顶层/函数内 print 统一收集。
    8.5 改写：_print_ = _print_(_getattr_)（工厂）→ _print._call_print(x)（收集）。"""

    def __init__(self):
        self.buf: list[str] = []

    def __call__(self, ga=None):
        # 工厂调用：_print_(_getattr_) 或无参 → 返回自身（共享收集器）
        if ga is None or ga is _G:
            return self
        # 直接收集（兼容旧式 print 改写 _print_(x)）
        self.buf.append(str(ga))
        return self

    def _call_print(self, *objects):  # RestrictedPython 8.5 print 改写收集点
        self.buf.append(" ".join(str(o) for o in objects))
        return self

    def text(self) -> str:
        return chr(10).join(self.buf)  # \n（heredoc 转义坑：源码不能有真实换行符于字符串内）


_shared_out = _SharedOut()


class _SharedOut:
    """共享输出收集器（2026-08-26 修复）：8.5 的 _print_ 传 PrintCollector 类（工厂）时
    顶层 print 正常但**函数内 print 的收集器实例丢失**（def f(): print() 是学习代码最高频写法，
    实测静默无输出）。改为共享实例（callable），顶层/函数内 print 统一收集。
    8.5 改写：_print_ = _print_(_getattr_)（工厂）→ _print._call_print(x)（收集）。"""

    def __init__(self):
        self.buf: list[str] = []

    def __call__(self, ga=None):
        # 工厂调用：_print_(_getattr_) 或无参 → 返回自身（共享收集器）
        if ga is None or ga is _G:
            return self
        # 直接收集（兼容旧式 print 改写 _print_(x)）
        self.buf.append(str(ga))
        return self

    def _call_print(self, *objects):  # RestrictedPython 8.5 print 改写收集点
        self.buf.append(" ".join(str(o) for o in objects))
        return self

    def text(self) -> str:
        return "\n".join(self.buf)


_shared_out = _SharedOut()

# import 白名单：纯计算/数据处理标准库 + 数据分析库（numpy/pandas 2026-08-26 实测兼容）
ALLOWED_IMPORTS = {
    "math",
    "random",
    "datetime",
    "collections",
    "json",
    "re",
    "statistics",
    "itertools",
    "functools",
    "time",
    "string",
    "decimal",
    "fractions",
    "heapq",
    "bisect",
    "operator",
    "copy",
    "types",
    "enum",
    "dataclasses",
    "typing",
    "numpy",
    "pandas",
}

# 学习场景内置补全（2026-08-22）：RestrictedPython safe_builtins 太保守（81 个），
# 纯计算/容器类常用内置缺失（set/dict/list/enumerate/min/max/sum/any/all/map/filter）——
# 全是无系统能力的纯函数，与 len/range 同级安全；用户实测 RAG 代码 set() 报 NameError。
LEARN_BUILTINS = {
    "set": set,
    "dict": dict,
    "list": list,
    "enumerate": enumerate,
    "min": min,
    "max": max,
    "sum": sum,
    "any": any,
    "all": all,
    "map": map,
    "filter": filter,
    # 2026-08-26 实测放宽（纯函数无反射无 I/O，安全）：Python 学习场景高频但 safe_builtins 缺
    "next": next,
    "reversed": reversed,
    "iter": iter,
    "frozenset": frozenset,
}

# 受控输出目录（D 盘——用户铁律：数据不碰 C 盘）
_ROOT = pathlib.Path(__file__).resolve().parents[2]
_CHART_DIR = _ROOT / ".cache" / "sandbox_charts"
_OUTPUT_DIR = _ROOT / ".cache" / "sandbox_outputs"
# 隔离加固配额（2026-08-26 调研 P2b：防沙箱把磁盘写满/填爆目录）
_MAX_FILE_BYTES = 2 * 1024 * 1024  # 单文件 2MB 上限（SVG/CSV/报告）
_MAX_CHARTS = 500  # 图表目录文件数上限
_MAX_OUTPUTS = 200  # 产物目录文件数上限
_TTL_DAYS = 7  # 产物保留天数（生命周期 P2a：超期自动清理，防堆积）
# read_file 只读白名单根（DATA_DIR=项目根：memory/data/research 均为用户资料——真实资料分析用）
_READ_ROOTS = [
    _ROOT / "data",
    _ROOT / "memory",
    _ROOT / "research",
    _OUTPUT_DIR,  # 工作区（2026-08-26 调研 P0）：读上次 save_result 续算
]


def _cleanup_old() -> None:
    """产物生命周期（调研 P2a）：清理超过 TTL_DAYS 的图表/产物文件，防无限堆积。"""
    import time as _t

    from app.utils.safe_cleanup import drain, guard_tripped

    cutoff = _t.time() - _TTL_DAYS * 86400
    for d in (_CHART_DIR, _OUTPUT_DIR):
        if not d.exists() or guard_tripped():
            continue
        expired = []
        for f in d.iterdir():
            try:
                if f.is_file() and f.stat().st_mtime < cutoff:
                    expired.append(f)
            except Exception as _e:  # 单个文件 stat 失败不该中断整体清理
                print(f"[tools/_sandbox_runner] 跳过无法读取的产物 {f}: {_e}", flush=True)
        # 走 drain：被拒即刻停手，不把守卫计数刷爆（清理失败最多是产物留着，
        # 绝不能让"清理旧图表"把一次正常的沙箱执行干掉）
        n = drain(expired, context="tools/_sandbox_runner")
        if n:
            print(f"[tools/_sandbox_runner] 清理过期产物 {n} 个（TTL {_TTL_DAYS} 天）", flush=True)


def _check_quota(directory: pathlib.Path, limit: int) -> str | None:
    """隔离加固（调研 P2b）：目录文件数配额——超限拒绝写入，提示清理。"""
    try:
        n = sum(1 for f in directory.iterdir() if f.is_file())
        if n >= limit:
            return f"输出目录已满（{n}/{limit} 个文件）——先清理旧产物或换个名字"
    except Exception as _e:
        print(f"[tools/_sandbox_runner] 静默异常已可见化: {_e}", flush=True)
    return None


def _safe_import(name, globals=None, locals=None, fromlist=(), level=0):
    """白名单 __import__：只允许纯计算标准库；危险模块（os/sys/subprocess 等）拒绝。
    root=顶层模块名（import a.b 也只放行 a）。"""
    root = str(name).split(".")[0]
    if root not in ALLOWED_IMPORTS:
        raise ImportError(
            f"沙箱不允许 import {name}（仅开放纯计算标准库: {sorted(ALLOWED_IMPORTS)}；"
            "文件/网络/系统类模块一律禁止）"
        )
    return __import__(name, globals, locals, fromlist, level)


def _sandbox_write_guard(ob):
    """写守卫（2026-08-22 自定义）：RestrictedPython 官方 full_write_guard 只放行 dict/list，
    其他对象属性赋值需 __guarded_setattr__ 协议（受限类方法内 self.x = 会 TypeError）——
    官方威胁模型是"进程内共享对象污染"（Zope 场景）；本沙箱是**一次性子进程**
    （sandbox.py 每次 Popen 新解释器跑完即焚，无跨调用共享状态），该威胁模型不成立。
    故放行属性赋值（类/数据结构可用，学习场景刚需）；属性**读**仍走 default_guarded_getattr
    （__ 私有/危险属性越权读仍拦），import 白名单 + 子进程隔离兜底。"""
    return ob


# 增强赋值守卫（2026-08-22 补：8.4 把 'n += 1' 转成 'n = _inplacevar_("+=", n, 1)'——
# Guards 无现成实现，缺失导致 NameError。operator.iadd 等对齐 Python 原生语义
# （list += 原地 extend 等）。仅作用于受限变量，子进程隔离下安全）。
_INPLACE_OPS = {
    "+=": _op.iadd,
    "-=": _op.isub,
    "*=": _op.imul,
    "/=": _op.itruediv,
    "//=": _op.ifloordiv,
    "%=": _op.imod,
    "**=": _op.ipow,
    "&=": _op.iand,
    "|=": _op.ior,
    "^=": _op.ixor,
    "<<=": _op.ilshift,
    ">>=": _op.irshift,
}


def _inplacevar_(op, var, value):
    fn = _INPLACE_OPS.get(op)
    if fn is None:
        raise TypeError(f"不支持的增强赋值运算符: {op}")
    return fn(var, value)


# ============ 受控能力注入（2026-08-26 沙箱增强） ============


def _svg_esc(v):
    return str(v).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _svg_chart(points, kind, title, xlabel, ylabel):
    """深色主题 SVG 图表（匹配拾光 UI：青绿线/琥珀柱/紫散点）。纯 stdlib 生成，零依赖。"""
    W, H = 640, 360
    ML, MR, MT, MB = 56, 20, 36, 36
    pw, ph = W - ML - MR, H - MT - MB
    C_LINE, C_BAR, C_DOT, C_TEXT, C_GRID, C_AXIS = (
        "#3ec9b0",
        "#e6be78",
        "#7c5cff",
        "#8b93a3",
        "rgba(236,233,225,.07)",
        "rgba(236,233,225,.25)",
    )

    def esc(v):
        return _svg_esc(v)

    if kind == "pie":
        total = sum(p[2] for p in points) or 1
        cx, cy, r = W / 2, H / 2 - 10, 120
        palette = [
            "#3ec9b0",
            "#e6be78",
            "#7c5cff",
            "#f2994a",
            "#eb5757",
            "#4cb782",
            "#8f6bff",
            "#d9a441",
        ]
        ang = -90.0
        parts = []
        legend = []
        for i, (lab, _, val) in enumerate(points):
            frac = val / total
            a2 = ang + 360.0 * frac
            large = 1 if (a2 - ang) > 180 else 0
            x1 = cx + r * __import__("math").cos(__import__("math").radians(ang))
            y1 = cy + r * __import__("math").sin(__import__("math").radians(ang))
            x2 = cx + r * __import__("math").cos(__import__("math").radians(a2))
            y2 = cy + r * __import__("math").sin(__import__("math").radians(a2))
            color = palette[i % len(palette)]
            parts.append(
                f'<path d="M{cx:.0f} {cy:.0f} L{x1:.0f} {y1:.0f} A{r:.0f} {r:.0f} 0 {large} 1 {x2:.0f} {y2:.0f} Z" '
                f'fill="{color}" stroke="#0a0c11" strokeWidth="1.5"/>'
            )
            legend.append(
                f'<rect x="{W - 190}" y="{40 + i * 20}" width="10" height="10" rx="2" fill="{color}"/>'
                f'<text x="{W - 174}" y="{49 + i * 20}" fill="{C_TEXT}" font-size="11">{esc(lab)} {val} ({frac * 100:.1f}%)</text>'
            )
            ang = a2
        parts.extend(legend)
        title_y = 22
    else:
        xs = [p[1] for p in points]
        ys = [p[2] for p in points]
        x0, x1 = min(xs), max(xs)
        y0, y1 = min(ys), max(ys)
        if x0 == x1:
            x1 = x0 + 1
        if y0 == y1:
            y1 = y0 + 1
        pdx, pdy = (x1 - x0) * 0.06, (y1 - y0) * 0.14
        x0, x1 = x0 - pdx, x1 + pdx
        y0, y1 = y0 - pdy, y1 + pdy

        def sx(v):
            return ML + (v - x0) / (x1 - x0) * pw

        def sy(v):
            return MT + ph - (v - y0) / (y1 - y0) * ph

        parts = []
        # 水平网格 + y 刻度（5 条）
        for i in range(5):
            gy = MT + ph * i / 4
            gv = y1 - (y1 - y0) * i / 4
            parts.append(
                f'<line x1="{ML}" y1="{gy:.0f}" x2="{W - MR}" y2="{gy:.0f}" stroke="{C_GRID}" strokeWidth="1"/>'
            )
            parts.append(
                f'<text x="{ML - 6}" y="{gy + 3:.0f}" fill="{C_TEXT}" font-size="10" text-anchor="end">{esc(round(gv, 2))}</text>'
            )
        # 纵轴
        parts.append(
            f'<line x1="{ML}" y1="{MT}" x2="{ML}" y2="{MT + ph}" stroke="{C_AXIS}" strokeWidth="1"/>'
        )
        parts.append(
            f'<line x1="{ML}" y1="{MT + ph}" x2="{W - MR}" y2="{MT + ph}" stroke="{C_AXIS}" strokeWidth="1"/>'
        )

        if kind == "bar":
            n = len(points)
            bw = pw / max(1, n) * 0.62
            for i, (lab, _, v) in enumerate(points):
                bx = ML + pw * i / max(1, n) + (pw / max(1, n) - bw) / 2
                by = sy(v)
                bh = MT + ph - by
                parts.append(
                    f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bw:.1f}" height="{max(1, bh):.1f}" rx="3" fill="{C_BAR}" opacity="0.88"/>'
                )
                if n <= 12:
                    parts.append(
                        f'<text x="{bx + bw / 2:.1f}" y="{by - 4:.0f}" fill="{C_TEXT}" font-size="10" text-anchor="middle">{esc(round(v, 2))}</text>'
                    )
                    parts.append(
                        f'<text x="{bx + bw / 2:.1f}" y="{MT + ph + 14:.0f}" fill="{C_TEXT}" font-size="9" text-anchor="middle">{esc(lab)}</text>'
                    )
        elif kind == "scatter":
            for _, x, y in points:
                parts.append(f'<circle cx="{sx(x):.1f}" cy="{sy(y):.1f}" r="4.5" fill="{C_DOT}"/>')
        else:  # line
            pts = " ".join(f"{sx(x):.1f},{sy(y):.1f}" for _, x, y in points)
            parts.append(
                f'<polyline points="{pts}" fill="none" stroke="{C_LINE}" strokeWidth="2" strokeLinejoin="round"/>'
            )
            for _, x, y in points:
                parts.append(f'<circle cx="{sx(x):.1f}" cy="{sy(y):.1f}" r="3.5" fill="{C_LINE}"/>')
            if len(points) <= 12:
                for _, x, y in points:
                    parts.append(
                        f'<text x="{sx(x):.1f}" y="{sy(y) - 7:.0f}" fill="{C_TEXT}" font-size="9" text-anchor="middle">{esc(round(y, 2))}</text>'
                    )
        if kind in ("scatter", "line") and len(points) <= 16:
            for lab, x, _ in points:
                parts.append(
                    f'<text x="{sx(x):.1f}" y="{MT + ph + 14:.0f}" fill="{C_TEXT}" font-size="9" text-anchor="middle">{esc(lab)}</text>'
                )
        title_y = 22

    title_x = W / 2
    head = ""
    if title:
        head += f'<text x="{title_x:.0f}" y="{title_y}" fill="#ece9e1" font-size="13" font-weight="600" text-anchor="middle">{esc(title)}</text>'
    if kind != "pie" and ylabel:
        head += f'<text x="14" y="{MT + ph / 2:.0f}" fill="{C_TEXT}" font-size="10" text-anchor="middle" transform="rotate(-90 14 {MT + ph / 2:.0f})">{esc(ylabel)}</text>'
    if kind != "pie" and xlabel:
        head += f'<text x="{W / 2:.0f}" y="{H - 8}" fill="{C_TEXT}" font-size="10" text-anchor="middle">{esc(xlabel)}</text>'

    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
        f'style="background:transparent;max-width:100%">'
        f"{head}{''.join(parts)}</svg>"
    )
    return svg


def _chart(data, kind="line", title="", xlabel="", ylabel=""):
    """画图（沙箱注入）：data 支持 [1,2,3]（自动序号）/ [{'x':..,'y':..}] / [[x,y],...] / {标签:值}（饼图）。
    返回 markdown 图片引用，SVG 图表直接显示在对话里。kind: line/bar/scatter/pie"""
    kind = str(kind).lower()
    if kind not in ("line", "bar", "scatter", "pie"):
        raise ValueError(f"chart kind 仅支持 line/bar/scatter/pie，收到 {kind}")

    # 归一化 → points: (label, x_or_None, y)；x 为数值时保留数值（line/scatter 需要），否则 None（柱/饼用标签）
    points = []

    def _to_num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    if isinstance(data, dict):
        points = [(str(k), None, float(v)) for k, v in data.items()]
    elif isinstance(data, (list, tuple)) and data:
        first = data[0]
        if isinstance(first, (int, float)):
            points = [(str(i), float(i), float(v)) for i, v in enumerate(data)]
        elif isinstance(first, (list, tuple)) and len(first) >= 2:
            points = [(str(d[0]), _to_num(d[0]), float(d[1])) for d in data]
        elif isinstance(first, dict) and "x" in first and "y" in first:
            points = [(str(d["x"]), _to_num(d["x"]), float(d["y"])) for d in data]
        elif isinstance(first, str) and len(data) == 2:
            points = [(str(data[0]), None, float(data[1]))]
    if not points:
        raise ValueError(
            "chart 数据为空或格式不支持（[1,2,3] / [{'x','y'}] / [[x,y]] / {标签:值}）"
        )
    # 数值类图表（line/scatter/bar 的坐标）：必须全部有数值 x，否则降级用索引
    if kind in ("line", "scatter", "bar"):
        if all(x is not None for _, x, _ in points):
            pass
        else:
            points = [(lab, float(i), y) for i, (lab, x, y) in enumerate(points)]

    svg = _svg_chart(points, kind, title, xlabel, ylabel)
    if len(svg.encode("utf-8")) > _MAX_FILE_BYTES:
        return "(chart 图表过大被拒——数据量太大，减少采样点后重试)"
    _CHART_DIR.mkdir(parents=True, exist_ok=True)
    q = _check_quota(_CHART_DIR, _MAX_CHARTS)
    if q:
        return f"({q})"
    fname = f"{uuid.uuid4().hex[:12]}.svg"
    (_CHART_DIR / fname).write_text(svg, encoding="utf-8")
    return f"![](/charts/{fname})"


def _read_file(path):
    """读文件（沙箱注入）：只读拾光数据目录（data/ 下 uploads/kb 等用户资料），返回内容。
    安全：路径白名单锁死（真实路径解析后必须位于 data/ 内），越权路径拒绝。"""
    try:
        p = pathlib.Path(str(path)).resolve()
        ok = False
        for root in _READ_ROOTS:
            # 2026-09-02 TC-S03 修复：startswith 前缀匹配会把 data-experiment/data-test-tmp
            # 等兄弟目录放行（root 无尾斜杠）——白名单边界必须按**组件边界**判定
            try:
                p.relative_to(root.resolve())
                ok = True
                break
            except ValueError:
                continue
        if not ok:
            return "(read_file 仅允许读取用户资料目录: memory/ data/ research/)"
        if not p.is_file():
            return f"(文件不存在: {p.name})"
        text = p.read_text(encoding="utf-8", errors="replace")
        if len(text) > 4000:
            return text[:4000] + f"\n…(已截断，全文 {len(text)} 字符)"
        return text
    except Exception as e:
        return f"(read_file 失败: {e})"


def _save_result(content, name="result.txt"):
    """保存分析结果（沙箱注入）：写 D 盘 sandbox_outputs/，返回对话内可点击的下载链接。
    name 仅允许字母数字._-（防路径穿越）；同名自动加序号不覆盖；单文件 2MB/目录 200 文件配额。"""
    import re

    safe = re.sub(r"[^A-Za-z0-9._-]", "_", str(name)) or "result.txt"
    if not safe.endswith((".txt", ".csv", ".json", ".md", ".log", ".py")):
        safe += ".txt"
    text = str(content)
    if len(text.encode("utf-8")) > _MAX_FILE_BYTES:
        return f"(结果过大被拒（>{_MAX_FILE_BYTES // 1024 // 1024}MB）——拆分后分次保存)"
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    q = _check_quota(_OUTPUT_DIR, _MAX_OUTPUTS)
    if q:
        return f"({q})"
    # 同名不覆盖：report.txt 已存在 → report_2.txt
    p = _OUTPUT_DIR / safe
    i = 2
    while p.exists():
        p = _OUTPUT_DIR / f"{pathlib.Path(safe).stem}_{i}{pathlib.Path(safe).suffix}"
        i += 1
    p.write_text(text, encoding="utf-8")
    return (
        f"[下载 {p.name}](/outputs/{p.name})"
        "（B2 2026-08-27：分析成果可归档——如需进个人知识库，用 read_file 读回内容后调 kb_ingest，"
        "模型会判断哪些成果值得留存）"
    )


def main():
    _cleanup_old()  # 生命周期（P2a）：每次沙箱运行顺带清理超期产物
    with open(sys.argv[1], encoding="utf-8") as cf:
        code = cf.read()
    # __name__ 惯用法放宽（2026-08-26）：RestrictedPython 编译器拒 dunder 变量名——
    # `if __name__ == "__main__":` 是学习代码最高频惯用法，本沙箱是模块执行场景（恒真），
    # 文本层替换为 if True:（安全：仅匹配该精确模式，不涉及任何属性/逃逸面）
    code = code.replace('if __name__ == "__main__":', "if True:  # __main__ guard (sandbox)")
    # __name__ 惯用法放宽（2026-08-26）：RestrictedPython 编译器拒 dunder 变量名——
    # `if __name__ == "__main__":` 是学习代码最高频惯用法，本沙箱是模块执行场景（恒真），
    # 文本层替换为 if True:（安全：仅匹配该精确模式，不涉及任何属性/逃逸面）
    code = code.replace('if __name__ == "__main__":', "if True:  # __main__ guard (sandbox)")
    try:
        compiled = compile_restricted_exec(code)
    except SyntaxError as e:
        print(f"(语法错误: {e})", file=sys.stderr)
        return
    if getattr(compiled, "errors", None):
        print(f"(受限检查未通过: {'; '.join(compiled.errors)})", file=sys.stderr)
        return
    glb = safe_globals.copy()
    glb.update(
        {
            "_getattr_": _G,
            "_getitem_": default_guarded_getitem,
            "_getiter_": iter,
            # RestrictedPython 8.4 官方双解包守卫（2026-08-22 补：for 循环解包走
            # _iter_unpack_sequence_，普通赋值解包走 _unpack_sequence_——只装一个会 NameError）
            "_unpack_sequence_": guarded_unpack_sequence,
            "_iter_unpack_sequence_": guarded_iter_unpack_sequence,
            # 写守卫（2026-08-22：官方 full_write_guard 威胁模型=进程内共享对象，本沙箱一次性
            # 子进程不适用——自定义放行守卫，类/数据结构可用；读守卫 default_guarded_getattr 保留）
            "_write_": _sandbox_write_guard,
            # 8.4 注入逻辑执行 _print_(_getattr_) → 传共享实例收集器（函数内 print 修复）
            "_print_": _shared_out,
            # 增强赋值守卫（2026-08-22：n += 1 → _inplacevar_("+=", n, 1)）
            "_inplacevar_": _inplacevar_,
            # 类定义必需（2026-08-22：8.4 把 class X: 转成 class X(metaclass=__metaclass__)）
            "__metaclass__": type,
            "__name__": "__sandbox__",
            # 受控能力注入（2026-08-26 沙箱增强：画图/读资料/存结果）
            "chart": _chart,
            "read_file": _read_file,
            "save_result": _save_result,
        }
    )
    # 白名单 import（2026-08-21）：safe_builtins 无 __import__（默认全禁），注入白名单版
    # 学习场景内置补全（2026-08-22）：safe_builtins + LEARN_BUILTINS
    glb["__builtins__"] = {**safe_builtins, **LEARN_BUILTINS, "__import__": _safe_import}
    try:
        exec(compiled.code, glb)
    except Exception as e:
        print(f"(运行错误: {type(e).__name__}: {e})", file=sys.stderr)
        return
    out = _shared_out.text()
    if out:
        print(out, end="")


if __name__ == "__main__":
    main()
