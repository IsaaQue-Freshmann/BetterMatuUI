"""代码编辑器：语法高亮 + 行号 + 当前行 + 括号匹配。

编辑器是唯一不手绘的控件 —— 文本编辑涉及光标、选区、输入法、滚动等大量细节，
用真实文本控件是唯一合理的选择；但它的**外观**（配色、行号槽、当前行、
字体）完全由主题令牌驱动，视觉上和自绘部分一致。
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import (QColor, QFont, QFontMetrics, QPainter, QSyntaxHighlighter,
                           QTextCharFormat, QTextCursor, QTextFormat)
from PySide6.QtWidgets import QPlainTextEdit, QTextEdit, QWidget

from .theme import theme
from .widgets import mono_font

KEYWORDS = [
    "alignas", "alignof", "asm", "auto", "bool", "break", "case", "catch", "char",
    "class", "const", "constexpr", "continue", "default", "delete", "do", "double",
    "else", "enum", "explicit", "extern", "false", "float", "for", "friend", "goto",
    "if", "inline", "int", "long", "mutable", "namespace", "new", "noexcept",
    "nullptr", "operator", "private", "protected", "public", "register", "return",
    "short", "signed", "sizeof", "static", "struct", "switch", "template", "this",
    "throw", "true", "try", "typedef", "typename", "union", "unsigned", "using",
    "virtual", "void", "volatile", "while", "cin", "cout", "endl", "std", "string",
]

TYPES = [
    "size_t", "FILE", "string", "vector", "map", "set", "pair", "istream",
    "ostream", "ifstream", "ofstream", "stringstream",
]

# 常见标准库函数名，高亮出来读代码更顺眼
FUNCS = [
    "printf", "scanf", "malloc", "free", "memset", "memcpy", "strlen", "strcpy",
    "strcmp", "fopen", "fclose", "fgets", "fputs", "sprintf", "sscanf", "abs",
    "sqrt", "pow", "fabs", "fmod", "ceil", "floor", "sin", "cos", "tan", "log",
    "exp", "sort", "max", "min", "swap", "push_back", "size", "length", "begin", "end",
]


class CCppHighlighter(QSyntaxHighlighter):
    """C/C++ 高亮规则。配色全部取自主题的 code_* 令牌。"""

    def __init__(self, document) -> None:
        super().__init__(document)
        self._rules: List[Tuple[re.Pattern, str]] = []
        self.rebuild()

    def rebuild(self) -> None:
        """主题切换后重建规则（颜色变了）。"""
        kw = "|".join(KEYWORDS)
        ty = "|".join(TYPES)
        fn = "|".join(FUNCS)
        self._rules = [
            (re.compile(r"//[^\n]*"), "code_comment"),
            (re.compile(r"/\*.*?\*/", re.S), "code_comment"),
            (re.compile(r"^\s*#\s*\w+", re.M), "code_preproc"),
            (re.compile(r"\b(" + kw + r")\b"), "code_keyword"),
            (re.compile(r"\b(" + ty + r")\b"), "code_type"),
            (re.compile(r"\b(" + fn + r")(?=\s*\()"), "code_func"),
            (re.compile(r'"[^"\\]*(?:\\.[^"\\]*)*"'), "code_string"),
            (re.compile(r"'[^'\\]*(?:\\.[^'\\]*)*'"), "code_string"),
            (re.compile(r"\b(0[xX][0-9a-fA-F]+|\d+\.?\d*[fFlLuU]*)\b"), "code_number"),
        ]
        self.rehighlight()

    def _fmt(self, token: str, bold: bool = False) -> QTextCharFormat:
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(getattr(theme().palette, token)))
        if bold:
            fmt.setFontWeight(QFont.Weight.DemiBold)
        return fmt

    def highlightBlock(self, text: str) -> None:  # noqa: N802
        for pattern, token in self._rules:
            fmt = self._fmt(token, bold=(token == "code_keyword"))
            for m in pattern.finditer(text):
                self.setFormat(m.start(), m.end() - m.start(), fmt)


class _LineNumberArea(QWidget):
    def __init__(self, editor: "CodeEditor") -> None:
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(self._editor.line_number_width(), 0)

    def paintEvent(self, event) -> None:  # noqa: N802
        self._editor.paint_line_numbers(event)


class CodeEditor(QPlainTextEdit):
    """带行号与主题配色的代码编辑器。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._gutter = _LineNumberArea(self)
        self._highlighter = CCppHighlighter(self.document())
        self._readonly_mode = False

        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setTabStopDistance(QFontMetrics(mono_font()).horizontalAdvance(" ") * 4)
        self.setFrameShape(QPlainTextEdit.Shape.NoFrame)

        self.blockCountChanged.connect(lambda _: self._update_gutter_width())
        self.updateRequest.connect(self._on_update_request)
        self.cursorPositionChanged.connect(self._refresh_extra_selections)

        self.apply_theme()
        self._update_gutter_width()
        self._refresh_extra_selections()

    # ---- 主题 ----
    def set_readonly_mode(self, readonly: bool) -> None:
        """只读模式（看历史提交时）：真的禁止编辑，并把底色压暗一档作为提示。"""
        self._readonly_mode = readonly
        self.setReadOnly(readonly)      # 光改样式是不够的，必须真的锁住编辑
        self.apply_theme()

    def apply_theme(self) -> None:
        pal = theme().palette
        self.setFont(mono_font())
        bg = pal.surface_alt if self._readonly_mode else pal.code_bg
        self.setStyleSheet(
            f"QPlainTextEdit{{background:{bg};color:{pal.code_text};"
            f"border:none;selection-background-color:{pal.accent_soft};"
            f"selection-color:{pal.text};}}"
        )
        self._highlighter.rebuild()
        self._gutter.update()
        self._refresh_extra_selections()

    # ---- 行号槽 ----
    def line_number_width(self) -> int:
        digits = max(3, len(str(max(1, self.blockCount()))))
        return 14 + QFontMetrics(mono_font()).horizontalAdvance("9") * digits

    def _update_gutter_width(self) -> None:
        self.setViewportMargins(self.line_number_width(), 0, 0, 0)

    def _on_update_request(self, rect: QRect, dy: int) -> None:
        if dy:
            self._gutter.scroll(0, dy)
        else:
            self._gutter.update(0, rect.y(), self._gutter.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_gutter_width()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._gutter.setGeometry(QRect(cr.left(), cr.top(),
                                       self.line_number_width(), cr.height()))

    def paint_line_numbers(self, event) -> None:
        pal = theme().palette
        p = QPainter(self._gutter)
        p.fillRect(event.rect(), QColor(pal.code_gutter))

        block = self.firstVisibleBlock()
        number = block.blockNumber() + 1
        top = self.blockBoundingGeometry(block).translated(self.contentOffset()).top()
        bottom = top + self.blockBoundingRect(block).height()
        current = self.textCursor().blockNumber() + 1
        fm = QFontMetrics(mono_font())
        width = self._gutter.width() - 8

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                is_current = number == current
                p.setPen(QColor(pal.text_dim if is_current else pal.text_muted))
                f = mono_font()
                f.setWeight(QFont.Weight.DemiBold if is_current else QFont.Weight.Normal)
                p.setFont(f)
                p.drawText(QRect(0, int(top), width, fm.height()),
                           Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                           str(number))
            block = block.next()
            top = bottom
            bottom = top + self.blockBoundingRect(block).height()
            number += 1
        p.end()

    # ---- 当前行 + 括号匹配 ----
    def _refresh_extra_selections(self) -> None:
        selections: List[QTextEdit.ExtraSelection] = []
        pal = theme().palette

        # 当前行底色
        sel = QTextEdit.ExtraSelection()
        sel.format.setBackground(QColor(pal.hover))
        sel.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
        sel.cursor = self.textCursor()
        sel.cursor.clearSelection()
        selections.append(sel)

        # 括号匹配
        match = self._match_bracket()
        if match is not None:
            fmt = QTextEdit.ExtraSelection()
            fmt.format.setBackground(QColor(pal.accent_soft))
            fmt.format.setForeground(QColor(pal.accent))
            fmt.cursor = match
            selections.append(fmt)

        self.setExtraSelections(selections)

    def _match_bracket(self) -> Optional[QTextCursor]:
        text = self.toPlainText()
        pos = self.textCursor().position()
        pairs = {"(": ")", "[": "]", "{": "}"}
        reverse = {v: k for k, v in pairs.items()}

        def scan(start: int, ch: str, forward: bool) -> Optional[int]:
            depth = 0
            step = 1 if forward else -1
            i = start
            while 0 <= i < len(text):
                if text[i] == ch:
                    depth += 1
                elif text[i] == (reverse[ch] if forward else pairs[ch]):
                    depth -= 1
                    if depth == 0:
                        return i
                i += step
            return None

        for offset in (-1, 0):
            idx = pos + offset
            if 0 <= idx < len(text):
                ch = text[idx]
                if ch in pairs:
                    found = scan(idx + 1, ch, True)
                elif ch in reverse:
                    found = scan(idx - 1, ch, False)
                else:
                    continue
                if found is None:
                    return None
                cur = QTextCursor(self.document())
                cur.setPosition(idx)
                cur.movePosition(QTextCursor.MoveOperation.NextCharacter,
                                 QTextCursor.MoveMode.KeepAnchor)
                return cur
        return None

    # ---- 编辑体验 ----
    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Tab and not event.modifiers():
            self.insertPlainText("    ")
            return
        if event.key() == Qt.Key.Key_Backtab:
            cur = self.textCursor()
            cur.movePosition(QTextCursor.MoveOperation.StartOfBlock)
            for _ in range(4):
                cur.deleteChar()
            return
        super().keyPressEvent(event)

    def text(self) -> str:
        return self.toPlainText()

    def set_text(self, text: str) -> None:
        self.setPlainText(text)
        cur = self.textCursor()
        cur.movePosition(QTextCursor.MoveOperation.Start)
        self.setTextCursor(cur)
