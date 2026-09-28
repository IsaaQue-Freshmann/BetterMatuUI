#!/usr/bin/env python3
"""加载码图的题库与提交记录，落到 SQLite 与 JSON 快照。

只读工具：除了登录，全部请求都是 GET。本工具**不构造任何提交请求**，
也不会碰 upload_assignment_by_* 这类端点。

默认是断点续爬：已经抓过的题目详情/提交详情会跳过，重跑只补缺口，
所以中断了直接再跑一次就行，不会重复请求。

用法（凭据从环境变量 MATU_USER / MATU_PASS 读取）：

    .venv/bin/python tools/crawl.py tasks          # 题库（列表 + 详情）
    .venv/bin/python tools/crawl.py homework       # 我的班级 -> 作业 -> 作业内题目
    .venv/bin/python tools/crawl.py submissions    # 作业状态 + 成绩详单
    .venv/bin/python tools/crawl.py all            # 全部

常用参数：
    --interval 3.0   请求最小间隔秒数（默认 3.0，比探针更保守）
    --limit N        本次最多处理多少条详情，用于小步试跑
    --refresh        忽略断点，重新抓取详情
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from matu.core import parsers as P  # noqa: E402
from matu.core.accounts import AccountStore  # noqa: E402
from matu.core.client import MatuClient  # noqa: E402

# 数据按账号隔离存放（项目外），路径由 AccountStore 统一决定
P_TASK_LIST = "/task/listtotaltask?page={page}"
P_TASK_DETAIL = "/task/taskdetail?taskid={task_id}"
P_MY_CLASSES = "/course/liststudentclass?page={page}"
P_CLASS_HOMEWORK = "/task/liststudenttaskgroup?_class.id={class_id}&page={page}"
P_GROUP_TASKS = "/task/listTaskGroup_Task?taskGroup.id={group_id}"
P_SUBMISSIONS = "/assignment/listassignment?page={page}"
P_SCORE_DETAIL = "/assignment/scoredetail?assignmentid={aid}"


def ensure_login(client: MatuClient) -> None:
    user, password = os.environ.get("MATU_USER"), os.environ.get("MATU_PASS")
    if user and password:
        if client.login(user, password):
            print("[登录] 成功")
            return
        raise SystemExit("[登录] 失败，请检查凭据。")
    # 没有凭据就用已保存的会话，先验证会话还有效
    resp = client.get("/page/files/left.jsp")
    if MatuClient.looks_like_login_page(resp.text):
        raise SystemExit("[登录] 会话已失效，请从项目外的凭据文件注入 MATU_USER/MATU_PASS 后重跑。")
    print("[登录] 复用已保存的会话")


def crawl_task_list(client: MatuClient, store: Store,
                    refresh: bool = False, limit=None) -> None:
    """抓题目总表全部分页 + 每题详情。

    实现放在 core/refresh.py，界面上"为当前账号加载完整题库"用的是同一份代码。
    """
    from matu.core import refresh as R
    counts = R.refresh_task_bank(
        client, store,
        log=lambda m: print(f"[题库] {m}"),
        progress=lambda d, t, s: (d % 20 == 0 or d == t) and
                                 print(f"[题目详情] {d}/{t}（最近: {s[:24]}）"),
        refresh_details=refresh, limit=limit)
    print(f"[汇总] 分页 {counts['pages']} 页，详情 {counts['details']}/{counts['total_details']}")


def crawl_task_details(client: MatuClient, store: Store, limit=None, refresh=False) -> None:
    """兼容旧入口：只补详情（内部分页也走一遍，很快）。"""
    crawl_task_list(client, store, refresh=refresh, limit=limit)


def crawl_classes(client: MatuClient, store: Store) -> None:
    """只抓班级列表（课程名/班级名/分数）。界面里"c语言"这一级就来自这里。"""
    html = client.get(P_MY_CLASSES.format(page=1)).text
    classes = _parse_classes(html)
    store.save_classes(classes)
    for c in classes:
        print(f"[班级] {c['class_id']}  {c['course']} / {c['name']}  分数 {c['score']}")


def crawl_homework(client: MatuClient, store: Store) -> None:
    """我的班级 -> 每次作业 -> 作业内题目。

    实现放在 core/refresh.py，界面上的"刷新"用的是同一份代码。
    """
    from matu.core import refresh as R
    counts = R.refresh_class_data(client, store, log=lambda m: print(f"[班级] {m}"))
    print(f"[汇总] 班级 {counts['classes']} 个，作业 {counts['groups']} 次，"
          f"作业内题目 {counts['tasks']} 道")


def _parse_classes(html: str) -> list:
    """解析 `我的班级`，取班级 id（链接形如 liststudenttaskgroup?_class.id=641）。"""
    import re
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    found = {}
    for a in soup.find_all("a", href=re.compile(r"_class\.id=(\d+)")):
        m = re.search(r"_class\.id=(\d+)", a["href"])
        if not m:
            continue
        cid = int(m.group(1))
        if cid in found:
            continue
        row = a.find_parent("tr")
        cells = [c.get_text(" ", strip=True) for c in row.find_all("td", recursive=False)] if row else []
        found[cid] = {
            "class_id": cid,
            "course": cells[0] if cells else "",
            "name": cells[1] if len(cells) > 1 else "",
            "score": cells[2] if len(cells) > 2 else "",
        }
    return list(found.values())


def crawl_submissions(client: MatuClient, store: Store, detail_limit=None, refresh=False) -> None:
    """作业状态（提交记录）+ 成绩详单。"""
    page, total = 1, 1
    while page <= total:
        html = client.get(P_SUBMISSIONS.format(page=page)).text
        subs = P.parse_submissions(html)
        total = max(total, P.parse_pager(html)[1])
        store.save_submissions(subs)
        print(f"[提交记录] 第 {page}/{total} 页，{len(subs)} 条")
        page += 1

    ids = store.pending_submission_ids() if not refresh else [
        r["assignment_id"] for r in store.conn.execute("SELECT assignment_id FROM submissions")
    ]
    if detail_limit:
        ids = ids[:detail_limit]
    print(f"[成绩详单] 待抓 {len(ids)} 条")
    for i, aid in enumerate(ids, 1):
        store.save_submission_detail(aid, P.parse_score_detail(client.get(
            P_SCORE_DETAIL.format(aid=aid)).text))
        if i % 5 == 0 or i == len(ids):
            print(f"[成绩详单] {i}/{len(ids)}")


def main() -> int:
    parser = argparse.ArgumentParser(description="码图只读爬虫（不会提交任何代码）")
    parser.add_argument("what", choices=["classes", "tasks", "details", "homework",
                                         "submissions", "all"])
    parser.add_argument("--account", default="", help="账号名（默认取环境变量 MATU_USER）")
    # 0.5 秒/题：站点的结构对所有账号统一，但内容随账号不同，
    # 换账号要整份重爬，所以这里比探针阶段放快一些，仍是串行、无并发。
    parser.add_argument("--interval", type=float, default=0.2, help="请求最小间隔秒数（默认 0.2）")
    parser.add_argument("--jitter", type=float, default=0.05, help="叠加的随机抖动上限（默认 0.05）")
    parser.add_argument("--limit", type=int, default=None, help="详情类请求本run上限")
    parser.add_argument("--refresh", action="store_true", help="忽略断点，重新抓详情")
    args = parser.parse_args()

    username = args.account or os.environ.get("MATU_USER", "")
    if not username:
        print("需要账号：用 --account 指定，或从环境变量注入 MATU_USER。")
        return 2

    accounts = AccountStore()
    store = accounts.open(username)
    client = MatuClient(min_interval=args.interval, jitter=args.jitter,
                        max_requests=700, logger=None,
                        session_file=accounts.session_path(username))
    print(f"[账号] {username}  ->  {store.path}")
    ensure_login(client)

    if args.what in ("classes", "all"):
        crawl_classes(client, store)
    if args.what in ("tasks", "all"):
        crawl_task_list(client, store)
    if args.what in ("details", "tasks", "all"):
        crawl_task_details(client, store, args.limit, args.refresh)
    if args.what in ("homework", "all"):
        crawl_homework(client, store)
    if args.what in ("submissions", "all"):
        crawl_submissions(client, store, args.limit, args.refresh)

    accounts.touch_crawl(username, store)
    store.export_json(accounts.snapshot_path(username))
    print("\n===== 统计 =====")
    for k, v in store.stats().items():
        print(f"  {k}: {v}")
    print(f"\n数据库: {store.path}")
    print(f"JSON 快照: {accounts.snapshot_path(username)}")
    print(f"本次请求数: {client.request_count}（审计日志 ~/.bettermatu/requests.log）")
    store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
