# 码图站点接口摸底（matu.uestc.edu.cn）

摸清时间：2026-09-28。所有结论来自实际请求，来源分两类，**必须区分对待**：

- **已验证**：用 GET 请求真实访问过、拿到了预期内容。
- **仅读表单**：只读取了页面的 HTML 表单结构，**从未发送过该请求**。

本阶段（加载数据）**不允许调用任何提交类接口**。下面第 5 节列出的提交端点
全部属于"仅读表单"，是给后续桌面端实现留的接口说明，不是本阶段可动用的东西。

---

## 1. 站点概况

| 项 | 值 |
| --- | --- |
| 入口 | `http://matu.uestc.edu.cn/` → JS 跳 `/aptat` |
| 应用上下文 | `/aptat` |
| 服务端 | Apache-Coyote（Tomcat），**Java + Struts2 + JSP**，页面全服务端渲染 |
| 协议 | **纯 HTTP，无 HTTPS** |
| 会话 | `JSESSIONID` Cookie（`Path=/aptat`），URL 里也会重写成 `;jsessionid=xxx` |
| 界面骨架 | 老式 `<frameset>`：`top.jsp`（80px）+ `left.jsp`（213px）+ `mainfra.jsp` |
| 作者/年代 | 页面注释显示作者 Jhat，2011 年；页面总体是 2015 年前后的风格 |
| 网络 | 当前网络可直连；校外可能要校园网/VPN |

**没有 JSON API。** 所有数据都要从 HTML 里解析，所以解析规则集中放在
`src/matu/core/parsers.py`，站点改版时只改这一个文件。

站点**不支持中文输入输出**（官方文档明确要求程序内不得输出中文）。

---

## 2. 登录

**已验证。**

```http
GET  /aptat/user/login.action
POST /aptat/user/dologin.action;jsessionid=<ID>
     Content-Type: application/x-www-form-urlencoded

     user.Login=<账号>&user.Password=<密码>
```

- 表单 `id="dologin"`，只有两个字段：`user.Login`、`user.Password`（`maxlength=20`）。
- **没有验证码**，所以账号密码自动登录可行。
- 登录成功 → 302 跳到 `/aptat/user/welcome.action`，返回 frameset 管理端。
- 登录失败 → 退回登录页（含 `id="dologin"` 表单）。
- 判定方式：页面含 `dologin` 表单 = 未登录；含 `mainfra.jsp`/`frameset` = 已登录。
- 退出：`GET /aptat/user/logout`。

⚠️ 因为是明文 HTTP，密码在链路上不加密。这既不是我们引入的问题，也意味着
凭据不该在公共网络使用，且绝不能写进日志。

---

## 3. 导航结构（`left.jsp` 菜单，已验证）

```
课程中心    我的班级        GET /aptat/course/liststudentclass
            课程申请        GET /aptat/course/listallcourse
题目中心    题目总表        GET /aptat/task/listtotalvisibletask      ← 题库主入口
            搜索作业        GET /aptat/page/files/searchtask.jsp
            作业状态        GET /aptat/assignment/listassignment      ← 提交记录
            提交总结        GET /aptat/assignment/listassignmentgrade ← 按题汇总
个人管理    个人信息/修改密码  selfinfo.jsp / chpwd.jsp
系统帮助    相关资料        GET /aptat/user/list_server_files
            学生手册        GET /aptat/page/document/student_operation_guide.htm
            提交注意事项    GET /aptat/page/document/assignment_commit_attention.htm
```

---

## 4. 数据类接口（全部已验证，只读）

### 4.1 题库

```http
GET /aptat/task/listtotalvisibletask          # 第 1 页
GET /aptat/task/listtotaltask?page=N          # 第 N 页，共 22 页
```

表格列：`题目编号 | 名称 | 出题老师 | 语言要求 | 平台 | 编译器 | 编译类型 | 出题时间 | 操作`

- 每页 10 题，共 22 页（约 200+ 题）。
- 每行有指向详情的链接 `taskdetail?taskid=N`。

```http
GET /aptat/task/taskdetail?taskid=N
GET /aptat/task/taskdetail?taskid=N&taskGroupTask.id=M&taskGroup.id=G   # 从作业进入时
```

详情页内容：`<legend>` 是题名；表格里是题号、语言要求；**正文在 `<pre>` 里**
（原样保留空格缩进，完型填空类题目正文本身就是代码，格式不能丢）。

页面上有"上传作业"按钮，JS 跳到提交入口（见第 5 节）。

### 4.2 班级与作业

```http
GET /aptat/course/liststudentclass?page=N
```
班级行 → `作业列表` `liststudenttaskgroup?_class.id=<班级id>`、
`考试列表` `desktop_exam/list_student_desktop_exam?_class.id=<班级id>`。

当前账号实测数据：课程 `c语言`，班级 `2026软件设计思想与方法1`，班级 id `641`，分数 `7.0`。

```http
GET /aptat/task/liststudenttaskgroup?_class.id=641&page=N     # 作业列表
GET /aptat/task/listTaskGroup_Task?taskGroup.id=<作业id>       # 作业内题目
```

作业列表列：`编号 | 名称 | 总分比例 | 时间`。实测两次作业：
`8877 操作环境练习（权重 0.0）`、`8878 第1次上机（权重 0.1）`。

作业内题目列表列：`题目编号 | 名称 | 语言要求 | 允许提交次数 | 分值 | 详情`。
**`允许提交次数` 只在这个层级出现**，实测每道题都是 `100` —— 这就是你说的
"提交有 100 次限制"的来源，是**每题各自 100 次**。

每行两个动作链接：

- 查看题目信息 → `taskdetail?taskid=N&taskGroupTask.id=M&taskGroup.id=G`
- 查看已提交情况 → `listttudenttaskgrouptaskassignmentforstudent?taskGroupTask.id=M`
  （注意路径里 `listttudent` 是站点自己的拼写错误，三个 t，照抄不能改）

### 4.3 提交记录

```http
GET /aptat/assignment/listassignment?page=N       # 全部提交记录，实测共 4 页
GET /aptat/assignment/listassignment?taskid=N     # 只看某题
```

列：`题目编号 | 名称 | 提交语言 | 时间 | 状态 | 分数 | 详情`。
行内链接：

- 查看 → `GET /aptat/assignment/scoredetail?assignmentid=<id>`
- 下载 → `GET /aptat/file/downloadassignmentfile?assignmentid=<id>`

```http
GET /aptat/assignment/scoredetail?assignmentid=<id>
```
这是"查看上传结果"的核心数据源，正文形如：

```
扣分:100
When test group(1) step(1),the input is (),the real output is not right.
```

即**扣分分值 + 评测失败原因**（哪个测试组、第几步、输入是什么、为什么错）。

```http
GET /aptat/assignment/listassignmentgrade?page=N   # 提交总结，按题聚合，实测共 2 页
```

### 4.4 其他已知端点

| 端点 | 说明 |
| --- | --- |
| `GET /aptat/user/list_server_files` | 相关资料下载 |
| `GET /aptat/desktop_exam/list_student_desktop_exam?_class.id=N` | 考试列表（有独立的考试模块，本次未深入） |
| `POST /aptat/assignment/delete_student_answers` | 删除某次提交，**只读表单，从未调用** |
| `POST /aptat/assignment/addcomment?assignmentid=N` | 给提交加评论，**只读表单，从未调用** |

---

## 5. 提交接口（✅ 已实测验证）

验证方式：在 `操作环境练习 / hello world`（taskGroupTask.id=45334）上真实提交了一次
输出 `world` 的正确代码。该一次性授权由用户明确给出，证据留在
`data/submit_probe/`，脚本 `tools/submit_once.py` 跑完即自我封禁（标记文件防重复）。

从题目详情页的"上传作业"进入：

```http
GET /aptat/assignment/upload?task.id=<题目id>&taskGroupTask.id=<作业内题目id>&taskGroup.id=<作业id>
```

返回一个二选一页面，提供**两种提交方式**：

**方式 1 —— 源码内容直接提交（App 用这条）**

```http
POST /aptat/assignment/upload_assignment_by_copy_paste
     taskGroupTask.id=<作业内题目id>    # 从题库提交时留空
     taskGroup.id=<作业id>              # 从题库提交时留空
     task.id=<题目id>
     task.name=<题名>
     sourcecode=<源码正文>              # textarea
     Submit=提交
```

**实测行为（这些不实测是猜不出来的）：**

- **不跳转**。直接返回 `200`，正文是一个小页面，可见文本就一句：
  **"上传成功！查看状态"**。所以判断提交成功必须看正文里有没有"上传成功"，
  只看状态码会把错误页也当成成功。
- **评测是同步的**：POST 本身耗时约 **3.7 秒**，返回时已经评完。
- 成功页的"确定"按钮指向这道作业题的提交历史：
  `/aptat/assignment/listttudenttaskgrouptaskassignmentforstudent?taskGroupTask.id=<id>`
  （页面里是 `onclick="window.location.href='...'"`，可从正文抠出）

**方式 2 —— 源文件上传提交**（`POST /assignment/upload_assignment_by_single_file`，
multipart，字段 `fileUpload`；页面原文写"单个源文件（.c、.cpp）上传"）。
**未实测**，App 不使用——代码本来就在编辑器里，走方式 1 更直接。

### 提交后去哪里取结果（已验证）

提交后 `taskid=N` 的记录会多出一条，`assignment_id` 全局递增，
所以**提交前先记下当前最大 assignment_id，提交后取比它大的那条**，
就不会把历史记录误当成这次的结果：

```http
GET /aptat/assignment/listassignment?taskid=<题目id>            # 找新记录，拿 assignment_id
GET /aptat/assignment/scoredetail?assignmentid=<assignment_id>  # 拿扣分与失败原因
```

**满分时 `scoredetail` 页面是空的**（实测满分记录返回空正文），
界面必须显示成"满分，无扣分"而不是一个空框。

### 作业内提交 vs 题库提交，记录归属不同（容易踩坑）

同一个第 1 题，从"操作环境练习"作业里提交的记录挂在 `taskGroupTask.id=45334` 名下，
而从"题目总表"直接提交的记录**不在**这个列表里。所以：

- 从「我的班级 → 作业 → 题目」进入 → 提交必须带上 `taskGroupTask.id` 和 `taskGroup.id`
- 从「题目中心（题库）」进入 → 这两个字段留空

### 这条结论对 UI 很关键

平台自身只接受**一个源文件**或**粘贴一段源码**，不接受压缩包。
所以之前悬着的"编辑器要不要做多文件"有答案了：

- **编辑器做单文件就够了。** 每道题一个编辑区，提交走方式 1（粘贴源码）。
- "编译整个文件夹内容"指的是**服务器端**评测时的目录结构（老师预置
  `teacher_main` 等文件），学生端仍然只交一个文件。
- 官方文档里提到的"提交的压缩包中含有 myhead.h"，是**历史遗留说法**，
  与现在的两个提交表单不符，按表单为准。

**提交页的代码框永远是空的**（已实测 `204 完型填空`、`5 teacher_main`、
`4 整目录` 三种题型，`<textarea name="sourcecode">` 均为 0 字符）。
站点不会预填任何模板或骨架，所以编辑器不能指望从提交页拿初始代码 ——
这是 App 需要补的价值：把题面里的代码骨架一键带进编辑区。

---

## 6. 三种编译类型（全量 358 题实测分布）

| 编译类型 | 题目数 | 含义 | 提交要求 |
| --- | --- | --- | --- |
| `编译整个文件夹内容` | 138 | 服务器端整目录编译 | 学生写完整程序（含 main） |
| `完型填空` | 119 | 补全给定残缺代码 | 题面给出"部分代码"，学生补全后提交完整可编译源码 |
| `编译整个文件夹内容（老师提供teacher_main作为入口函数）` | 101 | 老师提供 `teacher_main` 作入口 | 学生**只写 main 以外的函数实现**，不得自带 main |

语言要求：C 42 题、C++ 316 题。平台/编译器：全部 `Windows / VC`。

**完型填空的骨架在题目描述里，不在别处。** 实测题目详情页的 `<pre>` 正文就
包含完整的残缺代码（含缩进），形如"部分代码如下所示：… 部分代码已给出，
请补充完整。"，页面里没有任何模板或附件下载链接。所以：

- 题目描述必须**原样保留空白与缩进**（解析器就是这么做的），
  否则代码骨架会变成不可读的一坨。
- 编辑器要能并排显示"题面代码"和"我的代码"，或者支持把题面代码一键
  拷进编辑区再补全。
- 有 46 道完型填空题的描述短于 100 字符，属于简单题（如 #204
  "请在空格处添加相应代码，使程序打印出world即可"）。

官方提交注意事项里的硬性规则（对做题和校验都有用）：

- 提交未通过编译 = 0 分。
- 任意多余输出视为错误（`printf("请输入a：")` 这类提示语会直接判错）。
- 需要额外输入才能返回的程序（如 `system("pause")`）判错。
- `teacher_main` 类题目若自带 main，0 分。
- 不许 `freopen` 重定向、不许停屏语句。
- 不支持中文输入输出。

---

## 7. 加载时的坑（已实现规避）

1. **深嵌套表格**：取单元格必须 `recursive=False`，否则内层表格的 `<td>`
   会被拉平，表头行被误当成数据行。
2. **表头识别要精确匹配**：外层容器的单个大 `<td>` 文本是整页拼接，
   用子串匹配会误命中。
3. **`jsessionid` 出现在 URL 里**：缓存文件名要把它剥掉，否则每次是新文件。
4. **`listttudent` 三 t 拼写错误**：照抄，别"修正"。
5. **编码**：页面头声明 `charset=UTF-8`，但部分页面不带，requests 会猜成
   ISO-8859-1 导致乱码，客户端已强制按 UTF-8 解码。
6. **会话失效**：任何页面都可能被退回登录表单，用 `looks_like_login_page` 判定。

---

## 8. 当前项目的只读保障

不是为了自觉，是代码层面堵死：

- `src/matu/core/client.py` 里只有登录在 `POST_ALLOWLIST` 内，其余 POST 一律
  抛 `PostNotAllowed`。
- `SUBMISSION_HINTS`（`submit`/`upload`/`answer`/`judge`/`grade`/…）
  优先级高于白名单，命中即拒绝。
- 还有全局开关 `ENABLE_SUBMISSION = False`，将来要实现提交必须**同时**
  改这个开关和白名单，不可能"顺手"发出去一个提交。
- 每个请求追加到 `~/.bettermatu/requests.log`，随时可核对有没有 POST 过东西。
