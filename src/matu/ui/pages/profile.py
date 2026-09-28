"""个人中心页：账号与登录 + 我的数据 + 设置区块。

设置不是独立窗口，而是和账号信息**同层的一个区块，排在下面**，
通过「跳到设置」按钮或 ⌘, 直接滚到该位置。
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QLineEdit, QScrollArea,
                               QVBoxLayout, QWidget)

from ..panels import InfoRow, SectionTitle
from ..settings_sections import SettingsSections
from ..theme import theme
from ..widgets import Card, Divider, VectorButton, ui_font


def _input_qss() -> str:
    pal = theme().palette
    return (
        f"QLineEdit{{background:{pal.surface_alt};color:{pal.text};"
        f"border:1px solid {pal.border};border-radius:8px;padding:8px 10px;}}"
        f"QLineEdit:focus{{border:1px solid {pal.accent};background:{pal.surface};}}"
    )


class ProfilePage(QWidget):
    login_requested = Signal(str, str)
    logout_requested = Signal()
    theme_changed = Signal()
    data_changed = Signal()
    account_switched = Signal()

    def __init__(self, workspace, config, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._ws = workspace
        self._config = config

        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(32, 28, 32, 32)
        lay.setSpacing(10)

        title = QLabel("个人中心", inner)
        title.setFont(ui_font(22, QFont.Weight.DemiBold))
        lay.addWidget(title)
        lay.addSpacing(6)

        # ---- 账号 ----
        self._account_card = Card(inner)
        al = QVBoxLayout(self._account_card)
        al.setContentsMargins(20, 16, 20, 16)
        al.setSpacing(10)

        self._who = QLabel("", self._account_card)
        self._who.setFont(ui_font(15, QFont.Weight.DemiBold))
        al.addWidget(self._who)

        self._state = QLabel("", self._account_card)
        self._state.setFont(ui_font())
        self._state.setWordWrap(True)
        al.addWidget(self._state)

        self._form = QWidget(self._account_card)
        fl = QVBoxLayout(self._form)
        fl.setContentsMargins(0, 4, 0, 0)
        fl.setSpacing(8)
        self._user = QLineEdit(self._form)
        self._user.setPlaceholderText("学号 / 用户名")
        self._pwd = QLineEdit(self._form)
        self._pwd.setPlaceholderText("密码")
        self._pwd.setEchoMode(QLineEdit.EchoMode.Password)
        self._pwd.returnPressed.connect(self._emit_login)
        fl.addWidget(self._user)
        fl.addWidget(self._pwd)
        row = QWidget(self._form)
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addStretch(1)
        self._login_btn = VectorButton("登录", "check", VectorButton.PRIMARY, row, min_width=96)
        self._login_btn.clicked.connect(self._emit_login)
        rl.addWidget(self._login_btn)
        fl.addWidget(row)
        self._form.setStyleSheet(_input_qss())
        al.addWidget(self._form)

        self._actions = QWidget(self._account_card)
        gl = QHBoxLayout(self._actions)
        gl.setContentsMargins(0, 0, 0, 0)
        gl.setSpacing(8)
        gl.addStretch(1)
        self._jump_btn = VectorButton("跳到设置", "settings", VectorButton.SUBTLE,
                                      self._actions)
        self._jump_btn.clicked.connect(self.scroll_to_settings)
        self._logout_btn = VectorButton("退出登录", "logout", VectorButton.GHOST,
                                        self._actions)
        self._logout_btn.clicked.connect(self.logout_requested.emit)
        gl.addWidget(self._jump_btn)
        gl.addWidget(self._logout_btn)
        al.addWidget(self._actions)
        lay.addWidget(self._account_card)

        note = QLabel("密码只用于本次登录，不会写入磁盘；程序只保存站点会话 Cookie。"
                      "要彻底退出，点「退出登录」即可清除本地会话。", inner)
        note.setWordWrap(True)
        note.setFont(ui_font(11))
        lay.addWidget(note)

        # ---- 我的数据 ----
        lay.addWidget(SectionTitle("我的数据", "取自本地库，不联网", inner))
        data_card = Card(inner)
        dl = QVBoxLayout(data_card)
        dl.setContentsMargins(20, 12, 20, 12)
        dl.setSpacing(0)
        self._rows = {}
        for key, label in [("subs", "提交记录"), ("tasks", "尝试过的题目"),
                           ("full", "满分次数"), ("hw", "作业内题目"),
                           ("bank", "本地题库")]:
            r = InfoRow(label, "—", data_card)
            self._rows[key] = r
            dl.addWidget(r)
        lay.addWidget(data_card)

        # ---- 设置（同一层界面，排在个人中心内容下面）----
        lay.addSpacing(10)
        head = QLabel("设置", inner)
        head.setFont(ui_font(18, QFont.Weight.DemiBold))
        lay.addWidget(head)
        self._sections = SettingsSections(config, workspace, inner)
        self._sections.theme_changed.connect(self.theme_changed.emit)
        self._sections.data_changed.connect(self.data_changed.emit)
        self._sections.account_switched.connect(self.account_switched.emit)
        lay.addWidget(self._sections)

        lay.addStretch(1)

        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._scroll.setWidget(inner)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self._scroll)

        self.refresh_state()
        self.refresh_stats()
        self._ws.changed.connect(self._on_workspace_changed)

    # 账号切换后这两个必须跟着换，所以做成属性而不是构造时的快照
    @property
    def _store(self):
        return self._ws.store

    @property
    def _session(self):
        return self._ws

    def _on_workspace_changed(self) -> None:
        self.refresh_state()
        self.refresh_stats()

    # ---- 状态刷新 ----
    def refresh_state(self) -> None:
        logged = self._session.logged_in
        # 用保存的会话 Cookie 复用时是知道"已登录"但不知道用户名的，
        # 这时候不能显示成"未登录" —— 那会和下面那句状态自相矛盾
        display = self._display_name()
        if logged:
            self._who.setText(display or self._session.username
                              or "已登录（会话已保存）")
        else:
            self._who.setText("未登录")
        self._state.setText(
            "已登录，可以提交代码。" if logged else
            "未登录。浏览本地题库不需要登录；要提交代码请在这里登录。")
        self._form.setVisible(not logged)
        self._actions.setVisible(logged)

    def _display_name(self) -> str:
        """站点上爬到的姓名（存在本地库里；没取过就为空）。"""
        try:
            row = self._store.conn.execute(
                "SELECT value FROM meta WHERE key='display_name'").fetchone()
            return (row[0] if row else "") or ""
        except Exception:                      # noqa: BLE001
            return ""

    def refresh_stats(self) -> None:
        try:
            stats = self._store.stats()
            full = self._store.conn.execute(
                "SELECT COUNT(*) FROM submissions WHERE score=100").fetchone()[0]
            tried = self._store.conn.execute(
                "SELECT COUNT(DISTINCT task_id) FROM submissions").fetchone()[0]
            self._rows["subs"].set_value(str(stats.get("提交记录数", 0)))
            self._rows["tasks"].set_value(str(tried))
            self._rows["full"].set_value(str(full))
            self._rows["hw"].set_value(str(stats.get("作业内题目数", 0)))
            self._rows["bank"].set_value(f"{stats.get('题目总数', 0)} 道")
            if hasattr(self, "_sections"):
                self._sections.refresh_stats()
        except Exception:                       # 数据库异常不该让界面崩
            pass

    def apply_theme(self) -> None:
        self._form.setStyleSheet(_input_qss())

    # ---- 交互 ----
    def scroll_to_settings(self) -> None:
        """滚到页面里的设置区块（不再弹独立窗口）。"""
        target = self._sections.y()
        self._scroll.verticalScrollBar().setValue(max(0, target - 12))

    def _emit_login(self) -> None:
        user = self._user.text().strip()
        pwd = self._pwd.text()
        if not user or not pwd:
            self._state.setText("请填写账号和密码。")
            return
        self._login_btn.setEnabled(False)
        self._state.setText("正在登录…")
        self.login_requested.emit(user, pwd)

    def login_failed(self, message: str) -> None:
        self._login_btn.setEnabled(True)
        self._state.setText(f"登录失败：{message}")
        self.refresh_state()

    def login_succeeded(self) -> None:
        self._login_btn.setEnabled(True)
        self._pwd.clear()
        self.refresh_state()
        self.refresh_stats()
