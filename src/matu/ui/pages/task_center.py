"""题目中心页：层级与网站一致，UI 框架与「我的班级」相同。

    题目中心
    ├── 题目总表   ← 就是题库，可展开成全部题目
    ├── 搜索作业
    ├── 作业状态
    └── 提交总结

选中题目时右区就是编辑器 + 提交 + 结果，复用与「我的班级」**同一个**
`CodeArea`，不是另写一份。

内容全部属于当前账号（题库 = 该账号可见的题），和「我的班级」共用
同一个按账号隔离的库。换账号后要重新加载，界面上的刷新按钮就是干这个的。

新账号登录后会**边加载边往目录里加**：每加载完一题，如果"题目总表"是展开的，
就把这条插进去；折叠状态下看不出区别——这正是需求里要的行为。
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QLineEdit, QScrollArea,
                               QStackedWidget, QTreeWidgetItem, QVBoxLayout,
                               QWidget)

from ..class_tree import Node, bank_task_node, build_task_center_tree
from ..panels import OverviewList, SectionTitle
from ..theme import theme
from ..widgets import Card, GripSplitter, ui_font
from .my_class import BrowserPanel, CodeArea


class BankCrawlWorker(QThread):
    """整份抓取当前账号的数据，顺序按用途排：班级 → 提交记录 → 题库。

    顺序不是随便定的：班级与作业体量小，先让「我的班级」可用；提交记录是
    数据中心三项指标的来源，必须早于题库；题库几百道题最慢，放最后。
    """

    progressed = Signal(int, int, str)
    task_added = Signal(int)
    phase_changed = Signal(str)
    done = Signal(dict)
    failed = Signal(str)

    CRAWL_INTERVAL = 0.1          # 用户指定的节奏：0.2 秒/题
    CRAWL_JITTER = 0.05
    MAX_REQUESTS = 700

    def __init__(self, workspace) -> None:
        super().__init__()
        self._ws = workspace
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        from ...core import refresh as R
        client = self._ws.client
        old = (client.min_interval, client.jitter, client.max_requests)
        client.min_interval, client.jitter = self.CRAWL_INTERVAL, self.CRAWL_JITTER
        client.max_requests = self.MAX_REQUESTS
        try:
            counts = R.refresh_all(
                client, self._ws.store,
                phase=lambda text, ratio: self.phase_changed.emit(text),
                progress=lambda d, t, s: self.progressed.emit(d, t, s),
                should_stop=lambda: self._stop,
                on_task_saved=lambda tid: self.task_added.emit(tid),
            )
            self._ws.accounts.touch_crawl(self._ws.username, self._ws.store)
            counts["stopped"] = self._stop
            self.done.emit(counts)
        except Exception as exc:                      # noqa: BLE001
            self.failed.emit(f"{type(exc).__name__}: {exc}")
        finally:
            client.min_interval, client.jitter, client.max_requests = old


class ListPanel(QWidget):
    """右区的只读列表：作业状态 / 提交总结 / 搜索结果都用它。"""

    row_activated = Signal(tuple)    # ("task", task_id) 或 ("submission", aid, task_id)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        t = theme()
        pal = t.palette

        self._title = QLabel("", self)
        self._title.setFont(ui_font(18, QFont.Weight.DemiBold))
        self._title.setStyleSheet(f"color:{pal.text};")
        self._hint = QLabel("", self)
        self._hint.setFont(ui_font())
        self._hint.setStyleSheet(f"color:{pal.text_muted};")
        self._hint.setWordWrap(True)

        self._search = QLineEdit(self)
        self._search.setPlaceholderText("输入题号或题名片段…")
        self._search.setVisible(False)
        self._search.textChanged.connect(self._on_search)
        self._rows: List[tuple] = []
        self._task_ids: List[int] = []
        self._payloads: List[tuple] = []      # 每行的点击载荷
        self._searchable = False
        self.apply_theme()

        self._list = OverviewList(self)
        self._list.row_clicked.connect(self._on_row)

        inner = QWidget()
        il = QVBoxLayout(inner)
        il.setContentsMargins(t.metrics.space_xl, t.metrics.space_xl,
                              t.metrics.space_xl, t.metrics.space_xl)
        il.setSpacing(t.metrics.space_sm)
        il.addWidget(self._title)
        il.addWidget(self._hint)
        il.addWidget(self._search)
        card = Card(inner)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(t.metrics.space_md, t.metrics.space_md,
                              t.metrics.space_md, t.metrics.space_md)
        cl.addWidget(self._list)
        il.addWidget(card)
        il.addStretch(1)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(inner)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(scroll)

        self._rows: List[tuple] = []
        self._task_ids: List[int] = []
        self._searchable = False

    def apply_theme(self) -> None:
        """主题切换后重新取色（否则深色主题下还留着浅色的输入框与文字）。"""
        pal = theme().palette
        self._search.setStyleSheet(
            f"QLineEdit{{background:{pal.surface_alt};color:{pal.text};"
            f"border:1px solid {pal.border};border-radius:8px;padding:8px 10px;}}"
            f"QLineEdit:focus{{border:1px solid {pal.accent};background:{pal.surface};}}")
        self._title.setStyleSheet(f"color:{pal.text};")
        self._hint.setStyleSheet(f"color:{pal.text_muted};")

    def show_rows(self, title: str, hint: str,
                  rows: List[tuple],
                  task_ids: List[int], searchable: bool = False,
                  payloads: Optional[List[tuple]] = None) -> None:
        self._title.setText(title)
        self._hint.setText(hint)
        self._rows, self._task_ids = rows, task_ids
        self._payloads = payloads if payloads is not None else [
            ("task", tid) for tid in task_ids]
        self._searchable = searchable
        self._search.setVisible(searchable)
        if searchable:
            self._search.clear()
        self._list.set_rows(rows)

    def _on_search(self, text: str) -> None:
        if not self._searchable:
            return
        needle = text.strip().lower()
        if not needle:
            self._list.set_rows(self._rows)
            return
        keep = [(row, tid, pay)
                for row, tid, pay in zip(self._rows, self._task_ids, self._payloads)
                if needle in row[1].lower() or needle in str(tid)]
        self._list.set_rows([r for r, _t, _p in keep])
        self._task_ids = [t for _r, t, _p in keep]
        self._payloads = [p for _r, _t, p in keep]

    def _on_row(self, index: int) -> None:
        if 0 <= index < len(self._payloads):
            self.row_activated.emit(self._payloads[index])


class TaskCenterPage(QWidget):
    """题目中心。左目录 + 右内容（编辑器或列表）。"""

    bank_crawl_state = Signal(str)      # 供外部（设置页/状态栏）显示
    data_loaded = Signal()              # 一轮加载完成：让所有页面刷新

    def __init__(self, workspace, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._ws = workspace
        self._root: Optional[Node] = None
        self._bank_worker: Optional[BankCrawlWorker] = None
        self._bank_items: Dict[int, QTreeWidgetItem] = {}

        self._browser = BrowserPanel(self)
        self._code = CodeArea(workspace, self)
        self._list = ListPanel(self)
        self._empty = QWidget(self)          # 没选东西时右区什么都不显示
        self._stack = QStackedWidget(self)
        self._stack.addWidget(self._empty)
        self._stack.addWidget(self._code)
        self._stack.addWidget(self._list)

        split = GripSplitter(Qt.Orientation.Horizontal, self)
        split.setChildrenCollapsible(False)
        split.setHandleWidth(9)
        split.addWidget(self._browser)
        split.addWidget(self._stack)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([280, 1020])

        # 加载状态条：只在有话说的时候出现
        self._status = QLabel("", self)
        self._status.setFont(ui_font(theme().small_font_size))
        self._status.setContentsMargins(theme().metrics.space_lg, 4,
                                        theme().metrics.space_lg, 4)
        self._status.setVisible(False)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(split, 1)
        lay.addWidget(self._status)

        self._browser.node_selected.connect(self._on_selected)
        self._browser.node_activated.connect(self._on_activated)
        self._browser.refresh_requested.connect(self.start_bank_crawl)
        self._code.submit_confirmed.connect(self._submit)
        self._list.row_activated.connect(self._on_list_row)
        self._ws.changed.connect(self.reload)
        self.bank_crawl_state.connect(self._set_status)

        self.reload()

    def _set_status(self, text: str) -> None:
        pal = theme().palette
        self._status.setText(text)
        self._status.setStyleSheet(f"color:{pal.text_dim};")
        self._status.setVisible(bool(text))

    # ---------------- 数据 ----------------

    def reload(self) -> None:
        self._root = build_task_center_tree(self._ws.store)
        self._browser.load(self._root)
        self._reindex()
        # 不预选任何题目：右区保持空白
        self._code.set_task(None, self._ws.store)
        self._stack.setCurrentWidget(self._empty)
        bank = self._bank_node()
        if bank is not None and not bank.children:
            # 没有题库数据时给个明确指引，而不是一片空白
            self._stack.setCurrentWidget(self._list)
            self._list.show_rows(
                "还没有题库数据", "当前账号还没有加载过题库。点目录栏上的刷新按钮"
                                   "开始加载（约 0.5 秒/题），加载到的题会边加载边出现在目录里。",
                [], [])

    def _reindex(self) -> None:
        """把树上已有的目录项记进索引，供"边加载边加"去重。

        不建这个索引的话，重新加载一个已有数据的账号时，已经挂在树上的题
        会被 _on_task_added 再插一遍 —— 目录里出现重复条目。
        """
        self._bank_items.clear()
        bank_item = self._bank_item()
        if bank_item is None:
            return
        for i in range(bank_item.childCount()):
            child = bank_item.child(i)
            node = child.data(0, Qt.ItemDataRole.UserRole)
            if node is not None and node.task_id:
                self._bank_items[node.task_id] = child

    def _bank_node(self) -> Optional[Node]:
        if self._root is None:
            return None
        for child in self._root.children:
            if child.kind == "section":
                return child
        return None

    def _bank_item(self) -> Optional[QTreeWidgetItem]:
        node = self._bank_node()
        if node is None:
            return None
        return self._browser._find_item(node)        # noqa: SLF001

    def _find_task_node(self, task_id: int) -> Optional[Node]:
        bank = self._bank_node()
        if bank is None:
            return None
        for child in bank.children:
            if child.task_id == task_id:
                return child
        return None

    def _on_list_row(self, payload: tuple) -> None:
        """列表点行：历史记录打开那一次提交，题目则进工作区。"""
        if not payload:
            return
        if payload[0] == "submission" and len(payload) >= 3:
            self.open_submission_record(int(payload[1]), int(payload[2]))
        else:
            self.open_task(int(payload[1]))

    def open_submission_record(self, assignment_id: int, task_id: int) -> None:
        """从「作业状态」进入：直接打开对应的那条历史记录（只读）。"""
        node = self._find_task_node(task_id)
        if node is None:
            return
        self._browser.select_node(node, reveal=False)
        self._code.set_task(node, self._ws.store)      # 先备好上下文
        self._stack.setCurrentWidget(self._code)
        self._code.open_submission(assignment_id)      # 再打开那条记录

    def open_task(self, task_id: int) -> None:
        """直接进入某题的代码区（列表点击、回溯都走这里）。"""
        node = self._find_task_node(task_id)
        if node is None:
            return
        self._browser.select_node(node, reveal=False)
        self._code.set_task(node, self._ws.store)
        self._stack.setCurrentWidget(self._code)

    def _show_task(self, node: Node) -> None:
        """点题目直接进工作区：编辑器 + 底部文件列表同屏。

        底部那段就是"文件列表"（本地未提交文件 + 站点历史提交），
        所以不需要再单独跳一层列表页 —— 历史记录一直看得见。
        """
        self._code.set_task(node, self._ws.store)
        self._stack.setCurrentWidget(self._code)

    # ---------------- 目录交互 ----------------

    def _on_selected(self, node: Node) -> None:
        if node.kind == "task":
            self._show_task(node)
            return
        self._stack.setCurrentWidget(self._list)
        if node.kind == "section":                   # 题目总表
            self._show_bank()
        elif node.kind == "search":
            self._show_search()
        elif node.kind == "submissions":
            self._show_submissions()
        elif node.kind == "grades":
            self._show_grades()
        else:
            self._list.show_rows(node.label, "在左侧选择一项。", [], [])

    def _on_activated(self, node: Node) -> None:
        self._browser.set_location(node)

    def _show_bank(self) -> None:
        bank = self._bank_node()
        n = len(bank.children) if bank else 0
        self._list.show_rows("题目总表", f"当前账号可见 {n} 道题。"
                                        "展开左侧目录逐题查看，或在这里搜索。",
                             [], [], searchable=False)
        self._show_search()

    def _show_search(self) -> None:
        bank = self._bank_node()
        if bank is None:
            return
        rows = [("file-code", t.label, t.meta, t.badge, f"#{t.task_id}")
                for t in bank.children]
        ids = [t.task_id for t in bank.children]
        self._list.show_rows("搜索作业", "输入题号或题名片段筛选；点击结果直接进入编辑。",
                             rows, ids, searchable=True)

    def _show_submissions(self) -> None:
        rows, ids, payloads = [], [], []
        for s in self._ws.store.get_submissions_all():
            rows.append(("check" if s.get("score") == 100 else "file-code",
                         s.get("name", ""),
                         s.get("submitted_at", ""), f"{s.get('score')} 分",
                         f"#{s['task_id']}"))
            ids.append(int(s["task_id"]))
            # 带上该次提交的 id：点进去直接打开这条历史记录（只读）
            payloads.append(("submission", int(s["assignment_id"]), int(s["task_id"])))
        self._list.show_rows("作业状态",
                             f"共 {len(rows)} 条提交记录（最近在前）。"
                             "点击一条直接打开那次提交的源码（只读）。",
                             rows, ids, payloads=payloads)

    def _show_grades(self) -> None:
        rows, ids = [], []
        for g in self._ws.store.get_task_grades():
            rows.append(("chart", g.get("name", ""),
                         f"提交 {g['n']} 次", f"最高 {g['best']} 分",
                         f"#{g['task_id']}"))
            ids.append(int(g["task_id"]))
        self._list.show_rows("提交总结", f"涉及 {len(rows)} 道题。点击进入该题。",
                             rows, ids)

    # ---------------- 加载 ----------------

    def check_and_resume(self) -> None:
        """启动自检：对比本地与站点的题数，不足就接着加载。

        对付"加载到一半把程序关掉"：题库缓存 100 道、站点 800 道 → 续传；
        两边一致 → 不管详情是否齐全，正常运行即可（详情按需加载）。
        只花 1~2 个请求（读一次题目总表的分页信息）。
        """
        if not self._ws.has_account or not self._ws.logged_in:
            return
        if self._bank_worker is not None and self._bank_worker.isRunning():
            return
        try:
            from ...core import refresh as R
            cached, remote = R.bank_totals(self._ws.client, self._ws.store)
        except Exception as exc:                      # noqa: BLE001
            self.bank_crawl_state.emit(f"启动自检失败（不影响使用）：{exc}")
            return
        if remote and cached < remote:
            gap = remote - cached
            self.bank_crawl_state.emit(
                f"检测到上次未加载完（本地 {cached} / 站点 {remote} 题），"
                f"正在接着加载剩余 {gap} 题…")
            self.start_bank_crawl(auto=True)
        else:
            self.bank_crawl_state.emit(
                f"数据完整（本地 {cached} / 站点 {remote} 题）")

    def maybe_autocrawl(self) -> None:
        """新账号自动开始加载。

        判定很直接：已登录、有账号、但库里一道题都没有 —— 那就是新账号，
        需要把该账号的数据整份拉一遍。
        """
        if not self._ws.has_account or not self._ws.logged_in:
            return
        if self._ws.has_data:
            return
        if self._bank_worker is not None and self._bank_worker.isRunning():
            return
        self.bank_crawl_state.emit("检测到新账号，开始加载题库…")
        self.start_bank_crawl(auto=True)

    def start_bank_crawl(self, auto: bool = False) -> None:
        """开始整份加载。

        正在加载时点刷新**不会中断**——只提示一句"正在进行中"。
        （以前这里会把正在跑的加载停掉，用户一刷新就断在半路。）
        """
        if self._bank_worker is not None and self._bank_worker.isRunning():
            self.bank_crawl_state.emit("正在加载中，请稍候…（不会因为点刷新而中断）")
            return
        if not self._ws.has_account:
            self.bank_crawl_state.emit("还没有账号，无法加载。")
            return
        if not self._ws.logged_in:
            self.bank_crawl_state.emit("未登录，无法加载。请先到「个人中心」登录。")
            return
        self._bank_worker = BankCrawlWorker(self._ws)
        self._bank_worker.phase_changed.connect(self.bank_crawl_state.emit)
        self._bank_worker.progressed.connect(
            lambda d, t, s: self.bank_crawl_state.emit(
                f"加载中 {d}/{t}　{s}"))
        self._bank_worker.task_added.connect(self._on_task_added)
        self._bank_worker.done.connect(self._on_crawl_done)
        self._bank_worker.failed.connect(
            lambda m: self.bank_crawl_state.emit(f"加载失败：{m}"))
        self.bank_crawl_state.emit("开始加载题库…")
        self._bank_worker.start()

    def _on_task_added(self, task_id: int) -> None:
        """边加载边加目录项。

        只有"题目总表"是**展开**的时候才插进去——折叠时不做任何可见变化，
        这样用户不展开就不会看到列表在跳。
        """
        bank_item = self._bank_item()
        if bank_item is None or not bank_item.isExpanded():
            return
        if task_id in self._bank_items:
            return
        row = self._ws.store.get_task(task_id)
        if not row:
            return
        node = bank_task_node(row)
        item = QTreeWidgetItem([node.label])
        item.setData(0, Qt.ItemDataRole.UserRole, node)
        bank_item.addChild(item)
        self._bank_items[task_id] = item

    def _on_crawl_done(self, counts: dict) -> None:
        tail = "（已停止）" if counts.get("stopped") else ""
        self.bank_crawl_state.emit(
            f"加载完成{tail}：{counts.get('pages', 0)} 页题目、"
            f"{counts.get('submissions', 0)} 条提交记录。")
        self.reload()
        self.data_loaded.emit()      # 主窗口据此刷新所有页面

    # ---------------- 提交 ----------------

    def _submit(self, source: str) -> None:
        from .my_class import SubmitWorker
        node = self._code._node                        # noqa: SLF001
        if node is None:
            return
        self._code.set_submitting()
        self._worker = SubmitWorker(self._ws, node, source)
        self._worker.progress.connect(self._code._result.set_submitting)
        self._worker.succeeded.connect(self._code.show_result)
        self._worker.failed.connect(self._code.show_error)
        self._worker.start()
