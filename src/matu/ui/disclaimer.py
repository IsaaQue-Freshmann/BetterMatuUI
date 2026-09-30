"""启动声明窗口。

每次打开软件都会弹出，用户必须明确选择「确认」或「退出」：
确认才继续启动，退出（包括按 Esc 或关掉窗口）直接结束程序。

文案逐字按需求给定，其中一句需要用红色强调 —— 需求里说明中括号本身不显示，
只把括号里的文字染红，所以这里用富文本着色而不是加括号。
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QScrollArea,
                               QVBoxLayout, QWidget)

from .theme import theme
from .widgets import Card, Divider, VectorButton, ui_font

WARNING_TEXT = "若因各种问题导致代码在该软件中保存失败，我们将很遗憾地告知您我们对此无能为力。"

PARAGRAPHS = [
    "BetterMatuUI 的代码编辑窗口应用作阅览代码和在您本地编辑完成代码之后粘贴的窗口。"
    "您编写的代码请务必在本地留好备份！切忌直接在代码编辑区直接书写您的代码。",
    None,      # 这一条是警告，单独渲染成红色
    "若您发现软件有任何奇怪的地方，请点击刷新按钮。若仍未恢复正常请您退出登录、"
    "删除缓存、退出程序再进入。通常问题会自行解决。如果问题仍存在，"
    "我们可以向您保证的是我们会持续维护，也欢迎提交 issue 并等待版本更新。",
    "若已了解请点击「确认」，否则请点击「退出」。",
]


class DisclaimerDialog(QDialog):
    """必须做出选择的启动声明。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        t = theme()
        pal = t.palette
        self.setWindowTitle("声明")
        self.setModal(True)
        self.setMinimumSize(620, 460)
        # 只留标题栏的关闭按钮也能被 Esc / 关闭动作触发 reject，一并当作「退出」
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)

        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(t.metrics.space_xl, t.metrics.space_lg,
                               t.metrics.space_xl, t.metrics.space_lg)
        lay.setSpacing(t.metrics.space_md)

        title = QLabel("使用前请阅读", inner)
        title.setFont(ui_font(20, QFont.Weight.DemiBold))
        title.setStyleSheet(f"color:{pal.text};")
        lay.addWidget(title)

        for para in PARAGRAPHS:
            label = QLabel(inner)
            label.setWordWrap(True)
            label.setTextFormat(Qt.TextFormat.RichText)
            label.setFont(ui_font(13))
            if para is None:
                label.setText(f'<span style="color:{pal.danger};'
                              f'font-weight:600;">{WARNING_TEXT}</span>')
            else:
                label.setText(f'<span style="color:{pal.text_dim};">{para}</span>')
            lay.addWidget(label)

        lay.addStretch(1)

        buttons = QWidget(inner)
        bl = QHBoxLayout(buttons)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(t.metrics.space_sm)
        bl.addStretch(1)
        quit_btn = VectorButton("退出", "x", VectorButton.GHOST, buttons, min_width=96)
        ok_btn = VectorButton("确认", "check", VectorButton.PRIMARY, buttons, min_width=110)
        quit_btn.clicked.connect(self.reject)
        ok_btn.clicked.connect(self.accept)
        bl.addWidget(quit_btn)
        bl.addWidget(ok_btn)
        lay.addWidget(buttons)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(inner)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(scroll)
        self.setStyleSheet(f"QDialog{{background:{pal.bg};}}")


def ask_for_consent(parent: Optional[QWidget] = None) -> bool:
    """弹出声明；返回 True 表示用户点了「确认」，可以继续启动。"""
    dlg = DisclaimerDialog(parent)
    return dlg.exec() == QDialog.DialogCode.Accepted
