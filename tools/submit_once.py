#!/usr/bin/env python3
"""一次性真实提交，用来验证提交流程，并留下证据供后续实现参照。

本项目唯一会真正提交代码的地方，所以刻意做成**物理上只能跑一次**：
  - 必须显式加 --confirm
  - 跑完写标记文件，第二次运行直接拒绝
  - 全程记录重定向链、耗时、每一步的原始 HTML

用法（题目坐标由命令行给，脚本内不写死账号相关的东西）：

    MATU_ENABLE_SUBMISSION=1 .venv/bin/python tools/submit_once.py \
        --task-id 1 --task-group-id 8877 --task-group-task-id 45334 \
        --task-name "hello world" --file /path/to/solution.cpp --confirm
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from matu.core import parsers as P          # noqa: E402
from matu.core import submit as S           # noqa: E402
from matu.core.client import MatuClient     # noqa: E402

MARKER = Path.home() / ".bettermatu" / "submitted_once.marker"
OUT_DIR = ROOT / "data" / "submit_probe"


def main() -> int:
    ap = argparse.ArgumentParser(description="一次性真实提交（验证用）")
    ap.add_argument("--task-id", type=int, required=True)
    ap.add_argument("--task-group-id", type=int, required=True)
    ap.add_argument("--task-group-task-id", type=int, required=True)
    ap.add_argument("--task-name", required=True)
    ap.add_argument("--file", required=True, help="要提交的源码文件")
    ap.add_argument("--interval", type=float, default=3.0)
    ap.add_argument("--confirm", action="store_true", help="确认要真实提交")
    args = ap.parse_args()

    if not args.confirm:
        print("未加 --confirm，什么都不会发生。")
        return 2
    if MARKER.exists():
        print(f"拒绝执行：标记文件已存在 {MARKER}")
        print(f"（内容是上次提交记录）{MARKER.read_text(encoding='utf-8')}")
        return 3
    if not os.environ.get("MATU_ENABLE_SUBMISSION", "").strip():
        print("拒绝执行：未设置 MATU_ENABLE_SUBMISSION=1，提交总闸是关的。")
        return 4

    source_path = Path(args.file)
    if not source_path.is_file():
        print(f"源码文件不存在: {source_path}")
        return 5
    source = source_path.read_text(encoding="utf-8")

    user, password = os.environ.get("MATU_USER"), os.environ.get("MATU_PASS")
    if not user or not password:
        print("缺少 MATU_USER / MATU_PASS 环境变量。")
        return 6

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    client = MatuClient(min_interval=args.interval, max_requests=40, logger=print)
    report: dict = {"started_at": time.strftime("%Y-%m-%d %H:%M:%S"), "steps": []}

    print("=" * 70)
    print("【1】登录")
    print("=" * 70)
    if not client.login(user, password):
        print("登录失败，中止。")
        return 7

    print("=" * 70)
    print(f"【2】提交前先记录基线：这道题当前最新一条提交的 assignment_id")
    print("=" * 70)
    before = P.parse_submissions(client.get(S.LIST_BY_TASK.format(task_id=args.task_id)).text)
    before = [s for s in before if s.task_id == args.task_id]
    baseline = max((s.assignment_id for s in before), default=0)
    print(f"当前已有 {len(before)} 条提交，最大 assignment_id = {baseline}")
    report["baseline_assignment_id"] = baseline
    report["baseline_count"] = len(before)

    print()
    print("=" * 70)
    print(f"【3】真实提交题目 #{args.task_id}「{args.task_name}」 —— 只此一次")
    print("=" * 70)
    print("提交的源码：")
    print("-" * 70)
    print(source.rstrip())
    print("-" * 70)

    outcome = S.submit_source(
        client,
        task_id=args.task_id,
        task_name=args.task_name,
        sourcecode=source,
        task_group_task_id=args.task_group_task_id,
        task_group_id=args.task_group_id,
    )

    print(f"\n耗时: {outcome.elapsed:.2f} 秒")
    print("重定向链（逐跳）:")
    for url, code in outcome.redirect_chain:
        print(f"    {code}  {url}")
    print(f"最终落地: {outcome.landed_url}")
    report["elapsed"] = outcome.elapsed
    report["redirect_chain"] = outcome.redirect_chain
    report["landed_url"] = outcome.landed_url

    (OUT_DIR / "03_landed.html").write_text(outcome.landed_html, encoding="utf-8")

    landed_text = P.BeautifulSoup(outcome.landed_html, "lxml").get_text(" ", strip=True)
    print(f"\n落地页可见文本（前 400 字）:\n  {landed_text[:400]}")
    report["landed_text"] = landed_text[:2000]

    # 站点可能同步跳转到成绩页，直接从落地页里把 assignmentid 抠出来
    import re
    ids = re.findall(r"assignmentid=(\d+)", outcome.landed_html)
    print(f"\n落地页里出现的 assignmentid: {sorted(set(ids)) or '无'}")
    report["landed_assignment_ids"] = sorted(set(ids))

    print()
    print("=" * 70)
    print("【4】拉取结果（有限次尝试，不轮询）")
    print("=" * 70)
    found = None
    for attempt in range(1, 5):
        time.sleep(args.interval if attempt > 1 else 2)
        subs = P.parse_submissions(
            client.get(S.LIST_BY_TASK.format(task_id=args.task_id)).text
        )
        subs = [s for s in subs if s.task_id == args.task_id]
        fresh = [s for s in subs if s.assignment_id > baseline]
        print(f"  第 {attempt} 次: 该题共 {len(subs)} 条记录，新增 {len(fresh)} 条")
        if fresh:
            found = max(fresh, key=lambda s: s.assignment_id)
            break
    report["attempts_used"] = attempt

    if found is None:
        print("\n未发现新记录。可能提交未被接受，或站点异步评测尚未生成记录。")
        report["found_submission"] = None
    else:
        print(f"\n✓ 新记录: assignment_id={found.assignment_id}")
        print(f"    状态={found.status}  分数={found.score}  时间={found.submitted_at}")
        detail = S.fetch_score_detail(client, found.assignment_id)
        print(f"\n成绩详单正文:\n{'-' * 70}\n{detail}\n{'-' * 70}")
        (OUT_DIR / "04_scoredetail.txt").write_text(detail, encoding="utf-8")
        report["found_submission"] = found.to_dict()
        report["score_detail"] = detail

        oc = S.SubmitOutcome(ok=True, submission=found, score_detail=detail)
        print(f"\n界面要展示的三项：得分={oc.score}  扣分={oc.deduction}  原因={oc.reason!r}")

    report["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    report["request_count"] = client.request_count
    (OUT_DIR / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    MARKER.parent.mkdir(parents=True, exist_ok=True)
    MARKER.write_text(
        f"已于 {time.strftime('%Y-%m-%d %H:%M:%S')} 对 task_id={args.task_id} "
        f"真实提交一次（assignment_id="
        f"{found.assignment_id if found else '未知'}）。此标记防止重复提交。\n",
        encoding="utf-8",
    )
    print(f"\n证据已保存: {OUT_DIR}")
    print(f"一次性标记已写入: {MARKER}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
