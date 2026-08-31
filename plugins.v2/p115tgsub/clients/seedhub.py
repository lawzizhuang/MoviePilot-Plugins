"""SeedHub 公开磁力资源客户端。

仅请求 seedhub_pro Telegram 消息中公开的 /movies/<数字ID>/ 页面及其同源
link_start 页面；不登录、不使用 Cookie、不处理验证码或 .torrent 文件。
"""
from __future__ import annotations

import base64
import html
import re
from html.parser import HTMLParser
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import parse_qs, urljoin, urlsplit

import requests

from app.log import logger


class _SeedListParser(HTMLParser):
    """提取 ul.seeds 中每个 li 的发布标题、条目 ID 和展示信息。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.items: List[Dict[str, Any]] = []
        self._in_seeds = 0
        self._item: Optional[Dict[str, Any]] = None
        self._li_depth = 0
        self._in_feature = False
        self._in_size = False
        self._in_time = False
        self._text: List[str] = []

    def handle_starttag(self, tag: str, attrs: Iterable[tuple]) -> None:
        attrs_map = dict(attrs)
        css_class = attrs_map.get("class", "")
        if tag == "ul" and "seeds" in css_class.split():
            self._in_seeds += 1
            return
        if not self._in_seeds:
            return
        if tag == "li" and self._item is None:
            self._item = {"title": "", "link": "", "features": [], "size": "", "updated_at": ""}
            self._li_depth = 1
            return
        if self._item is None:
            return
        if tag == "li":
            self._li_depth += 1
        if tag == "a" and "seed_id=" in attrs_map.get("href", ""):
            self._item["title"] = html.unescape(attrs_map.get("title", "").strip())
            self._item["link"] = html.unescape(attrs_map.get("href", "").strip())
        self._in_feature = tag == "code" and "seed-feature" in css_class.split()
        self._in_size = tag == "code" and "size" in css_class.split()
        self._in_time = tag == "span" and "create-time" in css_class.split()
        if self._in_feature or self._in_size or self._in_time:
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._item is not None and (self._in_feature or self._in_size or self._in_time):
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._item is not None:
            value = " ".join("".join(self._text).split())
            if tag == "code" and self._in_feature:
                if value:
                    self._item["features"].append(value)
                self._in_feature = False
            elif tag == "code" and self._in_size:
                self._item["size"] = value
                self._in_size = False
            elif tag == "span" and self._in_time:
                self._item["updated_at"] = value
                self._in_time = False
            if tag == "li":
                self._li_depth -= 1
                if self._li_depth <= 0:
                    if self._item.get("title") and self._item.get("link"):
                        self.items.append(self._item)
                    self._item = None
            return
        if tag == "ul" and self._in_seeds:
            self._in_seeds -= 1


class SeedHubClient:
    """读取 SeedHub 公开电影页，并受控解码其公开 link_start Magnet。"""

    BASE_URL = "https://sidhub.cc"
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131 Safari/537.36"
    )
    _MOVIE_RE = re.compile(r"^/movies/(\d+)/?$", re.IGNORECASE)
    _DATA_RE = re.compile(r"\bconst\s+data\s*=\s*[\"']([A-Za-z0-9+/=_-]+)[\"']", re.IGNORECASE)

    def __init__(self, proxy: Any = None, timeout: int = 20, max_candidates: int = 5) -> None:
        self.timeout = max(5, min(int(timeout or 20), 60))
        self.max_candidates = max(1, min(int(max_candidates or 5), 20))
        self._proxies = proxy if isinstance(proxy, dict) else ({"http": proxy, "https": proxy} if proxy else None)
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": self.USER_AGENT,
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Referer": f"{self.BASE_URL}/",
        })
        self._page_cache: Dict[str, str] = {}

    @classmethod
    def movie_id_from_url(cls, url: str) -> str:
        try:
            parsed = urlsplit(str(url or ""))
            if parsed.scheme != "https" or parsed.hostname.casefold() != "sidhub.cc":
                return ""
            match = cls._MOVIE_RE.fullmatch(parsed.path)
            return match.group(1) if match else ""
        except Exception:
            return ""

    @classmethod
    def movie_url(cls, movie_id: str) -> str:
        return f"{cls.BASE_URL}/movies/{int(movie_id)}/"

    def _get(self, url: str) -> Optional[str]:
        if url in self._page_cache:
            return self._page_cache[url]
        try:
            response = self._session.get(url, timeout=self.timeout, proxies=self._proxies)
            if response.status_code != 200:
                logger.warning(f"SeedHub 公开页面请求失败：HTTP {response.status_code}")
                return None
            self._page_cache[url] = response.text
            return response.text
        except requests.RequestException as exc:
            logger.warning(f"SeedHub 公开页面请求失败：{type(exc).__name__}")
            return None

    @classmethod
    def parse_seed_list(cls, page: str, movie_id: str) -> List[Dict[str, Any]]:
        parser = _SeedListParser()
        try:
            parser.feed(page or "")
            parser.close()
        except Exception:
            return []
        output: List[Dict[str, Any]] = []
        for raw in parser.items:
            link = str(raw.get("link") or "")
            parsed = urlsplit(link)
            seed_id = (parse_qs(parsed.query).get("seed_id") or [""])[0]
            if not str(seed_id).isdigit() or parsed.path.rstrip("/") != "/link_start":
                continue
            output.append({
                "source": "seedhub", "movie_id": str(movie_id), "seed_id": str(seed_id),
                "title": str(raw.get("title") or ""), "file_name": str(raw.get("title") or ""),
                "size": str(raw.get("size") or ""), "features": list(raw.get("features") or []),
                "updated_at": str(raw.get("updated_at") or ""), "link_path": link,
            })
        return output

    @classmethod
    def parse_magnet_page(cls, page: str) -> str:
        match = cls._DATA_RE.search(str(page or ""))
        if not match:
            return ""
        try:
            encoded = match.group(1).replace("-", "+").replace("_", "/")
            encoded += "=" * (-len(encoded) % 4)
            value = base64.b64decode(encoded, validate=True).decode("utf-8", "strict").strip()
            return value if value.casefold().startswith("magnet:?") else ""
        except (ValueError, UnicodeError):
            return ""

    def resolve_magnet(self, resource: Dict[str, Any]) -> str:
        """仅访问由列表页生成的同源 link_start；不记录 Magnet 原文。"""
        movie_id = str(resource.get("movie_id") or "")
        seed_id = str(resource.get("seed_id") or "")
        link_path = str(resource.get("link_path") or "")
        if not movie_id.isdigit() or not seed_id.isdigit():
            return ""
        parsed = urlsplit(link_path)
        if parsed.path.rstrip("/") != "/link_start" or (parse_qs(parsed.query).get("seed_id") or [""])[0] != seed_id:
            return ""
        page = self._get(urljoin(self.BASE_URL, link_path))
        return self.parse_magnet_page(page or "") if page else ""

    def list_resources(self, movie_url: str) -> List[Dict[str, Any]]:
        movie_id = self.movie_id_from_url(movie_url)
        if not movie_id:
            return []
        page = self._get(self.movie_url(movie_id))
        if not page:
            return []
        resources = self.parse_seed_list(page, movie_id)
        logger.info(f"SeedHub/{movie_id}：发现 {len(resources)} 个公开磁力候选")
        return resources[:self.max_candidates]
