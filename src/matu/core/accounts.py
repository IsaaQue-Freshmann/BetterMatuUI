"""按账号隔离的本地数据。

加载到的题目、班级、作业、提交记录都**随账号不同而不同**，所以绝不放在项目里，
而是每个账号一个目录，放在应用数据目录下：

    ~/.bettermatu/accounts/<账号>/
        matu.db          SQLite：题库、班级、作业、提交记录
        snapshot.json    导出快照
        session.json     该账号的会话 Cookie（可复用，省一次登录）
        docs/            站点文档正文（学生手册、提交注意事项）

需要区分清楚的两件事：

- **站点结构是统一的**：页面、接口、字段对所有账号都一样，
  所以 `core/parsers.py`、`core/client.py`、`core/submit.py` 与账号无关。
- **站点内容是账号私有的**：有哪些班级、哪些作业、哪些题、提交记录，
  都只属于某个账号。换账号必须重新加载，旧账号的数据留在它自己的目录里。

设置界面里的"账号与缓存"就是基于这里列目录实现的。
"""

from __future__ import annotations

import json
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from .client import MATU_HOME
from .store import Store

ACCOUNTS_DIR = MATU_HOME / "accounts"
_SAFE = re.compile(r"[^A-Za-z0-9_.\-]")


@dataclass
class AccountInfo:
    """一个已缓存账号的概况，用于设置界面展示与按账号删除。"""

    username: str
    path: Path
    size_bytes: int = 0
    tasks: int = 0
    tasks_with_detail: int = 0
    homework_tasks: int = 0
    submissions: int = 0
    classes: int = 0
    last_crawl: str = ""
    is_active: bool = False
    error: str = ""

    @property
    def size_text(self) -> str:
        n = float(self.size_bytes)
        for unit in ("B", "KB", "MB", "GB"):
            if n < 1024 or unit == "GB":
                return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
            n /= 1024
        return f"{n:.1f} GB"


class AccountStore:
    """账号目录的管理者。不持有连接，按需 open。"""

    def __init__(self, base: Optional[Path] = None) -> None:
        self.base = Path(base or ACCOUNTS_DIR)

    # ---- 路径 ----
    @staticmethod
    def key(username: str) -> str:
        """把账号转成安全的目录名。保证不会变成 . / .. / 空。"""
        cleaned = _SAFE.sub("_", (username or "").strip())
        cleaned = cleaned.strip(".")
        return cleaned or "unknown"

    def dir_for(self, username: str) -> Path:
        return self.base / self.key(username)

    def db_path(self, username: str) -> Path:
        return self.dir_for(username) / "matu.db"

    def snapshot_path(self, username: str) -> Path:
        return self.dir_for(username) / "snapshot.json"

    def session_path(self, username: str) -> Path:
        return self.dir_for(username) / "session.json"

    def docs_dir(self, username: str) -> Path:
        return self.dir_for(username) / "docs"

    # ---- 打开与创建 ----
    def exists(self, username: str) -> bool:
        return self.db_path(username).exists()

    def open(self, username: str) -> Store:
        """打开（必要时创建）某账号的库。"""
        path = self.db_path(username)
        path.parent.mkdir(parents=True, exist_ok=True)
        store = Store(path)
        store.set_meta("username", username)
        return store

    # ---- 列举与删除 ----
    def list(self, active: str = "") -> List[AccountInfo]:
        if not self.base.is_dir():
            return []
        out: List[AccountInfo] = []
        for child in sorted(self.base.iterdir()):
            if not child.is_dir():
                continue
            info = AccountInfo(username=child.name, path=child)
            info.size_bytes = _dir_size(child)
            info.is_active = bool(active) and child == self.dir_for(active)
            db = child / "matu.db"
            if db.exists():
                try:
                    store = Store(db)
                    meta = {
                        r["key"]: r["value"]
                        for r in store.conn.execute("SELECT key, value FROM meta")
                    }
                    # 目录名是账号的安全化结果，真实账号存在 meta 里
                    info.username = meta.get("username") or child.name
                    info.last_crawl = meta.get("last_crawl", "")
                    s = store.stats()
                    info.tasks = s.get("题目总数", 0)
                    info.tasks_with_detail = s.get("题目详情已抓", 0)
                    info.homework_tasks = s.get("作业内题目数", 0)
                    info.submissions = s.get("提交记录数", 0)
                    info.classes = store.conn.execute(
                        "SELECT COUNT(*) FROM classes").fetchone()[0]
                    store.close()
                except Exception as exc:                  # noqa: BLE001
                    info.error = f"{type(exc).__name__}: {exc}"
            else:
                info.error = "目录里没有数据库"
            out.append(info)
        return out

    def delete(self, username: str) -> int:
        """删除某账号的全部本地数据，返回释放的字节数。"""
        path = self.dir_for(username)
        if not path.exists():
            return 0
        freed = _dir_size(path)
        shutil.rmtree(path, ignore_errors=True)
        return freed

    def touch_crawl(self, username: str, store: Store) -> None:
        """记录一次加载完成的时间。"""
        store.set_meta("last_crawl", time.strftime("%Y-%m-%d %H:%M:%S"))


def _dir_size(path: Path) -> int:
    total = 0
    for p in path.rglob("*"):
        try:
            if p.is_file():
                total += p.stat().st_size
        except OSError:
            pass
    return total
