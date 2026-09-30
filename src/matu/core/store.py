"""本地存储：SQLite 落库 + JSON 快照导出。

设计成可断点续传：每题记录 detail_fetched 标记，重跑只补没抓到的部分，
不会重复请求已经拿过的页面。
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Iterable, List, Optional

from .models import HomeworkTask, Submission, Task


class _LockedConn:
    """给 sqlite3 连接套一层锁。

    两个问题一起解决：
    1. sqlite3 默认禁止跨线程使用连接，而加载/回溯/刷新都跑在后台线程里；
    2. 后台线程与界面线程可能同时读写。

    关掉 check_same_thread（在 connect 处）并让所有访问都过这把锁，
    已有的 conn.execute(...) 调用无需改动就变成线程安全的。
    """

    def __init__(self, conn: sqlite3.Connection, lock: threading.RLock) -> None:
        self._conn = conn
        self._lock = lock

    def execute(self, *args, **kwargs):
        with self._lock:
            return self._conn.execute(*args, **kwargs)

    def executemany(self, *args, **kwargs):
        with self._lock:
            return self._conn.executemany(*args, **kwargs)

    def executescript(self, *args, **kwargs):
        with self._lock:
            return self._conn.executescript(*args, **kwargs)

    def commit(self) -> None:
        with self._lock:
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __getattr__(self, name):
        return getattr(self._conn, name)

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    task_id        INTEGER PRIMARY KEY,
    name           TEXT DEFAULT '',
    teacher        TEXT DEFAULT '',
    language       TEXT DEFAULT '',
    platform       TEXT DEFAULT '',
    compiler       TEXT DEFAULT '',
    compile_type   TEXT DEFAULT '',
    created_at     TEXT DEFAULT '',
    description    TEXT DEFAULT '',
    detail_fetched INTEGER DEFAULT 0,
    fetched_at     TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS classes (
    class_id INTEGER PRIMARY KEY,
    course   TEXT DEFAULT '',
    name     TEXT DEFAULT '',
    score    TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS homework_groups (
    task_group_id INTEGER PRIMARY KEY,
    class_id      INTEGER,
    name          TEXT DEFAULT '',
    weight        REAL,
    created_at    TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS homework_tasks (
    task_group_task_id INTEGER PRIMARY KEY,
    task_group_id      INTEGER,
    task_id            INTEGER,
    class_id           INTEGER,
    name               TEXT DEFAULT '',
    language           TEXT DEFAULT '',
    max_submissions    INTEGER,
    score              REAL
);

CREATE TABLE IF NOT EXISTS submissions (
    assignment_id  INTEGER PRIMARY KEY,
    task_id        INTEGER,
    name           TEXT DEFAULT '',
    language       TEXT DEFAULT '',
    submitted_at   TEXT DEFAULT '',
    status         TEXT DEFAULT '',
    score          INTEGER,
    detail_url     TEXT DEFAULT '',
    download_url   TEXT DEFAULT '',
    detail_text    TEXT DEFAULT '',
    detail_fetched INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS drafts (
    draft_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id            INTEGER NOT NULL,
    task_group_task_id INTEGER DEFAULT 0,
    task_group_id      INTEGER DEFAULT 0,
    name               TEXT DEFAULT '',
    code               TEXT DEFAULT '',
    created_at         TEXT DEFAULT '',
    updated_at         TEXT DEFAULT '',
    from_assignment_id INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


# 旧的库需要就地升级的列（重复执行会报错，忽略即可）
MIGRATIONS = (
    "ALTER TABLE submissions ADD COLUMN code_text TEXT DEFAULT ''",
)


class Store:
    def __init__(self, path) -> None:
        # ":memory:" 用于"当前没有账号"时的空库，让界面代码不必到处判空
        self.path = Path(path) if str(path) != ":memory:" else Path(":memory:")
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        raw = sqlite3.connect(
            ":memory:" if str(self.path) == ":memory:" else str(self.path),
            check_same_thread=False)      # 后台线程也要读写同一个库
        raw.row_factory = sqlite3.Row
        self.conn = _LockedConn(raw, self._lock)
        self.conn.executescript(SCHEMA)
        for sql in MIGRATIONS:
            try:
                self.conn.execute(sql)
            except sqlite3.OperationalError:
                pass          # 列已存在
        self.conn.commit()

    @property
    def is_empty_db(self) -> bool:
        return str(self.path) == ":memory:"

    def close(self) -> None:
        self.conn.commit()
        self.conn.close()

    def set_meta(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO meta(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        self.conn.commit()

    # ---------------- 题目 ----------------

    def save_tasks(self, tasks: Iterable[Task]) -> int:
        rows = [
            (t.task_id, t.name, t.teacher, t.language, t.platform, t.compiler,
             t.compile_type, t.created_at)
            for t in tasks
        ]
        self.conn.executemany(
            "INSERT INTO tasks(task_id, name, teacher, language, platform, compiler,"
            " compile_type, created_at) VALUES(?,?,?,?,?,?,?,?) "
            "ON CONFLICT(task_id) DO UPDATE SET name=excluded.name,"
            " teacher=excluded.teacher, language=excluded.language,"
            " platform=excluded.platform, compiler=excluded.compiler,"
            " compile_type=excluded.compile_type, created_at=excluded.created_at",
            rows,
        )
        self.conn.commit()
        return len(rows)

    def save_task_detail(self, task_id: int, description: str,
                         name: str = "", language: str = "") -> None:
        self.conn.execute(
            "UPDATE tasks SET description=?, "
            "name=CASE WHEN ?<>'' THEN ? ELSE name END, "
            "language=CASE WHEN ?<>'' THEN ? ELSE language END, "
            "detail_fetched=1, fetched_at=? WHERE task_id=?",
            (description, name, name, language, language,
             time.strftime("%Y-%m-%d %H:%M:%S"), task_id),
        )
        self.conn.commit()

    def pending_detail_ids(self) -> List[int]:
        cur = self.conn.execute(
            "SELECT task_id FROM tasks WHERE detail_fetched=0 ORDER BY task_id"
        )
        return [r["task_id"] for r in cur.fetchall()]

    def all_task_ids(self) -> List[int]:
        cur = self.conn.execute("SELECT task_id FROM tasks ORDER BY task_id")
        return [r["task_id"] for r in cur.fetchall()]

    # ---------------- 班级 ----------------

    def save_classes(self, classes: Iterable[dict]) -> int:
        rows = [(c["class_id"], c.get("course", ""), c.get("name", ""),
                 str(c.get("score", ""))) for c in classes]
        self.conn.executemany(
            "INSERT INTO classes(class_id, course, name, score) VALUES(?,?,?,?)"
            " ON CONFLICT(class_id) DO UPDATE SET course=excluded.course,"
            " name=excluded.name, score=excluded.score",
            rows,
        )
        self.conn.commit()
        return len(rows)

    # ---------------- 作业 ----------------

    def save_homework_groups(self, groups: Iterable[dict], class_id: int) -> None:
        self.conn.executemany(
            "INSERT INTO homework_groups(task_group_id, class_id, name, weight, created_at)"
            " VALUES(?,?,?,?,?) ON CONFLICT(task_group_id) DO UPDATE SET"
            " name=excluded.name, weight=excluded.weight, created_at=excluded.created_at",
            [(g["task_group_id"], class_id, g.get("name", ""), g.get("weight"),
              g.get("created_at", "")) for g in groups],
        )
        self.conn.commit()

    def save_homework_tasks(self, items: Iterable[dict], class_id: int) -> None:
        self.conn.executemany(
            "INSERT INTO homework_tasks(task_group_task_id, task_group_id, task_id,"
            " class_id, name, language, max_submissions, score) VALUES(?,?,?,?,?,?,?,?)"
            " ON CONFLICT(task_group_task_id) DO UPDATE SET"
            " name=excluded.name, language=excluded.language,"
            " max_submissions=excluded.max_submissions, score=excluded.score",
            [(i["task_group_task_id"], i["task_group_id"], i["task_id"], class_id,
              i.get("name", ""), i.get("language", ""), i.get("max_submissions"),
              i.get("score")) for i in items],
        )
        self.conn.commit()

    # ---------------- 提交记录 ----------------

    def save_submissions(self, subs: Iterable[Submission]) -> int:
        rows = [(s.assignment_id, s.task_id, s.name, s.language, s.submitted_at,
                 s.status, s.score, s.detail_url, s.download_url) for s in subs]
        self.conn.executemany(
            "INSERT INTO submissions(assignment_id, task_id, name, language, submitted_at,"
            " status, score, detail_url, download_url) VALUES(?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(assignment_id) DO UPDATE SET status=excluded.status,"
            " score=excluded.score, detail_url=excluded.detail_url,"
            " download_url=excluded.download_url",
            rows,
        )
        self.conn.commit()
        return len(rows)

    def save_submission_detail(self, assignment_id: int, text: str) -> None:
        self.conn.execute(
            "UPDATE submissions SET detail_text=?, detail_fetched=1 WHERE assignment_id=?",
            (text, assignment_id),
        )
        self.conn.commit()

    def get_submission(self, assignment_id: int) -> Optional[dict]:
        row = self.conn.execute(
            "SELECT * FROM submissions WHERE assignment_id=?", (assignment_id,)).fetchone()
        return dict(row) if row else None

    def save_submission_code(self, assignment_id: int, code: str) -> None:
        """缓存某次提交的源码，供"回溯"用（缓存过就不必再联网）。"""
        self.conn.execute(
            "UPDATE submissions SET code_text=? WHERE assignment_id=?",
            (code, assignment_id),
        )
        self.conn.commit()

    def pending_submission_ids(self) -> List[int]:
        cur = self.conn.execute(
            "SELECT assignment_id FROM submissions WHERE detail_fetched=0"
            " ORDER BY assignment_id"
        )
        return [r["assignment_id"] for r in cur.fetchall()]

    # ---------------- 界面查询 ----------------

    def get_classes(self) -> List[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM classes ORDER BY class_id").fetchall()]

    def get_homework_groups(self, class_id: Optional[int] = None) -> List[dict]:
        if class_id is None:
            rows = self.conn.execute(
                "SELECT * FROM homework_groups ORDER BY class_id, task_group_id").fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM homework_groups WHERE class_id=? ORDER BY task_group_id",
                (class_id,)).fetchall()
        return [dict(r) for r in rows]

    def get_homework_tasks(self, task_group_id: int) -> List[dict]:
        rows = self.conn.execute(
            "SELECT * FROM homework_tasks WHERE task_group_id=?"
            " ORDER BY task_group_task_id", (task_group_id,)).fetchall()
        return [dict(r) for r in rows]

    def get_task(self, task_id: int) -> Optional[dict]:
        row = self.conn.execute(
            "SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        return dict(row) if row else None

    def count_submissions(self, task_id: int) -> int:
        """某道题已提交的次数（算"剩余提交次数"用）。"""
        return int(self.conn.execute(
            "SELECT COUNT(*) FROM submissions WHERE task_id=?", (task_id,)).fetchone()[0])

    def max_submissions_for(self, task_id: int) -> Optional[int]:
        """从作业里查这道题允许的提交总次数。

        站点只在**作业内题目**上给这个值（题目总表里没有），所以从题库
        进入题目时要回作业表查一次。
        """
        row = self.conn.execute(
            "SELECT MAX(max_submissions) FROM homework_tasks WHERE task_id=?",
            (task_id,)).fetchone()
        return int(row[0]) if row and row[0] is not None else None

    def get_submissions(self, task_id: int, limit: int = 20) -> List[dict]:
        rows = self.conn.execute(
            "SELECT * FROM submissions WHERE task_id=?"
            " ORDER BY assignment_id DESC LIMIT ?", (task_id, limit)).fetchall()
        return [dict(r) for r in rows]

    def get_submissions_all(self, limit: int = 500) -> List[dict]:
        """全部提交记录，最近在前（对应站点的「作业状态」）。"""
        rows = self.conn.execute(
            "SELECT * FROM submissions ORDER BY assignment_id DESC LIMIT ?",
            (limit,)).fetchall()
        return [dict(r) for r in rows]

    def get_task_grades(self) -> List[dict]:
        """按题汇总（对应站点的「提交总结」）：提交次数与最高分。"""
        rows = self.conn.execute(
            "SELECT task_id, MAX(name) AS name, COUNT(*) AS n,"
            " MAX(score) AS best, MAX(submitted_at) AS last_at"
            " FROM submissions GROUP BY task_id ORDER BY task_id").fetchall()
        return [dict(r) for r in rows]

    # ---------------- 本地草稿文件 ----------------

    def create_draft(self, task_id: int, name: str = "", code: str = "",
                     task_group_task_id: int = 0, task_group_id: int = 0,
                     from_assignment_id: int = 0) -> int:
        """新建一个本地文件。名字默认按时间取，重名自动加序号。"""
        if not name:
            # 带题目编号：一眼能看出这份文件属于哪道题，也避免跨题混淆
            name = f"#{task_id} 新文件 {time.strftime('%Y-%m-%d %H:%M:%S')}"
        base, n = name, 1
        while self.conn.execute("SELECT 1 FROM drafts WHERE task_id=? AND name=?",
                                (task_id, name)).fetchone():
            n += 1
            name = f"{base} ({n})"
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        cur = self.conn.execute(
            "INSERT INTO drafts(task_id, task_group_task_id, task_group_id, name,"
            " code, created_at, updated_at, from_assignment_id)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (task_id, task_group_task_id, task_group_id, name, code,
             stamp, stamp, from_assignment_id),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def update_draft_code(self, draft_id: int, code: str) -> None:
        self.conn.execute(
            "UPDATE drafts SET code=?, updated_at=? WHERE draft_id=?",
            (code, time.strftime("%Y-%m-%d %H:%M:%S"), draft_id))
        self.conn.commit()

    def rename_draft(self, draft_id: int, name: str) -> None:
        self.conn.execute("UPDATE drafts SET name=? WHERE draft_id=?", (name, draft_id))
        self.conn.commit()

    def get_draft(self, draft_id: int) -> Optional[dict]:
        row = self.conn.execute("SELECT * FROM drafts WHERE draft_id=?",
                                (draft_id,)).fetchone()
        return dict(row) if row else None

    def get_drafts(self, task_id: int) -> List[dict]:
        """某题的本地文件，最近更新的在前。"""
        rows = self.conn.execute(
            "SELECT * FROM drafts WHERE task_id=? ORDER BY draft_id DESC",
            (task_id,)).fetchall()
        return [dict(r) for r in rows]

    def delete_draft(self, draft_id: int) -> None:
        self.conn.execute("DELETE FROM drafts WHERE draft_id=?", (draft_id,))
        self.conn.commit()

    # ---------------- 导出 ----------------

    def stats(self) -> dict:
        q = lambda sql: self.conn.execute(sql).fetchone()[0]
        by_type = {
            r["compile_type"]: r["n"] for r in self.conn.execute(
                "SELECT compile_type, COUNT(*) n FROM tasks GROUP BY compile_type"
            )
        }
        return {
            "题目总数": q("SELECT COUNT(*) FROM tasks"),
            "题目详情已抓": q("SELECT COUNT(*) FROM tasks WHERE detail_fetched=1"),
            "编译类型分布": by_type,
            "作业次数": q("SELECT COUNT(*) FROM homework_groups"),
            "作业内题目数": q("SELECT COUNT(*) FROM homework_tasks"),
            "提交记录数": q("SELECT COUNT(*) FROM submissions"),
            "提交详情已抓": q("SELECT COUNT(*) FROM submissions WHERE detail_fetched=1"),
        }

    def export_json(self, path: Path) -> None:
        def rows(sql: str) -> List[dict]:
            return [dict(r) for r in self.conn.execute(sql).fetchall()]

        snapshot = {
            "exported_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "source": "http://matu.uestc.edu.cn/aptat",
            "classes": rows("SELECT * FROM classes ORDER BY class_id"),
            "tasks": rows("SELECT * FROM tasks ORDER BY task_id"),
            "homework_groups": rows("SELECT * FROM homework_groups ORDER BY task_group_id"),
            "homework_tasks": rows(
                "SELECT * FROM homework_tasks ORDER BY task_group_id, task_group_task_id"
            ),
            "submissions": rows("SELECT * FROM submissions ORDER BY assignment_id"),
        }
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8"
        )
