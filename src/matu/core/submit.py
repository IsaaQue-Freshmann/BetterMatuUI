"""提交与结果拉取。App 的"提交"按钮和"提交结果"栏都走这里。

提交流程（已在真实站点上验证过一次，见 docs/interfaces.md）：
    1. POST 源码内容到 upload_assignment_by_copy_paste
    2. 站点跳转到结果/状态页
    3. 从"作业状态"里定位这条新记录，取 assignment_id
    4. 拉该 assignment 的 scoredetail，拿到扣分与失败原因

设计约束：
- 提交只做一次，不自动重试。失败就如实报错，绝不静默重发
  （每题只有 100 次额度，重试是拿用户额度换容错）。
- 结果拉取只做有限次，不做定时轮询。
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from . import parsers as P
from .client import BASE_URL, MatuClient
from .models import Submission

UPLOAD_PAGE = (
    "/assignment/upload?task.id={task_id}"
    "&uploadMethod=upload_copy_paste&taskGroupTask.id={tgt_id}&taskGroup.id={group_id}"
)
UPLOAD_COPY_PASTE = "/assignment/upload_assignment_by_copy_paste"
LIST_BY_TASK = "/assignment/listassignment?taskid={task_id}"
SCORE_DETAIL = "/assignment/scoredetail?assignmentid={aid}"
DOWNLOAD_FILE = "/file/downloadassignmentfile?assignmentid={aid}"


def fetch_submitted_code(client: MatuClient, assignment_id: int) -> Tuple[str, str]:
    """取回某次提交的源码 —— 这就是"回溯"的数据来源。

    实测：`downloadassignmentfile` 返回 `text/plain`，正文就是当初提交的源码，
    Content-Disposition 里的文件名形如
    `题名_账号_时间戳.cpp`。
    返回 (源码, 文件名)。
    """
    resp = client.get(DOWNLOAD_FILE.format(aid=assignment_id), cache=False)
    filename = ""
    disposition = resp.headers.get("Content-Disposition", "")
    m = re.search(r'filename="?([^";]+)"?', disposition)
    if m:
        filename = m.group(1)
        # 站点用 GBK 编码文件名，requests 按 latin-1 解出来会是乱码
        try:
            filename = filename.encode("latin-1").decode("gbk")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    return resp.content.decode("utf-8", errors="replace"), filename


def fetch_task_submissions(client: MatuClient, task_id: int) -> Tuple[List[Submission], str]:
    """拉某道题的全部提交记录（对应网站「题目中心 / 作业状态」按题筛）。

    同时返回原始 HTML：会话失效时站点会把任何页面退回登录页，
    调用方需要靠它判断"拿到的其实是登录页"。
    """
    html = client.get(LIST_BY_TASK.format(task_id=task_id)).text
    subs = [s for s in P.parse_submissions(html) if s.task_id == task_id]
    return subs, html


def parse_deduction(detail_text: str) -> Optional[int]:
    """从成绩详单正文里取扣分。满分时站点给的是空正文，返回 None。"""
    m = re.search(r"扣分\s*[:：]\s*(\d+)", detail_text or "")
    return int(m.group(1)) if m else None


def parse_reason(detail_text: str) -> str:
    """取扣分原因：去掉"扣分:N"那一行后的正文。满分时为空字符串。"""
    lines = [
        ln.strip() for ln in (detail_text or "").splitlines()
        if ln.strip() and not re.match(r"^扣分\s*[:：]\s*\d+\s*$", ln.strip())
    ]
    return "\n".join(lines)


@dataclass
class SubmitOutcome:
    """一次提交的完整结果，供界面展示与排障。"""

    ok: bool                                # 站点是否明确回了"上传成功"
    message: str = ""                       # 面向用户的说明
    redirect_chain: List[Tuple[str, int]] = field(default_factory=list)
    landed_url: str = ""
    landed_html: str = ""
    landed_text: str = ""                   # 落地页可见文本
    status_url: str = ""                    # 成功页"查看状态"指向的地址
    submission: Optional[Submission] = None  # 站点上对应的那条记录
    score_detail: str = ""                   # 扣分与失败原因
    elapsed: float = 0.0

    @property
    def score(self) -> Optional[int]:
        if self.submission and self.submission.score is not None:
            return self.submission.score
        return None

    @property
    def deduction(self) -> Optional[int]:
        """扣分。站点给的是"扣分:N"，得分 = 100 - N。满分时该页为空，返回 None。"""
        return parse_deduction(self.score_detail)

    @property
    def reason(self) -> str:
        """扣分原因。满分时为空字符串。"""
        return parse_reason(self.score_detail)

    @property
    def is_full_score(self) -> bool:
        return self.score == 100

    def summary(self) -> str:
        """给界面用的一句话结论。"""
        if not self.ok:
            return self.message or "提交未成功"
        if self.score is None:
            return "提交成功，站点暂未返回分数"
        if self.is_full_score:
            return "提交成功 · 满分 100"
        return f"提交成功 · 得分 {self.score}（扣分 {self.deduction}）"


def submit_source(
    client: MatuClient,
    *,
    task_id: int,
    task_name: str,
    sourcecode: str,
    task_group_task_id: Optional[int] = None,
    task_group_id: Optional[int] = None,
) -> SubmitOutcome:
    """用"源码内容直接提交"方式提交一次。

    只提交一次，不重试。重定向链逐跳记录下来，便于确认落到哪个页面。
    """
    tgt = task_group_task_id if task_group_task_id is not None else ""
    grp = task_group_id if task_group_id is not None else ""

    # 先打开提交页。一个是让会话/preflight 状态正确，二是界面上要复用这页的字段。
    client.get(UPLOAD_PAGE.format(task_id=task_id, tgt_id=tgt, group_id=grp))

    payload = {
        "taskGroupTask.id": str(tgt),
        "taskGroup.id": str(grp),
        "task.id": str(task_id),
        "task.name": task_name,
        "sourcecode": sourcecode,
        "Submit": "提交",
    }

    started = time.monotonic()
    chain: List[Tuple[str, int]] = []
    page_url = BASE_URL + UPLOAD_PAGE.format(task_id=task_id, tgt_id=tgt, group_id=grp)

    # 提交本身：POST 且不自动跟跳转，先看清站点怎么回应。
    resp = client.post(UPLOAD_COPY_PASTE, data=payload, referer=page_url,
                       allow_redirects=False)
    chain.append((resp.url, resp.status_code))

    # 跟随跳转时**一律改用 GET**（浏览器的行为也是把 302/303 转成 GET）。
    # 绝不对跳转目标再发一次 POST —— 那会变成意外重复提交。
    hops = 0
    while (resp.status_code in (301, 302, 303, 307, 308)
           and "location" in resp.headers and hops < 5):
        loc = resp.headers["location"]
        nxt = loc if loc.startswith("http") else BASE_URL + (
            loc if loc.startswith("/") else "/" + loc
        )
        resp = client.get(nxt.replace(BASE_URL, ""), referer=page_url,
                          allow_redirects=False)
        chain.append((resp.url, resp.status_code))
        hops += 1

    elapsed = time.monotonic() - started
    landed = resp.text if resp is not None else ""

    # 实测：提交成功时站点返回 200，正文是"上传成功！查看状态"的小页面，
    # **不跳转**。所以不能只看状态码，必须看正文有没有"上传成功"。
    from bs4 import BeautifulSoup
    landed_text = (
        BeautifulSoup(landed, "lxml").get_text(" ", strip=True) if landed else ""
    )
    ok = "上传成功" in landed_text
    status_url = ""
    m = re.search(r"location\.href\s*=\s*['\"]([^'\"]+)['\"]", landed)
    if m:
        status_url = m.group(1)

    return SubmitOutcome(
        ok=ok,
        message=("上传成功" if ok else
                 (landed_text[:120] or f"站点返回 {getattr(resp, 'status_code', '无响应')}")),
        redirect_chain=chain,
        landed_url=resp.url if resp is not None else "",
        landed_html=landed,
        landed_text=landed_text[:2000],
        status_url=status_url,
        elapsed=elapsed,
    )


def find_submission(client: MatuClient, task_id: int,
                    after_assignment_id: int = 0) -> Optional[Submission]:
    """在"作业状态"里找这道题最新的一条提交记录。

    按 assignment_id 最大值取最新，不会把历史记录误当成这次的结果。
    """
    html = client.get(LIST_BY_TASK.format(task_id=task_id)).text
    subs = [s for s in P.parse_submissions(html) if s.task_id == task_id]
    fresh = [s for s in subs if s.assignment_id > after_assignment_id]
    if not fresh:
        return None
    return max(fresh, key=lambda s: s.assignment_id)


def fetch_score_detail(client: MatuClient, assignment_id: int) -> str:
    return P.parse_score_detail(client.get(SCORE_DETAIL.format(aid=assignment_id)).text)


def submit_and_collect(
    client: MatuClient,
    *,
    task_id: int,
    task_name: str,
    sourcecode: str,
    task_group_task_id: Optional[int] = None,
    task_group_id: Optional[int] = None,
    known_latest_assignment_id: int = 0,
    result_attempts: int = 3,
    result_interval: float = 3.0,
) -> SubmitOutcome:
    """提交一次并拉取结果。

    结果拉取做**有限次**尝试（默认最多 3 次、间隔 3 秒），因为站点评测可能不是
    同步完成的；但绝不做定时轮询——拉不到就如实告诉用户"结果还没出来"。
    """
    outcome = submit_source(
        client,
        task_id=task_id,
        task_name=task_name,
        sourcecode=sourcecode,
        task_group_task_id=task_group_task_id,
        task_group_id=task_group_id,
    )
    if not outcome.ok:
        return outcome

    for attempt in range(result_attempts):
        found = find_submission(client, task_id, after_assignment_id=known_latest_assignment_id)
        if found is not None:
            outcome.submission = found
            outcome.score_detail = fetch_score_detail(client, found.assignment_id)
            return outcome
        if attempt < result_attempts - 1:
            time.sleep(result_interval)

    outcome.message = "提交已完成，但站点暂未返回评测结果，请稍后手动刷新。"
    return outcome
