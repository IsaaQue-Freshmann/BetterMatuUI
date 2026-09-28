#!/usr/bin/env python3
"""把应用恢复到"首次打开"的干净状态（打包测试用）。

会清掉：
  ~/.bettermatu/            应用数据目录的整体内容
      accounts/             各账号的库、会话、导出快照、文档副本
      html/                 页面缓存
      settings.json         界面设置
      requests.log          请求审计日志
      submitted_once.marker 一次性提交标记
  项目内 data/              界面截图等验收产物
  项目内 __pycache__        Python 字节码缓存

**绝不会碰**：
  项目外的一处凭据文件        开发期用（删了本地加载脚本就跑不了）
  .venv/                    虚拟环境（打包要用）

执行前会先整体备份到 ~/.bettermatu.backup-<时间戳>/，所以是可回退的。

用法：
    .venv/bin/python tools/reset_state.py            # 预演，只列出要删什么
    .venv/bin/python tools/reset_state.py --apply    # 真的清
"""

from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

APP_HOME = Path.home() / ".bettermatu"

KEEP_IN_PROJECT = {".venv", ".git", "data"}     # data 单独处理


def dir_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def main() -> int:
    ap = argparse.ArgumentParser(description="恢复首次打开状态（会先备份）")
    ap.add_argument("--apply", action="store_true", help="真的执行")
    args = ap.parse_args()

    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = Path.home() / f".bettermatu.backup-{stamp}"

    print("将要清理：")
    targets = []
    if APP_HOME.is_dir():
        for child in sorted(APP_HOME.iterdir()):
            targets.append(child)
            print(f"  {child}  ({dir_size(child) / 1024:.0f} KB)")
    else:
        print("  ~/.bettermatu 不存在")

    project_data = ROOT / "data"
    if project_data.is_dir():
        for child in sorted(project_data.iterdir()):
            targets.append(child)
            print(f"  {child.relative_to(ROOT)}  ({dir_size(child) / 1024:.0f} KB)")

    pycache = [d for d in sorted(ROOT.rglob("__pycache__"))
               if ".venv" not in d.parts]          # 虚拟环境自己的字节码不用管
    for d in pycache:
        print(f"  {d.relative_to(ROOT)}")
    print()
    print("不会碰：项目外的凭据文件与 .venv/（打包要用）")

    if not args.apply:
        print(f"\n以上是预演。加 --apply 执行（会先备份到 {backup}）")
        return 0

    # ---- 备份 ----
    if APP_HOME.is_dir():
        shutil.copytree(APP_HOME, backup)
        print(f"\n已备份到 {backup}")

    # ---- 清理 ----
    for child in list(APP_HOME.iterdir()):
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)
        else:
            child.unlink(missing_ok=True)
    print(f"已清空 {APP_HOME}")

    if project_data.is_dir():
        for child in list(project_data.iterdir()):
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink(missing_ok=True)
        print(f"已清空 {ROOT / 'data'}")

    removed = 0
    for d in pycache:
        shutil.rmtree(d, ignore_errors=True)
        removed += 1
    print(f"已清除 {removed} 个 __pycache__")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
