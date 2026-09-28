"""把 SQLite 里的班级/作业/题目组织成界面用的树。

层级严格对齐站点，也对齐需求里给的路径示例：
    我的班级 / 作业列表 / c语言 / 第1次上机 / 计算e的x次方
对应 kind:  root  / section  / course / group   / task
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ..core.store import Store

# 每种节点的图标（矢量图标名）
ICON_FOR_KIND = {
    "root": "class",
    "section": "folder",
    "course": "folder",
    "group": "folder-open",
    "task": "file-code",
    # 系统帮助页复用同一套树与委托，文档节点用这个图标
    "doc": "info",
}


@dataclass
class Node:
    """树节点。label/meta/badge 决定这一行怎么画，其余字段供右侧详情用。"""

    kind: str
    label: str
    meta: str = ""            # 行右侧的次要信息（时间、语言…）
    badge: str = ""           # 行右侧的小徽章（分值、权重…）
    task_id: int = 0
    task_group_id: int = 0
    task_group_task_id: int = 0
    class_id: int = 0
    children: List["Node"] = field(default_factory=list)
    extra: Dict[str, object] = field(default_factory=dict)

    @property
    def is_leaf(self) -> bool:
        return not self.children

    @property
    def icon(self) -> str:
        return ICON_FOR_KIND.get(self.kind, "file-code")

    def path_labels(self) -> List[str]:
        """从根到自己的标签路径，用于面包屑。由 build 时写入 extra['_parents']。"""
        return list(self.extra.get("_parents", [])) + [self.label]


def _short_weight(weight) -> str:
    if weight is None:
        return ""
    try:
        return f"权重 {float(weight):g}"
    except (TypeError, ValueError):
        return ""


def build_class_tree(store: Store) -> Node:
    """从本地库构建「我的班级」树。

    只用已经爬下来的数据，不发任何网络请求 —— 界面启动即可秒开。
    """
    root = Node(kind="root", label="我的班级")
    section = Node(kind="section", label="作业列表")
    section.extra["_parents"] = ["我的班级"]
    root.children.append(section)

    classes = store.get_classes()
    if not classes:
        section.children.append(Node(
            kind="hint", label="没有本地数据，点右上角刷新",
            extra={"_parents": ["我的班级", "作业列表"]},
        ))
        return root

    for cls in classes:
        class_id = cls["class_id"]
        course = Node(
            kind="course",
            label=cls.get("course") or f"班级 {class_id}",
            meta=cls.get("name", ""),
            badge=f"{cls.get('score','')} 分" if cls.get("score") else "",
            class_id=class_id,
            extra={"_parents": ["我的班级", "作业列表"]},
        )
        section.children.append(course)

        groups = store.get_homework_groups(class_id)
        if not groups:
            course.children.append(Node(
                kind="hint", label="暂无作业",
                extra={"_parents": ["我的班级", "作业列表", course.label]},
            ))
        for g in groups:
            group = Node(
                kind="group",
                label=g.get("name") or f"作业 {g['task_group_id']}",
                meta=(g.get("created_at") or "").split(" ")[0],
                badge=_short_weight(g.get("weight")),
                task_group_id=g["task_group_id"],
                class_id=class_id,
                extra={"_parents": ["我的班级", "作业列表", course.label]},
            )
            course.children.append(group)

            items = store.get_homework_tasks(g["task_group_id"])
            for it in items:
                task = store.get_task(it["task_id"]) or {}
                group.children.append(Node(
                    kind="task",
                    label=it.get("name") or f"题目 {it['task_id']}",
                    # 目录栏空间优先留给题目名：语言、类型、分值都不显示，
                    # 需要时看右区（题面徽章、概览、结果栏都有）
                    meta="",
                    badge="",
                    task_id=it["task_id"],
                    task_group_id=g["task_group_id"],
                    task_group_task_id=it["task_group_task_id"],
                    class_id=class_id,
                    extra={
                        "_parents": ["我的班级", "作业列表", course.label, group.label],
                        "compile_type": task.get("compile_type", ""),
                        "max_submissions": it.get("max_submissions"),
                        "teacher": task.get("teacher", ""),
                        "created_at": task.get("created_at", ""),
                    },
                ))
    return root


def build_task_center_tree(store: Store) -> Node:
    """构建「题目中心」树。

    层级与网站一致（搜索作业 / 作业状态 / 提交总结 / 题目总表），
    但**顺序上把题目总表放在最后**：它一展开就是几百道题，
    放最上面会把其他三项挤得看不见。

    内容全部属于当前账号，和「我的班级」共用同一个按账号隔离的库。
    """
    root = Node(kind="root", label="题目中心")

    for key, label, meta in (
        ("search", "搜索作业", "按题号或名称查找"),
        ("submissions", "作业状态", "我的提交记录"),
        ("grades", "提交总结", "按题汇总"),
    ):
        root.children.append(Node(kind=key, label=label, meta=meta,
                                  extra={"_parents": ["题目中心"]}))

    rows = store.conn.execute(
        "SELECT task_id, name, language, compile_type, teacher FROM tasks"
        " ORDER BY task_id").fetchall()
    bank = Node(kind="section", label="题目总表",
                meta=f"{len(rows)} 题" if rows else "题库（还没有数据）")
    bank.extra["_parents"] = ["题目中心"]
    for row in rows:
        bank.children.append(bank_task_node(row))
    root.children.append(bank)
    return root


def bank_task_node(row) -> Node:
    """题库里的一道题。

    目录栏很窄，所以**不在题目名右侧显示语言和编译类型**——
    这些信息在右区的题面徽章里看得到。只保留最前面的题号标签。
    题库没有"作业上下文"，所以也不带 taskGroup 参数。
    """
    compile_type = row["compile_type"] or ""
    return Node(
        kind="task",
        label=row["name"] or f"题目 {row['task_id']}",
        meta="",                 # 语言不再占目录栏的横向空间
        badge="",                # 编译类型同理，去右区看
        task_id=row["task_id"],
        extra={
            "_parents": ["题目中心", "题目总表"],
            "compile_type": compile_type,
            "max_submissions": None,     # 允许提交次数只在作业里才有
            "language": row["language"] or "",
            "teacher": row["teacher"] or "",
        },
    )


# 编译类型在目录里显示成短标签，省地方
COMPILE_BADGE = {
    "编译整个文件夹内容": "整目录",
    "编译整个文件夹内容（老师提供teacher_main作为入口函数）": "teacher_main",
    "完型填空": "完型填空",
}


def find_task_node(root: Node, task_id: int) -> Optional[Node]:
    if root.kind == "task" and root.task_id == task_id:
        return root
    for child in root.children:
        found = find_task_node(child, task_id)
        if found is not None:
            return found
    return None


def all_nodes(root: Node) -> List[Node]:
    out = [root]
    for child in root.children:
        out.extend(all_nodes(child))
    return out
