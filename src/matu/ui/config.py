"""界面配置的读写（外观、字号、请求策略）。

存在应用数据目录下的 settings.json（项目外），与凭据无关。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict

from ..core.client import MATU_HOME

SETTINGS_FILE = MATU_HOME / "settings.json"


@dataclass
class Config:
    """全部可调项。新增设置项直接加字段即可，读取时会自动补默认值。"""

    # 外观
    appearance: str = "system"      # system | light | dark
    ui_font: str = ""               # 空 = 系统默认
    mono_font: str = ""             # 空 = 系统等宽
    ui_font_size: int = 13
    mono_font_size: int = 13

    # 窗口
    sidebar_collapsed: bool = True      # 默认就是简洁（图标）模式

    # 当前账号：数据与缓存都按它隔离，换账号就要重新加载
    active_account: str = ""

    # 请求策略
    request_interval: float = 0.1
    max_requests_per_run: int = 2048
    allow_submission: bool = True   # 提交总闸（界面上可关，关了就不会有任何提交）
    session_check_minutes: int = 30  # 每隔多久探一次登录态，掉了自动补登录

    # 提示
    skip_submit_confirm: bool = False   # "记住我的选择"

    @classmethod
    def load(cls) -> "Config":
        if not SETTINGS_FILE.exists():
            return cls()
        try:
            raw: Dict[str, Any] = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return cls()
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in raw.items() if k in known})

    def save(self) -> None:
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
