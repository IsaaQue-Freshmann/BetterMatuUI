#!/usr/bin/env python3
"""只读结构探针：抓取指定路径，输出表单、链接、框架与 AJAX 端点清单。

用途是摸清站点结构和接口。除了登录那一次 POST，本工具永远只发 GET，
不构造、不发送任何提交类请求。

用法（凭据从环境变量 MATU_USER / MATU_PASS 读取）：

    .venv/bin/python tools/probe.py /page/files/left.jsp /page/files/mainfra.jsp

加 --no-login 可跳过登录检查，直接用已有会话（省一个请求）。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from matu.core.client import CACHE_DIR, MatuClient  # noqa: E402


def strip_tags(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", value)).strip()


def summarize(path: str, html: str) -> None:
    print(f"\n{'=' * 78}\n{path}   ({len(html)} 字节)\n{'=' * 78}")

    frames = re.findall(r'<(?:frame|iframe)[^>]*src="([^"]+)"[^>]*name="([^"]*)"', html, re.I)
    if frames:
        print("\n[框架]")
        for src, name in frames:
            print(f"  {src}  (name={name})")

    forms = re.findall(r"<form[^>]*>.*?</form>", html, re.S | re.I)
    if forms:
        print("\n[表单]")
        for form in forms:
            action = re.search(r'action="([^"]*)"', form, re.I)
            method = re.search(r'method="([^"]*)"', form, re.I)
            name = re.search(r'(?:id|name)="([^"]*)"', form, re.I)
            print(f"  form {name.group(1) if name else '?'} -> "
                  f"{method.group(1).upper() if method else 'GET'} {action.group(1) if action else '?'}")
            for inp in re.finditer(r"<input[^>]*>", form, re.I):
                attrs = dict(re.findall(r'(\w+)="([^"]*)"', inp.group(0)))
                print(f"      input name={attrs.get('name', '-')!r} type={attrs.get('type', 'text')!r}"
                      f"{' value=' + repr(attrs['value']) if attrs.get('value') else ''}")
            for sel in re.finditer(r"<select[^>]*name=\"([^\"]*)\"", form, re.I):
                print(f"      select name={sel.group(1)!r}")

    anchors = re.findall(r"<a[^>]*>.*?</a>", html, re.S | re.I)
    if anchors:
        print("\n[链接]")
        seen = set()
        for a in anchors:
            href = re.search(r'href="([^"]*)"', a, re.I)
            target = re.search(r'target="([^"]*)"', a, re.I)
            onclick = re.search(r'onclick="([^"]*)"', a, re.I)
            text = strip_tags(a)[:48]
            key = (href.group(1) if href else "", text)
            if key in seen or (not text and not href):
                continue
            seen.add(key)
            bits = [href.group(1) if href else "(无 href)"]
            if target:
                bits.append(f"target={target.group(1)}")
            if onclick:
                bits.append(f"onclick={onclick.group(1)[:70]}")
            print(f"  {'  '.join(bits)}   |   {text}")

    jump = re.findall(r"(?:location(?:\.href)?|window\.open)\s*[=(]\s*[\"']([^\"']+)[\"']", html)
    ajax = re.findall(r"\$\.(?:post|get|ajax)\s*\(\s*[\"']([^\"']+)[\"']", html)
    if jump or ajax:
        print("\n[脚本跳转 / AJAX]")
        for u in dict.fromkeys(jump):
            print(f"  jump  {u}")
        for u in dict.fromkeys(ajax):
            print(f"  ajax  {u}")

    actions = sorted(set(re.findall(r"[\w./\-]*\.action[\w?=&%]*", html)))
    if actions:
        print("\n[.action 端点]")
        for a in actions:
            print(f"  {a}")

    body = strip_tags(re.sub(r"<(script|style).*?</\1>", " ", html, flags=re.S | re.I))
    if body:
        print("\n[可见文本前 500 字]")
        print("  " + body[:500])


def main() -> int:
    parser = argparse.ArgumentParser(description="码图站点只读结构探针")
    parser.add_argument("paths", nargs="+", help="要探测的路径，如 /page/files/left.jsp")
    parser.add_argument("--no-login", action="store_true", help="跳过登录检查，直接用已有会话")
    parser.add_argument("--interval", type=float, default=2.5, help="请求最小间隔秒数（默认 2.5）")
    args = parser.parse_args()

    client = MatuClient(min_interval=args.interval, logger=print)
    if not args.no_login:
        import os
        user, password = os.environ.get("MATU_USER"), os.environ.get("MATU_PASS")
        if not user or not password:
            print("缺少 MATU_USER / MATU_PASS，请先从项目外的凭据文件注入。")
            return 2
        if not client.login(user, password):
            print("登录失败，停止。")
            return 1
        print("登录成功。")

    for path in args.paths:
        resp = client.get(path)
        if MatuClient.looks_like_login_page(resp.text):
            print(f"\n!! {path} 返回的是登录表单，说明会话已失效。"
                  f"请去掉 --no-login 重新登录后再跑。")
            return 1
        summarize(path, resp.text)

    print(f"\n本次请求数: {client.request_count}（完整记录见 ~/.bettermatu/requests.log）")
    print(f"HTML 缓存目录: {CACHE_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
