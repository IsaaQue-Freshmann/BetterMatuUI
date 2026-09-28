"""数据中心的图表：热力条、三角雷达、折线图。

全部自绘（QPainter 矢量），颜色只从主题取，亮暗主题都跟着走。
"""

from __future__ import annotations

import math
from datetime import date
from typing import List, Optional, Sequence, Tuple

from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QSizePolicy, QWidget

from .theme import theme
from .widgets import rounded_path, ui_font


def script_font(size: int, weight: QFont.Weight = QFont.Weight.Bold) -> QFont:
    """评级用的花体字。

    Brush Script MT 是 macOS 与 Windows 都自带的书写体，缺失时依次回退到
    Segoe Script / Snell Roundhand / Apple Chancery。字体本身没有粗体，
    这里靠字重合成加粗。
    """
    f = QFont()
    f.setFamilies(["Brush Script MT", "Segoe Script", "Snell Roundhand",
                   "Apple Chancery", "cursive"])
    f.setPixelSize(size)
    f.setWeight(weight)
    f.setItalic(False)
    return f


class HeatStrip(QWidget):
    """GitHub 式热力条：53 个格子，一天一格，格子越深当天提交越多。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._cells: List[Tuple[date, date, int]] = []
        self.setMinimumHeight(76)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_cells(self, cells: Sequence[Tuple[date, date, int]]) -> None:
        self._cells = list(cells)
        self.update()

    # 五档色阶：0 次用底色，其余按次数加深（对数式，避免个别爆量把色阶拉平）
    def _cell_color(self, count: int) -> QColor:
        pal = theme().palette
        if count <= 0:
            return QColor(pal.surface_alt)
        base = QColor(pal.accent)
        levels = ((1, 0.28), (3, 0.45), (6, 0.62), (10, 0.80), (10 ** 9, 1.0))
        for limit, alpha in levels:
            if count <= limit:
                c = QColor(base)
                c.setAlphaF(alpha)
                return c
        return base

    def paintEvent(self, event) -> None:  # noqa: N802
        if not self._cells:
            return
        t = theme()
        pal = t.palette
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        pad = t.metrics.space_md
        legend_h = 20
        gap = 3.0
        n = len(self._cells)
        cell_w = max(4.0, (self.width() - pad * 2 - gap * (n - 1)) / n)
        cell_h = 22.0
        top = 18.0

        fm = QFontMetrics(ui_font(t.small_font_size))
        p.setFont(ui_font(t.small_font_size))

        for i, (start, end, count) in enumerate(self._cells):
            x = pad + i * (cell_w + gap)
            rect = QRectF(x, top, cell_w, cell_h)
            p.setBrush(self._cell_color(count))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawPath(rounded_path(rect, 4))
            # 每天一格时按周标日期，否则刻度会糊在一起
            if i % 7 == 0 or i == n - 1:
                p.setPen(QColor(pal.text_muted))
                label = f"{start.month}/{start.day}"
                p.drawText(QRectF(x - 6, top + cell_h + 3, 52, 14),
                           Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                           label)

        # 图例：少 → 多
        p.setPen(QColor(pal.text_muted))
        tag = "每天提交次数　少"
        p.drawText(QRectF(pad, 0, 240, 16),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, tag)
        x = pad + fm.horizontalAdvance(tag) + 6
        for count in (0, 1, 3, 6, 11):
            p.setBrush(self._cell_color(count))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawPath(rounded_path(QRectF(x, 2, 12, 12), 3))
            x += 15
        p.setPen(QColor(pal.text_muted))
        p.drawText(QRectF(x + 2, 0, 40, 16),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "多")
        p.end()

    def sizeHint(self):  # noqa: N802
        from PySide6.QtCore import QSize
        return QSize(900, 76)


class RadarChart(QWidget):
    """三角雷达图：三个轴，取值 0-100。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._values: List[Tuple[str, float]] = []
        self.setMinimumSize(300, 260)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_values(self, values: Sequence[Tuple[str, float]]) -> None:
        self._values = list(values)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        if len(self._values) < 3:
            return
        t = theme()
        pal = t.palette
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        cx = self.width() / 2
        cy = self.height() / 2 + 6
        radius = min(self.width() / 2 - 74, self.height() / 2 - 40)
        if radius < 40:
            return
        # 三个轴：正上、左下、右下
        angles = [-90.0, 150.0, 30.0]

        def point(idx: int, ratio: float) -> QPointF:
            a = math.radians(angles[idx])
            return QPointF(cx + math.cos(a) * radius * ratio,
                           cy + math.sin(a) * radius * ratio)

        # 底网格：25/50/75/100 四圈
        grid_pen = QPen(QColor(pal.border), 1)
        for ratio in (0.25, 0.5, 0.75, 1.0):
            poly = QPolygonF([point(i, ratio) for i in range(3)])
            p.setPen(grid_pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPolygon(poly)
        # 三个轴
        for i in range(3):
            p.setPen(QPen(QColor(pal.border_strong), 1))
            p.drawLine(QPointF(cx, cy), point(i, 1.0))

        # 数据多边形
        poly = QPolygonF([point(i, max(0.0, min(100.0, v)) / 100.0)
                          for i, (_n, v) in enumerate(self._values)])
        fill = QColor(pal.accent)
        fill.setAlphaF(0.28)
        p.setBrush(fill)
        p.setPen(QPen(QColor(pal.accent), 2))
        p.drawPolygon(poly)
        # 顶点
        for i, (_n, v) in enumerate(self._values):
            pt = point(i, max(0.0, min(100.0, v)) / 100.0)
            p.setBrush(QColor(pal.accent))
            p.setPen(QPen(QColor(pal.surface), 2))
            p.drawEllipse(pt, 4, 4)

        # 轴标签：名称 + 数值
        for i, (name, value) in enumerate(self._values):
            tip = point(i, 1.22)
            box = QRectF(tip.x() - 62, tip.y() - 20, 124, 44)
            p.setFont(ui_font(13, QFont.Weight.DemiBold))
            p.setPen(QColor(pal.text))
            p.drawText(box, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, name)
            p.setFont(ui_font(11))
            p.setPen(QColor(pal.text_muted))
            p.drawText(QRectF(box.x(), box.y() + 19, box.width(), 18),
                       Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                       f"{value:.0f}")
        p.end()


class LineChart(QWidget):
    """每日提交次数折线图。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._series: List[Tuple[date, int]] = []
        self.setMinimumHeight(170)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_series(self, series: Sequence[Tuple[date, int]]) -> None:
        self._series = list(series)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        if not self._series:
            return
        t = theme()
        pal = t.palette
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        left, right, top, bottom = 44.0, 12.0, 14.0, 26.0
        w = self.width() - left - right
        h = self.height() - top - bottom
        if w < 40 or h < 40:
            return

        values = [v for _d, v in self._series]
        peak = max(values) if values else 0
        top_value = max(1, peak)
        # 让峰值落在一条整齐的网格线上
        step = max(1, math.ceil(top_value / 4))
        top_value = step * 4

        fm = QFontMetrics(ui_font(t.small_font_size))
        # 横向网格 + 刻度
        for k in range(5):
            y = top + h - h * (k / 4)
            p.setPen(QPen(QColor(pal.border), 1))
            p.drawLine(QPointF(left, y), QPointF(left + w, y))
            p.setFont(ui_font(t.small_font_size))
            p.setPen(QColor(pal.text_muted))
            p.drawText(QRectF(0, y - 8, left - 8, 16),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       str(int(top_value * k / 4)))

        n = len(self._series)
        def x_at(i: int) -> float:
            return left + (w * i / (n - 1) if n > 1 else w / 2)

        def y_at(v: int) -> float:
            return top + h - h * (v / top_value if top_value else 0)

        pts = [QPointF(x_at(i), y_at(v)) for i, (_d, v) in enumerate(self._series)]

        # 面积填充 + 折线
        area = QPainterPath()
        area.moveTo(pts[0].x(), top + h)
        for pt in pts:
            area.lineTo(pt)
        area.lineTo(pts[-1].x(), top + h)
        area.closeSubpath()
        fill = QColor(pal.accent)
        fill.setAlphaF(0.14)
        p.setBrush(fill)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawPath(area)

        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(pal.accent), 2, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        path = QPainterPath(pts[0])
        for pt in pts[1:]:
            path.lineTo(pt)
        p.drawPath(path)

        # 数据点：有提交的才画实心点，免得一串零点喧宾夺主
        for i, (_d, v) in enumerate(self._series):
            if v <= 0:
                continue
            p.setBrush(QColor(pal.surface))
            p.setPen(QPen(QColor(pal.accent), 2))
            p.drawEllipse(pts[i], 3.2, 3.2)

        # 横轴日期：最多 6 个刻度
        p.setFont(ui_font(t.small_font_size))
        p.setPen(QColor(pal.text_muted))
        ticks = min(6, n)
        for k in range(ticks):
            i = round(k * (n - 1) / max(1, ticks - 1)) if ticks > 1 else 0
            d = self._series[i][0]
            p.drawText(QRectF(x_at(i) - 26, top + h + 5, 52, 16),
                       Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                       f"{d.month}/{d.day}")
        p.end()
