"""应用入口：主窗口装配、主题切换、设置窗口。

窗口用系统原生标题栏（macOS 上就是标准窗口），内容区全部自绘矢量。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import (QColor, QFont, QGuiApplication, QIcon, QKeySequence,
                           QShortcut)
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QMainWindow,
                               QStackedWidget, QVBoxLayout, QWidget)

from ..core.accounts import AccountStore
from .config import Config
from .pages.data_center import DataCenterPage
from .pages.help import HelpPage
from .pages.my_class import MyClassPage
from .pages.profile import ProfilePage
from .pages.task_center import TaskCenterPage
from .panels import Placeholder
from .sidebar import Sidebar
from .workspace import Workspace
from .theme import DARK, LIGHT, Theme, palette_for, set_theme, theme
from .widgets import ui_font

DB_PATH = Path(__file__).resolve().parents[3] / "data" / "matu.db"   # 仅迁移用，见 tools/migrate_data.py
PAGE_ORDER = ["my_class", "task_center", "data_center", "help", "profile"]


def build_theme(config: Config) -> Theme:
    """按配置构造主题。appearance=system 时跟随系统配色。"""
    mode = config.appearance
    if mode == "system":
        try:
            scheme = QGuiApplication.styleHints().colorScheme()
            mode = "dark" if scheme == Qt.ColorScheme.Dark else "light"
        except Exception:
            mode = "light"
    t = Theme(palette=palette_for(mode))
    t.ui_font_size = config.ui_font_size
    t.mono_font_size = config.mono_font_size
    t.ui_font_family = config.ui_font
    t.mono_font_family = config.mono_font
    return t


def app_qss() -> str:
    """全局 QSS：只负责 Qt 原生控件（滚动条、分隔条、提示）的矢量外观。

    注意：**绝不给 QWidget 设不透明背景**。卡片是自绘的，一旦让普通容器
    带上窗口底色，它们就会盖在卡片上，视觉上变成一个个"空洞"。
    """
    pal = theme().palette
    return f"""
    QMainWindow, QDialog {{ background: {pal.bg}; }}
    QWidget {{ color: {pal.text}; }}
    QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; }}
    QToolTip {{
        background: {pal.surface}; color: {pal.text};
        border: 1px solid {pal.border}; border-radius: 6px; padding: 5px 8px;
    }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{
        background: {pal.border_strong}; border-radius: 5px; min-height: 32px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {pal.text_muted}; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
    QScrollBar::handle:horizontal {{
        background: {pal.border_strong}; border-radius: 5px; min-width: 32px;
    }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
    QSplitter::handle {{ background: transparent; }}
    QSplitter::handle:hover {{ background: {pal.border}; }}
    """


def apply_app_icon(app: QApplication) -> None:
    """把图标换成我们的 {} 标记。

    图标由**同一个矢量绘制函数**渲染而来（tools/build_icon.py），所以界面
    侧栏的 logo、窗口图标、打包后的应用图标永远是同一个东西。

    这里只做 `setWindowIcon`：Qt 在 macOS 上会据此更新程序坞图标，且失败
    也不影响运行。

    （试过用 ctypes 直接调 AppKit 的 setApplicationIconImage 更"稳"，但
    实测那条路径会让进程被信号杀掉 —— 纯外观的事不该冒拖垮程序的风险，
    所以打包时靠 bundle 里的 .icns 来保证程序坞图标，那才是确定生效的。）
    """
    png = Path(__file__).resolve().parents[1] / "resources" / "app.png"
    if png.exists():
        app.setWindowIcon(QIcon(str(png)))


def restyle(widget: QWidget) -> None:
    """主题切换后让所有控件重新取色。"""
    for child in widget.findChildren(QWidget):
        hook = getattr(child, "apply_theme", None)
        if callable(hook):
            try:
                hook()
            except Exception:
                pass
        child.update()
    widget.update()


# ----------------------------------------------------------------- 登录线程

class LoginWorker(QThread):
    done = Signal(bool, str)

    def __init__(self, session: Workspace, user: str, password: str) -> None:
        super().__init__()
        self._session = session
        self._user = user
        self._password = password

    def run(self) -> None:
        try:
            ok = self._session.login(self._user, self._password)
            self.done.emit(ok, "" if ok else "账号或密码不正确，或者站点无法访问")
        except Exception as exc:                      # noqa: BLE001
            self.done.emit(False, f"{type(exc).__name__}: {exc}")


# ----------------------------------------------------------------- 主窗口

class MainWindow(QMainWindow):
    def __init__(self, workspace: Workspace, config: Config) -> None:
        super().__init__()
        self._ws = workspace
        self._config = config
        self._login_worker: Optional[LoginWorker] = None

        self.setWindowTitle("BetterMatuUI")
        self.resize(1360, 880)
        self.setMinimumSize(1080, 700)

        self._sidebar = Sidebar(self, collapsed=config.sidebar_collapsed)
        self._stack = QStackedWidget(self)

        self._my_class = MyClassPage(workspace, self)
        self._task_center = TaskCenterPage(workspace, self)
        self._data_center = DataCenterPage(workspace, self)
        self._profile = ProfilePage(workspace, config, self)
        pages = {
            "my_class": self._my_class,
            "task_center": self._task_center,
            "data_center": self._data_center,
            "help": HelpPage(self),
            "profile": self._profile,
        }
        self._pages = pages
        for key in PAGE_ORDER:
            self._stack.addWidget(pages[key])

        central = QWidget(self)
        lay = QHBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self._sidebar)
        lay.addWidget(self._stack, 1)
        self.setCentralWidget(central)

        # 信号
        self._sidebar.navigate.connect(self._on_navigate)
        self._sidebar.collapsed_changed.connect(self._on_collapsed)
        self._profile.login_requested.connect(self._on_login)
        self._profile.logout_requested.connect(self._on_logout)
        # 设置区块现在长在个人中心页里，主题/数据变更直接由它冒泡上来
        self._profile.theme_changed.connect(self._on_theme_changed)
        self._profile.data_changed.connect(self._on_data_changed)
        self._profile.account_switched.connect(self._on_account_changed)
        self._ws.changed.connect(self._on_account_changed)
        # 加载进度同时显示在「我的班级」底部（两个页面都能看到）
        self._task_center.bank_crawl_state.connect(self._my_class.set_status)

        QShortcut(QKeySequence("Ctrl+,"), self, self.open_settings)
        QShortcut(QKeySequence("Meta+,"), self, self.open_settings)
        QShortcut(QKeySequence("Ctrl+B"), self, self._sidebar.toggle_collapsed)

        # 加载指示器：每 250ms 看一眼有没有后台动作在跑（登录/加载/上传/下载）
        self._busy_timer = QTimer(self)
        self._busy_timer.setInterval(250)
        self._busy_timer.timeout.connect(self._refresh_busy)
        self._busy_timer.start()

        self._sidebar.set_selected("data_center")
        self._stack.setCurrentWidget(self._data_center)
        self._update_title()
        # 启动时用保存的 Cookie 静默探一次登录态（一个请求），失败不影响使用
        if self._ws.client.session.cookies:
            try:
                self._ws.try_saved_session()
            except Exception:
                pass
        self._profile.refresh_state()
        # 启动自检：上次若没加载完（比如中途关掉程序），这里接着加载
        QTimer.singleShot(600, self._startup_selfcheck)

    # 账号切换后数据整个换了，做成属性避免拿到旧快照
    @property
    def _store(self):
        return self._ws.store

    @property
    def _session(self):
        return self._ws

    def _refresh_busy(self) -> None:
        """侧栏那个旋转的加载指示器：有后台动作就转，没有就隐藏。"""
        workers = [getattr(self, "_login_worker", None),
                   getattr(self._task_center, "_bank_worker", None),
                   getattr(self._my_class, "_submit_worker", None),
                   getattr(self._my_class, "_refresh_worker", None)]
        for page in (self._my_class, self._task_center):
            files = getattr(getattr(page, "_code", None), "_files", None)
            if files is not None:
                workers += [getattr(files, "_history_worker", None),
                            getattr(files, "_code_worker", None)]
        busy = any(w is not None and getattr(w, "isRunning", lambda: False)()
                   for w in workers)
        self._sidebar.set_busy(busy)

    def _startup_selfcheck(self) -> None:
        if self._ws.logged_in:
            self._task_center.check_and_resume()

    def _update_title(self) -> None:
        self.setWindowTitle(f"BetterMatuUI — {self._ws.username}"
                            if self._ws.username else "BetterMatuUI")

    def _on_account_changed(self) -> None:
        self._update_title()
        self._my_class.reload()
        self._profile.refresh_state()
        self._profile.refresh_stats()
        # 切到的新账号若还没数据，同样自动开爬
        self._task_center.maybe_autocrawl()

    # ---- 导航 ----
    def _on_navigate(self, key: str) -> None:
        page = self._pages.get(key)
        if page is not None:
            self._stack.setCurrentWidget(page)
            if key == "profile":
                self._profile.refresh_state()
                self._profile.refresh_stats()

    def _on_collapsed(self, collapsed: bool) -> None:
        self._config.sidebar_collapsed = collapsed
        self._config.save()

    # ---- 账号 ----
    def _on_login(self, user: str, password: str) -> None:
        self._login_worker = LoginWorker(self._session, user, password)
        self._login_worker.done.connect(self._on_login_done)
        self._login_worker.start()

    def _on_login_done(self, ok: bool, message: str) -> None:
        if ok:
            self._profile.login_succeeded()
            # 登录成功后若是新账号（库里没数据），自动把该账号的数据爬一遍
            self._task_center.maybe_autocrawl()
            # 姓名还没取过就顺手取一次，这样个人中心和数据中心都能显示
            self._data_center.fetch_name_if_missing()
        else:
            self._profile.login_failed(message)
        self._sync_submission_gate()

    def _on_logout(self) -> None:
        self._session.logout()
        self._profile.refresh_state()
        self._sync_submission_gate()

    def _sync_submission_gate(self) -> None:
        """把设置里的提交总闸同步到网络客户端。"""
        self._session.client.allow_submission = self._config.allow_submission

    # ---- 设置（个人中心页内的区块，不再弹独立窗口） ----
    def open_settings(self) -> None:
        self._sidebar.set_selected("profile")
        self._on_navigate("profile")
        self._profile.scroll_to_settings()

    def _on_theme_changed(self) -> None:
        set_theme(build_theme(self._config))
        qapp = QApplication.instance()
        qapp.setStyleSheet(app_qss())
        qapp.setFont(ui_font())
        restyle(self)
        self._sync_submission_gate()

    def _on_data_changed(self) -> None:
        self._sync_submission_gate()
        self._my_class.reload()
        self._profile.refresh_stats()


def main(argv: Optional[list] = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    app = QApplication(argv)
    app.setApplicationName("BetterMatuUI")
    app.setApplicationDisplayName("BetterMatuUI")
    try:
        app.setStyle("Fusion")     # 统一各平台原生控件底子，再由 QSS 覆盖
    except Exception:
        pass

    config = Config.load()
    set_theme(build_theme(config))
    app.setFont(ui_font())
    app.setStyleSheet(app_qss())
    apply_app_icon(app)

    # 数据按账号隔离：Workspace 负责"当前是哪个账号、用哪个库、哪份会话"
    workspace = Workspace(config)

    win = MainWindow(workspace, config)
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
