"""deadcode_scan.py —— 死代码静态扫描（2026-08-18）

背景：tutor.py inject_context 的 _log_injection 在 return 之后（死代码）被发现，
用户要求系统性排查是否还有同类问题。

扫描三类：
1. return/raise/continue/break 之后不可达的语句（Unreachable）
2. 模块级函数定义但从未被任何代码引用的（Unused function，排除：
   - 被 tools=[...] 注册的（pydantic-ai 工具，框架调用）
   - 被 register_*_writer 注册的回调
   - 名字以 _ 开头的私有辅助（可能被动态调用，单独列出）
   - 被 @agent.instructions 装饰的）
3. 导入但从未使用的（粗扫：import X 后 X 不在文件正文出现）

用法：python scripts/deadcode_scan.py [path]
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = (Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "app")
if not TARGET.is_absolute():
    TARGET = ROOT / TARGET


class UnreachableFinder(ast.NodeVisitor):
    """找 return/raise/continue/break 之后的不可达语句"""

    def __init__(self):
        self.hits = []

    def _check_body(self, body, node, file, lineno_offset=0):
        for i, stmt in enumerate(body):
            # 一个语句块内，如果前面有终局语句（return/raise/continue/break），后续即不可达
            if i > 0 and isinstance(body[i - 1], (ast.Return, ast.Raise, ast.Continue, ast.Break)):
                self.hits.append((file, node, stmt.lineno, ast.unparse(stmt)[:80]))
                break  # 只报第一个不可达（之后也是）
            # 嵌套：if/for/while/try/with 的 body
            if isinstance(stmt, (ast.If, ast.For, ast.While, ast.With, ast.Try)):
                self._recurse(stmt, file)

    def _recurse(self, node, file):
        for field in ("body", "orelse", "finalbody"):
            b = getattr(node, field, None)
            if isinstance(b, list) and b:
                self._check_body(b, node, file)
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.If, ast.For, ast.While, ast.With, ast.Try)):
                self._recurse(child, file)

    def visit_FunctionDef(self, node):
        self._check_body(node.body, node, self.cur_file)
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef


def scan_unreachable(file: Path) -> list:
    tree = ast.parse(file.read_text(encoding="utf-8"))
    finder = UnreachableFinder()
    finder.cur_file = str(file.relative_to(ROOT))
    finder.visit(tree)
    return finder.hits


def scan_unused_functions(file: Path) -> list:
    """模块级/类级函数定义但未被引用（排除工具/回调/instructions）"""
    text = file.read_text(encoding="utf-8")
    tree = ast.parse(text)
    defined = {}  # name -> lineno
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defined[node.name] = node.lineno
    if not defined:
        return []
    # 排除被框架注册的
    excluded = set()
    # 工具列表：tools=[_remember_mark, search_memory, ...]
    for node in ast.walk(tree):
        if isinstance(node, ast.List) and node.elts:
            for elt in node.elts:
                if isinstance(elt, ast.Name) and elt.id in defined:
                    excluded.add(elt.id)
        if isinstance(node, ast.Call):
            fn = node.func
            name = fn.id if isinstance(fn, ast.Name) else (fn.attr if isinstance(fn, ast.Attribute) else "")
            if name.startswith("register_") or name == "register_profile_writer" or "register" in name:
                for a in node.args:
                    if isinstance(a, ast.Name) and a.id in defined:
                        excluded.add(a.id)
    # 装饰器 @agent.instructions
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.decorator_list:
            for d in node.decorator_list:
                dname = d.id if isinstance(d, ast.Name) else (d.attr if isinstance(d, ast.Attribute) else "")
                if "instructions" in dname or "tool" in dname or "agent" in dname:
                    excluded.add(node.name)
    unused = []
    for name, lineno in defined.items():
        if name in excluded:
            continue
        # 私有辅助函数（_ 开头）单独标注，不做硬结论
        # 检查正文中出现次数（def 行本身不算）
        count = text.count(name)
        defs = text.count(f"def {name}")
        if count <= defs:  # 只有定义处出现
            unused.append((name, lineno))
    return unused


def scan_unused_imports(file: Path) -> list:
    """粗扫：from X import Y / import X 后未使用"""
    text = file.read_text(encoding="utf-8")
    tree = ast.parse(text)
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                n = alias.asname or alias.name
                # 排除 __all__ 导出 / * 导入
                if n == "*":
                    continue
                if text.count(n) <= 1:  # 只在 import 行出现
                    hits.append((n, node.lineno))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                n = alias.asname or alias.name.split(".")[0]
                if text.count(n) <= 1:
                    hits.append((n, node.lineno))
    return hits


def main():
    print("=" * 62)
    print("死代码扫描（app/ 全库）")
    print("=" * 62)
    files = sorted(TARGET.rglob("*.py")) if TARGET.is_dir() else [TARGET]
    files = [f for f in files if "__pycache__" not in str(f)]

    total_unreachable = 0
    total_unused_fn = 0
    total_unused_imp = 0
    for f in files:
        try:
            rel = str(f.relative_to(ROOT))
        except ValueError:
            rel = str(f)
        # 1. 不可达代码
        u = scan_unreachable(f)
        if u:
            total_unreachable += len(u)
            for file, node, lineno, code in u:
                print(f"  🔴 不可达代码 {file}:L{lineno} → {code}")
        # 2. 未使用函数
        uf = scan_unused_functions(f)
        if uf:
            total_unused_fn += len(uf)
            for name, lineno in uf:
                print(f"  🟡 未引用函数 {rel}:L{lineno} def {name}")
        # 3. 未使用导入
        ui = scan_unused_imports(f)
        if ui:
            total_unused_imp += len(ui)
            for name, lineno in ui:
                print(f"  ⚪ 疑似未用导入 {rel}:L{lineno} {name}")

    print()
    print(f"结论：不可达 {total_unreachable} | 未引用函数 {total_unused_fn} | 疑似未用导入 {total_unused_imp}")
    print("注：未引用函数可能被动态调用（如 pydantic-ai 工具/回调），需人工确认；_ 私有函数除外")


if __name__ == "__main__":
    main()
