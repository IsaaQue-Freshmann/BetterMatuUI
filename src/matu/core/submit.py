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
from datetime import datetime
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


MAX_SUBMISSION_PAGES = 20      # 防呆上限：一道题的提交记录页数


def fetch_task_submissions(client: MatuClient, task_id: int,
                           pages: Optional[str] = "all"
                           ) -> Tuple[List[Submission], str]:
    """拉某道题的提交记录（对应网站「题目中心 / 作业状态」按题筛）。

    **必须翻页**：这个列表按时间升序，每页 10 条，第 1 页永远是最早的记录。
    以前只取第 1 页，于是提交数一超过 10 条，新记录就"查不到"了 ——
    提交成功却说"站点没返回数据"、文件列表也缺记录，根子都在这里。

    pages="all" 取全部；pages="last" 只取最后一页（找最新记录时最省）。
    同时返回第一页的原始 HTML，供调用方判断会话是否失效。
    """
    first_url = LIST_BY_TASK.format(task_id=task_id)
    first = client.get(first_url)
    html = first.text
    total = max(1, P.parse_pager(html)[1])

    collected = [s for s in P.parse_submissions(html) if s.task_id == task_id]
    if pages == "last" and total > 1:
        collected = []
        page_range = [total]
    else:
        page_range = range(2, min(total, MAX_SUBMISSION_PAGES) + 1)

    for page in page_range:
        page_html = client.get(f"{first_url}&page={page}").text
        collected += [s for s in P.parse_submissions(page_html)
                      if s.task_id == task_id]
    return collected, html


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
        """得分。

        **以成绩详单里的扣分为准**（得分 = 100 - 扣分）：提交刚结束时，
        列表页那一栏的分数可能还是 0（判题结果写库比列表刷新早不了多少），
        按列表读就会把 75 分显示成 0 分，用户得手动刷新几次才对 —— 这里
        直接用详单里的扣分反推，一次就准。
        """
        deduction = self.deduction
        if deduction is not None:
            return max(0, 100 - deduction)
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

    # 如果 POST 拿回来的是登录页，说明请求在会话失效的状态下被退回，**这一次
    # 根本没提交**（不是"提交了但没记录"）。补登录后重试一次是安全的。
    if client.relogin_hook is not None and client.looks_like_login_page(resp.text):
        if client.relogin_hook():
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


MAX_RESULT_AGE_SECONDS = 1800      # 只接受最近半小时内的记录作为"本次结果"

# 站点在提交记录的状态列上给的标记：
#   test  = 已生成记录但还没判完（此时分数列是 0、成绩详单是空的）
#   score = 已经判完，分数与扣分是最终值
JUDGED_STATUS = "score"
JUDGE_POLL_INTERVAL = 2.0          # 等待判题时的轮询间隔
JUDGE_TIMEOUT = 120.0              # 总等待上限（秒）


def is_judged(sub: Submission) -> bool:
    """这条记录判完了没有。"""
    return (sub.status or "").strip().lower() == JUDGED_STATUS


def _submitted_recently(when: str, max_age: int = MAX_RESULT_AGE_SECONDS) -> bool:
    """提交时间是不是足够新。

    这是防"假结果"的关键：如果本次提交其实没成功（站点没记录），
    仅凭 assignment_id 比基线大，可能会把站点上**别的**记录当成这次的结果，
    于是界面显示一个 0 分，但站点上根本没有这条提交。
    """
    try:
        stamp = datetime.strptime((when or "")[:19], "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return True                    # 解析不了就不拦，交给 assignment_id 判断
    return abs((datetime.now() - stamp).total_seconds()) <= max_age


def find_submission(client: MatuClient, task_id: int,
                    after_assignment_id: int = 0) -> Optional[Submission]:
    """在"作业状态"里找这道题**本次**新增的那条提交记录。

    两个条件同时满足才算：assignment_id 比基线大，且提交时间是最近的。
    """
    # 只看最后一页：列表按时间升序，最新的记录一定在末页
    subs, _html = fetch_task_submissions(client, task_id, pages="last")
    fresh = [s for s in subs
             if s.assignment_id > after_assignment_id
             and _submitted_recently(s.submitted_at)]
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
    result_attempts: Optional[int] = None,      # 兼容旧调用，已由超时替代
    result_interval: float = JUDGE_POLL_INTERVAL,
    on_progress=None,
) -> SubmitOutcome:
    """提交一次，并**等到站点真的判完**再返回。

    关键在"判完"的判定：站点的提交记录有个状态列 ——
        test  = 记录已生成，但还没判（分数列 0、成绩详单为空）
        score = 判完了，分数与扣分是最终值
    以前只看"有没有新记录"，拿到一条 test 状态的记录就当结果报出去，
    于是界面显示 0 分，用户得刷新两三次才看到真实的 90 分。

    现在按**状态**等，不看固定时间：一直轮询到状态变成 score，或者等满
    JUDGE_TIMEOUT 秒。等待期间通过 on_progress 汇报进度，界面显示"判题中"。
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

    report = on_progress or (lambda _m: None)
    deadline = time.monotonic() + JUDGE_TIMEOUT
    saw_record = False
    while True:
        found = find_submission(client, task_id,
                                after_assignment_id=known_latest_assignment_id)
        if found is not None:
            saw_record = True
            outcome.submission = found
            if is_judged(found):
                # 判完了：详单是权威值（得分 = 100 - 扣分）
                outcome.score_detail = fetch_score_detail(client, found.assignment_id)
                return outcome
            report("站点已收到提交，正在判题…")
        else:
            report("等待站点生成提交记录…")
        if time.monotonic() >= deadline:
            break
        time.sleep(result_interval)

    if saw_record:
        outcome.message = (f"站点已收到提交，但等待 {int(JUDGE_TIMEOUT)} 秒仍未判完。"
                           f"点「刷新历史」可以随时查看最新结果。")
    else:
        outcome.message = (
            "站点返回了「上传成功」，但没有生成提交记录 —— "
            "通常是站点的判题服务繁忙或丢单，请稍后重试。你的代码还在编辑器里。")
    return outcome

    # 站点回了「上传成功」却没生成记录 —— 实测会遇到（判题服务繁忙时会丢单）。
    # 这时候绝不能报一个分数出来：既不能拿旧记录冒充本次结果，也不该说"已完成"。
    # 如实告知，让用户稍后重试（代码还在编辑器里，不会丢）。
    outcome.message = (
        "站点返回了「上传成功」，但没有生成提交记录 —— "
        "通常是站点的判题服务繁忙或丢单，请稍后重试。你的代码还在编辑器里。")
    return outcome
