"""夸克分享转存适配层。

只在运行时接收 QuarkDisk 的 Cookie；不持久化、不展示、不记录 Cookie、分享提取码或 stoken。
"""
from __future__ import annotations

import random
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import parse_qs, urlsplit

import requests

from app.log import logger


@dataclass
class QuarkShareLinkStatus:
    """夸克分享链接的最小状态描述。"""

    is_valid: bool = False
    error_message: str = ""
    file_count: int = 0
    share_info: Dict[str, Any] = field(default_factory=dict)

    @property
    def status_text(self) -> str:
        return "有效" if self.is_valid else (self.error_message or "未知状态")


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
    SHARE_PAGE_BASE_URL = "https://drive-h.quark.cn/1/clouddrive"
    SHARE_SAVE_BASE_URL = "https://drive.quark.cn/1/clouddrive"
    _SHARE_URL_RE = re.compile(
        r"(?:https?://pan\.quark\.cn/s/|quark://share/)([A-Za-z0-9]+)",
        re.IGNORECASE,
    )
    _PASSWORD_RE = re.compile(
        r"(?:提取码|密码|passcode|code)\s*[：:=]?\s*([A-Za-z0-9]{4,16})",
        re.IGNORECASE,
    )
    _RISK_MARKERS = ("封禁", "风控", "限制", "频繁")

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
        if not isinstance(response, dict):
            return False
        return (
            response.get("status") in (None, 0, "0", 200, "200", 2000000, "2000000")
            and response.get("code") in (None, 0, "0", 200, "200")
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
                        "status": body.get("status", response.status_code),
                        "code": body.get("code", response.status_code),
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

    def _get_share_token(self, info: Dict[str, str]) -> str:
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
                "support_visit_limit_private_share": True,
            },
            base_url=self.SHARE_PAGE_BASE_URL,
        )
        token = str((self._data(result) or {}).get("stoken") or "")
        if not self._is_success(result) or not token:
            raise RuntimeError(str(result.get("message") or "获取夸克分享访问令牌失败"))
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
            },
            base_url=self.SHARE_PAGE_BASE_URL,
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
        is_dir = bool(raw.get("dir") or raw.get("is_dir") or file_type in (0, "0"))
        if file_type not in (None, 0, "0"):
            is_dir = False
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

    def check_share_status(self, share_url: str, password: str = "") -> QuarkShareLinkStatus:
        status = QuarkShareLinkStatus()
        info = self.extract_share_info(share_url, password)
        if not info:
            status.error_message = "无效的夸克分享链接格式"
            return status
        try:
            stoken = self._get_share_token(info)
            result = self._get_share_page(info["share_id"], stoken, size=1)
            if not self._is_success(result):
                status.error_message = str(result.get("message") or "夸克分享不可用")
                return status
            data = self._data(result)
            status.is_valid = True
            status.file_count = int(data.get("total") or 0) if isinstance(data, dict) else 0
            status.share_info = {"share_title": str(data.get("title") or "") if isinstance(data, dict) else ""}
        except Exception as exc:
            status.error_message = str(exc) or type(exc).__name__
        return status

    def list_share_files(
        self, share_url: str, password: str = "", max_depth: int = 3, target_season: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """递归读取分享树，保存 file-id 与仅运行期有效的文件令牌。"""
        info = self.extract_share_info(share_url, password)
        if not info:
            return []
        try:
            stoken = self._get_share_token(info)
            output: List[Dict[str, Any]] = []
            file_tokens: Dict[str, Dict[str, str]] = {}
            stack: List[Tuple[str, int, List[Dict[str, Any]]]] = [("0", 1, output)]
            while stack:
                parent_id, depth, target = stack.pop()
                page = 1
                while True:
                    result = self._get_share_page(info["share_id"], stoken, parent_id, page)
                    if not self._is_success(result):
                        raise RuntimeError(str(result.get("message") or "读取夸克分享目录失败"))
                    raw_items = self._page_items(self._data(result))
                    for raw in raw_items:
                        item = self._to_file(raw)
                        if not item:
                            continue
                        target.append(item)
                        if item["is_dir"] and depth < max(1, min(int(max_depth), 5)):
                            children: List[Dict[str, Any]] = []
                            item["children"] = children
                            stack.append((item["id"], depth + 1, children))
                        elif not item["is_dir"]:
                            file_tokens[item["id"]] = {"token": item.pop("_share_fid_token", ""), "parent_id": parent_id}
                        else:
                            item.pop("_share_fid_token", None)
                    if len(raw_items) < 100:
                        break
                    page += 1
            with self._cache_lock:
                self._share_items[info["share_id"]] = file_tokens
            return output
        except Exception as exc:
            logger.warning(f"读取夸克分享文件失败：{type(exc).__name__}")
            return []

    def _resolve_directory(self, path: str, create: bool = True) -> Optional[str]:
        """逐级解析夸克个人网盘目录；仅在真实转存阶段调用。"""
        current_id = "0"
        for part in (value for value in str(path or "/").split("/") if value):
            result = self._request(
                "GET", "file/sort",
                params={"pdir_fid": current_id, "_page": 1, "_size": 100, "_sort": "file_name:asc"},
            )
            if not self._is_success(result):
                return None
            found = next(
                (
                    self._to_file(raw) for raw in self._page_items(self._data(result))
                    if (item := self._to_file(raw)) and item["is_dir"] and item["name"] == part
                ),
                None,
            )
            if found:
                current_id = found["id"]
                continue
            if not create:
                return None
            created = self._request(
                "POST", "file",
                json_data={"pdir_fid": current_id, "file_name": part, "dir_init_lock": False, "dir_path": ""},
            )
            if not self._is_success(created):
                return None
            item = self._to_file(self._data(created))
            if not item:
                # 目录创建存在短暂异步可见窗口，重新查询一次。
                time.sleep(1)
                return self._resolve_directory(path, create=False)
            current_id = item["id"]
        return current_id

    def _save_shared_files(self, info: Dict[str, str], stoken: str, file_ids: List[str], target_id: str, file_tokens: List[str]) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "fid_list": file_ids, "fid_token_list": file_tokens,
            "to_pdir_fid": target_id, "pwd_id": info["share_id"],
            "stoken": stoken, "pdir_fid": "0", "scene": "link",
        }
        return self._request("POST", "share/sharepage/save", json_data=payload, base_url=self.SHARE_SAVE_BASE_URL, retries=0)

    def _wait_for_task(self, task_id: str, timeout: int = 60) -> bool:
        deadline = time.monotonic() + max(5, min(int(timeout), 180))
        retry_index = 0
        while time.monotonic() < deadline:
            result = self._request("GET", "task", params={"task_id": task_id, "retry_index": retry_index})
            task_status = (self._data(result) or {}).get("status")
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
        if not self.list_share_files(share_url, password=password):
            return [], selected
        with self._cache_lock:
            cached = dict(self._share_items.get(info["share_id"], {}))
        tokens = [str((cached.get(file_id) or {}).get("token") or "") for file_id in selected]
        if not all(tokens):
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
        for offset in range(0, len(selected), step):
            batch = selected[offset:offset + step]
            token_batch = tokens[offset:offset + step]
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
