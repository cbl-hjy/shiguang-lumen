"""doc_health.py —— 项目+记忆健康检查（防腐烂机器，挂回归门）

依据：docs/DATA-GOVERNANCE-PLAN.md（对齐 OpenAI Harness "doc-gardening" 原则）
定位：改代码/整理文档后顺手跑，不单独定时（回归门只响应事件，从不巡逻）。
输出：绿/黄/红 + 具体清单。退出码：0=绿，1=黄，2=红（回归门可据此判定）。

用法：python scripts/doc_health.py [--quiet]
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
MEMORY = ROOT / "memory"
DOCS = ROOT / "docs"
RESEARCH = ROOT / "research"
REPORTS = ROOT / "reports"

# 正式库白名单（data/ 顶层允许存在的文件/目录；探针一律进 archive/probes/）
DATA_ALLOWED = {
    "sessions.db", "wakeups.db", "service_guard.log", "memory.md",  # 运行数据
    "token_usage.csv", "injection_log.jsonl",  # 观测数据（2026-08-17 harness 增强）
    "archive", "backup", "kb", "uploads", "vector_mem", "vector_evolve",
    "friction_runs", "longhorizon_runs", "ux_shots", "ux_stress", "poc_chroma",
    "kb_debug", "kb_debug2", "kb_debug3", "README.md", "readme.md",
}

# 索引文件 → 应列出所在目录下的 md 文件（resume 已迁出项目：简历域 2026-08-15 起独立于 D:\work_buddy\2026秋招简历\，见 PROJECT-LAYOUT B 节）
INDEXES = {
    RESEARCH / "README.md": RESEARCH,
    REPORTS / "README.md": REPORTS,
}

# trash.md 归档天数提示
TRASH_ARCHIVE_DAYS = 30


def _load_json(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def check_memory_format() -> list[str]:
    """记忆格式合法：user_memory.md 每行 9 字段（日期|src=|imp=|cat=|内容）"""
    f = MEMORY / "user_memory.md"
    issues = []
    if not f.exists():
        return issues
    for i, ln in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
        if not ln.strip() or ln.startswith("#"):
            continue
        if not (ln.startswith("- ") and "src=" in ln and "imp=" in ln and "cat=" in ln):
            issues.append(f"user_memory.md 第{i}行格式不合法: {ln[:60]}")
    return issues


def check_index_correspondence() -> list[str]:
    """索引与文件一一对应：索引中引用的 md 应存在；目录中 md 应被索引（排除索引自身 README）"""
    issues = []
    for idx_file, dir_ in INDEXES.items():
        if not idx_file.exists():
            issues.append(f"索引缺失: {idx_file.relative_to(ROOT)}")
            continue
        idx_text = idx_file.read_text(encoding="utf-8")
        # 目录下实际 md（排除索引文件自身——README 引自己不算漏）
        actual = sorted(p.name for p in dir_.glob("*.md") if p.name != "README.md")
        # 索引中被反引号引用的文件名（粗匹配：md 文件名出现在索引中）
        referenced = {name for name in actual if name in idx_text}
        missing_ref = [n for n in actual if n not in referenced]
        # 索引里提到的文件不在目录（反向：扫描 `xxx.md` 模式）
        import re
        mentioned = set(re.findall(r"`([^`]+\.md)`", idx_text))
        ghost = sorted(m for m in mentioned if not (dir_ / m).exists() and not (ROOT / m).exists())
        if missing_ref:
            issues.append(f"{idx_file.relative_to(ROOT)} 未索引: {', '.join(missing_ref[:5])}")
        if ghost:
            issues.append(f"{idx_file.relative_to(ROOT)} 索引幽灵(文件不存在): {', '.join(ghost[:5])}")
    return issues


def check_trash_age() -> list[str]:
    """trash.md 条目时间：超 30 天提示归档"""
    f = MEMORY / "trash.md"
    if not f.exists():
        return []
    import re
    from datetime import date, datetime

    dates = re.findall(r"(\d{4}-\d{2}-\d{2})", f.read_text(encoding="utf-8"))
    stale = []
    today = date.today()
    for d in dates:
        try:
            dt = datetime.strptime(d, "%Y-%m-%d").date()
            if (today - dt).days > TRASH_ARCHIVE_DAYS:
                stale.append(d)
        except ValueError:
            continue
    if stale:
        return [f"trash.md 有 {len(stale)} 条超 {TRASH_ARCHIVE_DAYS} 天（最早 {min(stale)}），提示归档/物理清理"]
    return []


def check_unverified() -> list[str]:
    """unverified 计数：imp>=6 且 unverified 的记忆数（提示复查）"""
    f = MEMORY / "user_memory.md"
    if not f.exists():
        return []
    high_unverified = 0
    for ln in f.read_text(encoding="utf-8").splitlines():
        if not ln.startswith("- ") or "imp=" not in ln:
            continue
        try:
            imp = int(ln.split("imp=")[1].split("|")[0].strip())
        except (IndexError, ValueError):
            continue
        if imp >= 6 and "ver=verified" not in ln:
            high_unverified += 1
    if high_unverified:
        return [f"imp>=6 且未复查(ver=unverified)记忆 {high_unverified} 条 → 跑 memory_audit.py 复查"]
    return []


def check_data_cleanliness() -> list[str]:
    """data/ 顶层干净度：非白名单文件（探针回流检测）"""
    issues = []
    if not DATA.exists():
        return issues
    for p in DATA.iterdir():
        if p.name in DATA_ALLOWED:
            continue
        issues.append(f"data/ 顶层非白名单: {p.name}（探针应移 archive/probes/）")
    return issues


def check_docs_purity() -> list[str]:
    """项目内零简历文件（用户红线 2026-08-15：简历完全迁出项目 → 求职域 D:\\work_buddy\\2026秋招简历\\）。
    简历类文件（文件名含 resume/简历）一旦出现在项目顶层或 docs/ 即报错。"""
    import re
    issues = []
    for base, label in ((ROOT, "顶层"), (DOCS, "docs/")):
        if not base.exists():
            continue
        for p in base.iterdir():
            if p.is_dir() or p.suffix.lower() not in (".md", ".docx", ".pdf"):
                continue
            if re.search(r"resume|简历", p.name, re.IGNORECASE):
                issues.append(f"项目内发现简历文件: {p.relative_to(ROOT)}（应进求职域 D:\\work_buddy\\2026秋招简历\\，项目内零简历文件）")
    return issues


def check_dev_log_format() -> list[str]:
    """开发工具工作日志格式：## 标题带 (HH:MM) 时间 + 有"做了什么"段（章程见 .workbuddy/memory/README.md）。
    规则：2026-08-15（章程生效日）起的日志必须合规（违规=黄灯）；更早的历史日志是已发生事实，
    只统计不计数（历史不改写，防止篡改事实）。"""
    import re
    dev_mem = ROOT / ".workbuddy" / "memory"
    issues = []
    if not dev_mem.exists():
        return issues
    charter_date = "2026-08-15"
    for f in sorted(dev_mem.glob("2026-*.md")):
        if f.name == "README.md":
            continue
        must_comply = f.name[:10] >= charter_date
        text = f.read_text(encoding="utf-8")
        blocks = re.split(r"(?m)^## ", text)[1:]
        no_time = [b.splitlines()[0][:50] for b in blocks if not re.search(r"（\d{2}:\d{2}", b)]
        no_action = []
        for b in blocks:
            has_time = bool(re.search(r"（\d{2}:\d{2}", b))
            if has_time and "做了什么" not in b and "完成" not in b.splitlines()[0] and "定案" not in b.splitlines()[0] and "落地" not in b.splitlines()[0]:
                no_action.append(b.splitlines()[0][:50])
        if not must_comply:
            continue  # 历史日志豁免（不计数）
        if no_time:
            issues.append(f"{f.name} {len(no_time)} 个章节标题缺时间(HH:MM): {no_time[0]}...")
        if no_action:
            issues.append(f"{f.name} {len(no_action)} 个章节缺'做了什么'或结果态: {no_action[0]}...")
    return issues


def main() -> int:
    quiet = "--quiet" in sys.argv
    checks = [
        ("记忆格式", check_memory_format()),
        ("索引对应", check_index_correspondence()),
        ("trash 归档", check_trash_age()),
        ("unverified", check_unverified()),
        ("data 干净度", check_data_cleanliness()),
        ("docs 纯净度", check_docs_purity()),
        ("日志格式", check_dev_log_format()),
    ]
    all_issues = [(name, issues) for name, issues in checks if issues]
    red = [n for n, i in all_issues if n in ("data 干净度", "docs 纯净度", "记忆格式")]

    if not all_issues:
        print("doc_health: ✅ 全绿（记忆格式/索引/归档/复查/目录干净度全部合规）")
        return 0
    if quiet:
        print("doc_health: 发现问题")
        for name, issues in all_issues:
            for i in issues[:3]:
                print(f"  [{name}] {i}")
        return 2 if red else 1
    print("doc_health: 检查结果")
    for name, issues in all_issues:
        level = "🔴" if name in red else "🟡"
        print(f"  {level} {name}:")
        for i in issues:
            print(f"     - {i}")
    print(f"\n结论: {'红（需处理）' if red else '黄（建议处理）'}")
    return 2 if red else 1


if __name__ == "__main__":
    sys.exit(main())
