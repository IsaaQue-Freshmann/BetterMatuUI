"""HTML 解析器：把码图的页面转成数据模型。

站点是 2011 年的 Struts2 + 深嵌套表格，结构脆弱，所以这里的原则是
**按表头文案和标签特征定位，而不是按列序号**——页面加一列也不会解析错位。

两个必须守住的细节：
- 取单元格一律带 recursive=False。页面表格层层嵌套，不带这个参数会把
  内层表格的 td 全部拉平，表头行会被误当成数据行。
- 表头识别要求"每个表头文字各自独占一个单元格"，否则外层容器的那个
  大 td（文本是整页拼接）会误命中。

站点改版时只需要改这个文件。
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from bs4 import BeautifulSoup, Tag

from .models import Submission, Task

WS = re.compile(r"\s+")


def _text(node: Optional[Tag]) -> str:
    if node is None:
        return ""
    return WS.sub(" ", node.get_text(" ", strip=True)).strip()


def _int(value: str) -> Optional[int]:
    m = re.search(r"-?\d+", value or "")
    return int(m.group(0)) if m else None


def _float(value: str) -> Optional[float]:
    m = re.search(r"-?\d+(?:\.\d+)?", value or "")
    return float(m.group(0)) if m else None


def _direct_cells(row: Tag) -> List[Tag]:
    """只取该行自己的单元格，不含嵌套表格里的。"""
    cells = row.find_all(["td", "th"], recursive=False)
    return cells


def _row_cells(row: Tag) -> List[str]:
    return [_text(td) for td in _direct_cells(row)]


def _squeeze(label: str) -> str:
    return label.replace(" ", "").replace("\u3000", "").strip()


def _looks_like_header(row: Tag, must_have: List[str]) -> bool:
    labels = {_squeeze(_text(td)) for td in _direct_cells(row)}
    return all(_squeeze(h) in labels for h in must_have)


def _find_table_by_headers(soup: BeautifulSoup, must_have: List[str]) -> Optional[Tag]:
    """找到表头行真正包含全部指定文案的那张表。"""
    for table in soup.find_all("table"):
        for row in table.find_all("tr", recursive=False):
            if _looks_like_header(row, must_have):
                return table
    return None


def _header_index(row: Tag) -> Dict[str, int]:
    mapping: Dict[str, int] = {}
    for idx, cell in enumerate(_direct_cells(row)):
        label = _squeeze(_text(cell))
        if label:
            mapping[label] = idx
    return mapping


def _cell_by_header(cells: List[str], header: Dict[str, int], name: str,
                    default: str = "") -> str:
    idx = header.get(_squeeze(name))
    return cells[idx] if idx is not None and idx < len(cells) else default


def _pager(soup: BeautifulSoup) -> Tuple[int, int]:
    text = soup.get_text(" ", strip=True)
    cur = re.search(r"第\s*(\d+)\s*页", text)
    total = re.search(r"共\s*(\d+)\s*页", text)
    return (int(cur.group(1)) if cur else 1, int(total.group(1)) if total else 1)


def parse_pager(html: str) -> Tuple[int, int]:
    """返回页面的 (当前页码, 总页数)，分页遍历靠它。"""
    return _pager(BeautifulSoup(html, "lxml"))


# ---------------------------------------------------------------- 题目总表


def parse_task_list(html: str) -> Tuple[List[Task], int, int]:
    """解析 `题目总表` 的一页，返回 (题目列表, 当前页, 总页数)。"""
    soup = BeautifulSoup(html, "lxml")
    table = _find_table_by_headers(soup, ["题目编号", "编译类型"])
    tasks: List[Task] = []
    if table is None:
        return tasks, 1, 1

    header: Dict[str, int] = {}
    for row in table.find_all("tr", recursive=False):
        cells = _row_cells(row)
        if not cells:
            continue
        if _looks_like_header(row, ["题目编号", "编译类型"]):
            header = _header_index(row)
            continue
        if not header:
            continue

        link = row.find("a", href=re.compile(r"taskdetail\?taskid=\d+"))
        if link is None:
            continue
        m = re.search(r"taskid=(\d+)", link["href"])
        if not m:
            continue

        tasks.append(Task(
            task_id=int(m.group(1)),
            name=_cell_by_header(cells, header, "名称"),
            teacher=_cell_by_header(cells, header, "出题老师"),
            language=_cell_by_header(cells, header, "语言要求"),
            platform=_cell_by_header(cells, header, "平台"),
            compiler=_cell_by_header(cells, header, "编译器"),
            compile_type=_cell_by_header(cells, header, "编译类型"),
            created_at=_cell_by_header(cells, header, "出题时间"),
        ))

    cur, total = _pager(soup)
    return tasks, cur, total


# ---------------------------------------------------------------- 题目详情


def parse_task_detail(html: str) -> Dict[str, str]:
    """解析题目详情页。

    正文取 <pre> 块，这样能原样保留代码缩进和空格——
    完型填空和 teacher_main 类题目的正文本身就是代码，格式不能丢。
    """
    soup = BeautifulSoup(html, "lxml")
    result = {"name": "", "language": "", "description": ""}

    legend = soup.find("legend")
    if legend is not None:
        result["name"] = _text(legend)

    scope = soup.find("fieldset") or soup

    for td in scope.find_all("td"):
        if "语言要求" in _text(td):
            sibling = td.find_next_sibling("td")
            if sibling is not None:
                result["language"] = _text(sibling)
            break

    pres = scope.find_all("pre")
    if pres:
        blocks = [p.get_text().strip("\r\n").rstrip() for p in pres]
        result["description"] = "\n\n".join(b for b in blocks if b.strip())
    else:
        # 兜底：没有 <pre> 时取 fieldset 内除标签行外的文本
        lines = [
            ln.strip() for ln in scope.get_text("\n", strip=True).split("\n")
            if ln.strip() and ln.strip() not in {
                result["name"], "题 号:", "语言要求：", "通过题库进入", "上传作业", "返回",
            } and not re.fullmatch(r"\d+", ln.strip())
        ]
        result["description"] = "\n".join(lines)

    return result


# ---------------------------------------------------------------- 作业与提交


def parse_homework_groups(html: str) -> List[Dict[str, object]]:
    """解析 `我的班级 -> 作业列表`，取作业（TaskGroup）清单。"""
    soup = BeautifulSoup(html, "lxml")
    table = _find_table_by_headers(soup, ["编号", "总分比例"])
    groups: List[Dict[str, object]] = []
    if table is None:
        return groups

    header: Dict[str, int] = {}
    for row in table.find_all("tr", recursive=False):
        cells = _row_cells(row)
        if not cells:
            continue
        if _looks_like_header(row, ["编号", "总分比例"]):
            header = _header_index(row)
            continue
        if not header:
            continue
        link = row.find("a", href=re.compile(r"listTaskGroup_Task\?taskGroup\.id=\d+"))
        if link is None:
            continue
        m = re.search(r"taskGroup\.id=(\d+)", link["href"])
        if not m:
            continue
        groups.append({
            "task_group_id": int(m.group(1)),
            "name": _cell_by_header(cells, header, "名称"),
            "weight": _float(_cell_by_header(cells, header, "总分比例")),
            "created_at": _cell_by_header(cells, header, "时间"),
        })
    return groups


def parse_homework_tasks(html: str, task_group_id: int) -> List[Dict[str, object]]:
    """解析某次作业内的题目列表（含允许提交次数与分值）。"""
    soup = BeautifulSoup(html, "lxml")
    table = _find_table_by_headers(soup, ["题目编号", "允许提交次数"])
    items: List[Dict[str, object]] = []
    if table is None:
        return items

    header: Dict[str, int] = {}
    for row in table.find_all("tr", recursive=False):
        cells = _row_cells(row)
        if not cells:
            continue
        if _looks_like_header(row, ["题目编号", "允许提交次数"]):
            header = _header_index(row)
            continue
        if not header:
            continue
        link = row.find(
            "a", href=re.compile(r"taskdetail\?taskid=\d+&taskGroupTask\.id=\d+")
        )
        if link is None:
            continue
        m = re.search(r"taskid=(\d+)&taskGroupTask\.id=(\d+)", link["href"])
        if not m:
            continue
        items.append({
            "task_group_id": task_group_id,
            "task_group_task_id": int(m.group(2)),
            "task_id": int(m.group(1)),
            "name": _cell_by_header(cells, header, "名称"),
            "language": _cell_by_header(cells, header, "语言要求"),
            "max_submissions": _int(_cell_by_header(cells, header, "允许提交次数")),
            "score": _float(_cell_by_header(cells, header, "分值")),
        })
    return items


def parse_submissions(html: str) -> List[Submission]:
    """解析 `作业状态` 页的提交记录行。"""
    soup = BeautifulSoup(html, "lxml")
    table = _find_table_by_headers(soup, ["题目编号", "状态", "分数"])
    subs: List[Submission] = []
    if table is None:
        return subs

    header: Dict[str, int] = {}
    for row in table.find_all("tr", recursive=False):
        cells = _row_cells(row)
        if not cells:
            continue
        if _looks_like_header(row, ["题目编号", "状态", "分数"]):
            header = _header_index(row)
            continue
        if not header:
            continue

        detail = row.find("a", href=re.compile(r"scoredetail\?assignmentid=\d+"))
        if detail is None:
            continue
        m = re.search(r"assignmentid=(\d+)", detail["href"])
        if not m:
            continue
        download = row.find("a", href=re.compile(r"downloadassignmentfile\?assignmentid=\d+"))
        task_link = row.find("a", href=re.compile(r"taskdetail\?taskid=\d+"))

        # 作业状态页的"题目编号"是纯文本；有的页面做成链接，两种都兼容。
        task_id = _int(_cell_by_header(cells, header, "题目编号"))
        if task_id is None and task_link is not None:
            task_id = _int(task_link["href"])

        subs.append(Submission(
            assignment_id=int(m.group(1)),
            task_id=task_id or 0,
            name=_cell_by_header(cells, header, "名称"),
            language=_cell_by_header(cells, header, "提交语言"),
            submitted_at=_cell_by_header(cells, header, "时间"),
            status=_cell_by_header(cells, header, "状态"),
            score=_int(_cell_by_header(cells, header, "分数")),
            detail_url=detail["href"],
            download_url=download["href"] if download is not None else "",
        ))
    return subs


def parse_score_detail(html: str) -> str:
    """解析成绩详单页正文：扣分与评测失败原因，这是"查看上传结果"的核心信息。"""
    soup = BeautifulSoup(html, "lxml")
    scope = soup.find("fieldset") or soup.body or soup
    text = scope.get_text("\n", strip=True)
    lines = [
        ln.strip() for ln in text.split("\n")
        if ln.strip() and ln.strip() not in {"成绩详单", "评论", "-->", "提交", "提交评论"}
    ]
    return "\n".join(lines)
