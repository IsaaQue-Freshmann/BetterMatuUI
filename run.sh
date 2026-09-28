#!/usr/bin/env bash
# 启动 BetterMatuUI 桌面客户端。
#
#   ./run.sh              # 正常启动
#   ./run.sh --help       # 透传给 Python（界面暂时没有命令行参数）
#
# 第一次用需要先建好虚拟环境（见 README）。

set -euo pipefail

cd "$(dirname "$0")"

if [ ! -x .venv/bin/python ]; then
    echo "找不到虚拟环境 .venv，先执行：" >&2
    echo "  python3 -m venv .venv" >&2
    echo "  .venv/bin/pip install -i https://pypi.tuna.tsinghua.edu.cn/simple \\" >&2
    echo "      requests beautifulsoup4 lxml PySide6" >&2
    exit 1
fi

exec env PYTHONPATH=src .venv/bin/python -m matu.ui.app "$@"
