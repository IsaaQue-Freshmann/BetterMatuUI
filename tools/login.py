#!/usr/bin/env python3
"""登录码图，并把会话保存到项目之外。

凭据只从环境变量 MATU_USER / MATU_PASS 读取。本文件不含默认账号、
不含密码、也不含凭据文件的位置——项目里不留任何账号映射。

用法（凭据从环境变量读取，来源由你本机 shell 掌握，项目内不记录）：

    export MATU_USER=<你的账号>
    export MATU_PASS=<你的密码>
    .venv/bin/python tools/login.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from matu.core.client import CACHE_DIR, SESSION_FILE, MatuClient  # noqa: E402


def mask(value: str) -> str:
    if len(value) <= 4:
        return "*" * len(value)
    return value[:4] + "*" * (len(value) - 4)


def main() -> int:
    user = os.environ.get("MATU_USER")
    password = os.environ.get("MATU_PASS")
    if not user or not password:
        print("缺少 MATU_USER / MATU_PASS 环境变量，请先从项目外的凭据文件注入。")
        return 2

    print(f"账号: {mask(user)}")
    client = MatuClient(logger=print)

    ok = client.login(user, password)
    resp = getattr(client, "last_login_response", None)

    if resp is not None:
        print(f"\n登录 POST 落到: {resp.url}")
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        (CACHE_DIR / "_post_login.html").write_text(resp.text, encoding="utf-8")
        print(f"落地页已缓存: {CACHE_DIR / '_post_login.html'}")

    print(f"\n登录结果: {'成功' if ok else '失败'}")
    print(f"会话文件: {SESSION_FILE}")
    print(f"本次请求数: {client.request_count}（全部记录在 ~/.bettermatu/requests.log）")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
