#!/usr/bin/env python3
"""把站点上的两份帮助文档转成 Markdown，内置进项目。

**为什么可以内置**：系统帮助里的学生手册、提交注意事项是站点的静态内容，
对所有账号完全一样，不像班级/题目那样随账号不同，所以放进项目、
不必每个账号各爬一遍。

源是缓存里的 Word 导出的 HTML（结构很脏），这里做一次清洗：
段落、列表、代码块分开，代码块保留原样缩进。

用法：

    .venv/bin/python tools/build_help_docs.py            # 用缓存
    .venv/bin/python tools/build_help_docs.py --fetch    # 缓存缺失时联网抓一次
"""

from __future__ import annotations

import argparse
import html as htmllib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from matu.core.client import CACHE_DIR  # noqa: E402

OUT_DIR = ROOT / "src" / "matu" / "resources" / "help"

DOCS = [
    {
        "id": "student_manual",
        "title": "学生手册",
        "url": "/aptat/page/document/student_operation_guide.htm",
        "cache": "page__document__student_operation_guide.htm.html",
        "out": "student_manual.md",
    },
    {
        "id": "commit_attention",
        "title": "学生提交注意事项",
        "url": "/aptat/page/document/assignment_commit_attention.htm",
        "cache": "page__document__assignment_commit_attention.htm.html",
        "out": "commit_attention.md",
    },
]

CODE_HINT = re.compile(
    r"^\s*(#\s*include|#\s*define|void\s|int\s|char\s|double\s|float\s|"
    r"class\s|struct\s|printf|scanf|return|if\s*\(|for\s*\(|while\s*\(|"
    r"\{|\}|//|/\*|\*)")

# 明确是"一段代码的开头"的行：预处理指令、main、类/结构体、以及函数定义
STRONG_START = re.compile(
    r"^\s*(#\s*(include|define|ifndef|ifdef|endif)|"
    r"(void|int|char|double|float|bool|long|short|unsigned)\s+[\w*]+\s*\(|"
    r"(void|int)\s+main\s*\(|class\s+\w|struct\s+\w|template\s*<|using\s+namespace)")

# 代码里会出现的中文只可能在字符串里，且那类行一定带 ; ( " 等符号
_CODE_PUNCT = re.compile(r"[;{}()#/\\*=\"']")


def is_prose(line: str) -> bool:
    """判断一行是不是正文（而不是代码）。

    Word 把代码拆得很碎，`result) {`、`if(` 这种碎片行不能用来自行判断，
    否则会把一段代码切成好几块。改成"只要不是正文就还留在代码块里"。
    """
    s = line.strip()
    if not s:
        return False
    has_cjk = bool(re.search(r"[\u4e00-\u9fff]", s))
    if not has_cjk:
        return False
    if s.endswith(("。", "，", "：", "、", "；")) and not _CODE_PUNCT.search(s[:1]):
        return True
    # 整行中文、不含任何代码符号 —— 一定是正文
    return not _CODE_PUNCT.search(s)


def starts_code(line: str, prev: str) -> bool:
    """一行是不是一段代码的开头。"""
    if STRONG_START.match(line):
        return True
    if line.rstrip().endswith("{"):
        return True
    # 前一行是"如下，/："这类引导语，且本行看着像代码
    if prev and re.search(r"(如下|：|:)\s*$", prev.strip()) and looks_like_code(line):
        return True
    return False


def to_lines(raw_html: str) -> list:
    """把 Word 导出的 HTML 压成一行一段的纯文本。"""
    text = raw_html
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.S)
    text = re.sub(r"<(script|style|xml|head).*?</\1>", " ", text, flags=re.S | re.I)
    # 块级元素断行
    text = re.sub(r"</(p|div|tr|h[1-6]|li)\s*>", "\n", text, flags=re.I)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    # 行内标签直接去掉
    text = re.sub(r"<[^>]+>", "", text)
    text = htmllib.unescape(text)
    text = text.replace("\xa0", " ").replace("\u3000", " ")
    lines = []
    for ln in text.split("\n"):
        ln = re.sub(r"[ \t]+$", "", ln)
        if ln.strip():
            lines.append(ln.rstrip())
    return lines


def looks_like_code(line: str) -> bool:
    return bool(CODE_HINT.match(line))


def merge_number_titles(lines: list) -> list:
    """Word 里"1.1"和标题常常被拆成两行，这里合成一行，渲染出来才是完整标题。"""
    merged: list = []
    i = 0
    while i < len(lines):
        cur = lines[i].strip()
        nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
        if (re.fullmatch(r"\d+(\.\d+)*", cur) and 0 < len(nxt) <= 24
                and not looks_like_code(nxt)):
            merged.append(f"{cur} {nxt}")
            i += 2
            continue
        merged.append(lines[i])
        i += 1
    return merged


def to_markdown(title: str, url: str, lines: list) -> str:
    lines = merge_number_titles(lines)
    # 正文里不放"来源/出处"那行：来源信息在页面上没有意义
    out = [f"# {title}", ""]

    code_buf: list = []
    in_code = False

    def flush_code() -> None:
        nonlocal in_code
        if code_buf:
            out.append("```cpp")
            out.extend(code_buf)
            out.append("```")
            out.append("")
            code_buf.clear()
        in_code = False

    def emit_text(s: str) -> None:
        out.append(s)
        out.append("")

    for i, ln in enumerate(lines):
        prev = lines[i - 1] if i else ""
        if in_code:
            # 只有遇到正文才收尾：碎片行（`result) {`、`if(`）都会留在代码块里
            if not is_prose(ln):
                code_buf.append(ln)
                continue
            flush_code()
        elif starts_code(ln, prev):
            in_code = True
            code_buf.append(ln)
            continue

        stripped = ln.strip()
        # Word 目录那堆点线没有信息量，丢掉
        if re.search(r"\.{4,}", stripped):
            continue
        # 形如 "1、" "1.3.1" 的编号小标题：编号后面必须紧跟中文，
        # 否则 "5 10"（示例输入）这种会被误判成标题
        if (re.match(r"^\d+(\.\d+)*[\s、．.]\s*[\u4e00-\u9fff]", stripped)
                and len(stripped) < 40):
            emit_text(f"**{stripped}**")
        elif re.match(r"^[①②③④⑤⑥⑦⑧⑨⑩]", stripped):
            emit_text(f"- {stripped}")
        else:
            emit_text(stripped)

    flush_code()
    while out and out[-1] == "":
        out.pop()
    return "\n".join(out) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="生成内置帮助文档")
    ap.add_argument("--fetch", action="store_true", help="缓存缺失时联网抓取")
    args = ap.parse_args()

    import os
    client = None
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    index_lines = []

    for doc in DOCS:
        cache_file = CACHE_DIR / doc["cache"]
        if cache_file.exists():
            raw = cache_file.read_text(encoding="utf-8", errors="replace")
            src = f"缓存 {cache_file.name}"
        elif args.fetch:
            if client is None:
                from matu.core.client import MatuClient
                user = os.environ.get("MATU_USER", "")
                pwd = os.environ.get("MATU_PASS", "")
                client = MatuClient(min_interval=0.5, logger=print)
                if user and pwd:
                    client.login(user, pwd)
            path = doc["url"].replace("/aptat", "")
            raw = client.get(path).text
            src = f"联网 {doc['url']}"
        else:
            print(f"跳过 {doc['title']}：缓存缺失（加 --fetch 联网抓）")
            continue

        lines = to_lines(raw)
        md = to_markdown(doc["title"], doc["url"], lines)
        dest = OUT_DIR / doc["out"]
        dest.write_text(md, encoding="utf-8")
        head = md.split("\n", 3)[:3]
        print(f"  {dest.relative_to(ROOT)}  {len(lines)} 行  ({src})")
        index_lines.append({
            "id": doc["id"], "title": doc["title"], "file": doc["out"], "url": doc["url"],
            "lines": len(lines),
        })

    if index_lines:
        import json
        (OUT_DIR / "index.json").write_text(
            json.dumps({"docs": index_lines}, ensure_ascii=False, indent=2),
            encoding="utf-8")
        print(f"  {OUT_DIR.relative_to(ROOT)}/index.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
