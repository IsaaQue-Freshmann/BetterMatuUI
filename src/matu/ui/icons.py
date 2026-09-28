"""矢量图标：内嵌 SVG 路径，运行时渲染，无位图资源。

图标统一 24x24 视框、描边式（stroke）线性风格，与全矢量界面一致。
颜色在使用时传入，所以同一份路径能适配亮/暗主题和悬停态。

两种用法：
  - render(painter, name, rect, color)  —— 自绘控件里直接画，纯矢量，任意 DPI 清晰
  - pixmap(name, color, size)           —— 需要 QIcon/QPixmap 的地方（QTreeWidget 等）
"""

from __future__ import annotations

from typing import Dict, Optional

from PySide6.QtCore import QByteArray, QRect, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

# 24x24 视框的描边路径。{w} 是描边宽度。
_PATHS: Dict[str, str] = {
    # 我的班级：举手/学员
    "class": (
        '<path d="M17 20v-1.7a3.3 3.3 0 0 0-3.3-3.3H6.3A3.3 3.3 0 0 0 3 18.3V20"/>'
        '<circle cx="10" cy="7.5" r="3.5"/>'
        '<path d="M21 20v-1.7a3.3 3.3 0 0 0-2.5-3.2"/>'
        '<path d="M15.5 4.3a3.3 3.3 0 0 1 0 6.4"/>'
    ),
    # 题目中心：带勾的清单
    "tasks": (
        '<path d="M4 6.5h1.8l1 1 2.2-2.2"/>'
        '<path d="M4 12.5h1.8l1 1 2.2-2.2"/>'
        '<path d="M4 18.5h1.8l1 1 2.2-2.2"/>'
        '<path d="M12.5 6.5H20"/><path d="M12.5 12.5H20"/><path d="M12.5 18.5h5"/>'
    ),
    # 数据中心：柱状图
    "chart": (
        '<path d="M4 20h16"/>'
        '<rect x="5.5" y="12" width="3.2" height="6" rx="1"/>'
        '<rect x="10.4" y="8" width="3.2" height="10" rx="1"/>'
        '<rect x="15.3" y="4.5" width="3.2" height="13.5" rx="1"/>'
    ),
    # 系统帮助：问号
    "help": (
        '<circle cx="12" cy="12" r="8.5"/>'
        '<path d="M9.6 9.4a2.5 2.5 0 0 1 4.9.6c0 1.7-2.5 2.1-2.5 3.6"/>'
        '<path d="M12 17.2h.01"/>'
    ),
    # 个人中心：头像
    "user": (
        '<circle cx="12" cy="8.5" r="3.8"/>'
        '<path d="M4.8 20.2a7.4 7.4 0 0 1 14.4 0"/>'
    ),
    # 折叠/展开侧栏
    "panel-left": (
        '<rect x="3.5" y="4.5" width="17" height="15" rx="2.6"/>'
        '<path d="M9.5 4.5v15"/>'
    ),
    "chevron-left": '<path d="M14.5 6.5 9 12l5.5 5.5"/>',
    "chevron-right": '<path d="M9.5 6.5 15 12l-5.5 5.5"/>',
    "chevron-down": '<path d="M6.5 9.5 12 15l5.5-5.5"/>',
    # 前进 / 后退
    "arrow-left": '<path d="M19 12H5"/><path d="M11 6l-6 6 6 6"/>',
    "arrow-right": '<path d="M5 12h14"/><path d="M13 6l6 6-6 6"/>',
    # 刷新
    "refresh": (
        '<path d="M20 11.5a8 8 0 1 0-2.3 5.5"/>'
        '<path d="M20 5.5v6h-6"/>'
    ),
    # 提交：上传
    "submit": (
        '<path d="M12 16V4.5"/>'
        '<path d="M7.5 9 12 4.5 16.5 9"/>'
        '<path d="M4.5 15.5v2.6a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2v-2.6"/>'
    ),
    # 目录 / 文件
    "folder": (
        '<path d="M3.5 7.2a2 2 0 0 1 2-2h3.3l1.8 2.2h7.9a2 2 0 0 1 2 2v7.4a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z"/>'
    ),
    "folder-open": (
        '<path d="M3.5 7.2a2 2 0 0 1 2-2h3.3l1.8 2.2h7.9a2 2 0 0 1 2 2v1.1"/>'
        '<path d="M3.5 9.5h16.4l-1.7 7.6a2 2 0 0 1-2 1.6H5.5a2 2 0 0 1-2-2z"/>'
    ),
    "file-code": (
        '<path d="M13.5 3.5H7a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V9z"/>'
        '<path d="M13.5 3.5V9H19"/>'
        '<path d="M10.5 12.5 8.5 15l2 2.5"/><path d="M14 12.5 16 15l-2 2.5"/>'
    ),
    # 状态
    "check": '<path d="M5 12.5 10 17.5 19 7"/>',
    "check-circle": (
        '<circle cx="12" cy="12" r="8.5"/><path d="M8.4 12.3 11 14.9l4.7-5.2"/>'
    ),
    "x": '<path d="M6.5 6.5l11 11"/><path d="M17.5 6.5l-11 11"/>',
    "alert": (
        '<circle cx="12" cy="12" r="8.5"/>'
        '<path d="M12 7.8v4.9"/><path d="M12 16.2h.01"/>'
    ),
    # 主题
    "sun": (
        '<circle cx="12" cy="12" r="4.2"/>'
        '<path d="M12 2.8v2.1M12 19.1v2.1M4.5 4.5l1.5 1.5M18 18l1.5 1.5'
        'M2.8 12h2.1M19.1 12h2.1M4.5 19.5 6 18M18 6l1.5-1.5"/>'
    ),
    "moon": '<path d="M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5z"/>',
    "settings": (
        '<circle cx="12" cy="12" r="3.2"/>'
        '<path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-2.9 1.2 2 2 0 1 1-4 0 1.7 1.7 0 0 0-2.9-1.2l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1A1.7 1.7 0 0 0 2.6 15a2 2 0 1 1 0-4 1.7 1.7 0 0 0 1.2-2.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.9.3 1.7 1.7 0 0 0 1-1.5 2 2 0 1 1 4 0 1.7 1.7 0 0 0 2.9 1.2l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0 1.2 2.9 2 2 0 1 1 0 4z"/>'
    ),
    "logout": (
        '<path d="M9.5 20H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h3.5"/>'
        '<path d="M15.5 16 20 12l-4.5-4"/><path d="M20 12H9.5"/>'
    ),
    "trash": (
        '<path d="M4.5 7h15"/><path d="M9.5 7V5.2a1.2 1.2 0 0 1 1.2-1.2h2.6a1.2 1.2 0 0 1 1.2 1.2V7"/>'
        '<path d="M6.5 7l.9 12a1.6 1.6 0 0 0 1.6 1.5h6a1.6 1.6 0 0 0 1.6-1.5l.9-12"/>'
    ),
    "download": (
        '<path d="M12 4v11.5"/><path d="M7.5 11 12 15.5 16.5 11"/>'
        '<path d="M4.5 19.5h15"/>'
    ),
    "clock": '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3.2 1.9"/>',
    "code": '<path d="M9 7.5 4.5 12 9 16.5"/><path d="M15 7.5 19.5 12 15 16.5"/>',
    "info": (
        '<circle cx="12" cy="12" r="8.5"/>'
        '<path d="M12 11v5.2"/><path d="M12 7.9h.01"/>'
    ),
}

_cache: Dict[tuple, QIcon] = {}


def svg_text(name: str, color: str, width: float = 1.8) -> str:
    """生成完整 SVG 文本。颜色和描边宽度在使用时注入。"""
    body = _PATHS.get(name)
    if body is None:
        raise KeyError(f"未知图标: {name}（可用: {sorted(_PATHS)}）")
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
        f'fill="none" stroke="{color}" stroke-width="{width}" '
        f'stroke-linecap="round" stroke-linejoin="round">{body}</svg>'
    )


def render(painter: QPainter, name: str, rect: QRect, color: str,
           width: float = 1.8) -> None:
    """把图标直接矢量绘制到 painter 的 rect 里。

    自绘控件应当用这个而不是 pixmap —— 没有中间位图，任意 DPI 都锐利。
    """
    renderer = QSvgRenderer(QByteArray(svg_text(name, color, width).encode("utf-8")))
    renderer.render(painter, QRectF(rect))


def pixmap(name: str, color: str, size: int = 18, dpr: float = 2.0,
           width: float = 1.8) -> QPixmap:
    """渲染成 QPixmap（按设备像素比放大，Retina 下不发虚）。"""
    px = QPixmap(int(size * dpr), int(size * dpr))
    px.fill(Qt.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.Antialiasing, True)
    render(p, name, QRect(0, 0, int(size * dpr), int(size * dpr)), color, width)
    p.end()
    px.setDevicePixelRatio(dpr)
    return px


def icon(name: str, color: str, size: int = 18, dpr: float = 2.0) -> QIcon:
    key = (name, color, size, dpr)
    cached = _cache.get(key)
    if cached is None:
        cached = QIcon(pixmap(name, color, size, dpr))
        _cache[key] = cached
    return cached


def clear_cache() -> None:
    _cache.clear()


def available() -> list:
    return sorted(_PATHS)
