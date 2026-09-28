"""页面级矢量组件：提交结果栏、目录概览、信息行。

都遵守同一套规则：外观在 paintEvent 里用 QPainter 矢量绘制，颜色只从主题令牌取。
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

from PySide6.QtCore import QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QScrollArea, QSizePolicy,
                               QVBoxLayout, QWidget)

from . import icons
from .theme import theme
from .widgets import Badge, Card, Divider, rounded_path, ui_font


class InfoRow(QWidget):
    """一行"名称 —— 值"，左侧灰字右侧黑字，用于目录概览与设置项。"""

    def __init__(self, label: str, value: str = "", parent: Optional[QWidget] = None,
                 mono: bool = False) -> None:
        super().__init__(parent)
        self._label = label
        self._value = value
        self._mono = mono
        self.setFixedHeight(theme().metrics.row_h)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_value(self, value: str) -> None:
        self._value = value
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        t = theme()
        pal = t.palette
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        f = ui_font()
        p.setFont(f)
        fm = QFontMetrics(f)
        p.setPen(QColor(pal.text_dim))
        lw = min(fm.horizontalAdvance(self._label) + 4, int(self.width() * 0.42))
        p.drawText(QRect(0, 0, lw, self.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self._label)
        p.setPen(QColor(pal.text))
        if self._mono:
            from .widgets import mono_font
            p.setFont(mono_font(t.mono_font_size - 1))
        x = lw + t.metrics.space_md
        p.drawText(QRect(x, 0, self.width() - x, self.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   self._value.replace("\n", " "))
        p.end()


class SectionTitle(QWidget):
    """小节标题：小字号、字重中等、带可选右侧说明。"""

    def __init__(self, text: str, hint: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._text = text
        self._hint = hint
        self.setFixedHeight(28)

    def set_hint(self, hint: str) -> None:
        self._hint = hint
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        pal = theme().palette
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setFont(ui_font(theme().small_font_size + 1, QFont.Weight.DemiBold))
        p.setPen(QColor(pal.text_dim))
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   self._text)
        if self._hint:
            p.setFont(ui_font(theme().small_font_size))
            p.setPen(QColor(pal.text_muted))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                       self._hint)
        p.end()


class OverviewList(QWidget):
    """只读的名称+标注列表，用来展示一个目录下有什么（不做交互）。"""

    row_clicked = Signal(int)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        # 每行是 (图标, 名称, 右侧标注, 徽章) 或 (..., 题号标签)
        self._rows: List[tuple] = []
        self._hover = -1
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

    def set_rows(self, rows: Sequence[tuple]) -> None:
        self._rows = list(rows)
        self.setFixedHeight(max(1, len(self._rows)) * theme().metrics.row_h)
        self.update()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        idx = int(event.position().y()) // theme().metrics.row_h
        idx = idx if 0 <= idx < len(self._rows) else -1
        if idx != self._hover:
            self._hover = idx
            self.setCursor(Qt.CursorShape.PointingHandCursor if idx >= 0
                           else Qt.CursorShape.ArrowCursor)
            self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = -1
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        idx = int(event.position().y()) // theme().metrics.row_h
        if 0 <= idx < len(self._rows):
            self.row_clicked.emit(idx)

    def paintEvent(self, event) -> None:  # noqa: N802
        t = theme()
        pal = t.palette
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        fm = QFontMetrics(ui_font())
        fm_small = QFontMetrics(ui_font(t.small_font_size))
        for i, row in enumerate(self._rows):
            ic, name, meta, badge = row[0], row[1], row[2], row[3]
            tag = row[4] if len(row) > 4 else ""
            y = i * t.metrics.row_h
            if i == self._hover:
                p.setBrush(QColor(pal.hover))
                p.setPen(Qt.PenStyle.NoPen)
                p.drawPath(rounded_path(QRectF(0, y, self.width(), t.metrics.row_h),
                                        t.metrics.radius_sm))
            icons.render(p, ic, QRect(8, y + (t.metrics.row_h - t.metrics.icon) // 2,
                                      t.metrics.icon, t.metrics.icon),
                         pal.accent if i == self._hover else pal.text_dim, 1.8)

            x = 8 + t.metrics.icon + t.metrics.space_sm

            # 题号标签放在最前面
            if tag:
                tag_w = fm_small.horizontalAdvance(tag) + t.metrics.space_sm + 6
                p.setBrush(QColor(pal.accent_soft))
                p.setPen(Qt.PenStyle.NoPen)
                p.drawRoundedRect(QRectF(x, y + (t.metrics.row_h - 18) / 2, tag_w, 18), 5, 5)
                p.setFont(ui_font(t.small_font_size, QFont.Weight.Medium))
                p.setPen(QColor(pal.accent))
                p.drawText(QRect(int(x), y, int(tag_w), t.metrics.row_h),
                           Qt.AlignmentFlag.AlignCenter, tag)
                x += tag_w + 7

            # 右侧从右往左排：徽章 → 标注 → 名称，各自 elide，互不压字
            right = self.width() - 8
            badge_w = (fm_small.horizontalAdvance(badge) + t.metrics.space_sm * 2 + 2
                       if badge else 0)
            meta_w = min(fm_small.horizontalAdvance(meta), 150) if meta else 0
            badge_x = right - badge_w
            meta_x = badge_x - (t.metrics.space_sm if badge_w else 0) - meta_w
            name_w = max(24, meta_x - (t.metrics.space_md if meta_w else 0) - x)

            p.setFont(ui_font())
            p.setPen(QColor(pal.text))
            p.drawText(QRect(x, y, name_w, t.metrics.row_h),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                       fm.elidedText(name, Qt.TextElideMode.ElideRight, name_w))

            if meta:
                p.setFont(ui_font(t.small_font_size))
                p.setPen(QColor(pal.text_muted))
                p.drawText(QRect(int(meta_x) - 6, y, int(meta_w) + 6, t.metrics.row_h),
                           Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                           fm_small.elidedText(meta, Qt.TextElideMode.ElideRight,
                                               int(meta_w) + 8))

            if badge:
                p.setBrush(QColor(pal.accent_soft))
                p.setPen(Qt.PenStyle.NoPen)
                p.drawPath(rounded_path(
                    QRectF(badge_x, y + (t.metrics.row_h - 18) / 2, badge_w, 18), 9))
                p.setFont(ui_font(t.small_font_size, QFont.Weight.Medium))
                p.setPen(QColor(pal.accent))
                p.drawText(QRect(int(badge_x), y, int(badge_w), t.metrics.row_h),
                           Qt.AlignmentFlag.AlignCenter, badge)
        p.end()


class ResultPanel(Card):
    """提交结果栏：得分、扣分项、扣分原因。

    站点实测结论的落地：
      - 提交成功但满分的记录，scoredetail 页面是空的 -> 显示"满分，无扣分"
      - 未提交过 -> 显示引导文案，而不是空白
      - 提交中 -> 显示进度提示（活动指示用矢量圆环动画）
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._state = "idle"          # idle | unsubmitted | submitting | done | error
        self._score: Optional[int] = None
        self._deduction: Optional[int] = None
        self._reason: str = ""
        self._message: str = ""
        self._best: Optional[int] = None      # 未提交时下方小字用的历史最高分
        self._idle_text = "尚未提交。写好后点右上角「提交」，这里会显示评测结果。"
        self._spin = 0
        self.setMinimumHeight(120)

        # 徽章只建一次，之后改文字；绝不在 paintEvent 里创建控件
        self._badge = Badge("", "accent", self)
        self._badge.hide()

        from PySide6.QtCore import QTimer
        self._timer = QTimer(self)
        self._timer.setInterval(60)
        self._timer.timeout.connect(self._tick)

    # ---- 状态 ----
    def reset_idle(self, text: Optional[str] = None) -> None:
        self._state = "idle"
        self._score = self._deduction = None
        self._reason = self._message = ""
        if text:
            self._idle_text = text
        self._timer.stop()
        self._badge.hide()
        self._update_min_height()
        self.update()

    def set_submitting(self) -> None:
        self._state = "submitting"
        self._message = "正在提交并等待站点评测（实测约 3～4 秒）…"
        self._spin = 0
        self._badge.hide()
        self._timer.start()
        self._update_min_height()
        self.update()

    def set_result(self, score: Optional[int], deduction: Optional[int],
                   reason: str, message: str = "") -> None:
        self._state = "done"
        self._score, self._deduction, self._reason, self._message = (
            score, deduction, reason, message)
        if score is None:
            self._badge.set_text("未评测", "neutral")
        elif score == 100:
            self._badge.set_text("满分", "success")
        else:
            self._badge.set_text("有扣分", "danger")
        self._badge.show()
        self._timer.stop()
        self._update_min_height()
        self.update()

    def set_unsubmitted(self, best_score: Optional[int] = None) -> None:
        """本地文件还没提交过：结果栏显示"未提交"，历史最高分退到下方小字。

        直接显示历史最高分会让人以为"这个文件已经拿了这个分"，所以分数
        归到小字里，主位留给"未提交"这个事实。
        """
        self._state = "unsubmitted"
        self._score = self._deduction = None
        self._reason = self._message = ""
        self._best = best_score
        self._timer.stop()
        self._badge.hide()
        self._update_min_height()
        self.update()

    def set_error(self, message: str) -> None:
        self._state = "error"
        self._message = message
        self._badge.hide()
        self._timer.stop()
        self._update_min_height()
        self.update()

    def _tick(self) -> None:
        self._spin = (self._spin + 12) % 360
        self._update_min_height()
        self.update()

    # ---- 高度随内容增长（外面套滚动区来提供滚动条）----

    def _reason_width(self) -> int:
        """原因那一列可用宽度（与 paintEvent 里的排版保持一致）。"""
        t = theme()
        pad = t.metrics.space_lg
        if self.width() < 470:                      # 窄布局：原因占整行
            return max(80, self.width() - pad * 2)
        big = QFontMetrics(ui_font(30, QFont.Weight.DemiBold))
        sw = big.horizontalAdvance("—" if self._score is None else str(self._score))
        return max(80, self.width() - (pad + sw + 140) - pad)

    def _update_min_height(self) -> None:
        """内容多高就把最小高度设多高，让外层滚动区出现滚动条。

        不做内部滚动绘制：自定义绘制里裁剪视口很容易引入新的压字问题。
        """
        t = theme()
        pad = t.metrics.space_lg
        fm = QFontMetrics(ui_font())
        if self._state == "done":
            reason = self._reason.strip() or (
                "满分，站点未记录任何扣分项。" if self._score == 100 else "站点未给出具体原因。")
            h = fm.boundingRect(QRect(0, 0, self._reason_width(), 10000),
                                Qt.TextFlag.TextWordWrap, reason).height()
            needed = pad * 2 + 34 + max(h, 22) + 26
        elif self._state == "unsubmitted":
            needed = pad * 2 + 60
        else:
            needed = pad * 2 + fm.boundingRect(
                QRect(0, 0, max(120, self.width() - pad * 2 - 26), 10000),
                Qt.TextFlag.TextWordWrap,
                self._message or self._idle_text).height() + 16
        self.setMinimumHeight(max(112, int(needed)))

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._update_min_height()

    # ---- 绘制 ----
    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        t = theme()
        pal = t.palette
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pad = t.metrics.space_lg
        y = pad

        if self._state == "submitting":
            self._draw_spinner(p, QRect(pad, y, 16, 16))
            p.setFont(ui_font())
            p.setPen(QColor(pal.text_dim))
            p.drawText(QRect(pad + 26, y - 2, self.width() - pad * 2 - 26, 22),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                       self._message)
            p.end()
            return

        if self._state == "unsubmitted":
            pal = theme().palette
            p.setFont(ui_font(24, QFont.Weight.DemiBold))
            p.setPen(QColor(pal.text_muted))
            p.drawText(QRect(pad, y - 4, self.width() - pad * 2, 34),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                       "未提交")
            p.setFont(ui_font(t.small_font_size))
            p.setPen(QColor(pal.text_muted))
            best = ("还没有提交记录" if not self._best
                    else f"历史最高分：{self._best}")
            p.drawText(QRect(pad, y + 32, self.width() - pad * 2, 18),
                       Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft, best)
            p.end()
            return

        if self._state in ("idle", "error"):
            color = pal.danger if self._state == "error" else pal.text_muted
            name = "alert" if self._state == "error" else "info"
            icons.render(p, name, QRect(pad, y - 1, 16, 16), color, 1.8)
            p.setFont(ui_font())
            p.setPen(QColor(color))
            p.drawText(QRect(pad + 26, y - 3, self.width() - pad * 2 - 26, 60),
                       Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft
                       | Qt.TextFlag.TextWordWrap, self._message or self._idle_text)
            p.end()
            return

        # 完成态：得分 + 扣分项 + 扣分原因
        full = self._score == 100
        tone = pal.success if full else pal.danger

        # 大号得分
        big = ui_font(30, QFont.Weight.DemiBold)
        p.setFont(big)
        p.setPen(QColor(tone))
        score_text = "—" if self._score is None else str(self._score)
        fm = QFontMetrics(big)
        sw = fm.horizontalAdvance(score_text)
        p.drawText(QRect(pad, y - 6, sw + 4, 40),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, score_text)
        p.setFont(ui_font(t.small_font_size))
        p.setPen(QColor(pal.text_muted))
        p.drawText(QRect(pad + sw + 8, y + 6, 40, 24),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, "分")

        # 徽章：只挪位置，内容在 set_result 里更新（不在绘制里创建控件）
        self._badge.move(pad + sw + 40, y + 2)

        # 窄的时候改用竖排布局，否则原因那一列会被挤成一条缝
        if self.width() < 470:
            row_y = y + 46
            p.setFont(ui_font())
            p.setPen(QColor(pal.text_dim))
            p.drawText(QRect(pad, row_y, 60, 22),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, "扣分项")
            p.setPen(QColor(pal.text))
            p.drawText(QRect(pad + 62, row_y, self.width() - pad * 2 - 62, 22),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                       "无" if not self._deduction else str(self._deduction))
            p.setFont(ui_font(t.small_font_size))
            p.setPen(QColor(pal.text_dim))
            p.drawText(QRect(pad, row_y + 24, self.width() - pad * 2, 18),
                       Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft, "扣分原因")
            reason_rect = QRect(pad, row_y + 44, self.width() - pad * 2,
                                max(20, self.height() - row_y - 52))
        else:
            x2 = pad + sw + 140
            left_w = max(150, int(x2) - pad)
            p.setFont(ui_font())
            p.setPen(QColor(pal.text_dim))
            p.drawText(QRect(pad, y + 40, left_w, 22),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                       "扣分项" if self._deduction else "扣分")
            p.setPen(QColor(pal.text))
            p.drawText(QRect(pad + 64, y + 40, left_w, 22),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                       "无" if not self._deduction else str(self._deduction))
            p.setFont(ui_font(t.small_font_size + 1))
            p.setPen(QColor(pal.text_dim))
            p.drawText(QRect(int(x2), y - 2, self.width() - int(x2) - pad, 20),
                       Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft, "扣分原因")
            reason_rect = QRect(int(x2), y + 20, self.width() - int(x2) - pad,
                                max(20, self.height() - y - 30))

        reason = self._reason.strip() or (
            "满分，站点未记录任何扣分项。" if full else "站点未给出具体原因。")
        p.setFont(ui_font())
        p.setPen(QColor(pal.text if self._reason else pal.text_muted))
        p.drawText(reason_rect,
                   Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft
                   | Qt.TextFlag.TextWordWrap, reason)

        # 来源说明（"上次提交：…" / "历史提交 #N …"）画在左下角。
        # 没有它的话，切换本地文件与历史提交时这一栏可能完全看不出变化
        # （比如整道题都是满分，数字一样）。
        if self._message:
            p.setFont(ui_font(t.small_font_size))
            p.setPen(QColor(pal.text_muted))
            p.drawText(QRect(pad, self.height() - 22, self.width() - pad * 2, 18),
                       Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignLeft,
                       self._message)
        p.end()

    def _draw_spinner(self, p: QPainter, rect: QRect) -> None:
        """矢量圆环进度：一段圆弧随时间旋转，不用任何位图。"""
        pal = theme().palette
        p.save()
        p.translate(rect.center())
        p.rotate(self._spin)
        pen = QPen(QColor(pal.accent), 2.2, Qt.PenStyle.SolidLine,
                   Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        r = rect.width() / 2 - 1.5
        p.drawArc(QRectF(-r, -r, r * 2, r * 2), 0, 110 * 16)
        pen.setColor(QColor(pal.border))
        p.setPen(pen)
        p.drawArc(QRectF(-r, -r, r * 2, r * 2), 130 * 16, 230 * 16)
        p.restore()


class ReadonlyHint(QWidget):
    """只读模式的小字提示：警告图标 + 文字。

    刻意做成一行小字而不是占据整个结果栏 —— 结果栏要照常显示分数与扣分，
    只读只是一个状态注记。
    """

    def __init__(self, parent: Optional[QWidget] = None,
                 text: str = "只读模式") -> None:
        super().__init__(parent)
        self._text = text
        self.setFixedHeight(20)
        self.setVisible(False)

    def set_hint(self, text: str) -> None:
        self._text = text
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        pal = theme().palette
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        icons.render(p, "alert", QRect(0, 3, 14, 14), pal.warning, 1.9)
        p.setFont(ui_font(theme().small_font_size))
        p.setPen(QColor(pal.warning))
        p.drawText(QRect(19, 0, max(0, self.width() - 19), self.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   self._text)
        p.end()


class Placeholder(QWidget):
    """还没开发的页面占位：一个居中图标 + 标题 + 说明。"""

    def __init__(self, title: str, note: str, icon: str = "info",
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._title = title
        self._note = note
        self._icon = icon

    def paintEvent(self, event) -> None:  # noqa: N802
        t = theme()
        pal = t.palette
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        cx, cy = self.width() // 2, self.height() // 2
        size = 44
        icons.render(p, self._icon, QRect(cx - size // 2, cy - 74, size, size),
                     pal.text_muted, 1.6)
        p.setFont(ui_font(17, QFont.Weight.DemiBold))
        p.setPen(QColor(pal.text_dim))
        p.drawText(QRect(0, cy - 18, self.width(), 28),
                   Qt.AlignmentFlag.AlignCenter, self._title)
        p.setFont(ui_font())
        p.setPen(QColor(pal.text_muted))
        p.drawText(QRect(0, cy + 14, self.width(), 60),
                   Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop
                   | Qt.TextFlag.TextWordWrap, self._note)
        p.end()
