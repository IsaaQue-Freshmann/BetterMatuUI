"""设计令牌：全矢量界面的颜色、圆角、间距、字体。

**所有视觉数值集中在这里**，做亮/暗主题和后续微调只改这一个文件。
界面里不允许出现散落的颜色字面量。

矢量原则：图标是内嵌 SVG 路径，形状/圆角/阴影全部用 QPainter 矢量绘制，
项目里不存在任何位图资源（png/jpg/ico 只会在打包时作为应用图标出现）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict


@dataclass(frozen=True)
class Palette:
    """一套配色。字段名是语义化的，界面代码只引用语义，不引用色值。"""

    name: str

    bg: str             # 窗口底色
    sidebar: str        # 侧栏底色
    surface: str        # 卡片/面板底色
    surface_alt: str    # 次级面板、输入框底色
    hover: str          # 悬停态
    active: str         # 按下/选中态
    border: str         # 分隔线、描边
    border_strong: str  # 需要更明显分隔时

    text: str           # 主文本
    text_dim: str       # 次要文本
    text_muted: str     # 更弱的提示文本
    text_on_accent: str # 强调色上的文字

    accent: str         # 主强调色
    accent_hover: str
    accent_soft: str    # 强调色淡背景（选中行）
    success: str
    success_soft: str
    warning: str
    warning_soft: str
    danger: str
    danger_soft: str

    # 代码编辑器的语义色
    code_bg: str
    code_gutter: str
    code_text: str
    code_comment: str
    code_keyword: str
    code_type: str
    code_string: str
    code_number: str
    code_preproc: str
    code_func: str


LIGHT = Palette(
    name="light",
    bg="#F5F6F8",
    sidebar="#FFFFFF",
    surface="#FFFFFF",
    surface_alt="#F1F3F6",
    hover="#F2F4F7",
    active="#E9EDF5",
    border="#E3E7EC",
    border_strong="#CFD6DF",
    text="#171A1F",
    text_dim="#5A6472",
    text_muted="#8B95A5",
    text_on_accent="#FFFFFF",
    accent="#4A5FE0",
    accent_hover="#3F53CC",
    accent_soft="#EDF0FE",
    success="#17A34A",
    success_soft="#E8F7EE",
    warning="#C2740B",
    warning_soft="#FDF3E3",
    danger="#D93A3A",
    danger_soft="#FCECEC",
    code_bg="#FBFCFD",
    code_gutter="#F3F5F8",
    code_text="#1F2430",
    code_comment="#8A94A6",
    code_keyword="#A0308C",
    code_type="#1F7AA8",
    code_string="#2E7D32",
    code_number="#B26A00",
    code_preproc="#7A5AF8",
    code_func="#2B5FD9",
)

DARK = Palette(
    name="dark",
    bg="#131519",
    sidebar="#191C22",
    surface="#1D2027",
    surface_alt="#23272F",
    hover="#242932",
    active="#2B313C",
    border="#2C313A",
    border_strong="#3A404B",
    text="#E9ECF1",
    text_dim="#A3ACBA",
    text_muted="#727C8B",
    text_on_accent="#FFFFFF",
    accent="#7B8CF7",
    accent_hover="#8F9DFA",
    accent_soft="#252B45",
    success="#3DD68C",
    success_soft="#1B3229",
    warning="#E0A33E",
    warning_soft="#33291530",
    danger="#F16A6A",
    danger_soft="#3A2224",
    code_bg="#181B21",
    code_gutter="#1D2027",
    code_text="#E4E8EF",
    code_comment="#6E7A8C",
    code_keyword="#E08FDC",
    code_type="#6FC3E8",
    code_string="#8FCF8F",
    code_number="#E0B15E",
    code_preproc="#B4A3FB",
    code_func="#84AEF8",
)


@dataclass(frozen=True)
class Metrics:
    """尺寸令牌。全矢量界面靠这些统一节奏，避免各处硬编码像素。"""

    radius_sm: int = 6
    radius_md: int = 9
    radius_lg: int = 14
    radius_pill: int = 999

    space_xs: int = 4
    space_sm: int = 8
    space_md: int = 12
    space_lg: int = 16
    space_xl: int = 24

    sidebar_w: int = 216         # 展开态宽度
    sidebar_w_collapsed: int = 64  # 折叠态宽度
    nav_item_h: int = 38
    row_h: int = 30              # 目录列表行高
    toolbar_h: int = 44
    result_h: int = 200          # 下栏结果区默认高度
    border_w: int = 1
    icon: int = 18               # 图标基准尺寸

    ui_font_size: int = 13
    small_font_size: int = 11
    mono_font_size: int = 13


@dataclass
class Theme:
    """当前生效的主题。切换亮/暗就是换掉 palette。"""

    palette: Palette = field(default_factory=lambda: LIGHT)
    metrics: Metrics = field(default_factory=Metrics)
    ui_font_size: int = 13       # 设置界面可调
    mono_font_size: int = 13     # 设置界面可调
    ui_font_family: str = ""     # 空 = 用系统默认
    mono_font_family: str = ""   # 空 = 用系统等宽

    # 平台默认字体栈：必须是 Qt 能识别的真实族名。
    # （"-apple-system" 这种 CSS 关键字 Qt 不认，写了会刷一堆字体告警）
    SYSTEM_UI_STACK = (
        "'PingFang SC', 'Hiragino Sans GB', 'Heiti SC', "
        "'Microsoft YaHei', 'Segoe UI', 'Noto Sans CJK SC', sans-serif"
    )
    # 等宽字体栈里必须带中文字体：只给 Menlo 这类纯西文等宽字体时，
    # 中文会落到 Qt 的兜底字体上，容易出现方框/错位（"乱码"）
    SYSTEM_MONO_STACK = (
        "Menlo, 'PingFang SC', Monaco, 'Microsoft YaHei', "
        "'Cascadia Mono', Consolas, 'JetBrains Mono', "
        "'Noto Sans Mono CJK SC', 'Courier New', monospace"
    )

    @property
    def small_font_size(self) -> int:
        """次要文字字号，跟着主字号缩放。"""
        return max(10, self.ui_font_size - 2)

    def font_families(self) -> Dict[str, str]:
        return {
            "ui": self.ui_font_family or self.SYSTEM_UI_STACK,
            "mono": self.mono_font_family or self.SYSTEM_MONO_STACK,
        }

    def scaled(self, base: int) -> int:
        """按主字号缩放一个尺寸，让整体节奏跟着字号走。"""
        return max(1, round(base * self.ui_font_size / 13))


# 全局单例。界面通过 theme() 取当前主题，切换主题后调用 set_theme 并广播刷新。
_current = Theme()


def theme() -> Theme:
    return _current


def set_theme(new_theme: Theme) -> Theme:
    global _current
    _current = new_theme
    return _current


def palette_for(mode: str) -> Palette:
    return DARK if mode == "dark" else LIGHT
