# mac/ —— macOS 打包配置

这里只放**平台相关**的东西，Python 源码只有一份在 `src/`。

计划放置：

- `BetterMatuUI.spec` —— PyInstaller 打包配置（主窗口、图标、bundle id）
- `Info.plist` —— 应用元信息（`NSHighResolutionCapable` 等）
- `icon.icns` —— 应用图标

开发期先直接跑源码：

```bash
.venv/bin/python -m matu.ui.app     # 界面开发完成后可用
```

打包（界面完成后）：

```bash
.venv/bin/pip install pyinstaller
.venv/bin/pyinstaller mac/BetterMatuUI.spec
```

注意：PySide6 在 Python 3.9 上可用的是 `cp39-abi3` 稳定 ABI 轮子
（实测 6.10.3，`requires_python=<3.15,>=3.9`），所以不需要额外装新版 Python。
