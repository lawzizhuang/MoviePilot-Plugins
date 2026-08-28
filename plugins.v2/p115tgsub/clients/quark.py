"""夸克分享转存适配层。

只在运行时接收 QuarkDisk 的 Cookie；不持久化、不展示、不记录 Cookie、分享提取码或 stoken。
"""
from __future__ import annotations

import random
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple
from urllib.parse import parse_qs, urlsplit

import requests

from app.log import logger


class QuarkShareAccessError(RuntimeError):
    """夸克分享访问失败；仅携带脱敏分类，不保留响应原文。"""

    def __init__(self, category: str) -> None:
        self.category = category
        super().__init__(category)


@dataclass
class QuarkShareLinkStatus:
    """夸克分享链接的最小状态描述。"""

    is_valid: bool = False
    error_message: str = ""
    error_category: str = ""
    file_count: int = 0
    share_info: Dict[str, Any] = field(default_factory=dict)

    @property
    def status_text(self) -> str:
        if self.is_valid:
            return "有效"
        messages = {
            "invalid_link": "分享链接格式无效",
            "share_expired": "分享已失效或不存在",
            "password_invalid": "访问码缺失或错误",
            "access_denied": "分享访问受限",
            "risk_limited": "账号或分享访问受限",
            "network_error": "网络请求失败",
            "api_error": "夸克接口异常",
        }
        return messages.get(self.error_category, self.error_message or "未知状态")


class _RateLimiter:
    """单账号串行节流，避免分享读取/保存瞬时高频触发风控。"""

    def __init__(self, min_interval: float = 1.2, jitter_ratio: float = 0.2) -> None:
        self._min_interval = max(0.2, min(float(min_interval), 10.0))
        self._jitter_ratio = max(0.0, min(float(jitter_ratio), 0.5))
        self._last_request = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            interval = self._min_interval * (
                1 + random.uniform(-self._jitter_ratio, self._jitter_ratio)
            )
            wait_seconds = interval - (time.monotonic() - self._last_request)
            if wait_seconds > 0:
                time.sleep(wait_seconds)
            self._last_request = time.monotonic()


class QuarkShareClient:
    """夸克公开分享的只读校验与指定文件转存客户端。"""

    DRIVE_PC_BASE_URL = "https://drive-pc.quark.cn/1/clouddrive"
    SHARE_PAGE_BASE_URL = DRIVE_PC_BASE_URL
    SHARE_SAVE_BASE_URL = DRIVE_PC_BASE_URL
    _SHARE_URL_RE = re.compile(
        r"(?:https?://pan\.quark\.cn/s/|quark://share/)([A-Za-z0-9]+)",
        re.IGNORECASE,
    )
    _PASSWORD_RE = re.compile(
        r"(?:提取码|访问码|密码|passcode|code)\s*[：:=]?\s*([A-Za-z0-9]{4,16})",
        re.IGNORECASE,
    )
    _RISK_MARKERS = ("封禁", "风控", "限制", "频繁")
    _PAGE_SIZE = 50

    def __init__(
        self,
        cookie: str,
        proxy: Any = None,
        timeout: int = 30,
        min_interval: float = 1.2,
        risk_cooldown: int = 1800,
    ) -> None:
        self._cookie = str(cookie or "").strip()
        self._timeout = max(5, min(int(timeout or 30), 60))
        self._risk_cooldown = max(300, min(int(risk_cooldown or 1800), 86400))
        self._proxies = (
            proxy
            if isinstance(proxy, dict)
            else ({"http": proxy, "https": proxy} if proxy else None)
        )
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            "Referer": "https://pan.quark.cn/",
            "Origin": "https://pan.quark.cn",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        })
        self._rate_limiter = _RateLimiter(min_interval=min_interval)
        self._share_tokens: Dict[str, Tuple[str, float]] = {}
        self._share_items: Dict[str, Dict[str, Dict[str, str]]] = {}
        self._cache_lock = threading.RLock()
        self._transfer_blocked_until = 0.0
        self._transfer_block_reason = ""
        self._api_call_count = 0

    @property
    def transfer_risk_blocked(self) -> bool:
        return time.monotonic() < self._transfer_blocked_until

    @staticmethod
    def extract_share_info(share_url: str, password: str = "") -> Dict[str, str]:
        """提取分享 ID 与提取码；仅返回给运行内存调用方。"""
        value = str(share_url or "").strip()
        match = QuarkShareClient._SHARE_URL_RE.search(value)
        if not match:
            return {}
        query = parse_qs(urlsplit(value).query)
        extracted_password = str(password or "").strip()
        if not extracted_password:
            for key in ("pwd", "passcode", "code"):
                values = query.get(key) or []
                if values and str(values[0]).strip():
                    extracted_password = str(values[0]).strip()
                    break
        if not extracted_password:
            code_match = QuarkShareClient._PASSWORD_RE.search(value)
            extracted_password = code_match.group(1) if code_match else ""
        return {"share_id": match.group(1), "password": extracted_password}

    @staticmethod
    def extract_password(text: str) -> str:
        """从频道消息文本提取提取码，供当前运行的候选使用。"""
        match = QuarkShareClient._PASSWORD_RE.search(str(text or ""))
        return match.group(1) if match else ""

    @staticmethod
    def _is_success(response: Any) -> bool:
        if not isinstance(response, dict) or not response:
            return False
        status = response.get("status")
        code = response.get("code")
        if status is None and code is None:
            return False
        return (
            status in (None, 0, "0", 200, "200", 2000000, "2000000")
            and code in (None, 0, "0", 200, "200")
        )

    @staticmethod
    def _data(response: Any) -> Any:
        return response.get("data") or {} if isinstance(response, dict) else {}

    def reset_api_call_count(self) -> None:
        self._api_call_count = 0

    def get_api_call_count(self) -> int:
        return self._api_call_count

    def _request(
        self,
        method: str,
        endpoint: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        base_url: Optional[str] = None,
        retries: int = 2,
    ) -> Dict[str, Any]:
        """仅对网络瞬态异常重试；HTTP/业务错误不盲目重放转存请求。"""
        if not self._cookie:
            return {"status": 401, "code": 401, "message": "夸克 Cookie 未配置", "data": {}}
        url = f"{(base_url or self.DRIVE_PC_BASE_URL).rstrip('/')}/{endpoint.lstrip('/')}"
        request_params = {
            "pr": "ucpro",
            "fr": "pc",
            "uc_param_str": "",
            "__t": int(time.time() * 1000),
            "__dt": random.randint(100, 9999),
        }
        request_params.update(params or {})
        headers = {"Cookie": self._cookie}
        delay = 0.5
        for attempt in range(max(0, min(int(retries), 3)) + 1):
            try:
                self._rate_limiter.wait()
                self._api_call_count += 1
                response = self._session.request(
                    method.upper(), url, params=request_params, json=json_data,
                    headers=headers, timeout=self._timeout, proxies=self._proxies,
                )
                if response.status_code >= 400:
                    try:
                        body = response.json()
                    except ValueError:
                        body = {}
                    return {
                        # HTTP 失败必须固定视为失败，不能让响应体内的业务字段覆盖状态。
                        "status": response.status_code,
                        "code": response.status_code,
                        "message": body.get("message") or body.get("msg") or f"HTTP {response.status_code}",
                        "data": body.get("data") or {},
                    }
                try:
                    return response.json() if response.text else {"status": 200, "code": 0, "data": {}}
                except ValueError:
                    return {"status": -1, "code": -1, "message": "夸克接口返回非 JSON 响应", "data": {}}
            except (requests.Timeout, requests.ConnectionError) as exc:
                if attempt >= retries:
                    logger.warning(f"夸克请求网络失败：{endpoint}（已停止重试）")
                    return {"status": -1, "code": -1, "message": type(exc).__name__, "data": {}}
                time.sleep(delay)
                delay *= 2
            except requests.RequestException as exc:
                logger.warning(f"夸克请求失败：{endpoint} - {type(exc).__name__}")
                return {"status": -1, "code": -1, "message": type(exc).__name__, "data": {}}
        return {"status": -1, "code": -1, "message": "请求失败", "data": {}}

    def check_login(self) -> bool:
        """验证凭据，不打印账号、Cookie 或响应内容。"""
        result = self._request("GET", "member")
        if self._is_success(result):
            logger.info("夸克登录验证成功（已复用 QuarkDisk 配置）")
            return True
        logger.error("夸克登录验证失败，请检查 QuarkDisk Cookie 是否有效")
        return False

    def _share_cache_key(self, info: Dict[str, str]) -> str:
        # 密码不进入日志；进程内缓存键不持久化。
        return f"{info.get('share_id', '')}\0{info.get('password', '')}"

    @classmethod
    def _classify_share_error(cls, result: Dict[str, Any]) -> str:
        """将夸克响应归为可观测的脱敏类别，绝不向日志透传服务端原文。"""
        status = str(result.get("status") or "")
        code = str(result.get("code") or "")
        message = str(result.get("message") or result.get("msg") or "").casefold()
        text = f"{status} {code} {message}"
        if status == "-1" or code == "-1":
            return "network_error"
        if any(marker in text for marker in cls._RISK_MARKERS):
            return "risk_limited"
        if any(marker in text for marker in ("提取码", "访问码", "密码", "passcode", "password", "pwd")):
            return "password_invalid"
        if any(marker in text for marker in ("不存在", "已失效", "已取消", "已删除", "过期", "not found", "expired")):
            return "share_expired"
        if any(marker in text for marker in ("无权限", "权限", "拒绝", "access denied", "forbidden", "unauthorized")):
            return "access_denied"
        return "api_error"

    def _get_share_token(self, info: Dict[str, str]) -> str:
        """获取分享访问令牌；分享校验失败不重试，避免单个候选长时间阻塞同步。"""
        cache_key = self._share_cache_key(info)
        now = time.monotonic()
        with self._cache_lock:
            cached = self._share_tokens.get(cache_key)
            if cached and cached[1] > now:
                return cached[0]
        result = self._request(
            "POST", "share/sharepage/token",
            json_data={
                "pwd_id": info["share_id"],
                "passcode": info.get("password") or "",
            },
            base_url=self.SHARE_PAGE_BASE_URL,
            retries=0,
        )
        token = str((self._data(result) or {}).get("stoken") or "")
        if not self._is_success(result) or not token:
            raise QuarkShareAccessError(self._classify_share_error(result))
        with self._cache_lock:
            self._share_tokens[cache_key] = (token, now + 600)
        return token

    def _get_share_page(
        self, share_id: str, stoken: str, parent_id: str = "0", page: int = 1, size: int = 100
    ) -> Dict[str, Any]:
        return self._request(
            "GET", "share/sharepage/detail",
            params={
                "pwd_id": share_id, "stoken": stoken, "pdir_fid": parent_id,
                "force": "0", "_page": page, "_size": size,
                "_fetch_total": "1", "_sort": "file_type:asc,file_name:asc",
                "ver": "2", "_fetch_banner": "0", "_fetch_share": "0",
                "fetch_share_full_path": "0",
            },
            base_url=self.SHARE_PAGE_BASE_URL,
            retries=0,
        )

    @staticmethod
    def _to_file(raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not isinstance(raw, dict):
            return None
        file_id = raw.get("fid") or raw.get("file_id") or raw.get("id")
        name = str(raw.get("file_name") or raw.get("name") or "").strip()
        if file_id in (None, "") or not name:
            return None
        file_type = raw.get("file_type")
        # QAS 以 dir 字段作为目录真值；仅在接口未提供 dir/is_dir 时，才以
        # 已验证的 file_type=0 作为兼容兜底，绝不让 file_type 覆盖显式 dir。
        if raw.get("dir") is not None or raw.get("is_dir") is not None:
            is_dir = bool(raw.get("dir") or raw.get("is_dir"))
        else:
            is_dir = file_type in (0, "0")
        return {
            "id": str(file_id), "name": name, "is_dir": is_dir,
            "size": 0 if is_dir else int(raw.get("size") or raw.get("file_size") or 0),
            "sha1": str(raw.get("sha1") or ""),
            "_share_fid_token": str(raw.get("share_fid_token") or ""),
        }

    @staticmethod
    def _page_items(data: Any) -> List[Dict[str, Any]]:
        if not isinstance(data, dict):
            return []
        for key in ("list", "files", "items", "records"):
            value = data.get(key)
            if isinstance(value, list):
                return value
        return []

    @classmethod
    def _response_total(cls, response: Dict[str, Any]) -> Optional[int]:
        data = cls._data(response)
        metadata = response.get("metadata") if isinstance(response, dict) else None
        for value in (
            (metadata or {}).get("_total") if isinstance(metadata, dict) else None,
            data.get("total") if isinstance(data, dict) else None,
        ):
            try:
                total = int(value)
            except (TypeError, ValueError):
                continue
            if total >= 0:
                return total
        return None

    @classmethod
    def _has_more_pages(cls, response: Dict[str, Any], received: int, loaded: int, page_size: int) -> bool:
        """优先使用夸克返回的总数分页；空页必须终止，避免异常总数导致无限翻页。"""
        if received <= 0:
            return False
        total = cls._response_total(response)
        return loaded < total if total is not None else received >= page_size

    def check_share_status(self, share_url: str, password: str = "") -> QuarkShareLinkStatus:
        status = QuarkShareLinkStatus()
        info = self.extract_share_info(share_url, password)
        if not info:
            status.error_category = "invalid_link"
            return status
        started_at = time.monotonic()
        try:
            logger.info("夸克分享校验：正在获取访问令牌")
            stoken = self._get_share_token(info)
            logger.info("夸克分享校验：访问令牌获取完成，正在读取分享目录")
            result = self._get_share_page(info["share_id"], stoken, size=1)
            if not self._is_success(result):
                status.error_category = self._classify_share_error(result)
                return status
            data = self._data(result)
            status.is_valid = True
            status.file_count = self._response_total(result) or 0
            status.share_info = {"share_title": str(data.get("title") or "") if isinstance(data, dict) else ""}
            logger.info(f"夸克分享校验完成：{time.monotonic() - started_at:.1f} 秒")
        except QuarkShareAccessError as exc:
            status.error_category = exc.category
        except Exception:
            status.error_category = "api_error"
        return status

    @staticmethod
    def _should_skip_season_dir(dir_name: str, target_season: int) -> bool:
        patterns = [
            r"[Ss]eason\s*(\d+)", r"[Ss](\d+)", r"第\s*(\d+)\s*季",
            r"第\s*([一二三四五六七八九十]+)\s*季",
        ]
        cn_num_map = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
                      "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
        for pattern in patterns:
            match = re.search(pattern, str(dir_name or ""), re.IGNORECASE)
            if not match:
                continue
            value = match.group(1)
            try:
                found_season = cn_num_map[value] if value in cn_num_map else int(value)
            except ValueError:
                continue
            return found_season != int(target_season)
        return False

    def list_share_files(
        self, share_url: str, password: str = "", max_depth: int = 3, target_season: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """递归读取分享树，保存 file-id 与仅运行期有效的文件令牌。"""
        info = self.extract_share_info(share_url, password)
        if not info:
            return []
        try:
            started_at = time.monotonic()
            logger.info("夸克分享目录读取：开始")
            stoken = self._get_share_token(info)
            output: List[Dict[str, Any]] = []
            file_tokens: Dict[str, Dict[str, str]] = {}
            stack: List[Tuple[str, int, List[Dict[str, Any]]]] = [("0", 1, output)]
            while stack:
                parent_id, depth, target = stack.pop()
                page = 1
                loaded = 0
                while True:
                    result = self._get_share_page(
                        info["share_id"], stoken, parent_id, page, self._PAGE_SIZE
                    )
                    if not self._is_success(result):
                        raise RuntimeError("读取夸克分享目录失败")
                    raw_items = self._page_items(self._data(result))
                    for raw in raw_items:
                        item = self._to_file(raw)
                        if not item:
                            continue
                        target.append(item)
                        if item["is_dir"] and depth < max(1, min(int(max_depth), 5)):
                            if target_season and self._should_skip_season_dir(item["name"], target_season):
                                item.pop("_share_fid_token", None)
                                continue
                            children: List[Dict[str, Any]] = []
                            item["children"] = children
                            stack.append((item["id"], depth + 1, children))
                        elif not item["is_dir"]:
                            file_tokens[item["id"]] = {"token": item.pop("_share_fid_token", ""), "parent_id": parent_id}
                        else:
                            item.pop("_share_fid_token", None)
                    if not self._has_more_pages(result, len(raw_items), loaded + len(raw_items), self._PAGE_SIZE):
                        break
                    loaded += len(raw_items)
                    page += 1
            with self._cache_lock:
                self._share_items[self._share_cache_key(info)] = file_tokens
            logger.info(f"夸克分享目录读取完成：{len(file_tokens)} 个文件，耗时 {time.monotonic() - started_at:.1f} 秒")
            return output
        except Exception as exc:
            logger.warning(f"读取夸克分享文件失败：{type(exc).__name__}")
            return []

    def _list_personal_directory(self, parent_id: str) -> Optional[List[Dict[str, Any]]]:
        """分页读取夸克个人网盘单层目录；接口失败返回 None。"""
        output: List[Dict[str, Any]] = []
        page = 1
        loaded = 0
        while True:
            result = self._request(
                "GET", "file/sort",
                params={"pdir_fid": parent_id, "_page": page, "_size": self._PAGE_SIZE, "_sort": "file_name:asc"},
            )
            if not self._is_success(result):
                return None
            raw_items = self._page_items(self._data(result))
            for raw in raw_items:
                item = self._to_file(raw)
                if item:
                    output.append(item)
            if not self._has_more_pages(result, len(raw_items), loaded + len(raw_items), self._PAGE_SIZE):
                break
            loaded += len(raw_items)
            page += 1
        return output

    @staticmethod
    def _normalize_directory_path(path: str) -> str:
        """标准化夸克绝对目录路径，供 path_list 与 mkdir 使用。"""
        parts = [part for part in str(path or "").replace("\\", "/").split("/") if part]
        return "/" + "/".join(parts) if parts else "/"

    def _get_path_entry(self, path: str) -> Optional[Dict[str, Any]]:
        """按完整绝对路径查询个人网盘目录/文件 FID。"""
        normalized_path = self._normalize_directory_path(path)
        if normalized_path == "/":
            return {"fid": "0", "file_path": "/", "dir": True}
        result = self._request(
            "POST", "file/info/path_list",
            json_data={"file_path": [normalized_path], "namespace": "0"},
        )
        if not self._is_success(result):
            return None
        data = self._data(result)
        entries = data if isinstance(data, list) else self._page_items(data)
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            entry_path = self._normalize_directory_path(str(entry.get("file_path") or ""))
            if entry_path == normalized_path and entry.get("fid") not in (None, ""):
                return entry
        return None

    def _resolve_directory(self, path: str, create: bool = True) -> Optional[str]:
        """按 QAS 契约解析完整路径，缺失时一次性创建完整目录树。"""
        normalized_path = self._normalize_directory_path(path)
        existing = self._get_path_entry(normalized_path)
        if existing:
            return str(existing["fid"])
        if not create or normalized_path == "/":
            return None
        created = self._request(
            "POST", "file",
            json_data={
                "pdir_fid": "0", "file_name": "", "dir_path": normalized_path,
                "dir_init_lock": False,
            },
        )
        if not self._is_success(created):
            logger.warning("夸克完整目标目录创建失败")
            return None
        data = self._data(created)
        if isinstance(data, dict) and data.get("fid") not in (None, ""):
            return str(data["fid"])
        # 接口存在短暂可见窗口；只读回查一次，避免提交未知目录 FID。
        time.sleep(1)
        entry = self._get_path_entry(normalized_path)
        return str(entry["fid"]) if entry else None

    def get_pid_by_path(self, path: str, mkdir: bool = True) -> Any:
        """兼容 FileMatcher 目录检查：返回目录 ID，不存在时返回 -1。"""
        try:
            directory_id = self._resolve_directory(path, create=bool(mkdir))
        except Exception as exc:
            logger.warning(f"夸克解析目录失败：{type(exc).__name__}")
            return -1
        return directory_id or -1

    def list_files(self, path: str) -> List[Dict[str, Any]]:
        """列出夸克个人网盘目录内容，返回与 115 兼容的字段（n/fid/size）。"""
        parent_id = self._resolve_directory(path, create=False)
        if not parent_id:
            return []
        entries = self._list_personal_directory(parent_id)
        if entries is None:
            return []
        output: List[Dict[str, Any]] = []
        for item in entries:
            output.append({
                "n": item["name"],
                "fid": "0" if item["is_dir"] else item["id"],
                "size": int(item.get("size") or 0),
            })
        return output

    def confirm_files_exist(self, save_path: str, file_names: Iterable[str], retries: int = 3, interval: float = 2.0) -> Set[str]:
        """目标目录二次确认：转存成功与否以文件真实存在为准。"""
        wanted = set(str(value) for value in file_names if str(value))
        if not wanted:
            return set()
        attempts = max(1, min(int(retries), 6))
        delay = max(0.5, min(float(interval), 10.0))
        existing: Set[str] = set()
        for attempt in range(attempts):
            existing = set()
            for entry in self.list_files(save_path):
                name = str(entry.get("n") or "")
                if name in wanted:
                    existing.add(name)
            if wanted.issubset(existing):
                return existing
            if attempt + 1 < attempts:
                time.sleep(delay)
        return existing

    def _save_shared_files(
        self, info: Dict[str, str], stoken: str, file_ids: List[str], target_id: str,
        file_tokens: List[str],
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "fid_list": file_ids, "fid_token_list": file_tokens,
            "to_pdir_fid": target_id, "pwd_id": info["share_id"],
            "stoken": stoken, "pdir_fid": "0", "scene": "link",
        }
        return self._request(
            "POST", "share/sharepage/save", json_data=payload,
            params={"app": "clouddrive"},
            base_url=self.SHARE_SAVE_BASE_URL, retries=0,
        )

    def _wait_for_task(self, task_id: str, timeout: int = 60) -> bool:
        deadline = time.monotonic() + max(5, min(int(timeout), 180))
        retry_index = 0
        while time.monotonic() < deadline:
            result = self._request("GET", "task", params={"task_id": task_id, "retry_index": retry_index})
            if not self._is_success(result):
                return False
            task_status = (self._data(result) or {}).get("status")
            try:
                task_status = int(task_status)
            except (TypeError, ValueError):
                task_status = -1
            if task_status == 2:
                return True
            if task_status == 3:
                return False
            retry_index += 1
            time.sleep(1)
        return False

    def transfer_files_batch(
        self, share_url: str, file_ids: Iterable[str], save_path: str, *, password: str = "", batch_size: int = 5
    ) -> Tuple[List[str], List[str]]:
        """保存指定文件；遇明确风控信号后立即熔断，不继续消耗账号请求。"""
        selected = list(dict.fromkeys(str(value) for value in file_ids if str(value)))
        if not selected:
            return [], []
        if self.transfer_risk_blocked:
            logger.warning("夸克转存处于风控冷却期，已跳过本次保存")
            return [], selected
        info = self.extract_share_info(share_url, password)
        if not info:
            return [], selected
        cache_key = self._share_cache_key(info)
        with self._cache_lock:
            cached = dict(self._share_items.get(cache_key, {}))
        if not all((cached.get(file_id) or {}).get("token") for file_id in selected):
            if not self.list_share_files(share_url, password=password):
                return [], selected
            with self._cache_lock:
                cached = dict(self._share_items.get(cache_key, {}))

        records = [
            {
                "id": file_id,
                "token": str((cached.get(file_id) or {}).get("token") or ""),
                "parent_id": str((cached.get(file_id) or {}).get("parent_id") or "0"),
            }
            for file_id in selected
        ]
        if not all(record["token"] for record in records):
            logger.warning("夸克分享候选缺少临时文件令牌，已停止保存")
            return [], selected
        target_id = self._resolve_directory(save_path, create=True)
        if not target_id:
            logger.error("夸克目标目录不可用，已停止保存")
            return [], selected
        stoken = self._get_share_token(info)
        succeeded: List[str] = []
        failed: List[str] = []
        step = max(1, min(int(batch_size or 5), 20))
        for offset in range(0, len(records), step):
            batch_records = records[offset:offset + step]
            batch = [record["id"] for record in batch_records]
            token_batch = [record["token"] for record in batch_records]
            result = self._save_shared_files(info, stoken, batch, target_id, token_batch)
            task_id = str((self._data(result) or {}).get("task_id") or "")
            success = self._is_success(result) and (not task_id or self._wait_for_task(task_id))
            if success:
                succeeded.extend(batch)
                continue
            message = str(result.get("message") or result.get("msg") or "")
            failed.extend(batch)
            if any(marker in message for marker in self._RISK_MARKERS):
                self._transfer_block_reason = message or "账号转存受限"
                self._transfer_blocked_until = time.monotonic() + self._risk_cooldown
                failed.extend(selected[offset + len(batch):])
                logger.warning("夸克转存触发账号限制，已进入冷却期")
                break
        return succeeded, list(dict.fromkeys(failed))
