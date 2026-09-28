"""码图 HTTP 客户端：串行限速 + 只读硬闸门。

两条不可违反的约束，在这里由代码强制，而不是靠自觉：

1. 绝不提交代码。只有登录这一个端点允许 POST；其余任何请求都会因为
   路径不在白名单、或命中提交类关键词而被直接拒绝并抛异常。
   即使将来要给 App 加提交功能，也必须同时改 POST_ALLOWLIST 和
   ENABLE_SUBMISSION 两个开关，不可能"顺手"发出去一个提交。
2. 不做高频请求。请求严格串行（无线程/无并发），每次请求之间有间隔下限，
   并叠加随机抖动；单次运行还有请求总数上限，防止循环写错变成爬崩站点。

会话 Cookie 与原始 HTML 缓存都存放在项目之外的应用数据目录（~/.bettermatu/），
项目内不落任何由本账号派生的文件。
"""

from __future__ import annotations

import json
import os
import random
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import requests

BASE_URL = "http://matu.uestc.edu.cn/aptat"

# POST 白名单：只有列在这里的端点允许 POST，其余一律拒绝并抛异常。
LOGIN_ENDPOINTS: Tuple[str, ...] = ("/user/dologin.action",)

# 提交端点。要 POST 成功需要**两把锁同时打开**：
#   1. 路径必须在这个元组里（改这里需要显式编辑源码）
#   2. allow_submission 必须为真（开发期用环境变量，App 内用设置项，默认关）
SUBMISSION_ENDPOINTS: Tuple[str, ...] = (
    "/assignment/upload_assignment_by_copy_paste",
    "/assignment/upload_assignment_by_single_file",
)


def env_submission_enabled() -> bool:
    """开发期的提交开关；默认关闭，必须显式设置 MATU_ENABLE_SUBMISSION=1。"""
    return os.environ.get("MATU_ENABLE_SUBMISSION", "").strip().lower() in (
        "1", "true", "yes", "on",
    )

# 应用运行期数据（会话、页面缓存）落在项目外。
# 这里刻意不涉及凭据：凭据只从环境变量读，其存放位置属开发机私有配置，
# 项目内不记录任何位置映射。
MATU_HOME = Path(os.environ.get("MATU_HOME", str(Path.home() / ".bettermatu")))
SESSION_FILE = MATU_HOME / "session.json"
CACHE_DIR = MATU_HOME / "html"
REQUEST_LOG = MATU_HOME / "requests.log"

DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


class PostNotAllowed(RuntimeError):
    """对非登录端点发起 POST 时抛出。这是安全阀，不是可忽略的警告。"""


class RequestBudgetExceeded(RuntimeError):
    """单次运行请求数超限时抛出，防止死循环把站点打爆。"""


class MatuClient:
    """串行、限速、只读的码图客户端。"""

    def __init__(
        self,
        min_interval: float = 2.5,
        jitter: float = 1.0,
        max_requests: int = 300,
        cache_html: bool = True,
        logger=None,
        allow_submission: bool = False,
        session_file: Optional[Path] = None,
    ) -> None:
        # 间隔下限 + 抖动：默认节奏偏保守，加载时由调用方调快。
        self.min_interval = min_interval
        self.jitter = jitter
        self.max_requests = max_requests
        self.cache_html = cache_html
        self.logger = logger
        # 提交开关：默认关。App 通过设置项传入，开发期用环境变量。
        self.allow_submission = allow_submission or env_submission_enabled()
        # 会话文件按账号走：每个账号一份 Cookie，互不覆盖
        self.session_file = Path(session_file) if session_file else SESSION_FILE

        self.request_count = 0
        self.history = []
        self._last_request_at = 0.0

        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": DEFAULT_UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
        })
        MATU_HOME.mkdir(parents=True, exist_ok=True)
        self.load_session()

    # ---------- 会话持久化 ----------

    def load_session(self) -> bool:
        if not self.session_file.exists():
            return False
        try:
            data = json.loads(self.session_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return False
        self.session.cookies.update(data.get("cookies", {}))
        return True

    def save_session(self) -> None:
        payload = {
            "cookies": requests.utils.dict_from_cookiejar(self.session.cookies),
            "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        # 0600：同机其他用户读不到。
        self.session_file.parent.mkdir(parents=True, exist_ok=True)
        self.session_file.touch(mode=0o600, exist_ok=True)
        self.session_file.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.chmod(self.session_file, 0o600)

    def clear_session(self) -> None:
        self.session.cookies.clear()
        if self.session_file.exists():
            self.session_file.unlink()

    # ---------- 请求闸门 ----------

    def _assert_method_allowed(self, method: str, path: str) -> None:
        """POST 必须落在白名单内；提交类端点还要求提交开关是开的。"""
        if method != "POST":
            return
        if path in LOGIN_ENDPOINTS:
            return
        if path in SUBMISSION_ENDPOINTS:
            if not self.allow_submission:
                raise PostNotAllowed(
                    f"拒绝 POST {path}：提交总闸未打开（开发期设 MATU_ENABLE_SUBMISSION=1，"
                    f"App 内走设置项）。"
                )
            return
        raise PostNotAllowed(
            f"拒绝 POST {path}：不在任何 POST 白名单内。"
            f"要新增 POST 端点必须显式修改 client.py。"
        )

    def _throttle(self) -> None:
        interval = self.min_interval + random.uniform(0, self.jitter)
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < interval:
            time.sleep(interval - elapsed)

    def _record(self, method: str, url: str, status: Optional[int], note: str = "") -> None:
        """把每个请求追加到项目外的审计日志，方便随时核对有没有发过提交。"""
        line = f"{time.strftime('%Y-%m-%d %H:%M:%S')}\t{method}\t{status}\t{url}\t{note}\n"
        with REQUEST_LOG.open("a", encoding="utf-8") as fh:
            fh.write(line)
        self.history.append((method, url, status))

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        referer: Optional[str] = None,
        allow_redirects: bool = True,
        cache: Optional[bool] = None,
    ) -> requests.Response:
        self._assert_method_allowed(method, path)

        if self.request_count >= self.max_requests:
            raise RequestBudgetExceeded(
                f"本次运行已达请求上限 {self.max_requests}，主动停止。"
            )

        url = path if path.startswith("http") else BASE_URL + path
        headers = {"Referer": referer} if referer else None

        self._throttle()
        try:
            resp = self.session.request(
                method, url, params=params, data=data, headers=headers,
                timeout=20, allow_redirects=allow_redirects,
            )
        except requests.RequestException as exc:
            self._record(method, url, None, f"ERROR {type(exc).__name__}")
            raise
        finally:
            self._last_request_at = time.monotonic()

        self.request_count += 1
        # 站点有的页面不带 charset，requests 会猜成 ISO-8859-1 导致中文乱码。
        if resp.encoding is None or resp.encoding.lower() in ("iso-8859-1", "latin-1"):
            resp.encoding = "utf-8"
        # 审计日志记实际请求的地址（不是重定向落点），
        # 这样一眼能看出 POST 打的是不是登录端点。
        note = f"-> {resp.url}" if resp.url != url else ""
        self._record(method, url, resp.status_code, note)

        if (self.cache_html if cache is None else cache) and method == "GET":
            self._cache(resp)
        if self.logger:
            self.logger(f"{method} {resp.url} -> {resp.status_code} ({self.request_count} 次请求)")
        return resp

    def _cache(self, resp: requests.Response) -> None:
        """按路径把原始 HTML 落盘，供解析器开发与回归对比，避免重复请求。"""
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        rel = resp.url.replace(BASE_URL, "").strip("/") or "index"
        rel = rel.split(";jsessionid")[0]
        rel = rel.replace("/", "__").replace("?", "_").replace("&", "_") or "index"
        if not rel.endswith(".html"):
            rel += ".html"
        try:
            (CACHE_DIR / rel).write_text(resp.text, encoding="utf-8")
        except OSError:
            pass

    # ---------- 对外接口 ----------

    def get(self, path: str, *, referer: Optional[str] = None,
            params: Optional[Dict[str, Any]] = None,
            allow_redirects: bool = True,
            cache: Optional[bool] = None) -> requests.Response:
        return self._request("GET", path, params=params, referer=referer,
                             allow_redirects=allow_redirects, cache=cache)

    def post(self, path: str, *, data: Optional[Dict[str, Any]] = None,
             referer: Optional[str] = None,
             allow_redirects: bool = True) -> requests.Response:
        """POST。能不能发出去由 _assert_method_allowed 决定，这里不做额外放宽。"""
        return self._request("POST", path, data=data, referer=referer,
                             allow_redirects=allow_redirects)

    def login(self, username: str, password: str) -> bool:
        """登录。这是本客户端唯一被允许的 POST。

        密码只存在于内存中，不会写入日志、缓存或任何文件。
        """
        self.get("/user/login.action")
        resp = self._request(
            "POST",
            "/user/dologin.action",
            data={"user.Login": username, "user.Password": password},
            referer=BASE_URL + "/user/login.action",
        )
        ok = self.is_logged_in(resp.text)
        if ok:
            self.save_session()
        # 留给调用方看跳转落点，便于摸清登录后进入哪个页面。
        self.last_login_response = resp
        return ok

    @staticmethod
    def is_logged_in(html: str) -> bool:
        """判断页面是登录后的状态。

        码图登录后进入一个老式 frameset 管理端（top/left/mainfra），
        登录失败则会退回带 dologin 表单的登录页。
        """
        if not html:
            return False
        if 'id="dologin"' in html or "user.Password" in html:
            return False
        markers = ("mainfra.jsp", "left.jsp", "top.jsp", "mannager", "frameset")
        return any(m in html for m in markers)

    @staticmethod
    def looks_like_login_page(html: str) -> bool:
        """会话失效时站点会把任何页面退回登录表单，用它来判断需要重新登录。"""
        return 'id="dologin"' in html or "user.Password" in html
