"""数据中心的指标计算。

三个指标都归一到 0-100：

  正确率 = 拿过满分的题目数 / (这些题里未拿满分的提交次数 + 拿过满分的题目数)
           —— 分子是**题目数**而不是提交次数，所以反复刷同一道题不会提高它
  考勤度 = 日均提交次数（有提交的那天算 1，没提交的那天算 0.2，
           从账号 ID 前四位那年的 9 月 1 日起算）再映射到 0-100；
           用对数，20 次/天 = 100，再高也只是趋近 100，不会爆表
  狗卷度 = 拿过满分的题目数 / 该账号题库总题数

评级取三项均值：100-85 S，85-70 A，70-60 B，60-40 C，40 以下 D
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

# 考勤度锚点：日均多少次算满分
ATTENDANCE_ANCHOR = 20.0
# 没提交的那天按多少天计入分母
IDLE_DAY_WEIGHT = 0.2
# 热力图：53 个格子，每格 1 天
HEAT_CELLS = 53
HEAT_DAYS_PER_CELL = 1


@dataclass
class Stats:
    username: str = ""
    display_name: str = ""

    total_submissions: int = 0
    bank_size: int = 0
    tasks_with_100: int = 0
    non100_submissions: int = 0

    active_days: int = 0
    window_days: int = 0
    start_day: Optional[date] = None
    avg_per_day: float = 0.0

    accuracy: float = 0.0
    attendance: float = 0.0
    diligence: float = 0.0
    mean: float = 0.0
    grade: str = "D"

    per_day: Dict[str, int] = field(default_factory=dict)     # "YYYY-MM-DD" -> 次数
    first_submit_day: Optional[date] = None

    def explain(self) -> List[Tuple[str, str]]:
        """给界面用的口径说明，免得数字看起来像黑箱。"""
        return [
            ("正确率", f"{self.tasks_with_100} 道满分 / "
                       f"（{self.non100_submissions} 次非满分提交 + "
                       f"{self.tasks_with_100} 道满分）= {self.accuracy:.1f}"),
            ("考勤度", f"{self.total_submissions} 次提交 / {self.avg_per_day:.2f} 日均"
                       f"（{self.active_days} 个活跃日 + {self.window_days - self.active_days} "
                       f"个空日×0.01）→ {self.attendance:.1f}"),
            ("狗卷度", f"{self.tasks_with_100} 道满分 / 题库 {self.bank_size} 道 "
                       f"= {self.diligence:.1f}"),
        ]


def _parse_day(text: str) -> Optional[date]:
    try:
        return datetime.strptime((text or "")[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def attendance_start(username: str) -> Optional[date]:
    """考勤起算日 = 账号 ID 前四位那年的 9 月 1 日。"""
    head = (username or "")[:4]
    if head.isdigit():
        try:
            return date(int(head), 9, 1)
        except ValueError:
            return None
    return None


def grade_for(mean: float) -> str:
    """评级阈值。"""
    if mean >= 85:
        return "S"
    if mean >= 70:
        return "A"
    if mean >= 60:
        return "B"
    if mean >= 40:
        return "C"
    return "D"


def compute_stats(store, username: str = "", today: Optional[date] = None) -> Stats:
    """从本地库算全部指标。不发任何网络请求。"""
    today = today or date.today()
    st = Stats(username=username)
    st.bank_size = store.stats().get("题目总数", 0)

    rows = store.get_submissions_all(limit=100000)
    st.total_submissions = len(rows)
    if not rows:
        st.grade = grade_for(0.0)
        return st

    # 按日聚合（热力图与考勤度都用它）
    for r in rows:
        d = (r.get("submitted_at") or "")[:10]
        if d:
            st.per_day[d] = st.per_day.get(d, 0) + 1
    days = sorted(d for d in (_parse_day(k) for k in st.per_day) if d)
    st.first_submit_day = days[0] if days else None

    # ---- 正确率：分子按题目数算，避免刷分 ----
    tasks_100 = {r["task_id"] for r in rows if r.get("score") == 100}
    st.tasks_with_100 = len(tasks_100)
    st.non100_submissions = sum(
        1 for r in rows
        if r["task_id"] in tasks_100 and (r.get("score") or 0) != 100)
    denom = st.non100_submissions + st.tasks_with_100
    st.accuracy = (st.tasks_with_100 / denom * 100) if denom else 0.0

    # ---- 考勤度：活跃日算 1、空日算 0.01 ----
    start = attendance_start(username) or st.first_submit_day or today
    st.start_day = start
    st.window_days = max(1, (today - start).days + 1)
    st.active_days = sum(1 for d in days if start <= d <= today)
    weight = st.active_days * 1.0 + max(0, st.window_days - st.active_days) * IDLE_DAY_WEIGHT
    st.avg_per_day = (st.total_submissions / weight) if weight else 0.0
    if st.avg_per_day > 0:
        st.attendance = min(100.0, 100.0 * math.log1p(st.avg_per_day)
                            / math.log1p(ATTENDANCE_ANCHOR))
    else:
        st.attendance = 0.0

    # ---- 狗卷度：满分题目数 / 题库总数 ----
    st.diligence = (st.tasks_with_100 / st.bank_size * 100) if st.bank_size else 0.0

    st.mean = (st.accuracy + st.attendance + st.diligence) / 3.0
    st.grade = grade_for(st.mean)
    return st


def heat_cells(st: Stats, today: Optional[date] = None) -> List[Tuple[date, date, int]]:
    """热力图数据：(起始日, 结束日, 该格提交次数) 共 53 格，每格 1 天。

    最后一格就是今天，往前推 53 天。
    """
    today = today or date.today()
    total_days = HEAT_CELLS * HEAT_DAYS_PER_CELL
    first = today - timedelta(days=total_days - 1)
    cells: List[Tuple[date, date, int]] = []
    for i in range(HEAT_CELLS):
        cell_start = first + timedelta(days=i * HEAT_DAYS_PER_CELL)
        cell_end = cell_start + timedelta(days=HEAT_DAYS_PER_CELL - 1)
        count = sum(st.per_day.get((cell_start + timedelta(days=k)).isoformat(), 0)
                    for k in range(HEAT_DAYS_PER_CELL))
        cells.append((cell_start, cell_end, count))
    return cells


def daily_series(st: Stats, days: int = 30,
                 today: Optional[date] = None) -> List[Tuple[date, int]]:
    """折线图数据：最近 N 天的每日提交次数（没有提交的日子补 0）。"""
    today = today or date.today()
    out: List[Tuple[date, int]] = []
    for k in range(days - 1, -1, -1):
        d = today - timedelta(days=k)
        out.append((d, st.per_day.get(d.isoformat(), 0)))
    return out
