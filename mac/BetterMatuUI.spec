# -*- mode: python ; coding: utf-8 -*-
"""macOS 打包配置。

用法（在项目根目录）：
    .venv/bin/pyinstaller --distpath output/mac/build --workpath output/mac/work \
        mac/BetterMatuUI.spec

两个容易踩的点：
- 入口用 mac/launcher.py 而不是 src/matu/ui/app.py：后者是包内模块，用相对
  导入，直接当脚本跑会因缺少包上下文失败。
- datas 里的 resources 不能省：内置的帮助文档和运行期图标要一起进包。
"""

from pathlib import Path

ROOT = Path(SPECPATH).resolve().parents[0]      # SPECPATH = 本文件所在目录(mac/)，上一级是项目根
SRC = ROOT / "src"
ICON = ROOT / "mac" / "BetterMatuUI.icns"

APP_NAME = "BetterMatuUI"
DISPLAY_NAME = "BetterMatuUI Beta 1.0"

a = Analysis(
    [str(ROOT / "mac" / "launcher.py")],
    pathex=[str(SRC)],
    binaries=[],
    datas=[(str(SRC / "matu" / "resources"), "matu/resources")],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    # 界面只用到 QtCore/QtGui/QtWidgets/QtSvg，其余重型模块一律排除，
    # 否则包体里会塞进 WebEngine、3D、多媒体这些根本没用的东西
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

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,              # 不弹终端窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ICON),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=APP_NAME,
)

app = BUNDLE(
    coll,
    name=f"{APP_NAME}.app",
    icon=str(ICON),
    bundle_identifier="com.bettermatu.ui",
    info_plist={
        "CFBundleName": APP_NAME,
        "CFBundleDisplayName": DISPLAY_NAME,
        "CFBundleShortVersionString": "1.0",
        "CFBundleVersion": "1.0",
        "CFBundleGetInfoString": DISPLAY_NAME,
        "CFBundleExecutable": APP_NAME,
        "NSHighResolutionCapable": True,          # Retina 下不发虚
        "LSMinimumSystemVersion": "13.0",
        "LSApplicationCategoryType": "public.app-category.developer-tools",
        "NSHumanReadableCopyright": "Created by IsaaQue Freshmann SCU",
    },
)
