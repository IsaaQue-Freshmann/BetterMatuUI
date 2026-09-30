"""左侧菜单栏：logo、四个菜单、折叠开关、个人中心吸附底部。

全部自绘（含矢量图标与文字），折叠时宽度动画收窄、文字淡出，
展开/折叠状态会被记住。
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from PySide6.QtCore import (QEasingCurve, QPoint, QPointF, QRect, QRectF, Qt, QTimer,
                            QVariantAnimation, Signal)
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from . import icons
from .theme import theme
from .widgets import Divider, ui_font, rounded_path

# (键, 显示名, 图标)
NAV_ITEMS: List[Tuple[str, str, str]] = [
    ("my_class", "我的班级", "class"),
    ("task_center", "题目中心", "tasks"),
    ("data_center", "数据中心", "chart"),
    ("help", "系统帮助", "help"),
]
PROFILE_ITEM = ("profile", "个人中心", "user")

HEADER_H = 58


class NavButton(QWidget):
    """一个菜单项。自绘图标与文字，选中态是圆角胶囊。"""

    clicked = Signal(str)

    def __init__(self, key: str, label: str, icon: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.key = key
        self.label = label
        self.icon_name = icon
        self._selected = False
        self._hover = False
        self._alert = False      # 告警：图标右上角黄色带圈感叹号
        self._progress = 1.0     # 展开程度：1 完全展开，0 完全折叠
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setFixedHeight(theme().metrics.nav_item_h)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

    def set_selected(self, value: bool) -> None:
        if self._selected != value:
            self._selected = value
            self.update()

    def set_alert(self, alert: bool) -> None:
        if alert != self._alert:
            self._alert = alert
            self.update()

    def set_progress(self, value: float) -> None:
        self._progress = max(0.0, min(1.0, value))
        self.setToolTip(self.label if self._progress < 0.6 else "")
        self.update()

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hover = True
        self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = False
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(
                event.position().toPoint()):
            self.clicked.emit(self.key)

    def paintEvent(self, event) -> None:  # noqa: N802
        t = theme()
        pal = t.palette
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        pad = t.metrics.space_sm
        r = QRectF(self.rect()).adjusted(pad, 3, -pad, -3)

        if self._selected:
            p.setBrush(QColor(pal.accent_soft))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawPath(rounded_path(r, t.metrics.radius_md))
        elif self._hover:
            p.setBrush(QColor(pal.hover))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawPath(rounded_path(r, t.metrics.radius_md))

        color = pal.accent if self._selected else (pal.text if self._hover else pal.text_dim)

        # 图标始终居中于"折叠后的 64px 轨道"，这样动画中图标不会左右跳
        track_w = t.metrics.sidebar_w_collapsed
        icon_x = (track_w - t.metrics.icon) / 2
        icon_y = (self.height() - t.metrics.icon) / 2
        icons.render(p, self.icon_name,
                     QRect(int(icon_x), int(icon_y), t.metrics.icon, t.metrics.icon),
                     color, 1.9)

        # 告警：图标右上角的黄色带圈感叹号
        if self._alert:
            rad = t.metrics.icon / 2 + 1
            cx, cy = icon_x + t.metrics.icon - 2, icon_y - 1
            p.setBrush(QColor(pal.warning))
            p.setPen(QPen(QColor(pal.sidebar), 2))     # 描边把图标"挖"出来
            p.drawEllipse(QPointF(cx, cy), rad, rad)
            p.setPen(QPen(QColor(pal.bg), 1.8))
            f = QFont()
            f.setPixelSize(int(rad * 1.5))
            f.setBold(True)
            p.setFont(f)
            p.drawText(QRectF(cx - rad, cy - rad, rad * 2, rad * 2),
                       Qt.AlignmentFlag.AlignCenter, "!")

        # 文字随展开程度淡出并右移一点点
        if self._progress > 0.02:
            f = ui_font(weight=QFont.Weight.Medium if self._selected
                        else QFont.Weight.Normal)
            p.setFont(f)
            p.setPen(QColor(color))
            p.setOpacity(self._progress)
            x = int(track_w + 2)
            fm = QFontMetrics(f)
            p.drawText(QRect(x, 0, self.width() - x - pad, self.height()),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                       fm.elidedText(self.label, Qt.TextElideMode.ElideRight,
                                     self.width() - x - pad))
            p.setOpacity(1.0)
        p.end()


def paint_logo(painter: QPainter, size: float, radius_ratio: float = 0.3) -> None:
    """把 {} 标记画到 painter 上（矢量），应用图标与侧栏 logo 共用这一份。

    radius_ratio 是圆角占比：侧栏那种小尺寸用 0.3，应用图标用 0.22更像原生图标。
    """
    pal = theme().palette
    r = QRectF(0.5, 0.5, size - 1, size - 1)
    painter.setBrush(QColor(pal.accent))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawPath(rounded_path(r, size * radius_ratio))
    painter.setPen(QPen(QColor(pal.text_on_accent), max(1.0, size * 0.072),
                        Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                        Qt.PenJoinStyle.RoundJoin))
    painter.drawPath(_brace(QRectF(size * 0.24, size * 0.26, size * 0.15, size * 0.48),
                            mirror=False))
    painter.drawPath(_brace(QRectF(size * 0.61, size * 0.26, size * 0.15, size * 0.48),
                            mirror=True))


class LogoMark(QWidget):
    """应用标记：矢量绘制的圆角方块 + 花括号，不用位图。

    括号是"代码"，方块是"套壳"，正好是 BetterMatuUI 在做的事。
    """

    def __init__(self, parent: Optional[QWidget] = None, size: int = 28) -> None:
        super().__init__(parent)
        self._size = size
        self.setFixedSize(size, size)

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        paint_logo(p, self._size)
        p.end()


def _brace(rect: QRectF, mirror: bool) -> QPainterPath:
    """画一个花括号的矢量路径。"""
    path = QPainterPath()
    x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
    if mirror:
        x = x + w
        w = -w
    path.moveTo(x + w, y)
    path.cubicTo(x, y, x + w, y + h * 0.32, x, y + h * 0.42)
    path.lineTo(x, y + h * 0.5)
    path.lineTo(x, y + h * 0.58)
    path.cubicTo(x + w, y + h * 0.68, x, y + h, x + w, y + h)
    return path


class Sidebar(QWidget):
    """左侧菜单栏整体。"""

    navigate = Signal(str)
    collapsed_changed = Signal(bool)

    def __init__(self, parent: Optional[QWidget] = None, collapsed: bool = False) -> None:
        super().__init__(parent)
        t = theme()
        self._collapsed = collapsed
        self._progress = 0.0 if collapsed else 1.0
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.setFixedWidth(t.metrics.sidebar_w_collapsed if collapsed else t.metrics.sidebar_w)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)

        self._logo = LogoMark(self)
        self._buttons: List[NavButton] = []
        for key, label, ic in NAV_ITEMS + [PROFILE_ITEM]:
            btn = NavButton(key, label, ic, self)
            btn.clicked.connect(self._on_click)
            self._buttons.append(btn)

        self._busy = BusyIndicator(self)
        self._bubble: Optional[AlertBubble] = None
        self._toggle = CollapseToggle(self)
        # 这个连接之前漏了：开关点了没反应，就是因为 clicked 根本没接到槽上
        self._toggle.clicked.connect(self.toggle_collapsed)
        self.set_collapsed(collapsed, animate=False)

        self._anim = QVariantAnimation(self)
        self._anim.setDuration(190)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._anim.valueChanged.connect(self._on_anim)

    # ---- 交互 ----
    def _on_click(self, key: str) -> None:
        self.set_selected(key)
        self.navigate.emit(key)

    def set_selected(self, key: str) -> None:
        for btn in self._buttons:
            btn.set_selected(btn.key == key)

    def profile_button(self) -> NavButton:
        return self._buttons[-1]

    def set_login_alert(self, active: bool, text: str = "登陆状态已过期") -> None:
        """没登录时：个人中心图标加黄色感叹号，并在旁边弹一个黄色气泡。

        都用这个告警位，但**措辞按原因区分**：
          会话失效（自动重登也失败）→ "登陆状态已过期"
          用户自己点了退出登录      → "已退出登录"
          当前账号的缓存被删掉      → "缓存已删除，已退出登录"
        不区分的话，用户主动退出却被告知"已过期"，是一种误导。
        措辞由调用方给：主窗口盯着登录态的统一入口，别在各处零散地弹。
        """
        self.profile_button().set_alert(active)
        if active:
            host = self.window()
            if self._bubble is None or self._bubble.parent() is not host:
                self._bubble = AlertBubble(host)
            self._bubble.set_text(text)
            self._bubble.show()
            self._place_bubble()
            self._bubble.raise_()          # 置顶，压住内容区
        elif self._bubble is not None:
            self._bubble.hide()

    def _place_bubble(self) -> None:
        if self._bubble is None or not self._bubble.isVisible():
            return
        btn = self.profile_button()
        at = btn.mapTo(self.window(), QPoint(btn.width() + 2, 0))
        self._bubble.move(at.x(), at.y() + (btn.height() - self._bubble.height()) // 2)

    def set_busy(self, busy: bool) -> None:
        """有任何加载/上传/下载/登录在跑时让指示器转起来。"""
        self._busy.set_busy(busy)

    def is_collapsed(self) -> bool:
        return self._collapsed

    def toggle_collapsed(self) -> None:
        self.set_collapsed(not self._collapsed)

    def set_collapsed(self, collapsed: bool, animate: bool = True) -> None:
        self._collapsed = collapsed
        start, end = self._progress, (0.0 if collapsed else 1.0)
        self._toggle.set_tooltip("展开侧栏" if collapsed else "收起侧栏")
        self._toggle.update()
        # 状态一旦确定就通知出去（存档），不必等动画结束
        self.collapsed_changed.emit(collapsed)
        if not animate or start == end:
            self._on_anim(end)
            return
        self._anim.stop()
        self._anim.setStartValue(start)
        self._anim.setEndValue(end)
        self._anim.start()

    def _on_anim(self, value) -> None:
        self._progress = float(value)
        t = theme()
        w = t.metrics.sidebar_w_collapsed + (
            t.metrics.sidebar_w - t.metrics.sidebar_w_collapsed) * self._progress
        self.setFixedWidth(int(round(w)))
        for btn in self._buttons:
            btn.set_progress(self._progress)
        self.update()

    # ---- 布局 ----
    def resizeEvent(self, event) -> None:  # noqa: N802
        self._layout_children()

    def _layout_children(self) -> None:
        t = theme()
        w = self.width()
        y = t.metrics.space_md

        # logo 行
        self._logo.move(int((t.metrics.sidebar_w_collapsed - self._logo.width()) / 2), y)
        y += self._logo.height() + t.metrics.space_lg

        for btn in self._buttons[:len(NAV_ITEMS)]:
            btn.setGeometry(0, y, w, btn.height())
            y += btn.height() + 2

        # 底部：折叠开关 -> 分隔线 -> 个人中心
        prof = self._buttons[-1]
        prof.setGeometry(0, self.height() - prof.height() - t.metrics.space_sm,
                         w, prof.height())
        divider_y = prof.y() - t.metrics.space_sm
        self._toggle.setGeometry(int((t.metrics.sidebar_w_collapsed - self._toggle.width()) / 2),
                                 divider_y - self._toggle.height() - t.metrics.space_xs,
                                 self._toggle.width(), self._toggle.height())
        self._place_bubble()      # 气泡跟着个人中心的位置走

        # 加载指示器放在折叠开关上方
        self._busy.setGeometry(int((t.metrics.sidebar_w_collapsed - self._busy.width()) / 2),
                               self._toggle.y() - self._busy.height() - t.metrics.space_xs,
                               self._busy.width(), self._busy.height())

    def minimumSizeHint(self):  # noqa: N802
        return self.sizeHint()

    # ---- 绘制 ----
    def paintEvent(self, event) -> None:  # noqa: N802
        t = theme()
        pal = t.palette
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.fillRect(self.rect(), QColor(pal.sidebar))

        # 右侧描边
        p.setPen(QPen(QColor(pal.border), 1))
        p.drawLine(self.width() - 1, 0, self.width() - 1, self.height())

        # 标题：随展开程度淡出
        if self._progress > 0.02:
            p.setOpacity(self._progress)
            f = ui_font(15, QFont.Weight.DemiBold)
            p.setFont(f)
            p.setPen(QColor(pal.text))
            x = int(t.metrics.sidebar_w_collapsed) + 2
            p.drawText(QRect(x, t.metrics.space_md, self.width() - x - 8,
                             self._logo.height()),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                       "BetterMatuUI")
            p.setOpacity(1.0)

        # 底部个人中心上方的分隔线
        prof = self._buttons[-1]
        dy = prof.y() - t.metrics.space_sm
        p.setPen(QPen(QColor(pal.border), 1))
        p.drawLine(int(t.metrics.space_md / 2), dy, self.width() - int(t.metrics.space_md / 2), dy)
        p.end()


class BusyIndicator(QWidget):
    """加载指示器：一段旋转的矢量圆弧。

    只要有加载/上传/下载/登录在进行就转，动作结束就隐藏。
    """

    def __init__(self, parent: Optional[QWidget] = None, size: int = 26) -> None:
        super().__init__(parent)
        self._size = size
        self._angle = 0
        self.setFixedSize(size, size)
        self.setVisible(False)
        self._timer = QTimer(self)
        self._timer.setInterval(55)
        self._timer.timeout.connect(self._tick)

    def set_busy(self, busy: bool) -> None:
        if busy == self.isVisible():
            return
        self.setVisible(busy)
        if busy:
            self._timer.start()
        else:
            self._timer.stop()

    def _tick(self) -> None:
        self._angle = (self._angle + 30) % 360
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        t = theme()
        pal = t.palette
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = self._size / 2 - 3
        p.translate(self._size / 2, self._size / 2)
        # 底圈
        p.setPen(QPen(QColor(pal.border), 2.2, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap))
        p.drawEllipse(QRectF(-r, -r, r * 2, r * 2))
        # 转动的那一段
        p.rotate(self._angle)
        p.setPen(QPen(QColor(pal.accent), 2.2, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap))
        p.drawArc(QRectF(-r, -r, r * 2, r * 2), 0, 100 * 16)
        p.end()



class AlertBubble(QWidget):
    """微信式语言气泡：圆角矩形 + 左侧小尖角，提示"登录状态已过期"。

    它挂在**窗口**上而不是侧栏里：侧栏只有 64px 宽，气泡放进去会被裁掉；
    挂到窗口再 raise_() 才能浮在内容区之上。
    """

    def __init__(self, parent: QWidget, text: str = "登陆状态已过期") -> None:
        super().__init__(parent)
        self._text = text
        t = theme()
        fm = QFontMetrics(ui_font(t.small_font_size))
        self._w = fm.horizontalAdvance(text) + t.metrics.space_md * 2 + 12
        self._h = fm.height() + t.metrics.space_sm + 6
        self.resize(self._w, self._h)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def set_text(self, text: str) -> None:
        if text == self._text:
            return
        self._text = text
        t = theme()
        fm = QFontMetrics(ui_font(t.small_font_size))
        self._w = fm.horizontalAdvance(text) + t.metrics.space_md * 2 + 12
        self.resize(self._w, self._h)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        t = theme()
        pal = t.palette
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        tail = 7
        body = QRectF(tail, 0, self._w - tail, self._h)
        p.setBrush(QColor(pal.warning))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawPath(rounded_path(body, 8))
        tip = QPainterPath()
        cy = self._h / 2
        tip.moveTo(tail, cy - 5)
        tip.lineTo(0, cy)
        tip.lineTo(tail, cy + 5)
        tip.closeSubpath()
        p.drawPath(tip)
        p.setFont(ui_font(t.small_font_size, QFont.Weight.Medium))
        p.setPen(QColor(pal.bg))
        p.drawText(body, Qt.AlignmentFlag.AlignCenter, self._text)
        p.end()


class CollapseToggle(QWidget):
    """折叠开关：一个图标的按钮。"""

    clicked = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._hover = False
        self._tip = "收起侧栏"
        self.setFixedSize(30, 30)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

    def set_tooltip(self, text: str) -> None:
        self._tip = text
        self.setToolTip(text)

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
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if self._hover:
            p.setBrush(QColor(pal.hover))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawPath(rounded_path(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5),
                                    t.metrics.radius_sm))
        color = pal.text if self._hover else pal.text_muted
        inset = (self.width() - t.metrics.icon) // 2
        icons.render(p, "panel-left",
                     QRect(inset, inset, t.metrics.icon, t.metrics.icon), color)
        p.end()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
