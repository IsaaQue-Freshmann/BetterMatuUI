#!/usr/bin/env python3
"""把界面渲染成 PNG，用于离线验收（不需要显示器）。

用法：

    PYTHONPATH=src QT_QPA_PLATFORM=offscreen .venv/bin/python tools/screenshot_ui.py

产物在 data/ui_shots/ 下。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtCore import Qt                                    # noqa: E402
from PySide6.QtWidgets import QApplication                       # noqa: E402

from matu.ui import app as A                                     # noqa: E402
from matu.ui.config import Config                                # noqa: E402
from matu.ui.theme import set_theme                              # noqa: E402
from matu.ui.workspace import Workspace                          # noqa: E402

OUT = ROOT / "data" / "ui_shots"
SIZE = (1440, 900)


def shot(widget, name: str, size=SIZE) -> None:
    from PySide6.QtGui import QPixmap
    widget.resize(*size)
    QApplication.instance().processEvents()
    for _ in range(3):
        QApplication.instance().processEvents()
    pm: QPixmap = widget.grab()
    path = OUT / f"{name}.png"
    pm.save(str(path))
    print(f"  {name}.png  {pm.width()}x{pm.height()}")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    config = Config.load()
    config.appearance = "light"

    print("渲染中（离屏）…")
    for mode in ("light", "dark"):
        config.appearance = mode
        set_theme(A.build_theme(config))
        app.setFont(A.ui_font())
        app.setStyleSheet(A.app_qss())

        ws = Workspace(config)
        win = A.MainWindow(ws, config)
        win.show()
        QApplication.instance().processEvents()

        # 1) 我的班级：选中一道题（左目录 + 右编辑器/结果）
        page = win._pages["my_class"]                         # noqa: SLF001
        from matu.ui.class_tree import find_task_node
        task = find_task_node(page._root, 1) or find_task_node(page._root, 4)  # noqa: SLF001
        if task is not None:
            page._browser.select_node(task)                   # noqa: SLF001
            page._on_node_selected(task)                      # noqa: SLF001
        page._code._editor.set_text(                          # noqa: SLF001
            "#include<stdio.h>\n"
            "void main() {\n"
            "\tint n, i;\n"
            "\tscanf(\"%d\", &n);\n"
            "\tfor (i = 1; i <= 5; i++) {\n"
            "\t\tprintf(\"%d\", n);\n"
            "\t\tif (i < 5) printf(\" \");\n"
            "\t}\n"
            "\tprintf(\"\\n\");\n"
            "}\n"
        )
        page._code._result.set_result(                          # noqa: SLF001
            0, 100,
            "When test group(1) step(1),the input is (),"
            "the real output is not right.")
        shot(win, f"01_my_class_{mode}")

        # 2) 未提交时的空态
        page._code._result.reset_idle()                         # noqa: SLF001
        shot(win, f"02_my_class_idle_{mode}")

        # 3) 侧栏折叠态
        win._sidebar.set_collapsed(True, animate=False)          # noqa: SLF001
        shot(win, f"03_collapsed_{mode}")
        win._sidebar.set_collapsed(False, animate=False)         # noqa: SLF001

        # 3b) 代码区拖到最窄（验证能收窄 + 工具按钮自适应）
        split = page._browser.parentWidget()                     # noqa: SLF001
        if hasattr(split, "setSizes"):
            split.setSizes([900, 380])
            QApplication.instance().processEvents()
            shot(win, f"03b_narrow_code_{mode}")
            split.setSizes([400, 900])
            QApplication.instance().processEvents()

        # 4) 个人中心
        win._sidebar.set_selected("profile")                     # noqa: SLF001
        win._on_navigate("profile")                              # noqa: SLF001
        shot(win, f"04_profile_{mode}")

        # 5) 设置区块：在个人中心页里，⌘, 直接滚过去
        win.open_settings()
        QApplication.instance().processEvents()
        shot(win, f"05_settings_{mode}")

        # 6) 占位页（题目中心）
        win._sidebar.set_selected("task_center")                 # noqa: SLF001
        win._on_navigate("task_center")                          # noqa: SLF001
        shot(win, f"06_placeholder_{mode}")

        # 7) 系统帮助：选第二份文档（提交注意事项，含代码块）
        win._sidebar.set_selected("help")                        # noqa: SLF001
        win._on_navigate("help")                                 # noqa: SLF001
        help_page = win._pages["help"]                           # noqa: SLF001
        tree = help_page._build_tree()                           # noqa: SLF001
        if len(tree.children) > 1:
            help_page._on_selected(tree.children[1])             # noqa: SLF001
            QApplication.instance().processEvents()
        shot(win, f"07_help_{mode}")

        win.close()
    print(f"\n完成，产物在 {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
