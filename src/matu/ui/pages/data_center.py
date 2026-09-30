"""数据中心：个人信息 + 提交热力图 + 三维能力雷达 + 评级 + 提交折线图。

所有数据都来自本地库（题目中心加载下来的提交记录），不发网络请求；
只有"取姓名"会联网一次（站点把姓名放在 left.jsp 里），取到后存进库里。
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QScrollArea,
                               QSizePolicy, QVBoxLayout, QWidget)

from ...core.stats import Stats, compute_stats, daily_series, heat_cells
from ..charts import HeatStrip, LineChart, RadarChart, script_font
from ..panels import InfoRow, OverviewList, SectionTitle
from ..theme import theme
from ..widgets import Card, Divider, VectorButton, ui_font

GRADE_COLOR = {"S": "#E0A33E", "A": "#4A5FE0", "B": "#17A34A",
               "C": "#C2740B", "D": "#8B95A5"}


class NameWorker(QThread):
    """联网取一次姓名（站点的 left.jsp）。"""

    done = Signal(str)
    failed = Signal(str)

    def __init__(self, workspace) -> None:
        super().__init__()
        self._ws = workspace

    def run(self) -> None:
        from ...core import refresh as R
        try:
            name = R.fetch_profile_name(self._ws.client)
            if name:
                self._ws.store.set_meta("display_name", name)
            self.done.emit(name)
        except Exception as exc:                      # noqa: BLE001
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class DataCenterPage(QWidget):
    """数据中心页面。"""

    refresh_requested = Signal()      # 点刷新：交给主窗口去重新加载数据

    def __init__(self, workspace, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        t = theme()
        self._ws = workspace
        self._stats = Stats()
        self._worker: Optional[NameWorker] = None

        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(t.metrics.space_xl, t.metrics.space_lg,
                               t.metrics.space_xl, t.metrics.space_xl)
        lay.setSpacing(t.metrics.space_lg)

        # ---------------- 上板块 ----------------
        upper = QWidget(inner)
        ul = QHBoxLayout(upper)
        ul.setContentsMargins(0, 0, 0, 0)
        ul.setSpacing(t.metrics.space_lg)
        ul.addWidget(self._build_profile(upper), 0)
        ul.addWidget(self._build_heat(upper), 1)
        lay.addWidget(upper)

        # ---------------- 下板块 ----------------
        lower = QWidget(inner)
        ll = QVBoxLayout(lower)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(t.metrics.space_lg)
        ll.addWidget(self._build_radar(lower))
        ll.addWidget(self._build_line(lower))
        ll.addWidget(self._build_details(lower))
        lay.addWidget(lower)
        lay.addStretch(1)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(inner)

        # 底部状态条：默认首页也要看得到加载进度，否则登录后像什么都没发生
        self._status = QLabel("", self)
        self._status.setFont(ui_font(t.small_font_size))
        self._status.setContentsMargins(t.metrics.space_lg, 4, t.metrics.space_lg, 4)
        self._status.setVisible(False)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(scroll, 1)
        root.addWidget(self._status)

        self._ws.changed.connect(self.reload)
        self.reload()

    # ---------------- 上板块：个人信息 ----------------

    def _build_profile(self, parent: QWidget) -> QWidget:
        t = theme()
        pal = t.palette
        card = Card(parent)
        card.setFixedWidth(268)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(t.metrics.space_xl, t.metrics.space_xl,
                              t.metrics.space_xl, t.metrics.space_lg)
        cl.setSpacing(t.metrics.space_sm)

        who = QLabel("个人信息", card)
        who.setFont(ui_font(11, QFont.Weight.DemiBold))
        who.setStyleSheet(f"color:{pal.text_muted};")
        cl.addWidget(who)

        self._name = QLabel("—", card)
        self._name.setFont(ui_font(26, QFont.Weight.DemiBold))
        self._name.setStyleSheet(f"color:{pal.text};")
        self._name.setWordWrap(True)
        cl.addWidget(self._name)

        self._uid = QLabel("—", card)
        self._uid.setFont(ui_font(13))
        self._uid.setStyleSheet(f"color:{pal.text_dim};")
        self._uid.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        cl.addWidget(self._uid)
        cl.addSpacing(t.metrics.space_sm)

        self._rows = {}
        for key, label in (("subs", "提交总数"), ("days", "活跃天数"),
                           ("tasks", "满分题目"), ("bank", "题库总量")):
            r = InfoRow(label, "—", card)
            self._rows[key] = r
            cl.addWidget(r)

        cl.addStretch(1)
        self._name_btn = VectorButton("取姓名", "refresh", VectorButton.GHOST, card,
                                      tooltip="姓名可以从站点读到，取一次即缓存")
        self._name_btn.clicked.connect(self.fetch_name)
        cl.addWidget(self._name_btn)
        # 数据中心的数据全部来自本地库，所以这里只做一次重算，不发请求。
        # 真正把站点数据拉下来的是「加载」和「提交」，它们结束时会自动重算，
        # 这个按钮留给"我想手动再算一遍"的场合。
        self._refresh_btn = VectorButton("更新数据", "refresh", VectorButton.SUBTLE, card,
                                         tooltip="按本地已加载的数据重算一遍（不发请求），"
                                                 "所有页面一起刷新；与站点交互结束后会自动刷新")
        self._refresh_btn.clicked.connect(self.refresh_requested.emit)
        cl.addWidget(self._refresh_btn)
        return card

    # ---------------- 上板块：热力图 ----------------

    def _build_heat(self, parent: QWidget) -> QWidget:
        card = Card(parent)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(theme().metrics.space_xl, theme().metrics.space_lg,
                              theme().metrics.space_xl, theme().metrics.space_lg)
        cl.setSpacing(theme().metrics.space_sm)
        head = SectionTitle("提交热力图", "一天一格，共 53 格", card)
        cl.addWidget(head)
        self._heat = HeatStrip(card)
        cl.addWidget(self._heat)
        self._heat_hint = QLabel("", card)
        self._heat_hint.setFont(ui_font(theme().small_font_size))
        self._heat_hint.setStyleSheet(f"color:{theme().palette.text_muted};")
        cl.addWidget(self._heat_hint)
        cl.addStretch(1)
        return card

    # ---------------- 下板块：雷达 + 评级 ----------------

    def _build_radar(self, parent: QWidget) -> QWidget:
        t = theme()
        pal = t.palette
        card = Card(parent)
        hl = QHBoxLayout(card)
        hl.setContentsMargins(t.metrics.space_xl, t.metrics.space_lg,
                              t.metrics.space_xl, t.metrics.space_lg)
        hl.setSpacing(t.metrics.space_xl)

        left = QWidget(card)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(t.metrics.space_sm)
        ll.addWidget(SectionTitle("三维能力图", "三项指标均归一到 0-100", left))
        self._radar = RadarChart(left)
        ll.addWidget(self._radar, 1)
        hl.addWidget(left, 1)

        hl.addWidget(Divider(card, vertical=True))

        right = QWidget(card)
        right.setFixedWidth(240)
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(t.metrics.space_xs)
        rl.addWidget(SectionTitle("综合评级", "三项均值", right))

        self._grade = QLabel("—", right)
        self._grade.setFont(script_font(104))
        self._grade.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._grade.setFixedHeight(124)
        rl.addWidget(self._grade)

        self._mean = QLabel("—", right)
        self._mean.setFont(ui_font(15, QFont.Weight.DemiBold))
        self._mean.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._mean.setStyleSheet(f"color:{pal.text_dim};")
        rl.addWidget(self._mean)

        self._explain = QLabel("", right)
        self._explain.setFont(ui_font(t.small_font_size))
        self._explain.setStyleSheet(f"color:{pal.text_muted};")
        self._explain.setWordWrap(True)
        self._explain.setAlignment(Qt.AlignmentFlag.AlignTop)
        rl.addWidget(self._explain, 1)
        hl.addWidget(right, 0)
        return card

    # ---------------- 下板块：折线图 ----------------

    def _build_line(self, parent: QWidget) -> QWidget:
        t = theme()
        card = Card(parent)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(t.metrics.space_xl, t.metrics.space_lg,
                              t.metrics.space_xl, t.metrics.space_lg)
        cl.setSpacing(t.metrics.space_sm)
        self._line_title = SectionTitle("提交次数趋势", "最近 30 天", card)
        cl.addWidget(self._line_title)
        self._line = LineChart(card)
        cl.addWidget(self._line)
        return card

    # ---------------- 下板块：提交明细 ----------------

    def _build_details(self, parent: QWidget) -> QWidget:
        t = theme()
        card = Card(parent)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(t.metrics.space_xl, t.metrics.space_lg,
                              t.metrics.space_xl, t.metrics.space_lg)
        cl.setSpacing(t.metrics.space_sm)
        self._detail_title = SectionTitle("提交明细", "", card)
        cl.addWidget(self._detail_title)
        self._details = OverviewList(card)
        cl.addWidget(self._details)
        return card

    # ---------------- 数据 ----------------

    def _apply_colors(self) -> None:
        """按当前主题重取所有文字颜色。

        这些 QLabel 的样式是构造时设的，主题切换后不会自动跟着变 ——
        深色主题下就会留着浅色主题的深字，看起来像没上色。
        """
        t = theme()
        pal = t.palette
        self._name.setStyleSheet(f"color:{pal.text};")
        self._uid.setStyleSheet(f"color:{pal.text_dim};")
        self._heat_hint.setStyleSheet(f"color:{pal.text_muted};")
        self._mean.setStyleSheet(f"color:{pal.text_dim};")
        self._explain.setStyleSheet(f"color:{pal.text_muted};")
        self._grade.setStyleSheet(
            f"color:{GRADE_COLOR.get(self._stats.grade, pal.text)};")

    def reload(self) -> None:
        t = theme()
        st = compute_stats(self._ws.store, self._ws.username)
        self._stats = st

        name = self._ws.store.conn.execute(
            "SELECT value FROM meta WHERE key='display_name'").fetchone()
        display = (name[0] if name else "") or self._ws.username or "—"
        self._name.setText(display)
        self._uid.setText(st.username or "—")
        self._rows["subs"].set_value(str(st.total_submissions))
        self._rows["days"].set_value(str(st.active_days))
        self._rows["tasks"].set_value(str(st.tasks_with_100))
        self._rows["bank"].set_value(str(st.bank_size))
        self._name_btn.setVisible(not bool(name))

        self._heat.set_cells(heat_cells(st))
        first, last = (heat_cells(st)[0][0], heat_cells(st)[-1][1]) if st.per_day else (None, None)
        self._heat_hint.setText(
            f"共 {st.total_submissions} 次提交，分布在 {st.active_days} 个活跃日"
            + (f"　范围 {first} ~ {last}" if first else ""))

        self._radar.set_values([
            ("正确率", st.accuracy), ("考勤度", st.attendance), ("狗卷度", st.diligence)])

        self._grade.setText(st.grade)
        self._mean.setText(f"综合 {st.mean:.1f} 分")
        self._explain.setText("\n".join(f"{k}：{v}" for k, v in st.explain()))

        series = daily_series(st, days=30)
        self._line.set_series(series)
        self._line_title.set_hint(f"最近 30 天　峰值 {max((v for _d, v in series), default=0)} 次/天")

        rows: List[tuple] = []
        for s in self._ws.store.get_submissions_all(limit=200):
            rows.append(("check" if s.get("score") == 100 else "file-code",
                         s.get("name", ""),
                         (s.get("submitted_at") or "").replace(".0", ""),
                         f"{s.get('score')} 分", f"#{s['task_id']}"))
        self._details.set_rows(rows)
        self._detail_title.set_hint(f"{len(rows)} 条（最近在前）")
        self._apply_colors()
        self._heat.update()
        self._radar.update()
        self._line.update()

    def fetch_name_if_missing(self) -> None:
        """登录后若本地还没有姓名，就自动取一次（一个请求）。"""
        try:
            row = self._ws.store.conn.execute(
                "SELECT value FROM meta WHERE key='display_name'").fetchone()
            if row and row[0]:
                return
        except Exception:                      # noqa: BLE001
            return
        self.fetch_name()

    def fetch_name(self) -> None:
        if not self._ws.logged_in:
            self._name_btn.setText("未登录，取不到姓名")
            return
        if self._worker is not None and self._worker.isRunning():
            return
        self._name_btn.setEnabled(False)
        self._worker = NameWorker(self._ws)
        self._worker.done.connect(self._on_name)
        self._worker.failed.connect(lambda m: self._name_btn.setText(f"取姓名失败"))
        self._worker.start()

    def _on_name(self, name: str) -> None:
        self._name_btn.setEnabled(True)
        self._name_btn.setVisible(False)
        if name:
            self._name.setText(name)

    def set_status(self, text: str) -> None:
        """底部状态条（加载进度）。"""
        self._status.setText(text)
        self._status.setStyleSheet(f"color:{theme().palette.text_dim};")
        self._status.setVisible(bool(text))

    def apply_theme(self) -> None:
        self.reload()
