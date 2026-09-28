#!/usr/bin/env python3
"""把项目里旧位置的加载数据搬到"按账号隔离"的新位置。

背景：早期版本把数据放在项目内的 data/ 下，但爬到的题库/班级/提交记录
都是**账号私有**的，不该留在项目里。现在每个账号一个目录：

    ~/.bettermatu/accounts/<账号>/matu.db

用法（账号从环境变量取，避免把账号写进项目）：

    set -a; . <你的凭据文件>; set +a
    .venv/bin/python tools/migrate_data.py          # 预演，只打印要做什么
    .venv/bin/python tools/migrate_data.py --apply  # 真的搬
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from matu.core.accounts import AccountStore  # noqa: E402

LEGACY = [
    ("data/matu.db", "matu.db"),
    ("data/matu_snapshot.json", "snapshot.json"),
    ("data/docs", "docs"),
    ("data/submit_probe", "submit_probe"),
]


def main() -> int:
    ap = argparse.ArgumentParser(description="迁移旧位置的数据到按账号隔离的目录")
    ap.add_argument("--account", default="", help="账号名（默认取环境变量 MATU_USER）")
    ap.add_argument("--apply", action="store_true", help="真的执行（默认只预演）")
    args = ap.parse_args()

    username = args.account or os.environ.get("MATU_USER", "")
    if not username:
        print("需要账号：用 --account 指定，或从环境变量注入 MATU_USER。")
        return 2

    accounts = AccountStore()
    target_dir = accounts.dir_for(username)
    print(f"账号      : {username}")
    print(f"目标目录  : {target_dir}")
    print(f"数据库将落在: {accounts.db_path(username)}")
    print()

    moved = 0
    for rel, dest_name in LEGACY:
        src = ROOT / rel
        if not src.exists():
            print(f"  跳过  {rel}（不存在）")
            continue
        dest = target_dir / dest_name
        if dest.exists():
            print(f"  跳过  {rel}（目标已存在 {dest.name}，不覆盖）")
            continue
        size = (src.stat().st_size if src.is_file()
                else sum(p.stat().st_size for p in src.rglob("*") if p.is_file()))
        print(f"  {'搬移' if args.apply else '待搬'}  {rel}  ->  {dest}  ({size/1024:.0f} KB)")
        if args.apply:
            target_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dest))
            moved += 1

    if not args.apply:
        print("\n以上是预演。加 --apply 真正执行。")
        return 0

    print(f"\n完成，搬移 {moved} 项。")

    # 补一个"最近加载"时间：库里没有就用数据库文件的修改时间，
    # 否则设置界面会显示成空
    from matu.core.store import Store
    db = accounts.db_path(username)
    if db.exists():
        store = Store(db)
        meta = {r["key"]: r["value"]
                for r in store.conn.execute("SELECT key, value FROM meta")}
        if not meta.get("last_crawl"):
            import time
            stamp = time.strftime("%Y-%m-%d %H:%M:%S",
                                  time.localtime(db.stat().st_mtime))
            accounts.touch_crawl(username, store)
            print(f"已把「最近加载」记为 {stamp}（取自数据库文件时间）")
        store.close()

    # 项目内的 data/ 若只剩截图这类非账号产物，提示一下
    data_dir = ROOT / "data"
    if data_dir.is_dir():
        leftovers = sorted(p.name for p in data_dir.iterdir())
        if leftovers:
            print(f"项目内 data/ 仍留有: {leftovers}")
            print("（截图是验收产物，不是账号数据；如也想移出告诉我）")
        else:
            print("项目内 data/ 已清空。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
