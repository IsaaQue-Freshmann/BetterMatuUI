# BetterMatuUI 交接文档

给接手这个项目的下一个窗口/会话。读完这份就能接着干活。

项目位置：本仓库根目录。
Python 3.9.6 + PySide6 6.10.3，虚拟环境在 `.venv/`，入口 `PYTHONPATH=src .venv/bin/python -m matu.ui.app`（或 `./run.sh`）。

---

## 0. 一句话说清这个项目

码图（`matu.uestc.edu.cn`，电子科技大学的 C 语言作业平台）的**桌面客户端**：
把题库、编写、提交、评测结果、统计搬到本地，界面**全矢量自绘**（零位图素材）。
站点是 2011 年的 Java/Struts2 JSP 应用，**没有 JSON API**，所有数据靠解析 HTML。

---

## 1. 后端：加载的逻辑与思路

### 1.1 站点事实（都是实测出来的，别靠猜）

| 项 | 值 |
| --- | --- |
| 站点 | `http://matu.uestc.edu.cn/aptat`，**纯 HTTP**，无 HTTPS |
| 技术 | Apache-Coyote(Tomcat) + Struts2 + JSP，服务端渲染 |
| 会话 | `JSESSIONID` Cookie，URL 里也会重写 `;jsessionid=...` |
| 登录 | `POST /user/dologin.action`，字段 `user.Login` / `user.Password`，**无验证码** |
| 界面骨架 | frameset：`top.jsp` + `left.jsp` + `mainfra.jsp` |
| 姓名 | 在 `left.jsp` 的 `<span class="left-font02">` 里 |

主要端点：

```
课程中心  GET /course/liststudentclass                       班级列表
          GET /task/liststudenttaskgroup?_class.id=N         某班的作业列表
          GET /task/listTaskGroup_Task?taskGroup.id=N        某次作业的题目列表
题库      GET /task/listtotaltask?page=N                    题目总表（分页）
          GET /task/taskdetail?taskid=N                      题目详情（正文在 <pre> 里）
提交      GET /assignment/listassignment?page=N              全部提交记录
          GET /assignment/listassignment?taskid=N            某题的提交记录
          GET /assignment/scoredetail?assignmentid=N         成绩详单（扣分 + 失败原因）
          GET /file/downloadassignmentfile?assignmentid=N    取回那次提交的源码（回溯）
提交接口  POST /assignment/upload_assignment_by_copy_paste   源码直接提交
          POST /assignment/upload_assignment_by_single_file 单文件上传（本项目不用）
```

### 1.2 三个必须知道的坑（都踩过）

**坑一：`listassignment?taskid=N` 是按时间升序分页的，每页 10 条。**
第 1 页永远是最早的记录。只读第 1 页 → 提交数超过 10 条的题，新记录就"查不到"，
表现为"提交成功但站点没返回数据"、文件列表缺记录。**必须翻页**，找最新记录时取**末页**。
（`submit.fetch_task_submissions(pages="all"|"last")` 已经处理）

**坑二：会话失效有两种表现形态。**
1. 退回带登录表单的页面（`id="dologin"`）；
2. 返回一小段 **JS 跳转页**：`window.top.location.href=".../user/login.action"` —— 这种没有表单。
第 2 种以前没被识别，于是那段 HTML 被当成"源码"缓存并显示在编辑器里（用户报的"溯源代码不对"）。
`client.looks_like_login_page()` 现在两种都认，另有 `looks_like_html_not_code()` 兜底：
取回的"源码"如果以 `<html`/`<script` 开头就判定为网页，宁可报错也不当代码用。

**坑三：提交记录有状态列，值 `test` = 还没判完，`score` = 判完了。**
`test` 状态下分数列是 0、成绩详单是空的。**不能拿到记录就当结果报出去**，
否则界面显示 0 分、刷新两三次才变对。正确做法：轮询到状态变成 `score` 为止。
判完之后，**得分以成绩详单里的扣分为准**（得分 = 100 − 扣分），比列表的分数列可靠。

### 1.3 加载的顺序与策略

一次性全量加载（`core/refresh.refresh_all`），顺序按用途排：

```
① 班级与作业      体量最小，先让「我的班级」可用
② 提交记录与成绩详单  数据中心三项指标的来源，必须早于题库
③ 题库列表        **只取名称/语言/编译类型，不取题目正文**
```

第 ③ 步不取正文是本项目的关键提速手段：**一次全量加载从约 440 个请求降到 70 余个**。
正文在用户**点开某道题**时才抓那一道的（`refresh.fetch_task_detail`）。

**缓存策略**：缓存只用于离线查看。

- 未登录（离线）→ 读本地缓存
- 已登录 → **点什么加载什么**：打开某题就刷新该题的提交记录；点回溯就重新取那份源码；
  取到什么就用什么**覆盖**本地缓存

**请求克制**：串行、无并发、无轮询（只有提交后等判题这一个有限轮询）、失败不自动重试。
最小间隔默认 100 毫秒、单次运行上限 2048（都可在设置里改）。

### 1.4 只读闸门（安全设计，别拆掉）

`core/client.py` 里 POST 走白名单，不满足就抛 `PostNotAllowed`：

- 只有登录 `/user/dologin.action` 永远允许
- 提交类端点必须**同时**在 `SUBMISSION_ENDPOINTS` 且提交开关打开（默认关，
  开发期用环境变量 `MATU_ENABLE_SUBMISSION=1`，App 内走设置项）
- 其余任何 POST 一律拒绝

每个请求追加到 `~/.bettermatu/requests.log`，随时可审计。

### 1.5 数据存储（按账号隔离，**不在项目内**）

```
~/.bettermatu/
    accounts/<账号>/matu.db      题目、班级、作业、提交记录、本地文件（SQLite）
    accounts/<账号>/session.json 该账号的会话
    settings.json                界面设置
    requests.log                 请求审计
```

**站点结构对所有账号统一**（所以 `client/parsers/submit` 与账号无关），
**内容随账号不同**（班级/作业/题目都是账号私有的），换账号必须重新加载。

---

## 2. 前端：布局与命名

### 2.1 整体布局

```
┌──────────┬──────────────────────────────────────────────┐
│ 侧栏      │  详细界面（QStackedWidget，随菜单切换）        │
│ Sidebar  │                                              │
│ 216/64px │                                              │
└──────────┴──────────────────────────────────────────────┘
```

侧栏自上而下：`LogoMark`（矢量 `{}` 标记）→ 四个菜单 → `BusyIndicator`（加载转圈）
→ 分隔线 → `个人中心`（**始终吸附最底部**）；`CollapseToggle` 在个人中心上方，
折叠态宽度 64px、只留图标。登录失效时个人中心图标右上角出现黄圈感叹号 +
`AlertBubble`（黄色气泡，挂在窗口上以浮出侧栏）。

五个菜单对应五个页面类：

| 菜单 | 类 | 文件 |
| --- | --- | --- |
| 我的班级 | `MyClassPage` | `ui/pages/my_class.py` |
| 题目中心 | `TaskCenterPage` | `ui/pages/task_center.py` |
| 数据中心 | `DataCenterPage` | `ui/pages/data_center.py` |
| 系统帮助 | `HelpPage` | `ui/pages/help.py` |
| 个人中心 | `ProfilePage` → 内含 `SettingsSections` | `ui/pages/profile.py`、`ui/settings_sections.py` |

### 2.2 关键组件与文件对照

```
ui/theme.py         Palette / Metrics / Theme —— 所有颜色圆角间距集中在这里，界面里不许写死色值
ui/icons.py         29 个内嵌 SVG 图标，运行时按主题色渲染
ui/widgets.py       自绘基元：VectorButton / IconButton / Badge / Card / Divider /
                    Breadcrumb / VectorSpin（矢量步进器）/ GripSplitter（带可见分隔线）
ui/charts.py        HeatStrip（热力图）/ RadarChart（三角雷达）/ LineChart
ui/sidebar.py       Sidebar / NavButton / LogoMark / BusyIndicator / AlertBubble / CollapseToggle
ui/panels.py        ResultPanel（提交结果）/ ReadonlyHint（只读小字）/ OverviewPanel /
                    InfoRow / SectionTitle / OverviewList / Placeholder
ui/history.py       FileListPanel（底部"文件"列表：本地文件 + 历史提交）、
                    HistoryWorker / CodeWorker
ui/code_editor.py   CodeEditor（QPlainTextEdit + C/C++ 高亮 + 行号 + 括号匹配）
ui/disclaimer.py    DisclaimerDialog（启动声明）
ui/workspace.py     Workspace —— 当前账号的数据上下文（库 + 会话 + 重新登录）
ui/app.py           MainWindow 装配、主题切换、启动自检、加载指示器、登录告警
```

`MyClassPage` 与 `TaskCenterPage` 共用同一套左右结构：
左 `BrowserPanel`（`NodeTree` + 自绘 `TreeDelegate`），右 `CodeArea`。
`OverviewPanel` 在选中"文件夹"节点时显示。

**CodeArea 的上下结构**（"上中下等宽"，左右各 16px 边距）：

```
工具栏   #题号 题名 | 语言/编译类型/剩余次数徽章 | 导入题面代码 清空 提交
分栏1    StatementStrip（可折叠题面，高度可拖、按内容自适应且有上限）
         CodeEditor
分栏2    ResultPanel（得分/扣分项/扣分原因，高度随内容增长，外层滚动区出滚动条）
         ReadonlyHint（只读模式时才出现的一行小字）
         FileListPanel（文件列表：本地文件 + 历史提交，可回溯）
```

### 2.3 视觉约定（改界面时必须遵守）

- **全矢量**：图标是 SVG 路径、形状用 `QPainter` 画，**项目里不放位图素材**
- 颜色/圆角/间距**只从 `theme.py` 取**，不要在界面代码里写死
- 全局 QSS **绝不能给 `QWidget` 设不透明背景**：卡片是自绘的，
  普通容器带上底色会盖在卡片上，视觉上变成"空洞"
- 控件的外观一律在 `paintEvent` 里画，不用 QSS 外观、不用位图皮肤
- 主题切换后需要重新取色的控件要有 `apply_theme()`（`restyle()` 会递归调用）

---

## 3. 操作逻辑（用户视角）

### 3.1 启动

1. 弹**启动声明**（`DisclaimerDialog`），必须选「确认」才继续，「退出」/Esc 直接结束进程
2. 进入**数据中心**（默认页）
3. 600ms 后**启动自检**：若已登录，比对本地与站点的题数
   （`refresh.bank_totals`，只读题目总表分页，1~2 个请求）——
   本地少于站点就说明上次没加载完，**接着加载**（断点续传）
4. 若已登录但会话不可用 → 侧栏直接亮登录告警

### 3.2 登录（个人中心）

登录成功 → 自动做三件事：

1. **取姓名**（1 个请求，两个页面都显示）
2. 若是新账号/空库 → **整份加载**（班级 → 提交记录 → 题库列表）
3. 撤掉登录告警

### 3.3 进入题目的三条路径（行为不同，别搞混）

| 入口 | 行为 |
| --- | --- |
| 我的班级 / 题目总表 / 提交总结 | 打开**离现在最近的未提交文件**；没有就新建一个 |
| 作业状态（点某条记录） | 切到该题上下文 + **直接打开那一条历史记录**（只读） |
| 已点开题目 → 底部文件列表 | 同上：点本地文件进编辑、点历史提交进只读回溯 |

### 3.4 文件模型（核心概念）

每道题下面是一份"文件"列表，混排两类：

| 类型 | 命名 | 分数列 | 打开后 |
| --- | --- | --- | --- |
| **本地文件** | `#题号 新文件 时间戳` | 未提交 | 可写：清空 / 提交 |
| **历史提交** | 历史提交 | 实际分数 | **只读**：只显示「重新编辑至新文件」 |

- 切换文件/题目时**自动存档**（打字停顿 1.2 秒也存一次）
- 只读模式下编辑器真的锁住（`setReadOnly`）+ 底色压暗 + 下方一行 `⚠ 只读模式` 提示
- 「重新编辑至新文件」= 新建一个本地文件并把当前代码复制进去，回到可写
- 结果栏：本地文件显示「未提交」+ 下方小字标注历史最高分；历史提交显示那次的分数与扣分原因

### 3.5 提交

1. 点「提交」→ 确认框（显示**剩余次数** = 允许总次数 − 已提交，勾"记住我的选择"可跳过）
2. POST 源码 → 站点返回"上传成功"
3. **轮询该题最新记录直到状态变成 `score`**（每 2 秒一次，最多等 120 秒），
   等待期间结果栏显示"正在判题"进度
4. 判完 → 取成绩详单 → 显示 得分 / 扣分项 / 扣分原因
5. 提交成功后本地文件**保持"未提交"不变**，站点记录作为一条"历史提交"出现

### 3.6 回溯（取回历史提交的源码）

- 已登录 → **总是重新从站点取**，取到什么覆盖缓存什么
- 未登录 → 用本地缓存，并提示"离线"
- 只有**双击**历史提交行或点「回溯」才触发；一次一个请求

### 3.7 登录态维护

- **每个 GET 请求**都检查：拿回登录页 → 自动用本次会话内存里的凭据补登录 → 重试一次
- **每 30 分钟**（设置可改）定时探活，掉了自动补登录
- 提交那个 POST 只有在响应是登录页时才补登重试（那证明没提交成功，不会重复提交）
- 补登录也失败 → 侧栏亮告警（登录过期）/ 用户主动退出 → 亮"已退出登录"

---

## 4. 开发过程与已解决的问题（改代码前先读，避免重犯）

### 4.1 界面类

| 问题 | 根因 | 结论 |
| --- | --- | --- |
| 目录"默认折叠"失效 | Qt 的 `scrollTo` 为了让当前项可见会**自动展开祖先** | 覆写 `NodeTree.scrollTo`，只滚到"当前可见的最深祖先" |
| 卡片里出现"空洞" | 全局 QSS 给所有 `QWidget` 设了不透明底色，容器盖住了自绘卡片 | QSS 只给 QMainWindow/QDialog 设底色 |
| 结果栏内容多时压字 | 自绘面板高度固定 | 改成高度随内容增长 + 外层滚动区提供滚动条（**不要在自绘里做视口裁剪**） |
| 行右侧文字互相压 | 排版数学写错（标注矩形伸进徽章 6px、名称没给标注留位） | 改成从右往左依次排布，各自 elide；窄时逐级"弃车保帅"（先丢标注再丢徽章） |
| 极窄时文字重叠 | 同上 | 同上 |
| 删缓存/切账号后**静默掉登录**（侧栏不亮告警） | 告警只在"点退出登录"那一个调用点上设置，没跟着登录态走；而掉登录的路径有 6 条（主动退出、会话过期、补登录失败、被动发现、切账号、删缓存） | 告警改为由 `_on_login_state_changed` 按**状态**统一设置，更具体的措辞（"登陆状态已过期""缓存已删除，已退出登录"）在各场景覆盖；`_on_logout` 里那句重复的设置删掉了 |

### 4.2 数据与线程

| 问题 | 根因 | 结论 |
| --- | --- | --- |
| 后台任务一跑就崩 | sqlite3 默认禁止跨线程使用连接，而加载/回溯都在 QThread 里 | `Store` 用带锁的连接代理（`_LockedConn`，`check_same_thread=False` + 锁） |
| 点回溯没反应、缓存不更新 | 历史列表与取源码**共用一个 worker 槽位**，前者在跑就把后者静默挡掉 | 拆成 `_history_worker` / `_code_worker` 两个槽位 |
| 文件跨题串内容 | 保存计时器在"已切到新文件、编辑器还是旧内容"的间隙触发 | 切换前先 `_save_timer.stop()`；加文件归属校验；新建时静默清空编辑器 |
| 提交显示假 0 分 | 结果基线**联网取**、失败退化成 0，于是把站点旧记录当成本次结果 | 基线改从**本地库**取，并加"只接受最近 30 分钟内记录"的时间窗 |
| 提交显示 0（真实 75/90） | 拿到 `status=test` 的记录（还没判）就当结果报出去 | 轮询到 `status=score`；得分 = 100 − 扣分 |
| 新记录"查不到" | `listassignment?taskid=N` 升序分页，只读了第 1 页 | 翻页；找最新取末页 |
| 中文乱码 | 等宽字体栈里没有中文字体 | 栈里加 PingFang SC / 微软雅黑 / Noto CJK |

### 4.3 低级但致命的坑

- **Qt 在 `paintEvent` 里遇到异常会直接终止进程**（连报错都不输出）。
  自绘控件里用了没导入的名字（如 `QPointF`）就是这个后果 → 加名字前先确认导入。
- PySide6 的 `QBuffer(QByteArray())`：临时对象被回收后 QBuffer 拿着悬空指针 → **段错误**。
  必须持住那个 `QByteArray`。（生成 ICO 时踩到）
- Python 3.9 的 f-string 里**不能有反斜杠**，也不能用中文引号当字符串引号
  （写批量替换脚本时踩到多次，会导致脚本语法错误、改动根本没落盘）。
- 自绘控件里**绝不在 `paintEvent` 中创建子控件**（每次重绘都新建一个）。

---

## 5. 已知遗留问题（接手后可以优先处理）

1. ~~两处同类的分页风险~~ —— **已修**，见 §9：`fetch_class_groups` / `fetch_group_tasks`
   已按站点分页链接翻页，并有 `MAX_LIST_PAGES` 防呆上限
2. ~~`tools/` 里"爬虫"字样未改~~ —— **已改**，见 §9：全项目"爬*"字样已清成"加载*"
3. **二进制产物落后于代码**：`output/source/Beta1.2`（源码包，2026-09-30 出，
   含截至当日的全部修复，已 git init + 提交、工作区干净、可直接 push）
   **是当前的源码基准**；而 `output/mac/BetterMatuUI Beta 1.0.dmg`、
   `output/win/BetterMatuUI_Beta1.0_WinX86.exe` 仍是 Beta 1.0 的老二进制，
   要用 Beta 1.2 的代码重打：`mac/BetterMatuUI.spec` + `mac/build_dmg.sh`
   （版本号已统一到 1.2）；Windows 见 `win/`（version_info 也已同步 1.2）。
4. macOS 的 DMG 是 ad-hoc 签名，**用户首次打开仍需右键→打开**（无开发者证书绕不过）。
   Windows 侧同理会有 SmartScreen 提示。
5. 声明窗口目前**每次启动都弹**（按用户"每当首次打开"的字面要求），
   若要改成只弹一次需要加一个"已同意"标记。

---

## 6. 环境、凭据与纪律

- 虚拟环境 `.venv/`（Python 3.9.6），依赖 `requirements.txt`
- **凭据策略**：只从环境变量 `MATU_USER` / `MATU_PASS` 读取；
  来源由开发者自己的 shell 掌握，**项目内不记录任何账号信息，也不记录凭据文件的路径**
- 数据与缓存都在 `~/.bettermatu/`（项目外）
- 提交开关默认关（`MATU_ENABLE_SUBMISSION=1` 才开），提交端点另有白名单兜底
- 术语统一：界面与注释里用**"加载"**，不用"爬取"

## 7. 测试与验收方式

```bash
.venv/bin/python tools/selftest.py           # 离线解析自检（不联网）
PYTHONPATH=src QT_QPA_PLATFORM=offscreen .venv/bin/python tools/screenshot_ui.py
                                             # 离屏渲染各界面状态到 data/ui_shots/
                                             # 注意：**它会联网**——里面真的 new 了
                                             # MainWindow，本地会话有效时会发二十来个请求
./run.sh                                     # 真机启动
.venv/bin/python tools/reset_state.py --apply  # 恢复"首次打开"状态（会先备份）
```

**提交相关改动务必真机验证**（站点行为只有实测才知道），
用户曾授权在 `#1 hello world` 与 `#18 14_判断n是否为素数` 上做有限次真实提交，
额度用完即止；**提交前先确认是否还有授权**。

## 8. 用户的明确偏好（别做的事）

- 界面要"简洁现代美观"，**全矢量**
- 请求要克制："不要像疯狗一样疯狂请求"，不做轮询（提交等判题那一次除外）
- 缓存只用于离线，登录状态下"点什么加载什么"并用站点数据覆盖缓存
- **不允许**未经授权提交代码；提交有次数限制
- 遇到不确定的 UI 语义，**先问清楚再动手**

---

## 9. 本轮改动（2026-09-30）

- **两处分页漏取已修**（`src/matu/core/refresh.py`）：
  - 新增 `fetch_class_groups(client, class_id)` 与 `fetch_group_tasks(client, group_id)`，
    按站点自己的分页链接翻页（`liststudenttaskgroup?page=N&_class.id=X`、
    `listTaskGroup_Task?page=N&taskGroup.id=X`），`refresh_class_data` 改为调用它们
  - `P_GROUP_TASKS` 补上了 `&page={page}`（原来根本没有分页参数）
  - 新增防呆上限 `MAX_LIST_PAGES = 50`：站点若声称页数异常，取前 50 页并记一行日志
  - `tools/crawl.py` 里两个**从没被用过**的同名常量删掉了（其中 `P_GROUP_TASKS`
    是没有分页参数的旧版，留着迟早被误用）
- **`tools/selftest.py` 的 fixture 名修对**：原来"题目总表"写成 `listtotalvisibletask`
  （真实端点是 `listtotaltask`），"作业列表"漏了 `_page=1` 后缀 —— 这两条检查
  一直是**静默跳过**、从来没跑过。新增 `resolve()` 兼容带分页后缀的文件名后，
  自检 **6/6 全通过**（之前是 3 通过 3 跳过）。
- **术语统一**：`src/`、`tools/`、`README.md`、`docs/` 里 50 余处"爬*"字样改成"加载*"
  （"断点续爬"→"断点续传"，"边爬边加"→"边加载边加"，"点什么爬什么"→"点什么加载什么"）。
  `tools/crawl.py` 的**文件名没动**（改名会牵动 README/文档/脚本里的引用），要改说一声。

本轮验证方式（都是实测，不是推理）：

- 离线多页仿真：把缓存页改造成 3 页，确认两处都翻满 3 页、条目按页累积
- 真机只读核对（复用已保存会话，5 个请求，**不写库、不提交**）：
  `fetch_class_groups(641)` → 2 次作业、`fetch_group_tasks(8877)` → 1 道题，与本地库一致；
  对只有 1 页的列表请求 `page=2`，站点正常应答（不报错、不返回登录页）
- 防呆上限：站点声称 60 页时，实际只请求 50 次并记日志
- `tools/selftest.py` 6/6、全部 `.py` 编译通过

### 追加（同日，数据中心两项）

- **评级解释文字改为从算法常量派生**（`src/matu/core/stats.py`）：
  `Stats.explain()` 里"考勤度"那行原来写死了"空日×0.01"，而实际常量
  `IDLE_DAY_WEIGHT = 0.2` —— 说明和算法脱节。现在权重、锚点都从常量取
  （新增 `ACTIVE_DAY_WEIGHT = 1.0`，计算也改用它），文字形如
  `75 次提交 ÷（活跃 5 日×1 + 空 25 日×0.2）= 7.50 次/日 → 70.3（20 次/日 记满）`。
  **改算法只改常量，说明跟着变**，同类脱节不会再出现。
- **数据中心自动刷新**（`src/matu/ui/app.py`）：
  - 新增 `refresh_data_center()`：只按本地库重算（实测 ~1ms，不联网）
  - 新增 `_site_workers()`：把"要跟站点打交道"的后台任务集中列在一起，
    顺手把**设置页里那个"加载完整题库"也纳入**了（以前它既不转加载指示器、
    也不触发界面刷新）
  - 刷新时机：`_refresh_busy()` 里盯"忙 → 闲"拐点（一次交互刚结束就重算，
    以后新增交互自动覆盖）；`_startup_selfcheck()` 每次启动；`_on_data_changed()`
    设置页加载完成/删缓存之后；加载完成仍走原有的 `data_loaded → refresh_everything`
  - 实测：忙时不刷新、闲下来刷新一次、持续空闲不重复刷新（离线桩测试）
### 追加（同日，出 Beta 1.2 源码包）

- 位置 `output/source/Beta1.2`，**67 个文件、2.0 MB（含 .git）**，
  `main` 分支、一个提交、工作区干净——**可以直接 `git remote add` + `push`**。
- 文件集与 Beta1.1 完全一致，只多了一份 `docs/HANDOFF.md`（一并提交了；
  不想让它在公开仓库里的话删掉再 commit 即可）。
- 为这次出包同步改的东西：`README.md` 重写成发布版（版本号 1.2、新增
  「Beta 1.2 更新」与「只读与安全」两节、修掉"界面尚未开始"这类过时描述）；
  版本号统一到 1.2（`mac/BetterMatuUI.spec` 的 DISPLAY_NAME 与
  CFBundle 版本、`mac/build_dmg.sh` 的 VOL_NAME、`win/build_win.bat`、
  `win/version_info.txt`）；`.gitignore` 补上 `output/`（打包产物别进仓库）。
- 出包脚本没有：当时是用 rsync 排除 `.venv/ output/ data/ .DS_Store
  __pycache__ *.pyc mac/icon.iconset/` 后 `git init -b main` + 提交，
  **下次再出包照抄这行排除列表**。
- 上架前的验收（都跑过）：包内 `tools/selftest.py` 6/6、全部 `.py` 编译通过、
  离屏把 MainWindow 起起来（5 个页面都在）、无账号/姓名/密钥/开发机绝对路径、
  最大文件 359 KB（`docs/ui-mindmap.png`）。

### 追加（同日，截图工具不得写用户设置）

- **`tools/screenshot_ui.py` 会把真实的 `~/.bettermatu/settings.json` 重写掉**：
  它里面跑的是真 App、真 Config，而界面里有 4 处会存盘（折叠开关、
  `_activate` 换账号、删缓存、改请求策略）。10:11 那次渲染就把该文件的
  mtime 改了（值恰好没变，所以没被发现）。
- **修法**：工具里 `Config.save = lambda self: None` 焊死 —— 比逐个去猜
  哪条路径会写可靠。**验证**：离线跑完整套渲染，前后对比设置文件的
  mtime / 大小 / 内容，三者都没变。
- **排查中的教训**（免得下次再绕）：我一度以为是自己把 `sidebar_collapsed`
  写成了 `true`，其实是**用户自己那次 App 会话**写的 —— 靠
  `~/.bettermatu/requests.log` 的时间线（10:31:21 启动、10:31:49 登录、
  10:32:28 加载完，而设置文件写于 10:32:25）才分清谁干的。
  **请求日志能当"谁在什么时候动了手"的证据用**，别只看文件内容。

- **`tools/screenshot_ui.py` 补了数据中心的截图**（`08_data_center_{light,dark}.png`）：
  它是默认首页，之前居然一直没有截图，改了评级文案没处看。
### 追加（用户报的 bug：删缓存后静默掉登录）

- **现象**：在设置里删掉当前账号的缓存 → 自动退出登录，但侧栏**不亮告警**，
  用户看到的是"莫名其妙退出了登录，一声不吭"。
- **根因**：`set_login_alert` 只在"点退出登录"这一个调用点被调用。而会掉登录的
  路径实际有 6 条（主动退出、会话过期、自动补登录失败、被动发现是登录页、
  切账号、删缓存），其余 5 条全是静默的。
- **修法**（`src/matu/ui/app.py`）：告警改为挂在 `_on_login_state_changed` 上，
  按**状态**走；措辞由各场景覆盖：会话过期 → "登陆状态已过期"，
  删缓存 → "缓存已删除，已退出登录"，其余兜底 "已退出登录"。
  顺带修掉反向的 bug：**自动补登录成功后告警不会撤掉**（会留一个过期的黄标）。
  `_on_logout` 里那句重复的 `set_login_alert` 删了 —— 一个入口，别再散开。
- **验证**：把 `AccountStore` 指到临时目录（不碰真实的 `~/.bettermatu`）、
  `Config.save` 置空（不写真实设置）、`try_saved_session` 与 `client.get` 打桩
  （不联网），起真窗口跑了这些场景：被动掉登录亮告警 → 补登录撤告警 →
  走设置页真实入口删缓存（含确认框）得到"缓存已删除，已退出登录" →
  回归三条老路径（主动退出、会话过期、启动自检）措辞不变。
  这样测界面状态的办法以后可以照抄。

- **数据中心「更新数据」按钮的 tooltip 改成实话**：它原来写"重新加载本站数据"，
  但实现只做本地重算、根本不联网（用户确认过：**保持本地重算**，只把文案改准）。
  现在的提示语是"按本地已加载的数据重算一遍（不发请求），所有页面一起刷新；
  与站点交互结束后会自动刷新"。按钮名仍叫"更新数据"。
