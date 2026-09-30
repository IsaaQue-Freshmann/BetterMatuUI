#!/usr/bin/env python3
"""离线自检：拿已缓存的真实页面跑一遍解析器，验证解析没有失效。

不联网、不发请求。当站点改版导致解析失效时，跑这个脚本能立刻定位到是哪类页面。

用法：

    .venv/bin/python tools/selftest.py          # 用 ~/.bettermatu/html 里的缓存
    .venv/bin/python tools/selftest.py --dir=/path/to/html
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Callable, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from matu.core import parsers as P  # noqa: E402

CHECKS: List[Tuple[str, str, Callable[[str], bool]]] = [
    ("题目总表", "task__listtotaltask.html",
     lambda h: len(P.parse_task_list(h)[0]) > 0 and P.parse_task_list(h)[2] > 1),
    ("题目详情", "task__taskdetail_taskid=4.html",
     lambda h: bool(P.parse_task_detail(h)["description"])),
    ("作业列表", "task__liststudenttaskgroup__class.id=641.html",
     lambda h: len(P.parse_homework_groups(h)) > 0),
    ("作业内题目", "task__listTaskGroup_Task_taskGroup.id=8878.html",
     lambda h: all(i["max_submissions"] is not None
                   for i in P.parse_homework_tasks(h, 8878))),
    ("提交记录", "assignment__listassignment.html",
     lambda h: all(s.task_id > 0 for s in P.parse_submissions(h))),
    ("成绩详单", "assignment__scoredetail_assignmentid=2180377.html",
     lambda h: "扣分" in P.parse_score_detail(h)),
]


def resolve(base: Path, filename: str) -> Optional[Path]:
    """在缓存目录里找这份页面。

    缓存文件名由 URL 生成，带分页参数的页面会多出 `_page=N` 后缀
    （如 task__liststudenttaskgroup__class.id=641_page=1.html），
    所以先按原名找，找不到再按前缀找带分页的那份（优先第 1 页）。
    """
    exact = base / filename
    if exact.exists():
        return exact
    stem = filename[: -len(".html")]
    matches = sorted(base.glob(f"{stem}_page=*.html"))
    return matches[0] if matches else None


def main() -> int:
    parser = argparse.ArgumentParser(description="解析器离线自检")
    parser.add_argument("--dir", default=str(Path.home() / ".bettermatu" / "html"))
    args = parser.parse_args()

    base = Path(args.dir)
    if not base.is_dir():
        print(f"缓存目录不存在: {base}（先跑一次 tools/crawl.py 生成缓存）")
        return 2

    passed = skipped = failed = 0
    for label, filename, check in CHECKS:
        path = resolve(base, filename)
        if path is None:
            print(f"  跳过  {label:8s} —— 缓存缺失 {filename}")
            skipped += 1
            continue
        html = path.read_text(encoding="utf-8", errors="replace")
        try:
            ok = check(html)
        except Exception as exc:  # noqa: BLE001 —— 自检就是要把异常报出来
            print(f"  失败  {label:8s} —— 解析抛异常 {type(exc).__name__}: {exc}")
            failed += 1
            continue
        if ok:
            print(f"  通过  {label:8s} —— {filename}")
            passed += 1
        else:
            print(f"  失败  {label:8s} —— 解析结果为空或字段缺失，站点可能改版了")
            failed += 1

    print(f"\n通过 {passed}，跳过 {skipped}，失败 {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
