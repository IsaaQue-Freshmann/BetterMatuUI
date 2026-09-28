"""「我的班级」页面：左区目录浏览器 + 右区代码区。

左区：功能栏（前进/后退/刷新 + 当前位置路径）+ 访达风格的竖向树状列表。
      单击展开/收起，双击"进入"（记入历史），前进/后退沿历史移动。
右区：上栏题面（可折叠）+ 编辑器（语法高亮）+ 提交按钮；下栏提交结果。

数据全部来自本地 SQLite，打开页面不发任何网络请求；
只有"提交"和"刷新"才会联网，且提交后只拉取结果一次。
"""

from __future__ import annotations

import re
from typing import List, Optional

from PySide6.QtCore import (QModelIndex, QRect, QRectF, QSize, Qt, QThread,
                            QTimer, Signal)
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QDialog,
                               QHBoxLayout, QLabel, QPlainTextEdit, QScrollArea,
                               QSizePolicy, QSplitter, QStackedWidget,
                               QStyledItemDelegate, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from .. import icons
from ..class_tree import Node, build_class_tree, find_task_node
from ..code_editor import CodeEditor
from ..history import FileListPanel
from ..panels import (Badge, Divider, InfoRow, OverviewList, ReadonlyHint,
                      ResultPanel, SectionTitle)
from ..theme import theme
from ..widgets import (Breadcrumb, Card, GripSplitter, IconButton, VectorButton,
                       mono_font, ui_font)
from ...core import parsers as P
from ...core import submit as S

CHEVRON_W = 18
INDENT_W = 10        # 每一层的缩进量，由委托自绘（目录栏窄，缩进要省着用）
STATEMENT_MIN_H = 78        # 题面展开时的最小高度（约两行）
STATEMENT_COLLAPSED_H = 34  # 折叠后只剩标题条
STATEMENT_DEFAULT_H = 200   # 默认高度


# ----------------------------------------------------------------- 树 委托

class TreeDelegate(QStyledItemDelegate):
    """自己画行内容：展开箭头 + 图标 + 名称 + 右侧标注 + 徽章。

    不用 QTreeWidget 自带的分支指示器，因为它只能靠位图皮肤，
    而这里是全矢量界面：箭头也是矢量绘制的。
    """

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        return QSize(120, theme().metrics.row_h + 2)

    @staticmethod
    def depth_of(index: QModelIndex) -> int:
        """节点在树里的层级（根为 0）。"""
        depth, parent = 0, index.parent()
        while parent.isValid():
            depth += 1
            parent = parent.parent()
        return depth

    def paint(self, painter: QPainter, option, index: QModelIndex) -> None:
        t = theme()
        pal = t.palette
        node: Node = index.data(Qt.ItemDataRole.UserRole)
        if node is None:
            super().paint(painter, option, index)
            return

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = QRectF(option.rect).adjusted(2, 1, -2, -1)

        if option.state & option.state.__class__.State_Selected:
            painter.setBrush(QColor(pal.accent_soft))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(r, t.metrics.radius_sm, t.metrics.radius_sm)
        elif option.state & option.state.__class__.State_MouseOver:
            painter.setBrush(QColor(pal.hover))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(r, t.metrics.radius_sm, t.metrics.radius_sm)

        x = option.rect.left() + 3 + self.depth_of(index) * INDENT_W
        mid = option.rect.top() + option.rect.height() // 2

        # 展开箭头（只有有子节点才画）
        if not node.is_leaf:
            expanded = None
            tree = self.parent()
            if isinstance(tree, QTreeWidget):
                item = tree.itemFromIndex(index)
                if item is not None:
                    expanded = item.isExpanded()
            icons.render(painter, "chevron-down" if expanded else "chevron-right",
                         QRect(x, mid - 7, 14, 14), pal.text_muted, 2.1)
        x += CHEVRON_W

        # 图标
        icon_size = t.metrics.icon - 2
        icons.render(painter, node.icon,
                     QRect(x, mid - icon_size // 2, icon_size, icon_size),
                     pal.accent if node.kind in ("group", "course") else pal.text_dim, 1.8)
        x += icon_size + 7

        # 题目编号标签：放在每道题的最前面（题号不能少）
        fm_small = QFontMetrics(ui_font(t.small_font_size))
        tag = f"#{node.task_id}" if (node.kind == "task" and node.task_id) else ""
        if tag:
            tag_w = fm_small.horizontalAdvance(tag) + t.metrics.space_sm + 6
            painter.setBrush(QColor(pal.accent_soft))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(QRectF(x, mid - 9, tag_w, 18), 5, 5)
            painter.setFont(ui_font(t.small_font_size, QFont.Weight.Medium))
            painter.setPen(QColor(pal.accent))
            painter.drawText(QRect(int(x), option.rect.top(), int(tag_w),
                                   option.rect.height()),
                             Qt.AlignmentFlag.AlignCenter, tag)
            x += tag_w + 7

        # 右侧信息从右往左依次排：徽章 → 间距 → 标注 → 间距 → 名称。
        # 空间不够时**逐级弃车保帅**：先丢标注、再丢徽章，保证名称不被压字。
        fm = QFontMetrics(ui_font())
        right = option.rect.right() - 6
        badge_w = (fm_small.horizontalAdvance(node.badge) + t.metrics.space_sm * 2 + 2
                   if node.badge else 0)
        meta_w = min(fm_small.horizontalAdvance(node.meta), 150) if node.meta else 0
        min_name = 56
        if x + min_name + meta_w + (t.metrics.space_sm if badge_w else 0) + badge_w > right:
            meta_w = 0
        if x + min_name + badge_w > right:
            badge_w = 0
        badge_x = right - badge_w
        meta_x = badge_x - (t.metrics.space_sm if badge_w else 0) - meta_w
        name_w = meta_x - (t.metrics.space_md if meta_w else 0) - x
        if meta_w:
            meta_x -= 6          # 给 elideText 留余量，避免刚好放得下也被省略

        painter.setFont(ui_font())
        painter.setPen(QColor(pal.text if node.kind != "hint" else pal.text_muted))
        painter.drawText(QRect(x, option.rect.top(), max(24, name_w), option.rect.height()),
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                         fm.elidedText(node.label, Qt.TextElideMode.ElideRight,
                                       max(24, name_w)))

        if node.meta:
            painter.setFont(ui_font(t.small_font_size))
            painter.setPen(QColor(pal.text_muted))
            # 多留 6px 给 elideText 判断，否则刚好放得下的文本也会被省略成 "2026-09..."
            painter.drawText(QRect(int(meta_x), option.rect.top(), int(meta_w) + 6,
                                   option.rect.height()),
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                             fm_small.elidedText(node.meta, Qt.TextElideMode.ElideRight,
                                                 int(meta_w) + 8))

        if node.badge:
            painter.setBrush(QColor(pal.accent_soft))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(QRectF(badge_x, mid - 9, badge_w, 18), 9, 9)
            painter.setFont(ui_font(t.small_font_size, QFont.Weight.Medium))
            painter.setPen(QColor(pal.accent))
            painter.drawText(QRect(int(badge_x), option.rect.top(), int(badge_w),
                                   option.rect.height()),
                             Qt.AlignmentFlag.AlignCenter, node.badge)
        painter.restore()


# ----------------------------------------------------------------- 左区

class NodeTree(QTreeWidget):
    """目录树。

    必须拦掉 Qt 的一个默认行为：为了让"当前项"可见，`scrollTo` 会**自动把
    当前项的祖先逐级展开**，于是"目录默认全部折叠"会被悄悄破坏 ——
    只要选中的是一道深层题目，整条路径就被撑开了。
    这里改成：只在祖先都已展开时才滚到该项，否则滚到最近的那个可见祖先。
    """

    def scrollTo(self, index: QModelIndex, hint=None) -> None:  # noqa: N802
        if not index.isValid():
            return
        hint = hint if hint is not None else QTreeWidget.ScrollHint.EnsureVisible
        # 从根往下走，只要当前节点是展开的就能继续往下；
        # 停下来的那个就是"当前可见的最深祖先"，滚它不会触发任何展开。
        chain = []
        node = index
        while node.isValid():
            chain.append(node)
            node = node.parent()
        chain.reverse()                      # [顶层, ..., index]
        visible = chain[0]
        for candidate in chain[1:]:
            if not self.isExpanded(visible):
                break
            visible = candidate
        super().scrollTo(visible, hint)


class BrowserPanel(QWidget):
    """目录浏览器：功能栏 + 树状列表。"""

    node_activated = Signal(object)     # 双击"进入"
    node_selected = Signal(object)      # 选中
    refresh_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None,
                 show_refresh: bool = True) -> None:
        super().__init__(parent)
        t = theme()
        self._history: List[Node] = []
        self._index = -1

        self._back = IconButton("arrow-left", self, tooltip="后退")
        self._forward = IconButton("arrow-right", self, tooltip="前进")
        self._refresh = IconButton("refresh", self, tooltip="从站点刷新（会联网）")
        self._crumb = Breadcrumb(self)
        self._back.clicked.connect(self.go_back)
        self._forward.clicked.connect(self.go_forward)
        self._refresh.clicked.connect(self.refresh_requested.emit)

        bar = QWidget(self)
        bar.setFixedHeight(t.metrics.toolbar_h)
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(t.metrics.space_sm, 0, t.metrics.space_md, 0)
        bl.setSpacing(t.metrics.space_xs)
        bl.addWidget(self._back)
        bl.addWidget(self._forward)
        # 内容全部来自本地（内置文档或本地库）时不需要刷新按钮。
        # 注意：不放进布局的控件仍会被绘制在 (0,0)，会压在返回箭头上，
        # 所以这里必须显式隐藏，而不是"只是不加进布局"。
        if show_refresh:
            bl.addWidget(Divider(self, vertical=True))
            bl.addWidget(self._refresh)
        else:
            self._refresh.hide()
        bl.addWidget(self._crumb, 1)

        self.tree = NodeTree(self)
        self.tree.setHeaderHidden(True)
        self.tree.setRootIsDecorated(False)
        # 缩进也设为 0：Qt 的分支/缩进区域会画一块自定义不了的高亮，
        # 所以连缩进都由委托按层级自己画，树形外观 100% 受控。
        self.tree.setIndentation(0)
        self.tree.setUniformRowHeights(True)
        # 关掉展开动画：几百项时动画又慢又会让"折叠"状态一时读不准
        self.tree.setAnimated(False)
        self.tree.setExpandsOnDoubleClick(False)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.setItemDelegate(TreeDelegate(self.tree))
        self.tree.setMouseTracking(True)
        self.tree.setFrameShape(QTreeWidget.Shape.NoFrame)
        self.tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # 关掉 Qt 自己的选中底色与分支指示器 —— 它们会在我自绘的箭头位置
        # 画出一块突兀的蓝色，且只能靠位图皮肤改。这里全部由委托自绘。
        self.tree.setStyleSheet(
            "QTreeView{background:transparent;outline:none;}"
            "QTreeView::item{background:transparent;border:0px;}"
            "QTreeView::item:selected{background:transparent;}"
            "QTreeView::item:hover{background:transparent;}"
            "QTreeView::branch{background:transparent;image:none;border-image:none;}"
            "QTreeView::branch:selected{background:transparent;}"
        )
        self.tree.itemSelectionChanged.connect(self._on_selection)
        self.tree.itemDoubleClicked.connect(self._on_double_click)
        self.tree.viewport().installEventFilter(self)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(bar)
        lay.addWidget(Divider(self))
        lay.addWidget(self.tree, 1)
        # 允许被拖窄
        self.setMinimumWidth(200)
        self._update_nav_buttons()

    # ---- 构建 ----
    def load(self, root: Node) -> None:
        self.tree.clear()
        item = self._make_item(root)
        self.tree.addTopLevelItem(item)
        # 默认全部展开：目录层级不深，展开后一眼能看到有什么
        self.tree.expandAll()
        self.set_location(root)

    def _make_item(self, node: Node) -> QTreeWidgetItem:
        item = QTreeWidgetItem([node.label])
        item.setData(0, Qt.ItemDataRole.UserRole, node)
        for child in node.children:
            item.addChild(self._make_item(child))
        return item

    # ---- 历史 ----
    def collapse_all(self) -> None:
        """把目录收回全折叠状态。

        Qt 在 setCurrentItem/scrollToItem 时会自动展开路径以显示选中项，
        所以"默认折叠"必须在选中之后显式收回一次，否则会被悄悄撑开。
        """
        self.tree.collapseAll()

    def set_location(self, node: Node) -> None:
        """把某个节点设为"当前位置"：更新路径、记入历史、在树里选中并滚到可见。"""
        if self._index >= 0 and self._history[self._index] is node:
            return
        del self._history[self._index + 1:]
        self._history.append(node)
        self._index = len(self._history) - 1
        self._sync_crumb(node)
        self._select_in_tree(node)
        self._update_nav_buttons()

    def select_node(self, node: Node, record: bool = False,
                    reveal: bool = True) -> None:
        self._select_in_tree(node, reveal=reveal)
        if record:
            self.set_location(node)
        else:
            self._sync_crumb(node)

    def _sync_crumb(self, node: Node) -> None:
        self._crumb.set_segments(node.path_labels())

    def _select_in_tree(self, node: Node, reveal: bool = True) -> None:
        item = self._find_item(node)
        if item is None:
            return
        self.tree.blockSignals(True)
        self.tree.setCurrentItem(item)
        self.tree.blockSignals(False)
        if not reveal:
            # 不展开祖先：默认折叠时不应因为"选中"就把路径撑开
            return
        parent = item.parent()
        while parent is not None:
            parent.setExpanded(True)
            parent = parent.parent()
        self.tree.scrollToItem(item)

    def _find_item(self, target: Node, item: Optional[QTreeWidgetItem] = None) -> Optional[QTreeWidgetItem]:
        if item is None:
            for i in range(self.tree.topLevelItemCount()):
                found = self._find_item(target, self.tree.topLevelItem(i))
                if found is not None:
                    return found
            return None
        if item.data(0, Qt.ItemDataRole.UserRole) is target:
            return item
        for i in range(item.childCount()):
            found = self._find_item(target, item.child(i))
            if found is not None:
                return found
        return None

    def go_back(self) -> None:
        if self._index > 0:
            self._index -= 1
            node = self._history[self._index]
            self._sync_crumb(node)
            self._select_in_tree(node)
            self.node_selected.emit(node)
            self._update_nav_buttons()

    def go_forward(self) -> None:
        if self._index < len(self._history) - 1:
            self._index += 1
            node = self._history[self._index]
            self._sync_crumb(node)
            self._select_in_tree(node)
            self.node_selected.emit(node)
            self._update_nav_buttons()

    def _update_nav_buttons(self) -> None:
        self._back.setEnabled(self._index > 0)
        self._forward.setEnabled(self._index < len(self._history) - 1)
        self._back.update()
        self._forward.update()

    # ---- 交互 ----
    def _on_selection(self) -> None:
        item = self.tree.currentItem()
        if item is None:
            return
        node = item.data(0, Qt.ItemDataRole.UserRole)
        if node is not None:
            self._sync_crumb(node)
            self.node_selected.emit(node)

    def _on_double_click(self, item: QTreeWidgetItem, column: int) -> None:
        node = item.data(0, Qt.ItemDataRole.UserRole)
        if node is None:
            return
        item.setExpanded(not item.isExpanded())
        self.node_activated.emit(node)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        """点箭头区域 = 展开/收起；点其它地方交给正常选中逻辑。"""
        from PySide6.QtCore import QEvent
        if obj is self.tree.viewport() and event.type() == QEvent.Type.MouseButtonPress:
            pos = event.position().toPoint()
            item = self.tree.itemAt(pos)
            if item is not None:
                node = item.data(0, Qt.ItemDataRole.UserRole)
                rect = self.tree.visualItemRect(item)
                depth = 0
                parent = item.parent()
                while parent is not None:
                    depth += 1
                    parent = parent.parent()
                cx = rect.left() + 3 + depth * INDENT_W
                if (node is not None and not node.is_leaf
                        and cx <= pos.x() < cx + CHEVRON_W):
                    item.setExpanded(not item.isExpanded())
                    return True
        return super().eventFilter(obj, event)


# ----------------------------------------------------------------- 题面

def extract_code_skeleton(description: str) -> str:
    """从题面里抠出代码骨架。

    完型填空类题目的正文就是残缺代码，但正文往往还有说明文字。
    这里用启发式：从第一行"像代码"的行开始，到最后一行含 } 或 ; 的行结束。
    站点提交页不预填任何初始代码，所以这个功能是 App 补的价值。
    """
    if not description:
        return ""
    lines = description.splitlines()
    code_start = re.compile(
        r"^\s*(#\s*include|#\s*define|class\s|struct\s|template\s|using\s+namespace|"
        r"typedef\s|void\s|int\s+main|int\s+\w+\s*\(|char\s|double\s|float\s|"
        r"public:|private:|protected:)"
    )
    start = None
    for i, ln in enumerate(lines):
        if code_start.search(ln) or ln.rstrip().endswith("{"):
            start = i
            break
    if start is None:
        return ""
    end = None
    for i in range(len(lines) - 1, start - 1, -1):
        s = lines[i].strip()
        if s.endswith("}") or s.endswith(";"):
            end = i
            break
    if end is None or end <= start:
        return ""
    return "\n".join(lines[start:end + 1])


class StatementStrip(Card):
    """可折叠的题面。上栏是编辑器，但做题必须看得到题面，所以放在编辑器上方。"""

    collapse_changed = Signal(bool)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        t = theme()
        self._collapsed = False
        self._title = ""
        self._badges: List[str] = []
        self._chevron_rect = QRect()
        self.setCursor(Qt.CursorShape.ArrowCursor)

        self._body = QPlainTextEdit(self)
        self._body.setReadOnly(True)
        self._body.setFrameShape(QPlainTextEdit.Shape.NoFrame)
        self._body.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self._body.setFont(mono_font(t.mono_font_size - 1))
        self._body.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.apply_theme()
        # 高度由外面的分栏控制，所以这里不设上限（只保证折叠态的最小值）
        self.setMinimumHeight(STATEMENT_MIN_H)
        self.setMaximumHeight(16777215)

    def apply_theme(self) -> None:
        pal = theme().palette
        self._body.setStyleSheet(
            f"QPlainTextEdit{{background:transparent;color:{pal.text};border:none;}}"
        )

    def set_statement(self, title: str, description: str, badges: List[str]) -> None:
        self._title = title
        self._badges = badges
        self._body.setPlainText(description or "（这道题在站点上没有填写描述）")
        self.update()

    def set_collapsed(self, collapsed: bool) -> None:
        self._collapsed = collapsed
        self._body.setVisible(not collapsed)
        if collapsed:
            self.setMinimumHeight(STATEMENT_COLLAPSED_H)
            self.setMaximumHeight(STATEMENT_COLLAPSED_H)
        else:
            self.setMinimumHeight(STATEMENT_MIN_H)
            # 不再自设上限：高度交给外面的分栏，用户能自己拖
            self.setMaximumHeight(16777215)
        self.updateGeometry()
        self.collapse_changed.emit(collapsed)

    def is_collapsed(self) -> bool:
        return self._collapsed

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        t = theme()
        if not self._collapsed:
            self._body.setGeometry(
                t.metrics.space_lg, 34,
                self.width() - t.metrics.space_lg * 2,
                self.height() - 34 - t.metrics.space_sm)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._chevron_rect.contains(event.position().toPoint()):
            self.set_collapsed(not self._collapsed)

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        t = theme()
        pal = t.palette
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        self._chevron_rect = QRect(t.metrics.space_md, 9, 16, 16)
        icons.render(p, "chevron-right" if self._collapsed else "chevron-down",
                     self._chevron_rect, pal.text_dim, 2.1)

        p.setFont(ui_font(weight=QFont.Weight.Medium))
        p.setPen(QColor(pal.text))
        x = t.metrics.space_md + 22
        p.drawText(QRect(x, 4, self.width() - x - t.metrics.space_lg, 26),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, "题目描述")

        # 窄的时候标题与徽章全部让位，只留箭头和"题目描述"，
        # 否则它们会互相压字（徽章在工具栏已经有一份了）
        narrow = self.width() < 480
        badge_specs = []
        total_badge_w = 0
        if not narrow:
            for text in reversed(self._badges):
                f = ui_font(t.small_font_size, QFont.Weight.Medium)
                w = QFontMetrics(f).horizontalAdvance(text) + t.metrics.space_sm * 2 + 2
                badge_specs.append((text, w, f))
                total_badge_w += w + t.metrics.space_xs

        if self._title and not narrow:
            p.setFont(ui_font(t.small_font_size))
            p.setPen(QColor(pal.text_muted))
            avail = max(0, self.width() - x - t.metrics.space_lg - total_badge_w
                        - t.metrics.space_md)
            fm_small = QFontMetrics(ui_font(t.small_font_size))
            if avail > 60:
                p.drawText(QRect(x, 4, avail, 26),
                           Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                           fm_small.elidedText(self._title,
                                               Qt.TextElideMode.ElideLeft, avail))

        bx = self.width() - t.metrics.space_lg
        for text, w, f in badge_specs:
            bx -= w + t.metrics.space_xs
            if bx < x + 110:
                break
            p.setBrush(QColor(pal.surface_alt))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(QRectF(bx, 8, w, 18), 9, 9)
            p.setFont(f)
            p.setPen(QColor(pal.text_dim))
            p.drawText(QRect(int(bx), 4, int(w), 26), Qt.AlignmentFlag.AlignCenter, text)
        p.end()


# ----------------------------------------------------------------- 提交线程

class SubmitWorker(QThread):
    """后台提交，避免界面卡住（站点评测是同步的，实测约 3.7 秒）。"""

    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, session, node: Node, source: str) -> None:
        super().__init__()
        self._session = session
        self._node = node
        self._source = source

    def run(self) -> None:
        try:
            client = self._session.client
            # 先记基线：这道题当前最大的 assignment_id
            try:
                existing = P.parse_submissions(
                    client.get(S.LIST_BY_TASK.format(task_id=self._node.task_id)).text)
                baseline = max(
                    (s.assignment_id for s in existing if s.task_id == self._node.task_id),
                    default=0)
            except Exception:
                baseline = 0

            outcome = S.submit_and_collect(
                client,
                task_id=self._node.task_id,
                task_name=self._node.label,
                sourcecode=self._source,
                task_group_task_id=self._node.task_group_task_id or None,
                task_group_id=self._node.task_group_id or None,
                known_latest_assignment_id=baseline,
                result_attempts=3,
                result_interval=3.0,
            )
            # 落库：这样底部"文件列表"能立刻多出一条历史提交，
            # 不必再点一次"刷新历史"
            if outcome.ok and outcome.submission is not None:
                try:
                    self._session.store.save_submissions([outcome.submission])
                    self._session.store.save_submission_detail(
                        outcome.submission.assignment_id, outcome.score_detail)
                except Exception:                 # noqa: BLE001
                    pass
            self.succeeded.emit(outcome)
        except Exception as exc:                      # noqa: BLE001
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class RefreshWorker(QThread):
    """后台刷新班级数据（4 个左右的请求），完成后通知界面重建树。"""

    done = Signal(dict)
    failed = Signal(str)

    def __init__(self, workspace) -> None:
        super().__init__()
        self._ws = workspace

    def run(self) -> None:
        from ...core import refresh as R
        try:
            counts = R.refresh_class_data(self._ws.client, self._ws.store)
            self._ws.accounts.touch_crawl(self._ws.username, self._ws.store)
            self.done.emit(counts)
        except Exception as exc:                      # noqa: BLE001
            self.failed.emit(f"{type(exc).__name__}: {exc}")


# ----------------------------------------------------------------- 确认对话框

class ConfirmSubmitDialog(QDialog):
    """提交前确认，带"记住我的选择"。"""

    def __init__(self, task_name: str, remaining: Optional[int],
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        t = theme()
        pal = t.palette
        self.setWindowTitle("确认提交")
        self.setModal(True)
        self.setMinimumWidth(380)

        title = QLabel(f"确认提交「{task_name}」？", self)
        title.setFont(ui_font(14, QFont.Weight.DemiBold))
        title.setStyleSheet(f"color:{pal.text};")

        note = "站点的评测是同步进行的，提交后会等待约 3～4 秒才返回结果。"
        if remaining is not None:
            note += f"这道题还可以提交 {remaining} 次。"
        detail = QLabel(note, self)
        detail.setWordWrap(True)
        detail.setFont(ui_font())
        detail.setStyleSheet(f"color:{pal.text_dim};")

        self.remember = QCheckBox("记住我的选择，以后不再询问", self)
        self.remember.setFont(ui_font())
        self.remember.setStyleSheet(
            f"QCheckBox{{color:{pal.text_dim};spacing:8px;}}"
            f"QCheckBox::indicator{{width:16px;height:16px;border-radius:4px;"
            f"border:1px solid {pal.border_strong};background:{pal.surface};}}"
            f"QCheckBox::indicator:checked{{background:{pal.accent};"
            f"border:1px solid {pal.accent};}}"
        )

        cancel = VectorButton("取消", None, VectorButton.GHOST, self)
        ok = VectorButton("确认提交", "submit", VectorButton.PRIMARY, self, min_width=100)
        cancel.clicked.connect(self.reject)
        ok.clicked.connect(self.accept)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(ok)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(t.metrics.space_xl, t.metrics.space_xl,
                               t.metrics.space_xl, t.metrics.space_lg)
        lay.setSpacing(t.metrics.space_md)
        lay.addWidget(title)
        lay.addWidget(detail)
        lay.addWidget(self.remember)
        lay.addSpacing(t.metrics.space_sm)
        lay.addLayout(buttons)
        self.setStyleSheet(f"QDialog{{background:{pal.surface};}}")


# ----------------------------------------------------------------- 概览面板

class OverviewPanel(QWidget):
    """选中"文件夹"类节点（班级/作业）时右区显示的内容。"""

    child_activated = Signal(int)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        t = theme()
        self._inner = QWidget()
        self._lay = QVBoxLayout(self._inner)
        self._lay.setContentsMargins(t.metrics.space_xl, t.metrics.space_xl,
                                     t.metrics.space_xl, t.metrics.space_xl)
        self._lay.setSpacing(t.metrics.space_xs)
        self._lay.addStretch(1)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(self._inner)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(scroll)

    def _clear(self) -> None:
        while self._lay.count() > 1:
            item = self._lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def show_node(self, node: Node, store) -> None:
        t = theme()
        pal = t.palette
        self._clear()

        title = QLabel(node.label, self._inner)
        title.setFont(ui_font(20, QFont.Weight.DemiBold))
        title.setStyleSheet(f"color:{pal.text};")
        self._lay.insertWidget(0, title)

        sub = QLabel({"course": "班级", "group": "作业", "section": "全部作业",
                      "root": "我的班级"}.get(node.kind, ""), self._inner)
        sub.setFont(ui_font())
        sub.setStyleSheet(f"color:{pal.text_muted};")
        self._lay.insertWidget(1, sub)

        # 基本信息
        rows: List[tuple] = []
        if node.kind == "course":
            rows = [("班级名称", node.meta or "—"),
                    ("当前分数", node.badge.replace(" 分", "") or "—")]
        elif node.kind == "group":
            rows = [("所属班级", (node.extra.get("_parents") or ["", ""])[-1]),
                    ("总分比例", node.badge.replace("权重 ", "") or "—"),
                    ("创建时间", node.meta or "—"),
                    ("题目数量", f"{len(node.children)} 道")]
        elif node.kind == "task":
            task = store.get_task(node.task_id) or {}
            rows = [("题号", str(node.task_id)),
                    ("语言要求", task.get("language", "—")),
                    ("编译类型", task.get("compile_type", "—")),
                    ("出题老师", task.get("teacher", "—")),
                    ("允许提交次数", str(node.extra.get("max_submissions") or "—")),
                    ("分值", node.badge.replace(" 分", "") or "—")]
        if rows:
            card = Card(self._inner)
            cl = QVBoxLayout(card)
            cl.setContentsMargins(t.metrics.space_lg, t.metrics.space_md,
                                  t.metrics.space_lg, t.metrics.space_md)
            cl.setSpacing(0)
            for label, value in rows:
                cl.addWidget(InfoRow(label, str(value), card))
            self._lay.insertWidget(2, card)

        # 右区只展示这一层的基本信息，**不再列"包含"明细**：
        # 目录栏本身就能选，两处入口重复且容易和目录状态不同步


# ----------------------------------------------------------------- 右区代码区

COMPILE_SHORT = {
    "编译整个文件夹内容": "整目录编译",
    "编译整个文件夹内容（老师提供teacher_main作为入口函数）": "teacher_main 入口",
    "完型填空": "完型填空",
}


class CodeArea(QWidget):
    """右区：上栏题面 + 编辑器（含提交按钮），下栏提交结果。"""

    submit_confirmed = Signal(str)      # 带源码提交

    def __init__(self, session, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        t = theme()
        pal = t.palette
        self._session = session
        self._node: Optional[Node] = None
        self._always_submit = False
        self._statement_saved_h = STATEMENT_DEFAULT_H   # 展开时恢复用的高度
        self._pending_statement_h: Optional[int] = None  # 尚未落地的高度
        # 文件模型：当前在编辑哪个本地文件 / 在看哪次历史提交
        self._active_draft_id: Optional[int] = None
        self._active_submission_id: Optional[int] = None
        self._readonly_mode = False
        self._skeleton = ""
        self._allowed_total: Optional[int] = None   # 该题允许的提交总次数

        # --- 工具栏 ---
        self._title = QLabel("", self)
        self._title.setFont(ui_font(14, QFont.Weight.DemiBold))
        self._title.setStyleSheet(f"color:{pal.text};")

        self._badges: List[Badge] = [Badge("", "neutral", self) for _ in range(3)]
        for b in self._badges:
            b.hide()

        self._import_btn = VectorButton("导入题面代码", "code", VectorButton.SUBTLE, self,
                                        tooltip="把题目描述里的残缺代码拷进编辑区")
        self._reset_btn = VectorButton("清空", "trash", VectorButton.GHOST, self)
        self._submit_btn = VectorButton("提交", "submit", VectorButton.PRIMARY, self,
                                        min_width=88)
        self._import_btn.clicked.connect(self._import_skeleton)
        self._reset_btn.clicked.connect(lambda: self._editor.set_text(""))
        self._submit_btn.clicked.connect(self._on_submit_clicked)
        # 只读模式（打开了历史提交）时用它回到可写：把当前代码复制成一个新文件
        self._newfile_btn = VectorButton("重新编辑至新文件", "file-code",
                                         VectorButton.PRIMARY, self, min_width=150)
        self._newfile_btn.clicked.connect(self._new_from_history)
        self._newfile_btn.hide()

        bar = QWidget(self)
        bar.setFixedHeight(t.metrics.toolbar_h)
        bl = QHBoxLayout(bar)
        # 左右都用 space_lg，和下面题面/编辑器/结果栏对齐（上中下等宽）
        bl.setContentsMargins(t.metrics.space_lg, 0, t.metrics.space_lg, 0)
        bl.setSpacing(t.metrics.space_sm)
        bl.addWidget(self._title)
        for b in self._badges:
            bl.addWidget(b)
        bl.addStretch(1)
        bl.addWidget(self._import_btn)
        bl.addWidget(self._reset_btn)
        bl.addWidget(self._newfile_btn)
        bl.addWidget(self._submit_btn)

        # 编辑内容自动进入当前文件：打字停顿 1.2 秒存一次，切换文件/题目时也存
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(1200)
        self._save_timer.timeout.connect(self._save_current)

        # --- 题面 + 编辑器 ---
        self._statement = StatementStrip(self)
        self._statement.collapse_changed.connect(self._on_statement_collapsed)
        self._editor = CodeEditor(self)

        # 题面和编辑器放进一个竖向分栏：拖中间的分隔线就能改题面高度
        editor_wrap = QWidget(self)
        ewl = QVBoxLayout(editor_wrap)
        ewl.setContentsMargins(0, 0, 0, 0)
        ewl.addWidget(self._editor)

        self._editor_split = GripSplitter(Qt.Orientation.Vertical, self)
        self._editor_split.setChildrenCollapsible(False)
        self._editor_split.setHandleWidth(9)
        self._editor_split.addWidget(self._statement)
        self._editor_split.addWidget(editor_wrap)
        self._editor_split.setStretchFactor(0, 0)
        self._editor_split.setStretchFactor(1, 1)
        self._editor_split.setSizes([STATEMENT_DEFAULT_H, 380])

        top = QWidget(self)
        tl = QVBoxLayout(top)
        tl.setContentsMargins(t.metrics.space_lg, t.metrics.space_sm,
                              t.metrics.space_lg, 0)
        tl.setSpacing(0)
        tl.addWidget(self._editor_split)

        # --- 提交结果 + 历史提交 ---
        self._result = ResultPanel(self)
        self._result.setMinimumHeight(112)
        # 结果栏高度会随内容增长（扣分原因可能很长），外面套一层滚动区，
        # 内容超出时就出现竖向滚动条，而不是把文字压在一起
        result_scroll = QScrollArea(self)
        result_scroll.setWidgetResizable(True)
        result_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        result_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        result_scroll.setWidget(self._result)
        # 比结果栏自身的最小高度略大一点：否则短内容差几像素也会弹出滚动条
        result_scroll.setMinimumHeight(128)
        # 只读只是结果栏下面的一行小字，不占用结果栏本身
        self._readonly_hint = ReadonlyHint(self)
        self._files = FileListPanel(session, self)
        # 下栏外面包一层，让它和题面/编辑器有完全相同的左右边距
        bottom = QWidget(self)
        bw = QVBoxLayout(bottom)
        bw.setContentsMargins(t.metrics.space_lg, 0, t.metrics.space_lg,
                              t.metrics.space_lg)
        bw.setSpacing(t.metrics.space_sm)
        bw.addWidget(result_scroll)
        bw.addWidget(self._readonly_hint)
        bw.addWidget(self._files, 1)

        vsplit = GripSplitter(Qt.Orientation.Vertical, self)
        vsplit.setChildrenCollapsible(False)
        vsplit.setHandleWidth(9)
        vsplit.addWidget(top)
        vsplit.addWidget(bottom)
        vsplit.setStretchFactor(0, 3)
        vsplit.setStretchFactor(1, 2)
        vsplit.setSizes([470, 360])

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(bar)
        lay.addWidget(Divider(self))
        lay.addWidget(vsplit, 1)

        # 允许被拖得很窄：最小值是"还能用"的下限，不是装饰
        self.setMinimumWidth(320)
        self._editor.textChanged.connect(self._save_timer.start)
        self._files.draft_opened.connect(self._on_draft_opened)
        self._files.submission_opened.connect(self._on_submission_opened)
        self._files.new_file_requested.connect(lambda: self._create_draft())
        # 打开题目后后台校准完成时，已提交次数可能变了，"剩余次数"要跟着刷新
        self._files.history_updated.connect(lambda _tid: self._apply_remaining_badge())
        self.set_task(None)
        self._adapt_to_width()

    def _auto_statement_height(self, description: str) -> int:
        """按题面内容给一个合适的初始高度，并**设上限**。

        上限取两者较小值：绝对 360px，以及编辑区高度的 38%。
        只看内容不看可用空间的话，正文很长的完型填空题（75 行、1700 多字）
        会把编辑器挤到只剩一条缝。

        注意不能只看换行数：Word 导出的题面常常是一整行超长文本，
        换行数为 1 但显示出来要折好几行，这里按字符数补一个估算。
        """
        text = description or ""
        raw_lines = len(text.splitlines())
        wrapped = len(text) // 58 + 1          # 约 58 字折一行
        lines = max(raw_lines, wrapped)
        want = 46 + lines * 19
        avail = self._editor_split.height() or 600
        cap = int(max(STATEMENT_MIN_H, min(360, avail * 0.38)))
        return int(min(max(STATEMENT_MIN_H, want), cap))

    def _apply_statement_height(self, height: int) -> None:
        """记住题面高度并尽量立刻应用。

        控件可能还没布局（例如藏在 QStackedWidget 里刚被切到前台），
        此时分栏的可用高度还是初始值，直接 setSizes 会被压扁 ——
        所以记成待应用值，等 resizeEvent 里真正有空间了再落地。
        """
        self._statement_saved_h = height
        self._pending_statement_h = height
        self._flush_statement_height()

    def _flush_statement_height(self) -> None:
        self._retry_flush(0)

    def _retry_flush(self, attempt: int) -> None:
        """把待应用的题面高度落地。

        控件刚被 QStackedWidget 切到前台时，布局还没算完，
        这时读到的分栏高度还是初始值，直接 setSizes 会被压扁成最小值。
        所以下一帧重试几次，直到真的拿到可用高度。
        """
        height = self._pending_statement_h
        if height is None or self._statement.is_collapsed():
            return
        sizes = self._editor_split.sizes()
        total = sum(sizes)
        if total < 200:
            if attempt < 8:
                QTimer.singleShot(16, lambda: self._retry_flush(attempt + 1))
            return
        self._pending_statement_h = None
        self._editor_split.setSizes([height, max(120, total - height)])

    def _on_statement_collapsed(self, collapsed: bool) -> None:
        """折叠/展开题面时同步分栏比例，展开后回到原来的高度。"""
        sizes = self._editor_split.sizes()
        total = sum(sizes) or (STATEMENT_DEFAULT_H + 380)
        if collapsed:
            self._statement_saved_h = max(sizes[0], STATEMENT_DEFAULT_H)
            self._editor_split.setSizes(
                [STATEMENT_COLLAPSED_H, max(120, total - STATEMENT_COLLAPSED_H)])
        else:
            h = max(STATEMENT_MIN_H, self._statement_saved_h)
            self._editor_split.setSizes([h, max(120, total - h)])

    def apply_theme(self) -> None:
        """主题切换后重新取色。

        工具栏标题是 QLabel，颜色在构造时写死，主题一换就会留着旧主题的
        深色字，在深色背景上几乎看不见。
        """
        pal = theme().palette
        self._title.setStyleSheet(f"color:{pal.text};")

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._adapt_to_width()
        self._flush_statement_height()

    def _adapt_to_width(self) -> None:
        """窄的时候按优先级收起次要元素，保证主操作永远可见。"""
        w = self.width()
        for i, badge in enumerate(self._badges):
            badge.setVisible(w >= 600 + i * 88 and bool(badge.text()))
        compact = w < 540
        self._import_btn.set_compact(compact)
        self._reset_btn.set_compact(compact)
        self._newfile_btn.set_compact(w < 620)
        self._title.setVisible(w >= 400)

    # ---- 状态 ----
    def set_task(self, node: Optional[Node], store=None) -> None:
        self._save_current()                 # 切题前先把手上内容存进当前文件
        self._save_timer.stop()              # 别让它在新题目的文件上再触发一次
        self._node = node
        self._skeleton = ""
        self._active_submission_id = None
        if node is None:
            self._title.setText("")
            for b in self._badges:
                b.hide()
            self._editor.set_text("")
            self._statement.set_statement("", "", [])
            self._result.reset_idle("")
            self._active_draft_id = None
            self._set_readonly(True)
            self._files.set_task(None, store)
            return

        task = (store.get_task(node.task_id) if store else None) or {}
        description = task.get("description", "") or ""
        compile_type = task.get("compile_type", "") or node.extra.get("compile_type", "")

        # 标题带上题号，和目录里的标签形式一致，方便对号
        num = f"#{node.task_id}　" if node.task_id else ""
        self._title.setText(f"{num}{node.label}")
        badges = [
            (node.meta or task.get("language", "") or "—", "neutral"),
            (COMPILE_SHORT.get(compile_type, compile_type or "—"), "accent"),
        ]
        remaining = node.extra.get("max_submissions")
        if remaining is None and store is not None and node.task_id:
            # 题库里没有这个值，回作业表查（站点只在作业内题目上给）
            remaining = store.max_submissions_for(node.task_id)
        if remaining is not None:
            # 站点给的是"允许提交总次数"（如 100），减掉这道题已提交的次数
            # 才是"剩余"；打开题目后台校准完成后会再刷新一次
            self._allowed_total = int(remaining)
            self._apply_remaining_badge(store)
        else:
            # 站点没给这道题的允许次数（也不在任何作业里）：清掉徽章，
            # 否则会留着上一道题的"剩 N 次"
            self._allowed_total = None
            self._badges[2].set_text("")
            self._badges[2].hide()
        for badge, (text, tone) in zip(self._badges, badges):
            badge.set_text(text, tone)
            badge.show()

        self._statement.set_statement(node.label, description,
                                      [task.get("language", ""),
                                       COMPILE_SHORT.get(compile_type, compile_type)])
        self._apply_statement_height(self._auto_statement_height(description))
        self._skeleton = extract_code_skeleton(description)

        # 进入工作区：续写最近的未提交文件；一个都没有就新建（新进入）
        self._files.set_task(node, store)
        drafts = store.get_drafts(node.task_id) if store else []
        if drafts:
            self._load_draft(int(drafts[0]["draft_id"]))
        else:
            self._create_draft()

    # ---- 文件模型 ----

    def _apply_remaining_badge(self, store=None) -> None:
        """把"剩余提交次数"算出来填进第 3 个徽章。"""
        if not self._allowed_total:
            return
        store = store or self._session.store
        try:
            used = store.count_submissions(self._node.task_id) if self._node else 0
        except Exception:                     # noqa: BLE001
            used = 0
        left = max(0, self._allowed_total - used)
        badge = self._badges[2]
        badge.set_text(f"剩 {left} 次", "danger" if left <= 5 else "neutral")
        badge.show()
        self._adapt_to_width()

    def _show_draft_result(self) -> None:
        """本地文件是"未提交"状态：主位显示未提交，历史最高分退到小字。"""
        store = self._session.store
        task_id = self._node.task_id if self._node else 0
        rows = store.get_submissions(task_id, limit=100) if task_id else []
        best = max((r.get("score") or 0 for r in rows), default=None)
        self._result.set_unsubmitted(best)

    def _load_draft(self, draft_id: int) -> None:
        """打开一个本地文件：可写，右上角是清空/提交。

        顺序很关键：先停掉待保存的计时器，再切换"当前文件"。
        否则计时器可能在"已切到新文件、编辑器里还是旧内容"的瞬间触发，
        把上一个题目的代码写进新题目的文件里 —— 这就是串文件的来源。
        """
        self._save_timer.stop()
        draft = self._session.store.get_draft(draft_id) or {}
        self._active_draft_id = draft_id
        self._active_submission_id = None
        self._set_readonly(False)
        self._editor.set_text(draft.get("code", "") or "")
        self._save_timer.stop()
        self._files.set_active("draft", draft_id)
        # 从历史提交切回本地文件时，结果栏要跟着变回"未提交"
        self._show_draft_result()

    def _create_draft(self, code: str = "", from_assignment_id: int = 0) -> None:
        """新进入：新建一个本地文件（以时间命名），排在历史文件最上面。

        文件始终挂在**当前题目**下（task_id 取当前节点），所以换一道题
        就是另一个"新文件"，不会串到别的题目上。
        """
        node = self._node
        if node is None:
            return
        self._save_timer.stop()
        draft_id = self._session.store.create_draft(
            node.task_id, code=code,
            task_group_task_id=node.task_group_task_id or 0,
            task_group_id=node.task_group_id or 0,
            from_assignment_id=from_assignment_id)
        self._load_draft(draft_id)
        if not code:
            self._editor.set_text("")
        self._save_timer.stop()
        self._files.status.emit("已新建本地文件（未提交），编好内容后点「提交」。")

    def _save_current(self) -> None:
        """把编辑器内容存进当前本地文件。"""
        if self._readonly_mode or not self._active_draft_id:
            return
        try:
            self._session.store.update_draft_code(self._active_draft_id,
                                                  self._editor.text())
            self._files.set_active("draft", self._active_draft_id)
        except Exception:                     # noqa: BLE001 —— 存档失败不该打断编辑
            pass

    def _set_readonly(self, readonly: bool) -> None:
        """只读模式：打开的是历史提交。

        隐藏清空/提交，换成「重新编辑至新文件」——点它才把这份历史代码
        变成一个可写的新文件。
        """
        self._readonly_mode = readonly
        self._editor.set_readonly_mode(readonly)
        self._import_btn.setVisible((not readonly) and bool(self._skeleton))
        self._reset_btn.setVisible(not readonly)
        self._submit_btn.setVisible(not readonly)
        self._newfile_btn.setVisible(readonly)
        self._readonly_hint.setVisible(readonly)
        if readonly:
            self._readonly_hint.set_hint("只读模式　要修改就点右上角「重新编辑至新文件」")
        self._adapt_to_width()

    def _on_draft_opened(self, draft_id: int) -> None:
        self._save_current()
        self._load_draft(draft_id)

    def _on_submission_opened(self, assignment_id: int, code: str) -> None:
        """打开历史提交：只读，并且**结果栏显示这次提交自己的分数与扣分**。"""
        self._save_current()
        self._active_draft_id = None
        self._active_submission_id = assignment_id
        self._set_readonly(True)
        self._editor.set_text(code)
        self._files.set_active("submission", assignment_id)
        sub = self._session.store.get_submission(assignment_id) or {}
        detail = sub.get("detail_text", "") or ""
        self._result.set_result(
            sub.get("score"), S.parse_deduction(detail), S.parse_reason(detail),
            message=f"历史提交 #{assignment_id}"
                    f"　{(sub.get('submitted_at') or '').replace('.0', '')}")

    def _new_from_history(self) -> None:
        """从只读的历史代码切到可写：新建文件并把这版代码带过去。"""
        code = self._editor.text()
        aid = self._active_submission_id or 0
        self._create_draft(code=code, from_assignment_id=aid)
        self._files.status.emit(
            "已新建本地文件并复制了这份历史代码，现在可以编辑与提交。")

    def _import_skeleton(self) -> None:
        if self._node is None:
            return
        # 骨架放在题目描述里，从描述里抠
        description = self._statement._body.toPlainText()      # noqa: SLF001
        code = extract_code_skeleton(description)
        if code:
            self._editor.set_text(code)

    # ---- 提交 ----
    def _on_submit_clicked(self) -> None:
        if self._node is None:
            return
        if not self._editor.text().strip():
            self._result.set_error("代码是空的，先写点东西再提交。")
            return
        if not self._session.logged_in:
            self._result.set_error(
                "当前未登录。请到「个人中心」登录后再提交（本地题库不需登录就能看）。")
            return
        if not self._always_submit:
            dlg = ConfirmSubmitDialog(self._node.label,
                                      self._node.extra.get("max_submissions"), self)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            if dlg.remember.isChecked():
                self._always_submit = True
        self.submit_confirmed.emit(self._editor.text())

    def set_submitting(self) -> None:
        self._result.set_submitting()

    def show_result(self, outcome) -> None:
        if not outcome.ok:
            self._result.set_error(f"提交未成功：{outcome.message}")
            return
        self._result.set_result(outcome.score, outcome.deduction, outcome.reason,
                                message=outcome.summary())

    def show_error(self, message: str) -> None:
        self._result.set_error(message)


# ----------------------------------------------------------------- 页面

class MyClassPage(QWidget):
    """「我的班级」：左区目录浏览器 + 右区（概览 / 代码区）。"""

    def __init__(self, workspace, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        t = theme()
        self._ws = workspace
        self._submit_worker: Optional[SubmitWorker] = None
        self._refresh_worker: Optional[RefreshWorker] = None
        self._root: Optional[Node] = None

        self._browser = BrowserPanel(self)
        self._overview = OverviewPanel(self)
        self._code = CodeArea(workspace, self)
        # 没选题目时右区什么都不显示（不要自作主张替用户选一道题）
        self._empty = QWidget(self)
        self._stack = QStackedWidget(self)
        self._stack.addWidget(self._empty)
        self._stack.addWidget(self._overview)
        self._stack.addWidget(self._code)

        split = GripSplitter(Qt.Orientation.Horizontal, self)
        split.setChildrenCollapsible(False)
        split.setHandleWidth(9)
        split.addWidget(self._browser)
        split.addWidget(self._stack)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([300, 1000])

        # 底部状态条：加载进度也在这里显示（和题目中心保持一致）
        self._status = QLabel("", self)
        self._status.setFont(ui_font(theme().small_font_size))
        self._status.setContentsMargins(theme().metrics.space_lg, 4,
                                        theme().metrics.space_lg, 4)
        self._status.setVisible(False)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(split, 1)
        lay.addWidget(self._status)

        self._browser.node_selected.connect(self._on_node_selected)
        self._browser.node_activated.connect(self._on_node_activated)
        self._browser.refresh_requested.connect(self.refresh_from_site)
        self._overview.child_activated.connect(self._on_child_activated)
        self._code.submit_confirmed.connect(self._submit)
        # 换账号后数据整个换了，重载目录树
        self._ws.changed.connect(self.reload)

        self.reload()

    # 账号切换后这两个必须跟着换，所以做成属性而不是构造时的快照
    @property
    def _store(self):
        return self._ws.store

    @property
    def _session(self):
        return self._ws

    def set_status(self, text: str) -> None:
        """底部状态条（加载进度）。"""
        self._status.setText(text)
        self._status.setStyleSheet(f"color:{theme().palette.text_dim};")
        self._status.setVisible(bool(text))

    # ---- 数据 ----
    def reload(self) -> None:
        self._root = build_class_tree(self._store)
        self._browser.load(self._root)
        # 不预选任何题目：右区保持空白，由用户点开目录自己选
        self._code.set_task(None, self._store)
        self._stack.setCurrentWidget(self._empty)

    def refresh_from_site(self) -> None:
        if self._refresh_worker is not None and self._refresh_worker.isRunning():
            return
        if not self._session.logged_in:
            self._code.show_error("未登录，无法刷新。请到「个人中心」登录。")
            return
        self._code.show_error("正在从站点刷新班级数据…")
        self._refresh_worker = RefreshWorker(self._ws)
        self._refresh_worker.done.connect(self._on_refreshed)
        self._refresh_worker.failed.connect(
            lambda msg: self._code.show_error(f"刷新失败：{msg}"))
        self._refresh_worker.start()

    def _on_refreshed(self, counts: dict) -> None:
        self.reload()
        self._code.show_error(
            f"刷新完成：班级 {counts['classes']} 个，作业 {counts['groups']} 次，"
            f"作业内题目 {counts['tasks']} 道。")

    # ---- 选择 ----
    def _on_node_selected(self, node: Node) -> None:
        if node.kind == "task":
            self._stack.setCurrentWidget(self._code)
            self._code.set_task(node, self._store)
        else:
            self._stack.setCurrentWidget(self._overview)
            self._overview.show_node(node, self._store)

    def _on_node_activated(self, node: Node) -> None:
        self._browser.set_location(node)

    def _on_child_activated(self, index: int) -> None:
        node = self._browser.tree.currentItem()
        if node is None:
            return
        current = node.data(0, Qt.ItemDataRole.UserRole)
        if current is not None and 0 <= index < len(current.children):
            child = current.children[index]
            self._browser.select_node(child, record=True)

    # ---- 提交 ----
    def _submit(self, source: str) -> None:
        if self._code._node is None:                       # noqa: SLF001
            return
        self._code.set_submitting()
        self._submit_worker = SubmitWorker(self._session, self._code._node, source)  # noqa: SLF001
        self._submit_worker.succeeded.connect(self._on_submitted)
        self._submit_worker.failed.connect(self._code.show_error)
        self._submit_worker.start()

    def _on_submitted(self, outcome) -> None:
        self._code.show_result(outcome)
        # 提交成功后刷新底部文件列表：新记录会作为一条"历史提交"出现，
        # 本地文件按需求保持"未提交"状态不变
        code = self._code
        code._files.set_active("draft", code._active_draft_id or 0)   # noqa: SLF001
