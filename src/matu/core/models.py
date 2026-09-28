"""数据模型：题目、提交记录。"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class Task:
    """一道题目的全部可加载信息。

    字段与 `题目总表` 的列一一对应，description 来自题目详情页。
    """

    task_id: int
    name: str = ""
    teacher: str = ""
    language: str = ""          # 语言要求：C / C++
    platform: str = ""          # 平台：Windows / Linux
    compiler: str = ""          # 编译器：VC / GCC
    compile_type: str = ""      # 编译整个文件夹内容 / ...（老师提供teacher_main...） / 完型填空
    created_at: str = ""        # 出题时间
    description: str = ""       # 题目正文（详情页）
    detail_fetched: bool = False
    fetched_at: str = ""

    @property
    def needs_teacher_main(self) -> bool:
        return "teacher_main" in self.compile_type

    @property
    def is_fill_in_blank(self) -> bool:
        return "完型" in self.compile_type or "填空" in self.compile_type

    @property
    def is_folder_build(self) -> bool:
        return "文件夹" in self.compile_type

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class HomeworkTask:
    """某次作业里的一道题（题目 + 该次作业的附加信息）。

    允许提交次数在这个层级才有，是提交前的关键约束。
    """

    task_group_id: int          # 作业（TaskGroup）id
    task_group_task_id: int     # 作业内题目的 id，提交时必须带上
    task_id: int
    name: str = ""
    language: str = ""
    max_submissions: Optional[int] = None   # 允许提交次数
    score: Optional[float] = None           # 分值
    group_name: str = ""                    # 作业名称
    group_weight: Optional[float] = None    # 总分比例
    class_id: Optional[int] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Submission:
    """一条提交记录（作业状态页的每一行）。"""

    assignment_id: int
    task_id: int
    name: str = ""
    language: str = ""
    submitted_at: str = ""
    status: str = ""            # score / compile error / ...
    score: Optional[int] = None
    detail_url: str = ""
    download_url: str = ""
    detail_text: str = ""       # 成绩详单正文（扣分原因，评测失败信息）
    detail_fetched: bool = False

    def to_dict(self) -> dict:
        return asdict(self)
