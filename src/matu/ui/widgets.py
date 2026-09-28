"""自绘矢量控件基元：按钮、卡片、徽章、面包屑、分段控件。

这些控件都不用 QSS 外观，而是在 paintEvent 里用 QPainter 画矢量图形，
好处是亮/暗主题切换、悬停/按下/禁用态都能精确控制，且任意 DPI 都锐利。
"""

from __future__ import annotations

from typing import Callable, List, Optional, Sequence, Tuple

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QSplitter, QSplitterHandle, QWidget

from . import icons
from .theme import theme


# ----------------------------------------------------------------- 字体助手

def ui_font(size: Optional[int] = None, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    t = theme()
    f = QFont()
    f.setFamilies([s.strip().strip("'\"") for s in t.font_families()["ui"].split(",")])
    f.setPixelSize(size or t.ui_font_size)
    f.setWeight(weight)
    return f


def mono_font(size: Optional[int] = None) -> QFont:
    t = theme()
    f = QFont()
    f.setFamilies([s.strip().strip("'\"") for s in t.font_families()["mono"].split(",")])
    f.setPixelSize(size or t.mono_font_size)
    f.setStyleHint(QFont.StyleHint.Monospace)
    return f


def rounded_path(rect: QRectF, radius: float) -> QPainterPath:
    p = QPainterPath()
    p.addRoundedRect(rect, radius, radius)
    return p


# ----------------------------------------------------------------- 卡片

class Card(QWidget):
    """圆角面板。界面里的每一块"卡片"都用它，保证圆角与描边一致。"""

    def __init__(self, parent: Optional[QWidget] = None, radius: Optional[int] = None,
                 fill: Optional[str] = None, border: Optional[str] = None) -> None:
        super().__init__(parent)
        self._radius = radius
        self._fill = fill
        self._border = border
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)

    def paintEvent(self, event) -> None:  # noqa: N802
        t = theme()
        pal = t.palette
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        radius = self._radius if self._radius is not None else t.metrics.radius_lg
        p.setBrush(QColor(self._fill or pal.surface))
        p.setPen(QPen(QColor(self._border or pal.border), t.metrics.border_w))
        p.drawPath(rounded_path(r, radius))
        p.end()


# ----------------------------------------------------------------- 按钮

class VectorButton(QWidget):
    """矢量按钮。三种外观：primary（实心强调）、subtle（浅底）、ghost（无底）。

    图标可选，图标是矢量绘制，颜色随主题与状态变化。
    """

    clicked = Signal()

    PRIMARY, SUBTLE, GHOST, DANGER = "primary", "subtle", "ghost", "danger"

    def __init__(self, text: str = "", icon: Optional[str] = None,
                 kind: str = GHOST, parent: Optional[QWidget] = None,
                 min_width: int = 0, height: Optional[int] = None,
                 tooltip: str = "") -> None:
        super().__init__(parent)
        self._text = text
        self._icon = icon
        self._kind = kind
        self._hover = False
        self._pressed = False
        self._enabled_look = True
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self._min_width = min_width
        self._height = height
        self._compact = False        # 紧凑模式：只留图标，文字隐藏
        if tooltip:
            self.setToolTip(tooltip)
        self._recalc()

    # ---- 几何 ----
    @property
    def visible_text(self) -> str:
        """紧凑模式下（有图标时）不画文字。"""
        if self._compact and self._icon:
            return ""
        return self._text

    def set_compact(self, compact: bool) -> None:
        """窄容器下切紧凑：文字收起，只留图标，避免把面板撑宽。"""
        if compact == self._compact:
            return
        self._compact = compact
        if self._icon:
            self.setToolTip(self._text)
        self._recalc()

    def _recalc(self) -> None:
        t = theme()
        h = self._height or (t.metrics.nav_item_h - 6)
        fm = QFontMetrics(ui_font())
        text = self.visible_text
        w = fm.horizontalAdvance(text)
        if self._icon:
            w += t.metrics.icon + (6 if text else 0)
        w += t.metrics.space_lg * 2
        self.setFixedHeight(h)
        minimum = 0 if self._compact else self._min_width
        self.setMinimumWidth(max(minimum, w))
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.updateGeometry()

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(self.minimumWidth(), self.height())

    def setText(self, text: str) -> None:  # noqa: N802
        self._text = text
        self._recalc()

    def text(self) -> str:
        return self._text

    def set_kind(self, kind: str) -> None:
        self._kind = kind
        self.update()

    # ---- 交互 ----
    def enterEvent(self, event) -> None:  # noqa: N802
        self._hover = True
        self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = False
        self._pressed = False
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self.isEnabled():
            self._pressed = True
            self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._pressed and self.rect().contains(event.position().toPoint()):
            self._pressed = False
            self.update()
            self.clicked.emit()
            return
        self._pressed = False
        self.update()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.clicked.emit()

    # ---- 绘制 ----
    def paintEvent(self, event) -> None:  # noqa: N802
        t = theme()
        pal = t.palette
        enabled = self.isEnabled()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        bg, fg, border = self._colors(enabled)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setBrush(QColor(bg) if bg else Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(border), t.metrics.border_w) if border else Qt.PenStyle.NoPen)
        p.drawPath(rounded_path(r, t.metrics.radius_md))

        # 图标 + 文字整体居中
        text = self.visible_text
        fm = QFontMetrics(ui_font())
        icon_w = t.metrics.icon if self._icon else 0
        gap = 6 if (self._icon and text) else 0
        text_w = fm.horizontalAdvance(text) if text else 0
        total = icon_w + gap + text_w
        x = self.width() / 2 - total / 2
        if self._icon:
            icons.render(p, self._icon,
                         QRect(int(x), int((self.height() - t.metrics.icon) / 2),
                               t.metrics.icon, t.metrics.icon),
                         fg, 1.9)
            x += icon_w + gap
        if text:
            p.setPen(QColor(fg))
            p.setFont(ui_font(weight=QFont.Weight.Medium if self._kind == self.PRIMARY
                              else QFont.Weight.Normal))
            p.drawText(QRect(int(x), 0, int(text_w + 2), self.height()),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)
        p.end()

    def _colors(self, enabled: bool) -> Tuple[Optional[str], str, Optional[str]]:
        pal = theme().palette
        if not enabled:
            return (None, pal.text_muted, None) if self._kind == self.GHOST else (
                pal.surface_alt, pal.text_muted, None)
        if self._kind == self.PRIMARY:
            bg = pal.accent_hover if (self._hover or self._pressed) else pal.accent
            return bg, pal.text_on_accent, None
        if self._kind == self.DANGER:
            bg = pal.danger if self._pressed else (pal.danger_soft if self._hover else pal.danger)
            fg = pal.text_on_accent if (self._hover or self._pressed) else pal.danger
            return bg, fg, None
        if self._kind == self.SUBTLE:
            bg = pal.active if self._pressed else (pal.hover if self._hover else pal.surface_alt)
            return bg, pal.text, pal.border
        # GHOST
        if self._pressed:
            return pal.active, pal.text, None
        if self._hover:
            return pal.hover, pal.text, None
        return None, pal.text_dim, None


# ----------------------------------------------------------------- 图标按钮

class IconButton(QWidget):
    """只有一个图标的方形按钮（前进/后退/刷新/折叠都用它）。"""

    clicked = Signal()

    def __init__(self, icon: str, parent: Optional[QWidget] = None,
                 size: int = 30, tooltip: str = "", enabled: bool = True) -> None:
        super().__init__(parent)
        self._icon = icon
        self._size = size
        self._hover = False
        self._pressed = False
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        if tooltip:
            self.setToolTip(tooltip)
        self.setEnabled(enabled)

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hover = True
        self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = False
        self._pressed = False
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self.isEnabled():
            self._pressed = True
            self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._pressed and self.rect().contains(event.position().toPoint()):
            self._pressed = False
            self.update()
            self.clicked.emit()
            return
        self._pressed = False
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        t = theme()
        pal = t.palette
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if self._hover and self.isEnabled():
            p.setBrush(QColor(pal.active if self._pressed else pal.hover))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawPath(rounded_path(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5),
                                    t.metrics.radius_sm))
        color = pal.text if (self._hover and self.isEnabled()) else (
            pal.text_dim if self.isEnabled() else pal.text_muted)
        inset = (self._size - t.metrics.icon) // 2
        icons.render(p, self._icon, QRect(inset, inset, t.metrics.icon, t.metrics.icon), color)
        p.end()


# ----------------------------------------------------------------- 徽章

class Badge(QWidget):
    """小圆角标签，用来显示"满分/扣分/C++/100 分"这类短信息。"""

    def __init__(self, text: str = "", tone: str = "neutral",
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._text = text
        self._tone = tone
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._recalc()

    def _recalc(self) -> None:
        t = theme()
        fm = QFontMetrics(ui_font(t.small_font_size, QFont.Weight.Medium))
        h = fm.height() + 6
        self.setFixedSize(fm.horizontalAdvance(self._text) + t.metrics.space_sm * 2 + 2, h)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(self.width(), self.height())

    def set_text(self, text: str, tone: Optional[str] = None) -> None:
        self._text = text
        if tone:
            self._tone = tone
        self._recalc()
        self.update()

    def text(self) -> str:
        return self._text

    def set_tone(self, tone: str) -> None:
        self._tone = tone
        self.update()

    def _colors(self) -> Tuple[str, str]:
        pal = theme().palette
        return {
            "neutral": (pal.surface_alt, pal.text_dim),
            "accent": (pal.accent_soft, pal.accent),
            "success": (pal.success_soft, pal.success),
            "warning": (pal.warning_soft, pal.warning),
            "danger": (pal.danger_soft, pal.danger),
        }.get(self._tone, (pal.surface_alt, pal.text_dim))

    def paintEvent(self, event) -> None:  # noqa: N802
        t = theme()
        bg, fg = self._colors()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setBrush(QColor(bg))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawPath(rounded_path(QRectF(self.rect()), self.height() / 2))
        p.setPen(QColor(fg))
        p.setFont(ui_font(t.small_font_size, QFont.Weight.Medium))
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._text)
        p.end()


class VectorSpin(QWidget):
    """矢量步进器：[-] 数值 [+]，取代 QSpinBox。

    QSpinBox 的上下箭头是样式引擎画的，和矢量风格冲突，而且 QSS 只能靠位图
    换掉它（本项目不用位图）。这里自绘一个：加减号也是矢量路径。
    """

    valueChanged = Signal(int)

    def __init__(self, parent: Optional[QWidget] = None, minimum: int = 0,
                 maximum: int = 100, value: int = 0, step: int = 1,
                 suffix: str = "", width: int = 130) -> None:
        super().__init__(parent)
        self._min, self._max, self._step = minimum, maximum, step
        self._value = max(minimum, min(maximum, value))
        self._suffix = suffix
        self._hover = 0              # -1 减号 / 0 无 / 1 加号
        self.setFixedSize(width, 28)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

    # ---- 值 ----
    def value(self) -> int:
        return self._value

    def setValue(self, value: int) -> None:  # noqa: N802
        value = max(self._min, min(self._max, value))
        if value != self._value:
            self._value = value
            self.update()
            self.valueChanged.emit(value)

    def setRange(self, minimum: int, maximum: int) -> None:  # noqa: N802
        self._min, self._max = minimum, maximum
        self.setValue(self._value)

    # ---- 交互 ----
    def _zone(self, x: float) -> int:
        if x < self.width() / 2 - 18:
            return -1
        if x > self.width() / 2 + 18:
            return 1
        return 0

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        zone = self._zone(event.position().x())
        if zone != self._hover:
            self._hover = zone
            self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = 0
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        zone = self._zone(event.position().x())
        if zone:
            self.setValue(self._value + zone * self._step)
            self._hover = zone
            self.update()

    def wheelEvent(self, event) -> None:  # noqa: N802
        self.setValue(self._value + (1 if event.angleDelta().y() > 0 else -1) * self._step)

    # ---- 绘制 ----
    def paintEvent(self, event) -> None:  # noqa: N802
        t = theme()
        pal = t.palette
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setBrush(QColor(pal.surface_alt))
        p.setPen(QPen(QColor(pal.border), t.metrics.border_w))
        p.drawPath(rounded_path(r, 7))

        mid = self.height() / 2
        color = pal.text_dim if self.isEnabled() else pal.text_muted
        for side in (-1, 1):
            cx = self.width() / 2 + side * (self.width() / 2 - 15)
            zone_hot = self._hover == side and self.isEnabled()
            if zone_hot:
                p.setBrush(QColor(pal.hover))
                p.setPen(Qt.PenStyle.NoPen)
                p.drawPath(rounded_path(QRectF(cx - 12, mid - 11, 24, 22), 5))
            pen = QPen(QColor(pal.accent if zone_hot else color), 1.9,
                       Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.drawLine(QPointF(cx - 5, mid), QPointF(cx + 5, mid))       # 横杠
            if side > 0:                                                 # 加号的竖杠
                p.drawLine(QPointF(cx, mid - 5), QPointF(cx, mid + 5))

        p.setFont(ui_font())
        p.setPen(QColor(pal.text if self.isEnabled() else pal.text_muted))
        text = f"{self._value}{self._suffix}"
        p.drawText(QRectF(28, 0, self.width() - 56, self.height()),
                   Qt.AlignmentFlag.AlignCenter, text)
        p.end()


# ----------------------------------------------------------------- 分隔线

class Divider(QWidget):
    def __init__(self, parent: Optional[QWidget] = None, vertical: bool = False) -> None:
        super().__init__(parent)
        self._vertical = vertical
        if vertical:
            self.setFixedWidth(1)
            self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        else:
            self.setFixedHeight(1)
            self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def paintEvent(self, event) -> None:  # noqa: N802
        pal = theme().palette
        p = QPainter(self)
        p.setPen(QPen(QColor(pal.border), 1))
        if self._vertical:
            p.drawLine(self.width() // 2, 0, self.width() // 2, self.height())
        else:
            p.drawLine(0, self.height() // 2, self.width(), self.height() // 2)
        p.end()


# ----------------------------------------------------------------- 面包屑

class Breadcrumb(QWidget):
    """当前位置路径：我的班级 / 作业列表 / c语言 / 第1次上机 / 计算e的x次方。

    每一段可点击，点击即跳回该层级（和访达的路径栏同理）。
    """

    segment_clicked = Signal(int)   # 段索引

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._segments: List[str] = []
        self._hover_index = -1
        self._hits: List[Tuple[int, int, int]] = []  # (起点x, 终点x, 索引)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setMouseTracking(True)
        self.setFixedHeight(theme().metrics.toolbar_h - 10)

    def set_segments(self, segments: Sequence[str]) -> None:
        self._segments = list(segments)
        self._hover_index = -1
        self.update()

    def segments(self) -> List[str]:
        return list(self._segments)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        x = event.position().x()
        new = -1
        for start, end, idx in self._hits:
            if start <= x <= end:
                new = idx
                break
        if new != self._hover_index:
            self._hover_index = new
            self.setCursor(Qt.CursorShape.PointingHandCursor if new >= 0
                           else Qt.CursorShape.ArrowCursor)
            self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover_index = -1
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        x = event.position().x()
        for start, end, idx in self._hits:
            if start <= x <= end:
                self.segment_clicked.emit(idx)
                return

    def paintEvent(self, event) -> None:  # noqa: N802
        t = theme()
        pal = t.palette
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        f = ui_font()
        p.setFont(f)
        fm = QFontMetrics(f)
        x = 2
        self._hits = []
        for i, seg in enumerate(self._segments):
            last = i == len(self._segments) - 1
            color = pal.text if last else (
                pal.accent if i == self._hover_index else pal.text_dim)
            w = fm.horizontalAdvance(seg)
            p.setPen(QColor(color))
            p.drawText(QRect(x, 0, w + 2, self.height()),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, seg)
            if i < len(self._segments) - 1:
                self._hits.append((x, x + w, i))
            else:
                self._hits.append((x, x + w, i))
            x += w
            if not last:
                sep = "›"
                sw = fm.horizontalAdvance(sep)
                p.setPen(QColor(pal.text_muted))
                p.drawText(QRect(x + 3, 0, sw + 4, self.height()),
                           Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, sep)
                x += sw + 9
        p.end()


# ----------------------------------------------------------------- 分栏手柄

class _GripHandle(QSplitterHandle):
    """分栏手柄：中间画一条 1px 分隔线，悬停时加深。

    Qt 默认的 handle 是纯色块或需要位图皮肤，这里自己画，既明显又不粗暴。
    抓取区域仍是完整的 handle 宽度（默认 8px），所以好拖。
    """

    def __init__(self, orientation, parent) -> None:
        super().__init__(orientation, parent)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self._hover = False
        self.setCursor(Qt.CursorShape.SplitHCursor
                       if orientation == Qt.Orientation.Horizontal
                       else Qt.CursorShape.SplitVCursor)

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hover = True
        self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = False
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        t = theme()
        pal = t.palette
        p = QPainter(self)
        color = pal.accent if self._hover else pal.border_strong
        pen = QPen(QColor(color), 2 if self._hover else 1)
        p.setPen(pen)
        if self.orientation() == Qt.Orientation.Horizontal:
            x = self.width() // 2
            p.drawLine(x, 0, x, self.height())
        else:
            y = self.height() // 2
            p.drawLine(0, y, self.width(), y)
        p.end()


class GripSplitter(QSplitter):
    """带可见分隔线的分栏容器。分界线是矢量绘制的，不依赖位图皮肤。"""

    def createHandle(self):  # noqa: N802
        return _GripHandle(self.orientation(), self)
