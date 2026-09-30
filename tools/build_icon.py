#!/usr/bin/env python3
"""生成应用图标（矢量 logo -> PNG / ICNS）。

图标就是侧栏那个 {} 标记，同一个矢量绘制函数渲染出来的，
所以界面上的 logo 和程序坞/打包后的图标永远一致。

产物：
    src/matu/resources/app.png     运行期用（窗口图标、程序坞）
    mac/BetterMatuUI.icns          macOS 打包用
    mac/icon.iconset/              macOS 中间产物（给 iconutil）
    win/icon.ico                   Windows 打包用

三个平台的图标都从同一个矢量绘制函数渲染，改一处即三处同步。

用法：
    .venv/bin/python tools/build_icon.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import struct                                                   # noqa: E402

from PySide6.QtCore import QBuffer, QByteArray, Qt              # noqa: E402
from PySide6.QtGui import QImage, QPainter                      # noqa: E402
from PySide6.QtWidgets import QApplication                      # noqa: E402

from matu.ui.sidebar import paint_logo                          # noqa: E402

RES = ROOT / "src" / "matu" / "resources"
MAC = ROOT / "mac"
ICONSET = MAC / "icon.iconset"

# macOS 图标需要这几档尺寸（含 @2x）
SIZES = [16, 32, 64, 128, 256, 512, 1024]

# 画布内留的安全边距：macOS 原生图标的图案约占画布的 80%，
# 铺满整张画布会显得比旁边其他图标大一圈
CONTENT_RATIO = 0.80


def render_png(path: Path, size: int) -> None:
    img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    inset = size * (1.0 - CONTENT_RATIO) / 2.0
    p.translate(inset, inset)
    paint_logo(p, size * CONTENT_RATIO, radius_ratio=0.22)
    p.end()
    img.save(str(path))


def png_bytes(size: int) -> bytes:
    """把某尺寸的图标渲染成 PNG 字节（ICO 里直接嵌 PNG）。"""
    img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    inset = size * (1.0 - CONTENT_RATIO) / 2.0
    p.translate(inset, inset)
    paint_logo(p, size * CONTENT_RATIO, radius_ratio=0.22)
    p.end()
    # 必须持住这个 QByteArray：写成 QBuffer(QByteArray()) 的话临时对象会被
    # Python 回收，QBuffer 拿着悬空指针，直接段错误
    storage = QByteArray()
    buf = QBuffer(storage)
    buf.open(QBuffer.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    data = bytes(storage)
    buf.close()
    return data


def write_ico(path: Path, sizes: Sequence[int]) -> None:
    """手写 ICO 容器：Vista 之后允许在 ICO 里直接嵌 PNG，不需要 BMP 转换。

    结构：6 字节头 + 每张 16 字节目录项 + 依次排列的 PNG 数据。
    """
    images = [(s, png_bytes(s)) for s in sizes]
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries, payload = b"", b""
    for size, data in images:
        dim = size if size < 256 else 0          # 256 用 0 表示
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32,
                               len(data), offset + len(payload))
        payload += data
    path.write_bytes(header + entries + payload)


def main() -> int:
    app = QApplication(sys.argv)          # 主题需要 QApplication 才能建字体
    from matu.ui.theme import LIGHT, set_theme, Theme
    set_theme(Theme(palette=LIGHT))       # 图标固定用亮色版的强调色

    RES.mkdir(parents=True, exist_ok=True)
    if ICONSET.exists():
        shutil.rmtree(ICONSET)
    ICONSET.mkdir(parents=True)

    for size in SIZES:
        render_png(ICONSET / f"icon_{size}x{size}.png", size)
        if size <= 512:                    # @2x 档
            render_png(ICONSET / f"icon_{size}x{size}@2x.png", size * 2)
        print(f"  渲染 {size}px")

    # 运行期用一张 256px 的 PNG 就够（窗口图标 / 程序坞）
    render_png(RES / "app.png", 256)
    print(f"  {RES / 'app.png'}")

    # Windows 打包用 ico（Windows 不认 icns）
    ico = ROOT / "win" / "icon.ico"
    ico.parent.mkdir(parents=True, exist_ok=True)
    write_ico(ico, [16, 24, 32, 48, 64, 128, 256])
    print(f"  {ico}")

    # macOS 打包用 icns（iconutil 是系统自带工具）
    icns = MAC / "BetterMatuUI.icns"
    try:
        subprocess.run(["iconutil", "-c", "icns", str(ICONSET), "-o", str(icns)],
                       check=True, capture_output=True)
        print(f"  {icns}")
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        print(f"  icns 生成失败（非 macOS 或缺 iconutil）：{exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
