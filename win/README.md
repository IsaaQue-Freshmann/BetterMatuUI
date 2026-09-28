# win/ —— Windows 打包配置

这里只放**平台相关**的东西，Python 源码只有一份在 `src/`。

计划放置：

- `BetterMatuUI.spec` —— PyInstaller 打包配置
- `version_info.txt` —— exe 版本资源（公司、产品名、版本号）
- `icon.ico` —— 应用图标

打包（界面完成后，在 Windows 机器上执行）：

```bat
.venv\Scripts\pip install pyinstaller
.venv\Scripts\pyinstaller win\BetterMatuUI.spec
```

## 转 Windows 时需要留意的平台差异

mac 上开发完成后转到 Windows，以下几处需要实际验证（代码里已经按跨平台写，
但只有真机能确认）：

1. **凭据存储**：mac 用 Keychain，Windows 用 Credential Manager，
   要各写一份实现。
2. **字体**：等宽字体 mac 用 `Menlo`/`SF Mono`，Windows 用
   `Consolas`/`Cascadia Mono`，否则代码显示会不一致。
3. **高 DPI**：Windows 上需要显式开启高 DPI 缩放，否则界面发虚。
4. **路径**：统一用 `pathlib`，不要拼字符串。
5. **编码**：Windows 控制台默认 GBK，任何文件读写都要显式指定 `encoding="utf-8"`。
