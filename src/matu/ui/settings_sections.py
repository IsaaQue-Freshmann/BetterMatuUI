"""设置的各个分组区块。

设计成**可复用区块**而不是独立窗口：目前挂在「个人中心」页面下方，
和它是同一层界面。以后若要改成独立页面，把这个组件搬过去即可，不用重写。
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QHBoxLayout,
                               QLabel, QSlider, QSpinBox, QVBoxLayout, QWidget)

from ..core.client import CACHE_DIR, MATU_HOME
from ..core.store import Store
from .config import Config
from .panels import SectionTitle
from .theme import theme
from .widgets import Card, VectorButton, VectorSpin, ui_font

SITE_URL = "http://matu.uestc.edu.cn"
VERSION = "Beta 1.0"
CREDIT = "Created by IsaaQue Freshmann SCU"


def field_qss() -> str:
    """原生表单控件的矢量外观（无位图）。"""
    pal = theme().palette
    return (
        f"QComboBox,QSpinBox{{background:{pal.surface_alt};color:{pal.text};"
        f"border:1px solid {pal.border};border-radius:6px;padding:4px 8px;min-height:22px;}}"
        f"QComboBox:hover,QSpinBox:hover{{border:1px solid {pal.border_strong};}}"
        f"QComboBox::drop-down{{border:none;width:18px;}}"
        f"QComboBox QAbstractItemView{{background:{pal.surface};color:{pal.text};"
        f"border:1px solid {pal.border};selection-background-color:{pal.accent_soft};"
        f"selection-color:{pal.accent};outline:none;}}"
        f"QCheckBox{{color:{pal.text};spacing:8px;}}"
        f"QCheckBox::indicator{{width:16px;height:16px;border-radius:4px;"
        f"border:1px solid {pal.border_strong};background:{pal.surface};}}"
        f"QCheckBox::indicator:checked{{background:{pal.accent};border:1px solid {pal.accent};}}"
        f"QSlider::groove:horizontal{{height:4px;background:{pal.border};border-radius:2px;}}"
        f"QSlider::handle:horizontal{{width:14px;height:14px;margin:-6px 0;"
        f"border-radius:7px;background:{pal.accent};}}"
        f"QLabel{{color:{pal.text_dim};}}"
    )


class BankCrawlWorker(QThread):
    """为当前账号整份爬题库。

    换账号后必须整份重来：「题目总表」返回的是**该账号可见**的题，
    内容随账号不同，不能沿用上一个账号的结果。
    采用用户指定的节奏：0.5 秒/题，串行、无并发，可中途停止（已抓的已落库）。
    """

    progressed = Signal(int, int, str)
    done = Signal(dict)
    failed = Signal(str)

    CRAWL_INTERVAL = 0.2          # 与界面其它入口保持一致：0.2 秒/题
    CRAWL_JITTER = 0.05
    MAX_REQUESTS = 700

    def __init__(self, workspace) -> None:
        super().__init__()
        self._ws = workspace
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        from ..core import refresh as R
        client = self._ws.client
        old = (client.min_interval, client.jitter, client.max_requests)
        client.min_interval, client.jitter = self.CRAWL_INTERVAL, self.CRAWL_JITTER
        client.max_requests = self.MAX_REQUESTS
        try:
            # 整份抓取，顺序：班级 -> 提交记录 -> 题库（与界面统一入口同一份实现）
            counts = R.refresh_all(
                client, self._ws.store,
                log=lambda _m: None,
                progress=lambda d, t, s: self.progressed.emit(d, t, s),
                should_stop=lambda: self._stop,
            )
            self._ws.accounts.touch_crawl(self._ws.username, self._ws.store)
            counts["stopped"] = self._stop
            self.done.emit(counts)
        except Exception as exc:                      # noqa: BLE001
            self.failed.emit(f"{type(exc).__name__}: {exc}")
        finally:
            client.min_interval, client.jitter, client.max_requests = old


class SettingsSections(QWidget):
    """设置区块集合：账号与缓存 / 外观与主题 / 请求策略 / 数据与缓存 / 关于 / 更多。"""

    theme_changed = Signal()
    data_changed = Signal()
    account_switched = Signal()

    def __init__(self, config: Config, workspace,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._config = config
        self._ws = workspace
        self._bank_worker: Optional[BankCrawlWorker] = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        self._build_accounts(lay)
        self._build_appearance(lay)
        self._build_requests(lay)
        self._build_data(lay)
        self._build_about(lay)
        self._build_more(lay)
        self.apply_theme()

    # 账号切换后数据整个换了，做成属性避免拿到旧快照
    @property
    def _store(self):
        return self._ws.store

    @property
    def _session(self):
        return self._ws

    # ---------------- 布局辅助 ----------------

    def _section(self, lay: QVBoxLayout, text: str, hint: str = "") -> None:
        row = QWidget(self)
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 16, 0, 6)
        rl.setSpacing(8)
        label = QLabel(text, row)
        label.setFont(ui_font(11, QFont.Weight.DemiBold))
        rl.addWidget(label)
        if hint:
            h = QLabel(hint, row)
            h.setFont(ui_font(11))
            rl.addWidget(h)
        rl.addStretch(1)
        lay.addWidget(row)

    def _card(self, lay: QVBoxLayout) -> QVBoxLayout:
        card = Card(self)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(18, 12, 18, 12)
        cl.setSpacing(10)
        lay.addWidget(card)
        return cl

    def _row(self, cl: QVBoxLayout, label: str, widget: QWidget) -> None:
        row = QWidget(self)
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        lab = QLabel(label, row)
        lab.setFont(ui_font())
        lab.setMinimumWidth(118)
        rl.addWidget(lab)
        rl.addStretch(1)
        rl.addWidget(widget)
        cl.addWidget(row)

    def _hint(self, cl: QVBoxLayout, text: str) -> None:
        lab = QLabel(text, self)
        lab.setWordWrap(True)
        lab.setFont(ui_font(11))
        cl.addWidget(lab)

    @staticmethod
    def _slider(parent: QWidget, lo: int, hi: int, value: int):
        wrap = QWidget(parent)
        hl = QHBoxLayout(wrap)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(8)
        s = QSlider(Qt.Orientation.Horizontal, wrap)
        s.setRange(lo, hi)
        s.setValue(value)
        s.setFixedWidth(140)
        lab = QLabel(str(value), wrap)
        lab.setFont(ui_font(11))
        lab.setFixedWidth(22)
        s.valueChanged.connect(lambda v: lab.setText(str(v)))
        hl.addWidget(s)
        hl.addWidget(lab)
        return s, wrap

    # ---------------- 账号与缓存 ----------------

    def _build_accounts(self, lay: QVBoxLayout) -> None:
        self._section(lay, "账号与缓存", "每个账号的数据互相隔离")
        cl = self._card(lay)
        self._hint(cl, "站点的页面与接口结构对所有账号是统一的，但班级、作业、题目、"
                       "提交记录都属于各自账号。换账号后需要重新加载；"
                       "旧账号的数据保留在它自己那份缓存里，可以在这里单独删除。")

        self._accounts_host = QWidget(self)
        self._accounts_layout = QVBoxLayout(self._accounts_host)
        self._accounts_layout.setContentsMargins(0, 0, 0, 0)
        self._accounts_layout.setSpacing(6)
        cl.addWidget(self._accounts_host)

        # 加载按钮：换账号后必须整份重爬，这个入口就为它准备
        crow = QWidget(self)
        cbl = QHBoxLayout(crow)
        cbl.setContentsMargins(0, 6, 0, 0)
        cbl.setSpacing(8)
        cbl.addStretch(1)
        self._crawl_btn = VectorButton("为当前账号加载完整题库", "download",
                                       VectorButton.SUBTLE, crow,
                                       tooltip="约 0.5 秒/题，串行请求，可中途停止")
        self._crawl_btn.clicked.connect(self._toggle_bank_crawl)
        scan = VectorButton("重新扫描", "refresh", VectorButton.GHOST, crow)
        scan.clicked.connect(self.refresh_accounts)
        cbl.addWidget(self._crawl_btn)
        cbl.addWidget(scan)
        cl.addWidget(crow)

        self._crawl_progress = QLabel("", self)
        self._crawl_progress.setFont(ui_font(11))
        self._crawl_progress.setWordWrap(True)
        cl.addWidget(self._crawl_progress)

        self._accounts_msg = QLabel("", self)
        self._accounts_msg.setFont(ui_font(11))
        self._accounts_msg.setWordWrap(True)
        cl.addWidget(self._accounts_msg)
        self.refresh_accounts()

    def refresh_accounts(self) -> None:
        while self._accounts_layout.count():
            item = self._accounts_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        infos = self._ws.list_accounts()
        if not infos:
            empty = QLabel("还没有任何账号的缓存。登录后加载一次，这里就会出现。", self)
            empty.setFont(ui_font(11))
            self._accounts_layout.addWidget(empty)
            return

        for info in infos:
            self._accounts_layout.addWidget(self._account_row(info))

    def _account_row(self, info) -> QWidget:
        pal = theme().palette
        row = QWidget(self)
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 2, 0, 2)
        rl.setSpacing(10)

        name = QLabel(info.username, row)
        name.setFont(ui_font(13, QFont.Weight.DemiBold))
        name.setMinimumWidth(140)
        rl.addWidget(name)

        bits = []
        if info.error:
            bits.append(f"读取失败：{info.error}")
        else:
            bits.append(f"{info.tasks} 题（含详情 {info.tasks_with_detail}）")
            if info.classes:
                bits.append(f"{info.classes} 个班级")
            if info.homework_tasks:
                bits.append(f"{info.homework_tasks} 道作业题")
            if info.submissions:
                bits.append(f"{info.submissions} 条提交")
            bits.append(info.size_text)
            if info.last_crawl:
                bits.append(f"最近加载 {info.last_crawl}")
        detail = QLabel("　·　".join(bits), row)
        detail.setFont(ui_font(11))
        detail.setStyleSheet(f"color:{pal.text_muted};")
        rl.addWidget(detail, 1)

        if info.is_active:
            tag = QLabel("当前账号", row)
            tag.setFont(ui_font(11, QFont.Weight.Medium))
            tag.setStyleSheet(f"color:{pal.accent};")
            rl.addWidget(tag)
        else:
            use = VectorButton("切换到此账号", "check", VectorButton.GHOST, row)
            use.clicked.connect(lambda _=False, u=info.username: self._switch_to(u))
            rl.addWidget(use)

        delete = VectorButton("删除缓存", "trash", VectorButton.GHOST, row)
        delete.clicked.connect(lambda _=False, u=info.username: self._delete_cache(u))
        rl.addWidget(delete)
        return row

    def _switch_to(self, username: str) -> None:
        self._ws.switch_account(username)
        self._accounts_msg.setText(
            f"已切换到账号 {username}。它的缓存里已有 {self._ws.store.stats()['题目总数']} 道题；"
            f"如果内容不是最新的，去「我的班级」点刷新重新爬一次。")
        self.refresh_accounts()
        self.account_switched.emit()

    def _delete_cache(self, username: str) -> None:
        from PySide6.QtWidgets import QMessageBox
        active_note = "（这是当前账号，删除后会退出登录状态）" if username == self._ws.username else ""
        box = QMessageBox(self)
        box.setWindowTitle("删除缓存")
        box.setText(f"确定删除账号 {username} 的全部本地缓存吗？{active_note}")
        box.setInformativeText("只删除这台机器上爬下来的数据，不会影响站点上的任何内容，"
                               "也删不掉已经提交的作业。下次登录该账号需要重新加载。")
        box.setStandardButtons(QMessageBox.StandardButton.Cancel
                               | QMessageBox.StandardButton.Yes)
        box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        if box.exec() != QMessageBox.StandardButton.Yes:
            return
        freed = self._ws.delete_account_cache(username)
        self._accounts_msg.setText(
            f"已删除账号 {username} 的缓存，释放约 {freed / 1024 / 1024:.1f} MB。")
        self.refresh_accounts()
        self.data_changed.emit()
        self.account_switched.emit()

    # ---- 加载当前账号的完整题库 ----

    def _toggle_bank_crawl(self) -> None:
        if self._bank_worker is not None and self._bank_worker.isRunning():
            self._bank_worker.stop()
            self._crawl_progress.setText("正在停止…已抓到的部分已经落库，下次可续爬。")
            return
        if not self._ws.has_account:
            self._crawl_progress.setText("还没有账号。先到上面的账号卡片里登录。")
            return
        if not self._ws.logged_in:
            self._crawl_progress.setText("当前未登录，无法加载。请先登录。")
            return
        self._bank_worker = BankCrawlWorker(self._ws)
        self._bank_worker.progressed.connect(self._on_crawl_progress)
        self._bank_worker.done.connect(self._on_crawl_done)
        self._bank_worker.failed.connect(self._on_crawl_failed)
        self._crawl_btn.setText("停止加载")
        self._crawl_progress.setText("开始加载…")
        self._bank_worker.start()

    def _on_crawl_progress(self, done: int, total: int, name: str) -> None:
        self._crawl_progress.setText(
            f"正在加载：{done}/{total}　最近：{name}　"
            f"（约 0.5 秒/题，预计还需 {max(0, total - done) * 0.5 / 60:.1f} 分钟）")

    def _on_crawl_done(self, counts: dict) -> None:
        self._crawl_btn.setText("为当前账号加载完整题库")
        tail = "（中途停止）" if counts.get("stopped") else ""
        self._crawl_progress.setText(
            f"加载完成{tail}：分页 {counts.get('pages', 0)} 页，"
            f"题目详情 {counts.get('details', 0)} 道。")
        self.refresh_accounts()
        self.refresh_stats()
        self.data_changed.emit()

    def _on_crawl_failed(self, message: str) -> None:
        self._crawl_btn.setText("为当前账号加载完整题库")
        self._crawl_progress.setText(f"加载失败：{message}")

    # ---------------- 外观与主题 ----------------

    def _build_appearance(self, lay: QVBoxLayout) -> None:
        self._section(lay, "外观与主题")
        cl = self._card(lay)

        self._appearance = QComboBox(self)
        self._appearance.addItem("跟随系统", "system")
        self._appearance.addItem("亮色", "light")
        self._appearance.addItem("暗色", "dark")
        idx = self._appearance.findData(self._config.appearance)
        self._appearance.setCurrentIndex(max(0, idx))
        self._appearance.currentIndexChanged.connect(self._on_appearance)
        self._row(cl, "主题", self._appearance)

        self._ui_font_box = QComboBox(self)
        self._ui_font_box.addItem("系统默认", "")
        for fam in self._ui_families():
            self._ui_font_box.addItem(fam, fam)
        self._select(self._ui_font_box, self._config.ui_font)
        self._ui_font_box.currentIndexChanged.connect(self._on_font)
        self._row(cl, "界面字体", self._ui_font_box)

        self._mono_font_box = QComboBox(self)
        self._mono_font_box.addItem("系统等宽", "")
        for fam in self._mono_families():
            self._mono_font_box.addItem(fam, fam)
        self._select(self._mono_font_box, self._config.mono_font)
        self._mono_font_box.currentIndexChanged.connect(self._on_font)
        self._row(cl, "代码字体", self._mono_font_box)

        self._ui_size, ui_wrap = self._slider(self, 11, 18, self._config.ui_font_size)
        self._ui_size.valueChanged.connect(self._on_font)
        self._row(cl, "界面字号", ui_wrap)

        self._mono_size, mono_wrap = self._slider(self, 10, 22, self._config.mono_font_size)
        self._mono_size.valueChanged.connect(self._on_font)
        self._row(cl, "代码字号", mono_wrap)

    def _build_requests(self, lay: QVBoxLayout) -> None:
        self._section(lay, "请求策略")
        cl = self._card(lay)

        # 用毫秒做单位：以秒为单位时 0.3 会被整数取整抹成 0，
        # 界面上就显示成"0 秒"了
        self._interval = VectorSpin(
            self, minimum=0, maximum=5000,
            value=int(round(self._config.request_interval * 1000)),
            step=100, suffix=" 毫秒", width=150)
        self._interval.valueChanged.connect(self._on_requests)
        self._row(cl, "请求最小间隔", self._interval)

        self._max_req = VectorSpin(self, minimum=10, maximum=5000,
                                   value=self._config.max_requests_per_run,
                                   step=10, width=140)
        self._max_req.valueChanged.connect(self._on_requests)
        self._row(cl, "单次请求上限", self._max_req)

        self._allow_submit = QCheckBox("允许提交代码到站点", self)
        self._allow_submit.setChecked(self._config.allow_submission)
        self._allow_submit.stateChanged.connect(self._on_requests)
        cl.addWidget(self._allow_submit)

        self._skip_confirm = QCheckBox("提交时不再弹确认框", self)
        self._skip_confirm.setChecked(self._config.skip_submit_confirm)
        self._skip_confirm.stateChanged.connect(self._on_requests)
        cl.addWidget(self._skip_confirm)

        self._hint(cl, "所有请求串行发送并保持最小间隔，不做轮询、不自动重试。"
                       "关掉「允许提交」后，提交请求会被代码层直接拒绝。")

    def _build_data(self, lay: QVBoxLayout) -> None:
        self._section(lay, "数据与缓存")
        cl = self._card(lay)

        self._stats_label = QLabel("", self)
        self._stats_label.setFont(ui_font(11))
        self._stats_label.setWordWrap(True)
        cl.addWidget(self._stats_label)
        self.refresh_stats()

        row = QWidget(self)
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(8)
        export = VectorButton("导出 JSON 快照", "download", VectorButton.SUBTLE, row)
        export.clicked.connect(self._export)
        clear = VectorButton("清空页面缓存", "trash", VectorButton.SUBTLE, row)
        clear.clicked.connect(self._clear_cache)
        rl.addStretch(1)
        rl.addWidget(export)
        rl.addWidget(clear)
        cl.addWidget(row)

        self._data_msg = QLabel("", self)
        self._data_msg.setFont(ui_font(11))
        self._data_msg.setWordWrap(True)
        cl.addWidget(self._data_msg)
        self._hint(cl, "班级与作业数据的刷新按钮在「我的班级」页的目录栏上。")

    def _build_about(self, lay: QVBoxLayout) -> None:
        self._section(lay, "关于")
        cl = self._card(lay)
        for text, bold in ((f"BetterMatuUI {VERSION}", True),
                           (CREDIT, True),
                           (f"数据来源：{SITE_URL}", False),
                           (f"应用数据目录：{MATU_HOME}", False),
                           ("本项目是码图网站的个人桌面客户端，仅用于本人账号的查看、"
                            "编辑与提交；不做批量刷题、不做自动重试。", False)):
            lab = QLabel(text, self)
            lab.setWordWrap(True)
            lab.setFont(ui_font(12 if bold else 11,
                                QFont.Weight.DemiBold if bold else QFont.Weight.Normal))
            cl.addWidget(lab)

    def _build_more(self, lay: QVBoxLayout) -> None:
        self._section(lay, "更多设置", "（预留）")
        cl = self._card(lay)
        self._hint(cl, "这一组是预留扩展位：以后加功能只需要在这里加一个分组，"
                       "不用改页面结构。")

    # ---------------- 事件 ----------------

    def _on_appearance(self) -> None:
        self._config.appearance = self._appearance.currentData()
        self._config.save()
        self.theme_changed.emit()

    def _on_font(self) -> None:
        self._config.ui_font = self._ui_font_box.currentData() or ""
        self._config.mono_font = self._mono_font_box.currentData() or ""
        self._config.ui_font_size = self._ui_size.value()
        self._config.mono_font_size = self._mono_size.value()
        self._config.save()
        self.theme_changed.emit()

    def _on_requests(self) -> None:
        self._config.request_interval = self._interval.value() / 1000.0   # 毫秒 -> 秒
        self._config.max_requests_per_run = self._max_req.value()
        self._config.allow_submission = self._allow_submit.isChecked()
        self._config.skip_submit_confirm = self._skip_confirm.isChecked()
        self._config.save()
        # 立刻生效：同步到网络客户端，不必重启
        client = getattr(self._ws, "client", None)
        if client is not None:
            client.min_interval = self._config.request_interval
            client.jitter = min(0.15, self._config.request_interval / 4)
            client.max_requests = self._config.max_requests_per_run
        self.data_changed.emit()

    def _export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "导出 JSON 快照", str(Path.home() / "matu_snapshot.json"),
            "JSON (*.json)")
        if not path:
            return
        self._store.export_json(Path(path))
        self._data_msg.setText(f"已导出到 {path}")

    def _clear_cache(self) -> None:
        count = 0
        if CACHE_DIR.exists():
            count = len(list(CACHE_DIR.glob("*")))
            shutil.rmtree(CACHE_DIR, ignore_errors=True)
        self._data_msg.setText(f"已清空页面缓存（{count} 个文件）。"
                               f"缓存只影响解析，不影响本地题库。")

    # ---------------- 状态刷新 ----------------

    def refresh_stats(self) -> None:
        s = self._store.stats()
        self._stats_label.setText(
            f"本地题库：{s['题目总数']} 道（含详情 {s['题目详情已抓']}）　"
            f"作业内题目：{s['作业内题目数']} 道　"
            f"提交记录：{s['提交记录数']} 条\n"
            f"数据库：{self._store.path}"
        )

    def apply_theme(self) -> None:
        """主题切换后重新套用表单外观（由 restyle() 递归调用）。"""
        self.setStyleSheet(field_qss())

    # ---------------- 字体列表 ----------------

    @staticmethod
    def _ui_families() -> List[str]:
        prefer = ["PingFang SC", "Hiragino Sans GB", "Microsoft YaHei",
                  "Segoe UI", "Noto Sans CJK SC", "Source Han Sans SC", "Inter"]
        available = set(QFontDatabase.families())
        return [f for f in prefer if f in available]

    @staticmethod
    def _mono_families() -> List[str]:
        prefer = ["Menlo", "Monaco", "JetBrains Mono", "Fira Code", "Consolas",
                  "Cascadia Mono", "Source Code Pro", "Courier New"]
        available = set(QFontDatabase.families())
        return [f for f in prefer if f in available]

    @staticmethod
    def _select(box: QComboBox, family: str) -> None:
        idx = box.findData(family)
        box.setCurrentIndex(idx if idx >= 0 else 0)
