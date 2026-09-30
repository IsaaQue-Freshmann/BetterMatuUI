# -*- mode: python ; coding: utf-8 -*-
"""Windows 打包配置：单文件免安装 exe。

产物：build/BetterMatuUI.exe —— 一个文件，双击即用，不写注册表、不装任何东西。

两个容易踩的点：
- 入口用 win/launcher.py 而不是 src/matu/ui/app.py：后者是包内模块，
  用相对导入，直接当脚本跑会因缺少包上下文失败。
- datas 里的 resources 不能省：内置帮助文档和运行期图标要一起进 exe，
  否则打包后「系统帮助」是空的、图标也会丢。
"""

from pathlib import Path

ROOT = Path(SPECPATH).resolve().parents[0]        # SPECPATH = win/，上一级是项目根
SRC = ROOT / "src"
ICON = ROOT / "win" / "icon.ico"
VERSION_FILE = ROOT / "win" / "version_info.txt"

a = Analysis(
    [str(ROOT / "win" / "launcher.py")],
    pathex=[str(SRC)],
    binaries=[],
    datas=[(str(SRC / "matu" / "resources"), "matu/resources")],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    # 界面只用到 QtCore/QtGui/QtWidgets/QtSvg，其余重型模块一律排除，
    # 否则 exe 会塞进 WebEngine、3D、多媒体这些根本用不到的东西
    excludes=[
        "tkinter", "unittest", "pydoc_data", "test",
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
        "PySide6.QtWebEngineQuick", "PySide6.QtQuick", "PySide6.QtQml",
        "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DInput",
        "PySide6.Qt3DLogic", "PySide6.Qt3DAnimation", "PySide6.Qt3DExtras",
        "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtGraphs",
        "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets",
        "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtPositioning",
        "PySide6.QtSensors", "PySide6.QtSerialPort", "PySide6.QtWebSockets",
        "PySide6.QtWebChannel", "PySide6.QtPdf", "PySide6.QtPdfWidgets",
        "PySide6.QtDesigner", "PySide6.QtUiTools", "PySide6.QtHelp",
        "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtSpatialAudio",
        "PySide6.QtRemoteObjects", "PySide6.QtScxml", "PySide6.QtStateMachine",
        "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets", "PySide6.QtQuickWidgets",
        "PySide6.QtQuickControls2", "PySide6.QtQuickTest",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

# 单文件模式：binaries 与 datas 直接进 EXE，不再 COLLECT 成目录
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="BetterMatuUI",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                     # upx 压缩容易被杀软误报，关掉
    console=False,                 # 不弹黑色控制台窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ICON),
    version=str(VERSION_FILE),
)
