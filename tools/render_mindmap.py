#!/usr/bin/env python3
"""把 UI 规格树渲染成思维导图 SVG。

纯标准库，不依赖 graphviz/字体包。中文用系统字体渲染。
规格有改动时改下面的 TREE 再跑一次即可：

    .venv/bin/python tools/render_mindmap.py
"""

from __future__ import annotations

import html
from pathlib import Path
from typing import List, Tuple

# ----------------------------------------------------------------- 规格树
# (标签, 子节点列表)；子节点为空 = 叶子。第三项可选：'todo' 标记未定项。
TREE = [
    ("BetterMatuUI 界面规格 v1", [
        ("界面层级（两层）", [
            ("主界面", [
                ("左侧菜单栏", [
                    ("顶部 logo：BetterMatuUI", []),
                    ("展开态：图标 + 文字", []),
                    ("折叠态：一键切换 → 5 个位图图标，侧栏收窄", []),
                    ("我的班级", []),
                    ("题目中心", []),
                    ("数据中心", []),
                    ("系统帮助", []),
                    ("个人中心（始终吸附最底部）", []),
                ]),
                ("右侧详细界面（随菜单切换）", [
                    ("我的班级  ← 本轮开发", [
                        ("左区 · 目录浏览器", [
                            ("功能栏：前进 / 后退 / 当前位置详情", []),
                            ("竖向树状列表（macOS 访达风格）", []),
                            ("可展开、也可进入", []),
                            ("层级：我的班级 / 作业列表 / c语言 / 第一次上机 / 计算e^x", []),
                            ("每行右侧标注：时间、语言、编译类型、分值…", []),
                        ]),
                        ("右区 · 代码区（上下分栏）", [
                            ("上栏 · 文本编辑器（语法高亮）", [
                                ("右上角：提交按钮", []),
                                ("→ 确认弹窗「是否确认提交」", []),
                                ("→ 含「记住我的选择」", []),
                            ]),
                            ("下栏 · 提交结果（提交一次拉取一次）", [
                                ("得分", []),
                                ("扣分项", []),
                                ("扣分原因", []),
                            ]),
                        ]),
                    ]),
                    ("题目中心（待你说明）", []),
                    ("数据中心（待你说明）", []),
                    ("系统帮助（待你说明）", []),
                ]),
            ]),
            ("设置界面（独立层级）", [
                ("入口：个人中心 / 快捷键", []),
                ("内容待定（见问题四）", []),
            ]),
        ]),
        ("数据来源与刷新策略", [
            ("本地 SQLite：358 道题已全量离线", []),
            ("启动读本地 → 秒开，不发请求", []),
            ("刷新靠手动按钮，绝不轮询", []),
            ("提交后只拉取结果一次", []),
        ]),
        ("待确认（见问题一～四）", [
            ("① 「全位图开发」的确切程度", []),
            ("② 提交功能如何验证（不能盲写）", []),
            ("③ 窗口形态：有无边框", []),
            ("④ 设置界面放什么", []),
        ]),
    ]),
]

FONT = "'PingFang SC','Hiragino Sans GB','Microsoft YaHei',-apple-system,sans-serif"
MARGIN = 40
GAP_X = 56
ROW_H = 38
PAD_X = 16
NODE_H = 28
FONT_SIZE = 14


def text_width(s: str, size: int = FONT_SIZE) -> float:
    """粗略估算文本宽度：CJK 按 1 个字宽，ASCII 按 0.58 个字宽。"""
    return sum(size if ord(c) > 0x2E80 else size * 0.58 for c in s)


class Node:
    def __init__(self, label: str, children: List["Node"], depth: int = 0):
        self.label = label
        self.children = children
        self.depth = depth
        self.x = 0.0
        self.y = 0.0
        self.width = text_width(label) + PAD_X * 2
        self.parent: Node | None = None
        for c in children:
            c.parent = self


def build(raw, depth=0) -> Node:
    return Node(raw[0], [build(c, depth + 1) for c in raw[1]], depth)


def collect(node: Node, out: List[Node]) -> None:
    out.append(node)
    for c in node.children:
        collect(c, out)


def layout(root: Node) -> Tuple[List[Node], List[float], float]:
    nodes: List[Node] = []
    collect(root, nodes)

    depth_width = {}
    for n in nodes:
        depth_width[n.depth] = max(depth_width.get(n.depth, 0), n.width)

    x_at = {}
    cursor = MARGIN
    for d in sorted(depth_width):
        x_at[d] = cursor
        cursor += depth_width[d] + GAP_X

    # 叶子按顺序分配行，父节点取子节点行号均值
    row = [0]

    def place(node: Node) -> float:
        if not node.children:
            y = MARGIN + row[0] * ROW_H
            row[0] += 1
        else:
            ys = [place(c) for c in node.children]
            y = sum(ys) / len(ys)
        node.x = x_at[node.depth]
        node.y = y
        return y

    place(root)
    return nodes, [x_at[d] for d in sorted(x_at)], cursor


PALETTE = ["#1f2937", "#2563eb", "#0f766e", "#b45309", "#7c3aed"]


def render(root: Node) -> str:
    nodes, _, total_w = layout(root)
    total_h = MARGIN * 2 + max(1, max(n.y for n in nodes) + NODE_H) - MARGIN

    def color(node: Node) -> Tuple[str, str, str]:
        d = min(node.depth, len(PALETTE) - 1)
        if node.depth == 0:
            return "#111827", "#111827", "#ffffff"
        if node.depth == 1:
            return "#ffffff", PALETTE[d], PALETTE[d]
        return "#ffffff", "#d1d5db", "#1f2937"

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{total_w:.0f}" '
        f'height="{total_h:.0f}" viewBox="0 0 {total_w:.0f} {total_h:.0f}">',
        f'<rect width="100%" height="100%" fill="#f8fafc"/>',
        f'<style>text{{font-family:{FONT};font-size:{FONT_SIZE}px}}</style>',
    ]

    # 连线先画，压在节点下面
    for n in nodes:
        for c in n.children:
            x1, y1 = n.x + n.width, n.y + NODE_H / 2
            x2, y2 = c.x, c.y + NODE_H / 2
            mid = (x1 + x2) / 2
            parts.append(
                f'<path d="M{x1:.0f},{y1:.0f} C{mid:.0f},{y1:.0f} {mid:.0f},{y2:.0f} '
                f'{x2:.0f},{y2:.0f}" fill="none" stroke="#cbd5e1" stroke-width="1.5"/>'
            )

    for n in nodes:
        fill, stroke, text_color = color(n)
        weight = "600" if n.depth <= 1 else "400"
        parts.append(
            f'<rect x="{n.x:.0f}" y="{n.y:.0f}" width="{n.width:.0f}" height="{NODE_H}" '
            f'rx="7" fill="{fill}" stroke="{stroke}" stroke-width="1.2"/>'
        )
        parts.append(
            f'<text x="{n.x + PAD_X:.0f}" y="{n.y + NODE_H / 2 + 5:.0f}" '
            f'fill="{text_color}" font-weight="{weight}">{html.escape(n.label)}</text>'
        )

    parts.append("</svg>")
    return "\n".join(parts)


def main() -> int:
    root = build(TREE[0])
    out = Path(__file__).resolve().parents[1] / "docs" / "ui-mindmap.svg"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(root), encoding="utf-8")
    print(f"已生成: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
