"""系统帮助页：左目录 + 右内容，沿用「我的班级」那套结构。

两份文档（学生手册、学生提交注意事项）是**站点的静态内容，对所有账号一样**，
所以直接内置在项目里（`src/matu/resources/help/`），
既不占账号缓存，也不需要每个账号各爬一遍。

内容更新时用 `tools/build_help_docs.py` 重新生成。
"""

from __future__ import annotations

import html as htmllib
import json
import re
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QTextBrowser, QVBoxLayout,
                               QWidget)

from ..class_tree import Node
from ..panels import Badge, Divider
from ..theme import theme
from ..widgets import GripSplitter, ui_font
from .my_class import BrowserPanel

HELP_DIR = Path(__file__).resolve().parents[2] / "resources" / "help"


def _inline(text: str) -> str:
    """行内标记：**粗体** 与 `代码`。先转义再做标记，避免注入。"""
    text = htmllib.escape(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"`(.+?)`", r"<code>\1</code>", text)
    return text


def md_to_html(text: str) -> str:
    """把内置文档用的那套 Markdown 子集转成 HTML。

    为什么不直接用 QTextBrowser.setMarkdown：Qt 的 Markdown 导入器会直接
    构造 QTextDocument，**不走 CSS**，代码块加不了底色和等宽字体。
    先转成 HTML 再 setHtml，样式就完全受控。
    支持子集：H1/H2、粗体、行内代码、围栏代码块、无序列表、引用。
    """
    out: List[str] = []
    para: List[str] = []
    in_code = False
    in_list = False

    def flush_para() -> None:
        if para:
            out.append("<p>" + " ".join(para) + "</p>")
            para.clear()

    def close_list() -> None:
        nonlocal in_list
        if in_list:
            out.append("</ul>")
            in_list = False

    for raw in text.split("\n"):
        line = raw.rstrip()
        if line.startswith("```"):
            flush_para()
            close_list()
            out.append("</pre>" if in_code else "<pre>")
            in_code = not in_code
            continue
        if in_code:
            out.append(htmllib.escape(line) or "&nbsp;")
            continue
        stripped = line.strip()
        if not stripped:
            flush_para()
            close_list()
            continue
        if stripped.startswith("## "):
            flush_para()
            close_list()
            out.append(f"<h2>{_inline(stripped[3:])}</h2>")
            continue
        if stripped.startswith("# "):
            flush_para()
            close_list()
            out.append(f"<h1>{_inline(stripped[2:])}</h1>")
            continue
        if stripped.startswith("> "):
            flush_para()
            close_list()
            out.append(f"<blockquote>{_inline(stripped[2:])}</blockquote>")
            continue
        if stripped.startswith("- "):
            flush_para()
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{_inline(stripped[2:])}</li>")
            continue
        para.append(_inline(stripped))

    flush_para()
    close_list()
    if in_code:
        out.append("</pre>")
    return "\n".join(out)


def load_index() -> List[dict]:
    """读内置文档清单。缺文件时返回空列表，界面照常能开。"""
    index = HELP_DIR / "index.json"
    if not index.exists():
        return []
    try:
        data = json.loads(index.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    docs = []
    for item in data.get("docs", []):
        path = HELP_DIR / item.get("file", "")
        if path.exists():
            item["path"] = path
            docs.append(item)
    return docs


class MarkdownView(QTextBrowser):
    """文档阅读区。自己把 Markdown 转 HTML 再渲染，配色跟随主题。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setOpenExternalLinks(True)
        self.setFrameShape(QTextBrowser.Shape.NoFrame)
        self._current = ""
        self.apply_theme()

    def _css(self) -> str:
        t = theme()
        pal = t.palette
        mono = t.font_families()["mono"].split(",")[0].strip().strip("'\"")
        return f"""
            body {{ color: {pal.text}; font-size: {t.ui_font_size}px; }}
            h1 {{ font-size: {t.ui_font_size + 7}px; font-weight: 600; }}
            h2 {{ font-size: {t.ui_font_size + 2}px; font-weight: 600; }}
            pre {{
                font-family: "{mono}", Menlo, Consolas, monospace;
                font-size: {t.mono_font_size - 1}px;
                background-color: {pal.surface_alt};
                color: {pal.code_text};
                padding: 10px 12px;
                white-space: pre-wrap;
            }}
            code {{
                font-family: "{mono}", Menlo, Consolas, monospace;
                color: {pal.code_func};
            }}
            blockquote {{ color: {pal.text_muted}; }}
            a {{ color: {pal.accent}; }}
        """

    def apply_theme(self) -> None:
        self.setStyleSheet("QTextBrowser{background:transparent;border:none;}")
        if self._current:
            self._render()

    def _render(self) -> None:
        self.setHtml(
            f"<html><head><style>{self._css()}</style></head><body>"
            f"{md_to_html(self._current)}</body></html>")

    def show_document(self, markdown_text: str) -> None:
        # 正文里的一级标题去掉：工具栏已经显示标题，不必重复
        self._current = re.sub(r"\A#\s+.*\n+", "", markdown_text, count=1)
        self._render()
        self.verticalScrollBar().setValue(0)


class HelpPage(QWidget):
    """系统帮助：左目录管理，右具体内容。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        t = theme()
        pal = t.palette
        self._docs = load_index()

        self._browser = BrowserPanel(self, show_refresh=False)

        # ---- 右侧：标题行 + 文档 ----
        self._title = QLabel("系统帮助", self)
        self._title.setFont(ui_font(14, QFont.Weight.DemiBold))
        self._title.setStyleSheet(f"color:{pal.text};")

        self._builtin = Badge("内置内容", "accent", self)
        self._source = QLabel("", self)
        self._source.setFont(ui_font(t.small_font_size))
        self._source.setStyleSheet(f"color:{pal.text_muted};")

        bar = QWidget(self)
        bar.setFixedHeight(t.metrics.toolbar_h)
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(t.metrics.space_lg, 0, t.metrics.space_lg, 0)
        bl.setSpacing(t.metrics.space_sm)
        bl.addWidget(self._title)
        bl.addWidget(self._builtin)
        bl.addStretch(1)
        bl.addWidget(self._source)

        self._view = MarkdownView(self)
        body = QWidget(self)
        bwl = QVBoxLayout(body)
        bwl.setContentsMargins(t.metrics.space_lg, 0, t.metrics.space_lg,
                               t.metrics.space_lg)
        bwl.addWidget(self._view)

        right = QWidget(self)
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)
        rl.addWidget(bar)
        rl.addWidget(Divider(self))
        rl.addWidget(body, 1)

        split = GripSplitter(Qt.Orientation.Horizontal, self)
        split.setChildrenCollapsible(False)
        split.setHandleWidth(9)
        split.addWidget(self._browser)
        split.addWidget(right)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([280, 970])

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(split)

        self._browser.node_selected.connect(self._on_selected)
        self._browser.node_activated.connect(lambda _n: None)
        self._browser.load(self._build_tree())

    # ---- 目录树 ----
    def _build_tree(self) -> Node:
        root = Node(kind="root", label="系统帮助")
        if not self._docs:
            root.children.append(Node(
                kind="doc", label="没有内置文档",
                meta="运行 tools/build_help_docs.py 生成",
                extra={"_parents": ["系统帮助"]},
            ))
            return root
        for doc in self._docs:
            root.children.append(Node(
                kind="doc",
                label=doc.get("title", doc.get("id", "文档")),
                meta=f"{doc.get('lines', 0)} 行",
                extra={"_parents": ["系统帮助"], "url": doc.get("url", ""),
                       "file": str(doc.get("path", ""))},
            ))
        return root

    def _on_selected(self, node: Node) -> None:
        if node.kind != "doc" or not node.extra.get("file"):
            self._title.setText(node.label)
            self._builtin.setVisible(False)
            self._source.setText("")
            self._view.show_document(
                f"# {node.label}\n\n在左侧选择一份文档。\n")
            return
        path = Path(str(node.extra["file"]))
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            text = f"# 读取失败\n\n`{path}`\n\n{exc}"
        self._title.setText(node.label)
        self._builtin.setVisible(True)
        self._source.setText("")
        self._view.show_document(text)

    def apply_theme(self) -> None:
        """主题切换后重新取色：标题与来源是 QLabel，颜色构造时就写死了。"""
        pal = theme().palette
        self._title.setStyleSheet(f"color:{pal.text};")
        self._source.setStyleSheet(f"color:{pal.text_muted};")
        self._view.apply_theme()
