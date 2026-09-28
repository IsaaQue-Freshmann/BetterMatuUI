"""班级/作业数据的刷新逻辑。

界面右上角的"刷新"和 tools/crawl.py 的 homework 阶段共用这一份实现，
避免出现两套会走偏的代码。

请求量很小：班级列表 1 次 + 每次作业 1 次 + 每个班级的作业列表 1 次。
"""

from __future__ import annotations

import re
from typing import Callable, Dict, List, Optional

from bs4 import BeautifulSoup

from . import parsers as P
from .client import MatuClient
from .store import Store

P_MY_CLASSES = "/course/liststudentclass?page={page}"
P_CLASS_HOMEWORK = "/task/liststudenttaskgroup?_class.id={class_id}&page={page}"
P_GROUP_TASKS = "/task/listTaskGroup_Task?taskGroup.id={group_id}"
P_TASK_LIST = "/task/listtotaltask?page={page}"
P_TASK_DETAIL = "/task/taskdetail?taskid={task_id}"
P_SUBMISSIONS = "/assignment/listassignment?page={page}"
P_SCORE_DETAIL = "/assignment/scoredetail?assignmentid={aid}"


def refresh_task_bank(client: MatuClient, store: Store,
                      log: Optional[Callable[[str], None]] = None,
                      progress: Optional[Callable[[int, int, str], None]] = None,
                      refresh_details: bool = False,
                      limit: Optional[int] = None,
                      should_stop: Optional[Callable[[], bool]] = None,
                      on_task_saved: Optional[Callable[[int], None]] = None) -> Dict[str, int]:
    """抓「题目总表」的全部分页 + 每道题的详情。

    `题目总表` 是 listtotalvisibletask——**当前账号可见**的题，
    所以换账号之后必须重爬，不能沿用上一个账号的结果。

    progress(已完成, 总数, 当前项) 供界面显示进度；
    on_task_saved(task_id) 在每道题落库后回调，界面据此"边爬边往目录里加"；
    should_stop() 返回 True 时中途安全退出（已抓的部分都落库了，可断点续爬）。
    """
    say = log or (lambda _m: None)
    tick = progress or (lambda _d, _t, _s: None)
    saved = on_task_saved or (lambda _tid: None)

    first = client.get(P_TASK_LIST.format(page=1)).text
    tasks, _, total_pages = P.parse_task_list(first)
    store.save_tasks(tasks)
    for t in tasks:
        saved(t.task_id)
    say(f"题目总表 第 1/{total_pages} 页，{len(tasks)} 题")

    for page in range(2, total_pages + 1):
        if should_stop and should_stop():
            say("已停止（分页阶段）")
            break
        tasks, _, _ = P.parse_task_list(client.get(P_TASK_LIST.format(page=page)).text)
        store.save_tasks(tasks)
        for t in tasks:
            saved(t.task_id)
        # 分页阶段也要报进度，否则界面上几十秒看不出在动
        tick(page, total_pages, f"题目列表 第 {page} 页")
        say(f"题目总表 第 {page}/{total_pages} 页，{len(tasks)} 题")

    ids = (store.all_task_ids() if refresh_details else store.pending_detail_ids())
    if limit:
        ids = ids[:limit]
    total = len(ids)
    say(f"待抓详情 {total} 题")

    done = 0
    for task_id in ids:
        if should_stop and should_stop():
            say(f"已停止（详情阶段，已完成 {done}/{total}）")
            break
        detail = P.parse_task_detail(client.get(P_TASK_DETAIL.format(task_id=task_id)).text)
        store.save_task_detail(task_id, detail["description"],
                               detail["name"], detail["language"])
        done += 1
        saved(task_id)
        tick(done, total, detail["name"] or f"#{task_id}")
    return {"pages": total_pages, "details": done, "total_details": total}


def parse_classes(html: str) -> List[Dict[str, object]]:
    """解析「我的班级」，取课程名/班级名/分数。

    链接形如 liststudenttaskgroup?_class.id=641，班级 id 从这里取。
    """
    soup = BeautifulSoup(html, "lxml")
    found: Dict[int, Dict[str, object]] = {}
    for a in soup.find_all("a", href=re.compile(r"_class\.id=(\d+)")):
        m = re.search(r"_class\.id=(\d+)", a["href"])
        if not m:
            continue
        cid = int(m.group(1))
        if cid in found:
            continue
        row = a.find_parent("tr")
        cells = ([c.get_text(" ", strip=True) for c in row.find_all("td", recursive=False)]
                 if row else [])
        found[cid] = {
            "class_id": cid,
            "course": cells[0] if cells else "",
            "name": cells[1] if len(cells) > 1 else "",
            "score": cells[2] if len(cells) > 2 else "",
        }
    return list(found.values())


def refresh_submissions(client: MatuClient, store: Store,
                        log: Optional[Callable[[str], None]] = None,
                        progress: Optional[Callable[[int, int, str], None]] = None,
                        should_stop: Optional[Callable[[], bool]] = None) -> Dict[str, int]:
    """抓全部提交记录（作业状态）并补齐每条的扣分原因（成绩详单）。

    数据中心的三项指标全靠这里的数据，所以要排在题库之前先跑完。
    """
    say = log or (lambda _m: None)
    tick = progress or (lambda _d, _t, _s: None)

    page, total, saved = 1, 1, 0
    while page <= total:
        if should_stop and should_stop():
            say("已停止（提交记录分页阶段）")
            break
        html = client.get(P_SUBMISSIONS.format(page=page)).text
        subs = P.parse_submissions(html)
        total = max(total, P.parse_pager(html)[1])
        store.save_submissions(subs)
        saved += len(subs)
        say(f"提交记录 第 {page}/{total} 页，{len(subs)} 条")
        page += 1

    ids = [r["assignment_id"] for r in store.conn.execute(
        "SELECT assignment_id FROM submissions WHERE detail_fetched=0"
        " ORDER BY assignment_id")]
    if not ids:
        ids = [r["assignment_id"] for r in store.conn.execute(
            "SELECT assignment_id FROM submissions WHERE TRIM(COALESCE(detail_text,''))=''"
            " ORDER BY assignment_id")]
    total_detail = len(ids)
    done = 0
    for aid in ids:
        if should_stop and should_stop():
            say(f"已停止（成绩详单阶段，已完成 {done}/{total_detail}）")
            break
        store.save_submission_detail(aid, P.parse_score_detail(
            client.get(P_SCORE_DETAIL.format(aid=aid)).text))
        done += 1
        tick(done, total_detail, f"成绩详单 #{aid}")
    return {"submissions": saved, "details": done, "total_details": total_detail}


def refresh_all(client: MatuClient, store: Store,
                log: Optional[Callable[[str], None]] = None,
                phase: Optional[Callable[[str, float], None]] = None,
                progress: Optional[Callable[[int, int, str], None]] = None,
                should_stop: Optional[Callable[[], bool]] = None,
                on_task_saved: Optional[Callable[[int], None]] = None) -> Dict[str, int]:
    """整份数据抓取，顺序按用途排：

        ① 班级与作业   —— 体量小，先让"我的班级"可用
        ② 提交记录     —— 数据中心的三项指标靠它，必须早于题库
        ③ 题库全量     —— 体量最大（几百题），放最后

    phase(说明, 0~1) 汇报当前阶段；progress(已完成, 总数, 当前项) 汇报细粒度进度。
    """
    say = log or (lambda _m: None)
    told = phase or (lambda _s, _p: None)
    result: Dict[str, int] = {}

    told("① 正在加载我的班级…", 0.0)
    result.update(refresh_class_data(
        client, store, log=lambda m: told(f"① 我的班级　{m}", 0.12)))
    told("① 我的班级加载完成", 0.33)
    if should_stop and should_stop():
        return result

    told("② 正在加载提交记录与成绩详单…", 0.33)
    result.update(refresh_submissions(client, store, log=say, progress=progress,
                                      should_stop=should_stop))
    if should_stop and should_stop():
        return result

    told("③ 正在加载题库（题数较多）…", 0.66)
    result.update(refresh_task_bank(client, store, log=say, progress=progress,
                                    refresh_details=True, should_stop=should_stop,
                                    on_task_saved=on_task_saved))
    told("全部加载完成", 1.0)
    return result


def bank_totals(client: MatuClient, store: Store) -> Tuple[int, int]:
    """对比"本地已加载的题数"与"站点上的题数"。

    只看题目总表的分页信息，不开详情（1~2 个请求）：
    第 1 页给出总页数与每页条数，再取最后一页数一下尾页条数，于是
    站点题数 =（总页数 - 1）× 每页条数 + 尾页条数。

    用途：程序中途被关掉后再打开时，靠它判断"上次是否没加载完"。
    """
    cached = store.stats().get("题目总数", 0)
    first = client.get(P_TASK_LIST.format(page=1)).text
    tasks, _, total_pages = P.parse_task_list(first)
    per_page = len(tasks)
    if total_pages <= 1 or per_page == 0:
        return cached, per_page
    last_tasks, _, _ = P.parse_task_list(
        client.get(P_TASK_LIST.format(page=total_pages)).text)
    return cached, (total_pages - 1) * per_page + len(last_tasks)


def fetch_profile_name(client: MatuClient) -> str:
    """取账号对应的姓名。

    站点把它放在 `left.jsp` 的 `<span class="left-font02">` 里
    （紧跟"您好，"之后），是爬得到的，不需要用户自己填。
    """
    soup = BeautifulSoup(client.get("/page/files/left.jsp").text, "lxml")
    span = soup.find("span", class_="left-font02")
    return span.get_text(strip=True) if span is not None else ""


def refresh_class_data(client: MatuClient, store: Store,
                       log: Optional[Callable[[str], None]] = None) -> Dict[str, int]:
    """拉取班级 -> 作业 -> 作业内题目，全部写入本地库。

    返回各层级的条目数，供界面显示一行"刷新完成"的说明。
    """
    say = log or (lambda _msg: None)

    html = client.get(P_MY_CLASSES.format(page=1)).text
    classes = parse_classes(html)
    store.save_classes(classes)
    say(f"班级 {len(classes)} 个")

    group_total = task_total = 0
    for cls in classes:
        class_id = int(cls["class_id"])
        groups = P.parse_homework_groups(
            client.get(P_CLASS_HOMEWORK.format(class_id=class_id, page=1)).text)
        store.save_homework_groups(groups, class_id)
        group_total += len(groups)
        say(f"{cls.get('course','')} / {cls.get('name','')}：{len(groups)} 次作业")

        for g in groups:
            gid = int(g["task_group_id"])
            items = P.parse_homework_tasks(
                client.get(P_GROUP_TASKS.format(group_id=gid)).text, gid)
            for it in items:
                it["class_id"] = class_id
                it["group_name"] = g.get("name", "")
                it["group_weight"] = g.get("weight")
            store.save_homework_tasks(items, class_id)
            task_total += len(items)
    return {"classes": len(classes), "groups": group_total, "tasks": task_total}
