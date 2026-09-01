"""4K Monitor 匿名免费磁力客户端。

仅按 MoviePilot 已确认的 TMDB ID 请求单一影视资源列表；仅处理免费、未锁定候选。
不登录、不使用 Cookie、不调用解锁接口，也不记录磁力或短期令牌。
"""
from __future__ import annotations

import json
import re
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode, urlsplit

import requests

from app.log import logger
from app.schemas.types import MediaType


class FourKMonitorClient:
    """受控读取 4K Monitor 精确 TMDB 资源，并仅解析匿名免费磁力。"""

    BASE_URL = "https://4kmonitor.org"
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131 Safari/537.36"
    )
    _DETAIL_PATH_RE = re.compile(r"^/detail/\d+(?:-[A-Za-z0-9-]+)?/?$", re.IGNORECASE)
    _LIST_PAGE_SIZE = 100

    def __init__(self, proxy: Any = None, timeout: int = 20, max_candidates: int = 3,
                 min_interval_seconds: int = 2) -> None:
        self.timeout = max(5, min(int(timeout or 20), 60))
        self.max_candidates = max(1, min(int(max_candidates or 3), 10))
        self.min_interval_seconds = max(1, min(int(min_interval_seconds or 2), 10))
        self._proxies = proxy if isinstance(proxy, dict) else ({"http": proxy, "https": proxy} if proxy else None)
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": self.USER_AGENT,
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept": "application/json, text/plain, */*",
            "Referer": f"{self.BASE_URL}/",
        })
        self._blocked = False
        self._blocked_status = 0
        self._last_request_at = 0.0

    @property
    def blocked(self) -> bool:
        return self._blocked

    def begin_run(self) -> None:
        """重置本轮熔断，并保留请求节流状态。"""
        self._blocked = False
        self._blocked_status = 0

    def _pace(self) -> None:
        delay = self.min_interval_seconds - (time.monotonic() - self._last_request_at)
        if delay > 0:
            time.sleep(delay)
        self._last_request_at = time.monotonic()

    def _get(self, path: str, *, accept: str = "application/json, text/plain, */*",
             allow_redirects: bool = True) -> Optional[requests.Response]:
        if self._blocked:
            return None
        self._pace()
        try:
            response = self._session.get(
                f"{self.BASE_URL}{path}", timeout=self.timeout, proxies=self._proxies,
                headers={"Accept": accept}, allow_redirects=allow_redirects,
            )
        except requests.RequestException as exc:
            logger.warning(f"4K Monitor 请求失败：{type(exc).__name__}")
            return None
        if response.status_code in {403, 429}:
            self._blocked_status = response.status_code
            self._blocked = True
            logger.warning(f"4K Monitor 访问受限：HTTP {response.status_code}，本轮停止继续请求")
            return None
        if response.status_code not in {200, 302}:
            logger.warning(f"4K Monitor 请求失败：HTTP {response.status_code}")
            return None
        return response

    @staticmethod
    def _media_type_value(media_type: MediaType) -> str:
        return "tv" if media_type == MediaType.TV else "movie"

    @staticmethod
    def _is_free(resource: Dict[str, Any]) -> bool:
        try:
            cost = int(resource.get("credit_cost") or 0)
        except (TypeError, ValueError):
            return False
        return (
            resource.get("access_tier") == "free"
            and cost == 0
            and not bool(resource.get("is_locked"))
            and bool(resource.get("access_allowed"))
        )

    @classmethod
    def _normalize_resource(cls, item: Dict[str, Any], tmdb_id: int, tmdb_type: str) -> Optional[Dict[str, Any]]:
        try:
            resource_id = int(item.get("id") or 0)
            item_tmdb_id = int(item.get("tmdb_id") or 0)
        except (TypeError, ValueError):
            return None
        detail_path = str(item.get("detail_url") or "")
        parsed = urlsplit(detail_path)
        if (
            resource_id <= 0
            or item_tmdb_id != tmdb_id
            or str(item.get("tmdb_type") or "").casefold() != tmdb_type
            or parsed.scheme or parsed.netloc
            or not cls._DETAIL_PATH_RE.fullmatch(parsed.path)
            or parsed.query or parsed.fragment
            or not cls._is_free(item)
        ):
            return None
        title = str(item.get("title") or "").strip()
        if not title:
            return None
        return {
            "source": "4kmonitor",
            "resource_id": str(resource_id),
            "tmdb_id": str(tmdb_id),
            "tmdb_type": tmdb_type,
            "title": title,
            "match_titles": [
                title, str(item.get("tmdb_name") or "").strip(),
                str(item.get("tmdb_original_name") or "").strip(),
            ],
            "file_name": title,
            "detail_path": parsed.path,
            "source_type": str(item.get("source_type") or ""),
            "quality_tier": str(item.get("quality_tier") or ""),
            "hdr_format": str(item.get("hdr_format") or ""),
            "audio_format": str(item.get("audio_format") or ""),
            "video_codec": str(item.get("video_codec") or ""),
            "file_size": str(item.get("file_size") or ""),
            "file_size_bytes": int(item.get("file_size_bytes") or 0),
            "seeders": int(item.get("seeders") or 0),
        }

    def list_resources(self, mediainfo, media_type: MediaType) -> List[Dict[str, Any]]:
        """按精确 TMDB ID 取得免费候选；不执行磁力解析。"""
        try:
            tmdb_id = int(getattr(mediainfo, "tmdb_id", 0) or 0)
        except (TypeError, ValueError):
            return []
        if tmdb_id <= 0 or self._blocked:
            return []
        tmdb_type = self._media_type_value(media_type)
        query = urlencode({
            "tmdb_id": str(tmdb_id), "tmdb_type": tmdb_type,
            "page": "1", "per_page": str(self._LIST_PAGE_SIZE), "sort": "date", "order": "desc",
        })
        response = self._get(f"/api/resources?{query}")
        if not response:
            return []
        try:
            payload = response.json()
            rows = payload.get("data") or []
        except (ValueError, AttributeError):
            logger.warning("4K Monitor 资源列表响应无效")
            return []
        output: List[Dict[str, Any]] = []
        seen = set()
        for item in rows:
            if not isinstance(item, dict):
                continue
            resource = self._normalize_resource(item, tmdb_id, tmdb_type)
            resource_id = resource.get("resource_id") if resource else ""
            if resource and resource_id not in seen:
                seen.add(resource_id)
                output.append(resource)
                if len(output) >= self.max_candidates:
                    break
        total = payload.get("total", 0) if isinstance(payload, dict) else 0
        logger.info(f"4K Monitor/TMDB {tmdb_id}：索引 {total} 条，匿名免费候选 {len(output)} 条")
        return output

    def resolve_magnet(self, resource: Dict[str, Any]) -> str:
        """只对最终免费候选解析一次详情页和磁力跳转，不输出磁力内容。"""
        if self._blocked or str(resource.get("source") or "") != "4kmonitor":
            return ""
        detail_path = str(resource.get("detail_path") or "")
        parsed = urlsplit(detail_path)
        if parsed.scheme or parsed.netloc or not self._DETAIL_PATH_RE.fullmatch(parsed.path):
            return ""
        response = self._get(parsed.path, accept="text/html,application/xhtml+xml", allow_redirects=False)
        if not response or response.status_code != 200:
            if response and response.status_code == 302:
                logger.warning("4K Monitor 免费候选详情页发生跳转，跳过")
            return ""
        match = re.search(
            r'<script id="detail-bootstrap" type="application/json">(.*?)</script>', response.text, re.DOTALL
        )
        if not match:
            logger.warning("4K Monitor 免费候选详情数据缺失，跳过")
            return ""
        try:
            payload = json.loads(match.group(1))
            access = payload.get("initialAccess") or {}
            token_path = str(payload.get("magnetActionUrl") or "")
            detail_id = int(payload.get("resourceId") or 0)
        except (TypeError, ValueError, json.JSONDecodeError):
            return ""
        if (
            detail_id != int(resource.get("resource_id") or 0)
            or not self._is_free(access)
            or not re.fullmatch(r"/m/[A-Za-z0-9_.-]+", token_path)
        ):
            logger.warning("4K Monitor 候选权限或详情身份发生变化，跳过")
            return ""
        magnet_response = self._get(token_path, accept="*/*", allow_redirects=False)
        if not magnet_response or magnet_response.status_code != 302:
            logger.warning("4K Monitor 免费候选未返回磁力跳转，跳过")
            return ""
        magnet = str(magnet_response.headers.get("Location") or "").strip()
        if not magnet.casefold().startswith("magnet:?"):
            logger.warning("4K Monitor 磁力跳转无效，跳过")
            return ""
        return magnet
