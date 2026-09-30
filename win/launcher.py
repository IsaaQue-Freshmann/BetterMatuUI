#!/usr/bin/env python3
"""打包入口。

`src/matu/ui/app.py` 用的是包内相对导入（`from ..core import ...`），
直接把它当脚本跑会因为缺少包上下文而失败，所以打包时用这个启动器：
它先从 `src/` 把 `matu` 包导入进来，再调用真正的入口。
"""

import sys

from matu.ui.app import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
