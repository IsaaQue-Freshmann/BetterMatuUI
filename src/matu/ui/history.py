"""代码区底部的"文件"列表 + 回溯。

一道题下面的东西分两类，混在同一个列表里：

    本地文件      新建时以时间命名，分数显示"未提交"，进去可写
    历史提交      站点上已评过分的记录，进去是只读（回溯）

数据来源（与网站 题目中心/提交总结 一致）：

    GET /aptat/assignment/listassignment?taskid=N          该题的全部提交
    GET /aptat/assignment/scoredetail?assignmentid=N       那次的扣分与原因
    GET /aptat/file/downloadassignmentfile?assignmentid=N  那次的源码（回溯）

原则：先用本地库渲染（离线可用、秒开），再按需联网补齐；
每次操作都是有限次请求，不做轮询。
"""

from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import QSize, Qt, QThread, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QHeaderView, QLabel,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from ..core import submit as S
from ..core.client import MatuClient
from .theme import theme
from .widgets import Divider, VectorButton, ui_font

COL_NAME, COL_TIME, COL_SCORE, COL_ACTION = 0, 1, 2, 3
ACTION_ROW_H = 30      # 含操作按钮的行高下限


class HistoryWorker(QThread):
    """联网拉某题的提交列表，并补齐缺失的扣分原因。"""

    done = Signal(int, int, int)      # task_id, 记录数, 补齐的原因数
    failed = Signal(str)
    progress = Signal(str)

    def __init__(self, workspace, task_id: int) -> None:
        super().__init__()
        self._ws = workspace
        self._task_id = task_id

    def run(self) -> None:
        try:
            client, store = self._ws.client, self._ws.store
            subs, html = S.fetch_task_submissions(client, self._task_id)
            if MatuClient.looks_like_login_page(html):
                # 会话失效：站点把列表页退回了登录页。自动重登后重试一次
                self.progress.emit("登录已失效，正在重新登录…")
                if not self._ws.ensure_session():
                    self.failed.emit("登录已失效且无法自动重登，请到「个人中心」重新登录。")
                    return
                subs, html = S.fetch_task_submissions(client, self._task_id)
                if MatuClient.looks_like_login_page(html):
                    self.failed.emit("重新登录后仍未取到提交记录，请稍后再试。")
                    return
            store.save_submissions(subs)
            filled = 0
            for s in subs:
                row = store.get_submission(s.assignment_id) or {}
                if (row.get("detail_text") or "").strip():
                    continue
                self.progress.emit(f"拉取成绩详单 {s.assignment_id}…")
                store.save_submission_detail(
                    s.assignment_id,
                    S.fetch_score_detail(client, s.assignment_id))
                filled += 1
            self.done.emit(self._task_id, len(subs), filled)
        except Exception as exc:                      # noqa: BLE001
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class CodeWorker(QThread):
    """回溯：取回某次提交的源码。"""

    done = Signal(int, int, str, str)     # task_id, assignment_id, code, filename
    failed = Signal(str)

    def __init__(self, workspace, task_id: int, assignment_id: int) -> None:
        super().__init__()
        self._ws = workspace
        self._task_id = task_id
        self._assignment_id = assignment_id

    def run(self) -> None:
        try:
            code, filename = S.fetch_submitted_code(self._ws.client, self._assignment_id)
            if MatuClient.looks_like_login_page(code):
                # 取回的是登录页而不是源码 —— 会话掉了。自动重登后重试一次，
                # 否则会把一段 HTML 当成"源码"打开（这正是之前报的那个错）
                if not self._ws.ensure_session():
                    self.failed.emit("登录已失效且无法自动重登，"
                                     "请到「个人中心」重新登录后再回溯。")
                    return
                code, filename = S.fetch_submitted_code(self._ws.client,
                                                        self._assignment_id)
                if MatuClient.looks_like_login_page(code):
                    self.failed.emit("重新登录后仍未取到源码，请稍后再试。")
                    return
            self._ws.store.save_submission_code(self._assignment_id, code)
            self.done.emit(self._task_id, self._assignment_id, code, filename)
        except Exception as exc:                      # noqa: BLE001
            self.failed.emit(f"{type(exc).__name__}: {exc}")


def _action_button(wrap: QWidget, text: str, icon: str, slot,
                   tooltip: str = "") -> VectorButton:
    """列表行里的操作按钮。

    行高只有 30 出头，用默认 32px 高的按钮会被格子裁掉下沿（矩形看起来是坏的），
    所以这里统一用更矮的尺寸。
    """
    btn = VectorButton(text, icon, VectorButton.GHOST, wrap, height=23,
                       tooltip=tooltip)
    btn.clicked.connect(slot)
    return btn


class FileListPanel(QWidget):
    """文件列表：本地文件在前，历史提交在后。"""

    draft_opened = Signal(int)                # draft_id
    submission_opened = Signal(int, str)      # assignment_id, code
    new_file_requested = Signal()
    history_updated = Signal(int)             # task_id：提交记录刚被站点数据刷新过
    status = Signal(str)

    def __init__(self, workspace, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        t = theme()
        self._ws = workspace
        self._node = None
        # 历史列表与源码取回各占一个槽位：两者互不依赖。
        # 共用一个槽位时，打开题目触发的后台校准会把紧接着的回溯挡掉
        self._history_worker: Optional[object] = None
        self._code_worker: Optional[object] = None
        self._active = ("", 0)               # ("draft"|"submission", id)

        self._title = QLabel("文件", self)
        self._title.setFont(ui_font(13, QFont.Weight.DemiBold))
        self._hint = QLabel("", self)
        self._hint.setFont(ui_font(t.small_font_size))

        self._new = VectorButton("新建文件", "file-code", VectorButton.GHOST, self)
        self._new.clicked.connect(self.new_file_requested.emit)
        self._refresh = VectorButton("刷新历史", "refresh", VectorButton.GHOST, self,
                                     tooltip="从站点拉取这道题的提交记录与扣分原因")
        self._refresh.clicked.connect(self.refresh_from_site)

        bar = QWidget(self)
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(t.metrics.space_lg, 0, t.metrics.space_lg, 0)
        bl.setSpacing(t.metrics.space_sm)
        bl.addWidget(self._title)
        bl.addWidget(self._hint)
        bl.addStretch(1)
        bl.addWidget(self._new)
        bl.addWidget(self._refresh)

        self.tree = QTreeWidget(self)
        self.tree.setColumnCount(4)
        self.tree.setHeaderLabels(["文件", "时间", "分数", "操作"])
        self.tree.setRootIsDecorated(True)
        self.tree.setIndentation(14)
        self.tree.setUniformRowHeights(False)
        self.tree.setFrameShape(QTreeWidget.Shape.NoFrame)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.itemClicked.connect(self._on_item_clicked)
        self.tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        head = self.tree.header()
        # 必须关掉"最后一列自动撑满"（Qt 默认开着）：否则操作列会吃掉几百像素，
        # 文件名列被挤成一条缝，按钮也被塞进过窄的格子里画坏
        head.setStretchLastSection(False)
        head.setSectionResizeMode(COL_NAME, QHeaderView.ResizeMode.Stretch)
        for col, width in ((COL_TIME, 152), (COL_SCORE, 74), (COL_ACTION, 92)):
            head.setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)
            self.tree.setColumnWidth(col, width)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        lay.addWidget(bar)
        lay.addWidget(Divider(self))
        lay.addWidget(self.tree, 1)

        self._status = QLabel("", self)
        self._status.setFont(ui_font(t.small_font_size))
        self._status.setWordWrap(True)
        lay.addWidget(self._status)
        self.status.connect(self._status.setText)
        self.apply_theme()

    def apply_theme(self) -> None:
        """主题切换后重新取色。表头必须显式给底色，否则深色下会是白的。"""
        t = theme()
        pal = t.palette
        self.tree.setStyleSheet(
            f"QTreeWidget{{background:transparent;color:{pal.text};outline:none;}}"
            f"QTreeWidget::item{{padding:3px 0;}}"
            f"QTreeWidget::item:selected{{background:{pal.accent_soft};color:{pal.accent};}}"
            f"QHeaderView{{background:{pal.surface};border:none;}}"
            f"QHeaderView::section{{background:{pal.surface};color:{pal.text_muted};"
            f"border:none;border-bottom:1px solid {pal.border};padding:4px 6px;}}"
        )
        self._status.setStyleSheet(
            f"color:{pal.text_dim};padding:0 {t.metrics.space_lg}px 4px;")
        self._hint.setStyleSheet(f"color:{pal.text_muted};")

    # ---------------- 数据 ----------------

    def set_task(self, node, store=None) -> None:
        """切到某道题：先用缓存渲染，再由"点什么爬什么"策略联网校准。

        缓存**只用于离线查看**：已登录时，每打开一道题就把它的提交记录
        重新拉一遍，用站点数据覆盖本地 —— 站点上有新提交或旧记录有变时，
        本地不会停留在过期状态。
        """
        task_id = getattr(node, "task_id", 0) if node else 0
        changed = task_id != self.task_id()
        self._node = node
        self._active = ("", 0)
        self._reload_rows()
        if changed and task_id and self._ws.logged_in:
            self._quiet_refresh(task_id)

    def _quiet_refresh(self, task_id: int) -> None:
        """静默拉一次该题的提交记录（不打扰用户，结果到了再刷新列表）。"""
        if self._history_worker is not None and getattr(
                self._history_worker, "isRunning", lambda: False)():
            return
        self._history_worker = HistoryWorker(self._ws, task_id)
        self._history_worker.progress.connect(self.status.emit)
        self._history_worker.done.connect(self._on_history_done)
        self._history_worker.failed.connect(self._on_failed)
        self._history_worker.start()

    def task_id(self) -> int:
        return getattr(self._node, "task_id", 0) if self._node else 0

    def set_active(self, kind: str, ident: int) -> None:
        self._active = (kind, ident)
        self._reload_rows()

    def _reload_rows(self) -> None:
        self.tree.clear()
        task_id = self.task_id()
        if not task_id:
            self._hint.setText("")
            return

        drafts = self._ws.store.get_drafts(task_id)
        subs = self._ws.store.get_submissions(task_id, limit=100)
        hint = f"{len(drafts)} 个本地文件 · {len(subs)} 条历史提交"
        if subs:                              # 让"双击可回溯"这件事看得见
            hint += "　双击历史提交可直接回溯"
        self._hint.setText(hint)

        for d in drafts:                      # 本地文件排在最上面
            self._add_draft_row(d)
        for s in subs:
            self._add_submission_row(s)

    def _add_draft_row(self, draft: dict) -> None:
        pal = theme().palette
        item = QTreeWidgetItem([
            draft.get("name", "新文件"),
            (draft.get("updated_at") or draft.get("created_at") or ""),
            "未提交",
            "",
        ])
        item.setData(COL_NAME, Qt.ItemDataRole.UserRole, ("draft", int(draft["draft_id"])))
        item.setForeground(COL_SCORE, QColor(pal.text_muted))
        if (self._active == ("draft", int(draft["draft_id"]))):
            font = item.font(COL_NAME)
            font.setBold(True)
            item.setFont(COL_NAME, font)
            item.setForeground(COL_NAME, QColor(pal.accent))
        self.tree.addTopLevelItem(item)

        wrap = QWidget(self.tree)
        wl = QHBoxLayout(wrap)
        wl.setContentsMargins(0, 0, 4, 0)
        wl.setSpacing(4)
        wl.addStretch(1)
        wl.addWidget(_action_button(
            wrap, "打开", "file-code",
            lambda _=False, i=int(draft["draft_id"]): self.draft_opened.emit(i)))
        self.tree.setItemWidget(item, COL_ACTION, wrap)
        # 行高由文本尺寸决定、不理会格子里的控件，所以要显式要够高度，
        # 否则按钮的下沿会被裁掉（矩形看起来是坏的）
        item.setSizeHint(COL_ACTION, QSize(0, ACTION_ROW_H))

    def _add_submission_row(self, sub: dict) -> None:
        pal = theme().palette
        aid = int(sub.get("assignment_id") or 0)
        score = sub.get("score")
        item = QTreeWidgetItem([
            "历史提交",
            (sub.get("submitted_at") or "").replace(".0", ""),
            f"{score} 分" if score is not None else "—",
            "",
        ])
        item.setData(COL_NAME, Qt.ItemDataRole.UserRole, ("submission", aid))
        item.setForeground(COL_SCORE, QColor(pal.success if score == 100 else pal.danger))
        if self._active == ("submission", aid):
            font = item.font(COL_NAME)
            font.setBold(True)
            item.setFont(COL_NAME, font)
            item.setForeground(COL_NAME, QColor(pal.accent))
        self.tree.addTopLevelItem(item)

        # 展开行：扣分原因
        reason = (sub.get("detail_text") or "").strip()
        if not reason:
            reason = ("满分，站点未记录扣分项。" if score == 100
                      else "本地还没有这条的扣分原因，点「刷新历史」从站点拉取。")
        child = QTreeWidgetItem([reason])
        child.setFirstColumnSpanned(True)
        child.setForeground(0, QColor(pal.text_muted))
        item.addChild(child)
        item.setExpanded(False)

        wrap = QWidget(self.tree)
        wl = QHBoxLayout(wrap)
        wl.setContentsMargins(0, 0, 4, 0)
        wl.setSpacing(4)
        wl.addStretch(1)
        cached = bool((sub.get("code_text") or "").strip())
        hint = "这份源码已缓存，点开即用" if cached else "从站点取回这次提交的源码"
        wl.addWidget(_action_button(wrap, "回溯",
                                    "check" if cached else "download",
                                    lambda _=False, a=aid: self.open_submission(a),
                                    tooltip=hint))
        self.tree.setItemWidget(item, COL_ACTION, wrap)
        item.setSizeHint(COL_ACTION, QSize(0, ACTION_ROW_H))

    def _on_item_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        payload = item.data(COL_NAME, Qt.ItemDataRole.UserRole)
        if not payload:
            return
        kind, ident = payload
        if kind == "draft":
            self.draft_opened.emit(int(ident))

    def _on_item_double_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        """双击历史提交 = 直接回溯（取回并缓存源码）并以只读方式打开。

        本地文件双击等同于"打开"，但如果它已经是当前文件就不重复加载
        （单击已经打开过，双击会再触发一次，白白丢一次保存）。
        """
        payload = item.data(COL_NAME, Qt.ItemDataRole.UserRole)
        if not payload:
            return
        kind, ident = payload
        if kind == "submission":
            self.open_submission(int(ident))
        elif kind == "draft" and self._active != ("draft", int(ident)):
            self.draft_opened.emit(int(ident))

    # ---------------- 联网 ----------------

    def refresh_from_site(self) -> None:
        task_id = self.task_id()
        if not task_id:
            return
        if not self._ws.logged_in:
            self.status.emit("未登录，无法从站点拉取历史。请先到「个人中心」登录。")
            return
        if self._history_worker is not None and getattr(
                self._history_worker, "isRunning", lambda: False)():
            return
        self._refresh.setEnabled(False)
        self.status.emit("正在拉取历史提交…")
        self._history_worker = HistoryWorker(self._ws, task_id)
        self._history_worker.progress.connect(self.status.emit)
        self._history_worker.done.connect(self._on_history_done)
        self._history_worker.failed.connect(self._on_failed)
        self._history_worker.start()

    def _on_history_done(self, task_id: int, total: int, filled: int) -> None:
        self._refresh.setEnabled(True)
        if task_id == self.task_id():
            self._reload_rows()
        self.status.emit(f"历史提交已更新：{total} 条，补到扣分原因 {filled} 条。")
        self.history_updated.emit(task_id)

    def _on_failed(self, message: str) -> None:
        self._refresh.setEnabled(True)
        self.status.emit(f"拉取失败：{message}")

    def open_submission(self, assignment_id: int) -> None:
        """打开一次历史提交的源码。

        缓存策略：**已登录时一律重新从站点取**，取到什么就覆盖缓存什么；
        缓存只在未登录（离线）时用来查看。之前一直拿本地缓存当真相，
        所以站点上的实际源码与缓存不一致时，看到的永远是旧的那份。
        """
        task_id = self.task_id()
        if not task_id or not assignment_id:
            return
        cached = (self._ws.store.get_submission(assignment_id) or {}).get("code_text") or ""
        usable_cache = bool(cached.strip()) and not MatuClient.looks_like_login_page(cached)

        if not self._ws.logged_in:
            # 离线：只能用缓存
            if usable_cache:
                self.status.emit(f"离线：显示本地缓存的 #{assignment_id}（只读）。")
                self.submission_opened.emit(assignment_id, cached)
            else:
                self.status.emit("未登录且本地没有这份源码的缓存，无法查看。"
                                 "请到「个人中心」登录后重试。")
            return

        if self._code_worker is not None and getattr(
                self._code_worker, "isRunning", lambda: False)():
            return
        self.status.emit(f"正在从站点重新取回 #{assignment_id} 的源码…")
        self._code_worker = CodeWorker(self._ws, task_id, assignment_id)
        self._code_worker.done.connect(self._on_code_done)
        self._code_worker.failed.connect(self._on_failed)
        self._code_worker.start()

    def _on_code_done(self, task_id: int, assignment_id: int,
                      code: str, filename: str) -> None:
        self.status.emit(f"已从站点取回 #{assignment_id} 的源码（{filename}）并覆盖本地缓存。")
        self.submission_opened.emit(assignment_id, code)
        if task_id == self.task_id():
            self._reload_rows()
