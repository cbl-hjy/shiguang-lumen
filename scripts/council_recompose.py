# -*- coding: utf-8 -*-
"""重组 cangjie-skill 产物为星笺（sage card）——蒸馏工厂的"重组"路径。

cangjie-skill 已把书蒸馏成 BOOK_OVERVIEW.md + verified.md + 各 SKILL.md，
本脚本把这三类产物重组为拾光"先贤会议"用的星笺：
  立场声明（stance）← BOOK_OVERVIEW 主旨
  核心观点（core_claims，带引用/证据/预测力）← verified.md + SKILL.md R 段
  方法论（methodology）← BOOK_OVERVIEW 骨架 + SKILL.md I 段
  边界（boundaries）← BOOK_OVERVIEW 批判 + SKILL.md B 段
  术语（glossary）← BOOK_OVERVIEW 关键术语

用法:
  python scripts/council_recompose.py --src research/cangjie-packs/influence-skill --out data/sages
纯 stdlib，无第三方依赖。输出 <out>/<slug>.json + <out>/<slug>.md。
"""
import argparse
import json
import re
import sys
from pathlib import Path

SLUG_RE = re.compile(r"^## s\d+:\s*(\S+)\s*[—\-]\s*(.+)")
FIELD_RE = re.compile(r"^([A-Za-z_]+):\s*$")
LIST_ITEM_RE = re.compile(r"^[-*]\s+(.+)$")
NUM_ITEM_RE = re.compile(r"^\d+[\.、]\s*(.+)$")


def strip_bullet(line: str) -> str:
    m = LIST_ITEM_RE.match(line) or NUM_ITEM_RE.match(line)
    return m.group(1) if m else line


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def parse_overview(text: str) -> dict:
    """解析 BOOK_OVERVIEW.md，提取星笺骨架素材。"""
    d: dict = {"title": "", "author": "", "year": "", "stance": "",
               "skeleton": [], "propositions": [], "glossary": [],
               "limits": [], "blindspots": [], "unproven": [], "opposition": ""}
    # 基本信息
    for pat, key in [(r"书名\*\*[:：]\s*(.+)$", "title"),
                     (r"作者\*\*[:：]\s*(.+)$", "author"),
                     (r"出版年\*\*[:：]\s*(.+)$", "year")]:
        m = re.search(pat, text, re.M)
        if m:
            d[key] = m.group(1).strip()
    # 一句话主旨
    m = re.search(r"### 一句话主旨\s*\n(.+?)(?:\n###|\n\n)", text, re.S)
    if m:
        d["stance"] = m.group(1).strip()
    # 骨架论点
    m = re.search(r"### 骨架[^\n]*\n(.+?)(?:\n###|\n\n##)", text, re.S)
    if m:
        for line in m.group(1).splitlines():
            line = line.strip()
            it = re.match(r"^\d+\.\s*\*\*(.+?)\*\*(.*)$", line)
            if it:
                d["skeleton"].append(f"{it.group(1)}{it.group(2)}".strip())
    # 核心命题
    m = re.search(r"### 核心命题[^\n]*\n(.+?)(?:\n###|\n\n##)", text, re.S)
    if m:
        for line in m.group(1).splitlines():
            line = line.strip()
            it = NUM_ITEM_RE.match(line)
            if it:
                d["propositions"].append(it.group(1).strip())
    # 关键术语表
    m = re.search(r"### 关键术语.*?\n(.+?)(?:\n###|\n\n##)", text, re.S)
    if m:
        for line in m.group(1).splitlines():
            line = line.strip()
            if line.startswith("|") and not line.startswith("|---"):
                cells = [c.strip() for c in line.strip("|").split("|")]
                if len(cells) >= 2 and cells[0] not in ("术语", "作者的定义"):
                    d["glossary"].append({"term": cells[0], "def": cells[1]})
    # 批判四段
    for pat, key in [(r"### 作者的时代局限\n(.+?)(?=\n###|\n\n##|\Z)", "limits"),
                     (r"### 作者的立场盲点\n(.+?)(?=\n###|\n\n##|\Z)", "blindspots"),
                     (r"### 未被证明的假设\n(.+?)(?=\n###|\n\n##|\Z)", "unproven"),
                     (r"### 最强反对意见\n(.+?)(?=\n>|##|\Z)", "opposition")]:
        m = re.search(pat, text, re.S)
        if m:
            items = []
            for line in m.group(1).splitlines():
                line = line.strip()
                if LIST_ITEM_RE.match(line) or NUM_ITEM_RE.match(line):
                    items.append(strip_bullet(line))
            if key == "opposition":
                d[key] = " ".join(items) or m.group(1).strip().split("\n")[0]
            else:
                d[key] = items
    return d


def parse_verified(text: str) -> list:
    """解析 verified.md，提取每个 skill 的 title/证据/预测力/独特性。"""
    claims = []
    sections = re.split(r"(?=^## s\d+:)", text, flags=re.M)
    for sec in sections:
        hm = SLUG_RE.match(sec.strip())
        if not hm:
            continue
        slug, title = hm.group(1), hm.group(2).strip()
        c = {"slug": slug, "title": title, "evidence": [], "novel_question": "", "derived_answer": "", "novelty": ""}
        ev = re.search(r"V1_cross_domain:\s*\n(?:.*?\n)*?\s+evidence:\s*\n((?:.*\n)*?)(?=\s+V2_)", sec)
        if ev:
            for line in ev.group(1).splitlines():
                line = line.strip().lstrip("-")
                if line and not line.startswith("passed"):
                    c["evidence"].append(line)
        nq = re.search(r"novel_question:\s*\"?(.+?)\"?\s*$", sec, re.M)
        if nq:
            c["novel_question"] = nq.group(1).strip().strip('"')
        da = re.search(r"derived_answer:\s*\"?(.+?)\"?\s*$", sec, re.M)
        if da:
            c["derived_answer"] = da.group(1).strip().strip('"')
        nt = re.search(r"why_not_common:\s*\"?(.+?)\"?\s*$", sec, re.M)
        if nt:
            c["novelty"] = nt.group(1).strip().strip('"')
        claims.append(c)
    return claims


def parse_index(text: str) -> list:
    """解析 INDEX.md 的 skill 列表（book2skill 产物的 fallback 来源）。"""
    claims = []
    pat = re.compile(r"\[`([^`]+)`\]\(\./([^)]+)/SKILL\.md\)\s*[—-]+\s*(.+)")
    for line in text.splitlines():
        m = pat.search(line)
        if m:
            claims.append({"slug": m.group(1), "title": m.group(3).strip(), "evidence": [],
                           "novel_question": "", "derived_answer": "", "novelty": ""})
    return claims


def parse_skill_quote(skill_dir: Path) -> str:
    """从 SKILL.md 提取原文引用（R 段第一句引用）。"""
    sk = skill_dir / "SKILL.md"
    if not sk.exists():
        return ""
    text = sk.read_text(encoding="utf-8")
    m = re.search(r'## R — 原文[^\n]*\n\s*>\s*"?(.+?)"?\s*(?:\n>\s*—|\n\s*>\s*—|\Z)', text, re.S)
    if not m:
        return ""
    quote = m.group(1).strip()
    return quote[:120]


def parse_skill_detail(skill_dir: Path) -> dict:
    """从 SKILL.md 提取引用/案例/来源（不依赖 verified.md 格式）。"""
    sk = skill_dir / "SKILL.md"
    if not sk.exists():
        return {"quote": "", "cases": [], "source": ""}
    text = sk.read_text(encoding="utf-8")
    source = ""
    m = re.match(r"^---\n(.*?)\n---", text, re.S)
    if m:
        sc = re.search(r"source_chapter:\s*(.+)$", m.group(1), re.M)
        sb = re.search(r"source_book:\s*(.+)$", m.group(1), re.M)
        source = (sc.group(1).strip() if sc else "") + (" / " + sb.group(1).strip() if sb else "")
    quote = ""
    m = re.search(r"## R — 原文[^\n]*\n\s*>\s*[“\"\u201c]?(.+?)[”\"\u201d]?\s*$", text, re.M)
    if m:
        quote = m.group(1).strip()[:120]
    cases = []
    m = re.search(r"## A1[^\n]*\n(.+?)(?=\n## )", text, re.S)
    if m:
        for line in m.group(1).splitlines():
            cm = re.match(r"^#{2,3}\s*(案例\s*\d+[^\n]*)", line.strip())
            if cm:
                cases.append(cm.group(1).strip())
    return {"quote": quote, "cases": cases[:3], "source": source}


def build_sage(src: Path, slug: str) -> dict:
    """组合 BOOK_OVERVIEW + verified/INDEX + SKILL.md 为星笺 dict。"""
    ov = parse_overview(read_text(src / "BOOK_OVERVIEW.md"))
    vf = src / "verified.md"
    claims = parse_verified(read_text(vf)) if vf.exists() else []
    if not claims:  # book2skill 等非 cangjie 格式 → INDEX fallback
        claims = parse_index(read_text(src / "INDEX.md"))
    # 补充每条观点的原文引用、案例与来源章节
    for c in claims:
        detail = parse_skill_detail(src / c["slug"])
        c["quote"] = detail["quote"]
        c["cases"] = detail["cases"]
        c["source"] = detail["source"]
    clean_title = ov["title"].lstrip("《").rstrip("》")
    sage = {
        "id": slug,
        "name": f"《{clean_title}》" if clean_title else slug,
        "book": clean_title,
        "author": ov["author"],
        "year": ov["year"],
        "stance": ov["stance"],
        "core_claims": claims,
        "skeleton": ov["skeleton"],
        "propositions": ov["propositions"],
        "glossary": ov["glossary"][:15],
        "boundaries": {
            "limits": ov["limits"],
            "blindspots": ov["blindspots"],
            "unproven": ov["unproven"],
            "strongest_opposition": ov["opposition"],
        },
        "audit": {"tool": "cangjie-skill", "recomposed_by": "council_recompose.py",
                  "user_confirmed": False, "claims_count": len(claims)},
    }
    return sage


def to_markdown(sage: dict) -> str:
    L = [f"# 星笺：{sage['name']}", ""]
    L += [f"- **书**：{sage['book']}｜{sage['author']}｜{sage['year']}", ""]
    L += ["## 立场声明", "", sage["stance"], ""]
    L += ["## 核心观点", ""]
    for i, c in enumerate(sage["core_claims"], 1):
        L += [f"### {i}. {c['title']}（{c.get('slug', '')}）", ""]
        if c.get("quote"):
            L += [f"> “{c['quote']}”", ""]
        L += [f"- **主张**：{c['title']}", ""]
        if c.get("evidence"):
            L += ["- **证据**（跨域佐证）："]
            L += [f"  - {e}" for e in c["evidence"][:3]]
            L += [""]
        if c.get("derived_answer"):
            L += [f"- **预测力**（{c['novel_question']}）→ {c['derived_answer'][:100]}", ""]
        if c.get("cases"):
            L += ["- **案例**："]
            L += [f"  - {case}" for case in c["cases"]]
            L += [""]
        if c.get("source"):
            L += [f"- **出处**：{c['source']}", ""]
    L += ["## 方法论骨架", ""]
    for s in sage["skeleton"]:
        L += [f"- {s}", ""]
    L += ["## 边界", ""]
    L += ["### 时代局限"]
    L += [f"- {x}" for x in sage["boundaries"]["limits"]] or ["- 无"]
    L += ["", "### 立场盲点"]
    L += [f"- {x}" for x in sage["boundaries"]["blindspots"]] or ["- 无"]
    L += ["", "### 未被证明的假设"]
    L += [f"- {x}" for x in sage["boundaries"]["unproven"]] or ["- 无"]
    L += ["", f"### 最强反对意见", "", sage["boundaries"]["strongest_opposition"] or "无", ""]
    L += ["## 审计", ""]
    L += [f"- 蒸馏工具：{sage['audit']['tool']}（{sage['audit']['recomposed_by']}）", ""]
    L += [f"- 观点数：{sage['audit']['claims_count']}｜用户确认：{'是' if sage['audit']['user_confirmed'] else '否（待确认）'}", ""]
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description="重组 cangjie 产物为星笺")
    ap.add_argument("--src", required=True, help="cangjie 产物目录（含 BOOK_OVERVIEW.md）")
    ap.add_argument("--out", default="data/sages", help="输出目录")
    args = ap.parse_args()
    src = Path(args.src)
    out = Path(args.out)
    if not (src / "BOOK_OVERVIEW.md").exists():
        print(f"错误：{src} 下没有 BOOK_OVERVIEW.md", file=sys.stderr)
        return 1
    slug = src.name.split("-")[0] if src.name.endswith("-skill") else src.name
    sage = build_sage(src, slug)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{slug}.json").write_text(json.dumps(sage, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / f"{slug}.md").write_text(to_markdown(sage), encoding="utf-8")
    print(f"已生成星笺：{out / slug}.md / .json（{sage['audit']['claims_count']} 条观点）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
