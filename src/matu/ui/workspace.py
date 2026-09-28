"""工作区：当前账号的数据上下文。

一个账号 = 一个本地库 + 一份会话 Cookie。切换账号就是换这两样东西，
并广播 changed 让界面重新加载。

**为什么必须按账号隔离**：站点的页面/接口/字段结构对所有账号是统一的
（所以 parsers/client/submit 与账号无关），但内容——有哪些班级、哪些作业、
哪些题目、提交记录——完全属于账号私有。换账号必须重新爬，
旧账号的数据留在它自己的目录里，由设置界面按账号管理。

界面代码通过 workspace.store 拿数据，所以换账号后一次 reload 就能全部切换。
"""

from __future__ import annotations

import os
from typing import Optional, Tuple

from PySide6.QtCore import QObject, Signal

from ..core.accounts import AccountInfo, AccountStore
from ..core.client import MatuClient
from ..core.store import Store
from .config import Config

# 界面默认的请求节奏：比批量加载保守，避免用户连点造成请求堆积
UI_MIN_INTERVAL = 2.0
UI_JITTER = 0.8


class Workspace(QObject):
    """当前账号的数据上下文。"""

    changed = Signal()              # 账号或数据变了，界面要重载
    state_changed = Signal(str)     # logged_in | logged_out | checking

    def __init__(self, config: Config, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._config = config
        self.accounts = AccountStore()
        # 节奏由设置里的"请求策略"决定（默认 0.3 秒/次、单次上限 2048）
        self.client = MatuClient(
            min_interval=config.request_interval,
            jitter=min(0.15, config.request_interval / 4),
            max_requests=config.max_requests_per_run,
            allow_submission=config.allow_submission,
        )
        self._username = ""
        self._store = Store(":memory:")     # 没有账号时的空库，界面不用判空
        self._logged_in = False
        # 本次会话里用过的凭据，**只在内存**，用于会话过期后自动重登
        self._credentials: Optional[Tuple[str, str]] = None

        if config.active_account:
            self._activate(config.active_account, persist=False)
        else:
            # 首次运行或刚迁移完：如果只有一份已缓存账号，直接认领它，
            # 免得用户明明有数据却看到空界面
            cached = self.accounts.list()
            if len(cached) == 1:
                self._activate(cached[0].username)

    # ---------------- 状态 ----------------

    @property
    def username(self) -> str:
        return self._username

    @property
    def store(self) -> Store:
        return self._store

    @property
    def logged_in(self) -> bool:
        return self._logged_in

    @property
    def has_account(self) -> bool:
        return bool(self._username)

    @property
    def has_data(self) -> bool:
        """当前账号是否已经爬过数据。"""
        if not self.has_account:
            return False
        try:
            return self._store.stats().get("题目总数", 0) > 0
        except Exception:
            return False

    def _set_logged_in(self, value: bool) -> None:
        self._logged_in = value
        self.state_changed.emit("logged_in" if value else "logged_out")

    # ---------------- 账号切换 ----------------

    def _activate(self, username: str, persist: bool = True) -> None:
        """切到某账号：换库、换会话文件、加载它的 Cookie。"""
        if username != self._username and not self._store.is_empty_db:
            self._store.close()
        self._username = username
        self._store = self.accounts.open(username)
        # 会话也按账号走：每个账号一份 Cookie，互不覆盖
        self.client.session_file = self.accounts.session_path(username)
        self.client.session.cookies.clear()
        self.client.load_session()
        if persist:
            self._config.active_account = username
            self._config.save()
        self.changed.emit()

    def switch_account(self, username: str) -> None:
        """外部显式切换账号（例如从设置里选另一个已缓存账号）。"""
        self._activate(username)
        self._set_logged_in(False)

    # ---------------- 登录 ----------------

    def login(self, username: str, password: str) -> bool:
        """登录。成功即把当前账号切到这个账号，并保存它的会话。"""
        ok = self.client.login(username, password)
        if ok:
            # 记住凭据（仅内存）：站点的会话可能中途失效，那时要能自动重登
            self._credentials = (username, password)
            if username != self._username:
                self._activate(username)
            self._set_logged_in(True)
        return ok

    def relogin(self) -> bool:
        """会话失效时用内存里的凭据重新登录。没有凭据就返回 False。"""
        if not self._credentials:
            return False
        user, password = self._credentials
        try:
            ok = self.client.login(user, password)
        except Exception:                      # 网络问题不该让界面崩
            return False
        if ok:
            self._set_logged_in(True)
        return ok

    def ensure_session(self) -> bool:
        """确保会话可用：失效就自动重登。返回是否可用。

        用于"取回的是登录页"这种被动发现的情况。
        """
        if self.relogin():
            return True
        self._set_logged_in(False)
        return False

    def try_saved_session(self) -> bool:
        """用本地保存的 Cookie 试探会话是否还有效（一个请求）。"""
        if not self.client.session.cookies:
            return False
        self.state_changed.emit("checking")
        try:
            resp = self.client.get("/page/files/left.jsp")
        except Exception:                      # 网络问题不该让界面崩
            self._set_logged_in(False)
            return False
        ok = not MatuClient.looks_like_login_page(resp.text)
        self._set_logged_in(ok)
        return ok

    def credentials_from_env(self) -> Tuple[str, str]:
        """开发/调试用：从环境变量取凭据。正式流程走设置里的登录表单。"""
        return os.environ.get("MATU_USER", ""), os.environ.get("MATU_PASS", "")

    def login_from_env(self) -> bool:
        user, password = self.credentials_from_env()
        if not (user and password):
            return False
        return self.login(user, password)

    def logout(self) -> None:
        try:
            self.client.get("/user/logout")
        except Exception:
            pass
        self.client.clear_session()
        self._credentials = None
        self._set_logged_in(False)

    # ---------------- 缓存管理 ----------------

    def list_accounts(self) -> list:
        return self.accounts.list(active=self._username)

    def delete_account_cache(self, username: str) -> int:
        """删除某账号的本地缓存，返回释放的字节数。当前账号会被切到空库。"""
        freed = self.accounts.delete(username)
        if username == self._username:
            self._store = Store(":memory:")
            self._username = ""
            self._config.active_account = ""
            self._config.save()
            self.client.session.cookies.clear()
            self._set_logged_in(False)
            self.changed.emit()
        return freed
