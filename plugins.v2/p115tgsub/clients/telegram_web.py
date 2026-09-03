"""Telegram 公开频道搜索客户端（提取 115 与夸克分享链接）。"""
from __future__ import annotations

import html
import re
import time
import unicodedata
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import parse_qs, quote, unquote, urlsplit

import requests

from app.log import logger


@dataclass
class TelegramMessage:
    """Telegram 公开频道的一条搜索结果。"""

    channel: str
    message_id: str
    message_url: str
    text: str
    published_at: str = ""
    links: List[str] = field(default_factory=list)
    telegraph_links: List[str] = field(default_factory=list)


class _TelegramSearchPageParser(HTMLParser):
    """提取 t.me/s 搜索页中的消息文本和链接，不依赖 BeautifulSoup。"""

    _VOID_TAGS = {
        "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
        "meta", "param", "source", "track", "wbr",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.messages: List[Dict[str, Any]] = []
        self._message: Optional[Dict[str, Any]] = None
        self._depth = 0
        self._in_message_text = 0
        self._in_time = 0

    def handle_starttag(self, tag: str, attrs: Sequence[tuple]) -> None:
        attrs_map = dict(attrs)
        css_class = attrs_map.get("class", "")

        # 以带 data-post 的消息本体为边界，不能以 wrapper 或普通标签计数。
        # Telegram 消息中常有 <img> 等无闭合标签；旧实现会使深度无法归零，
        # 进而丢掉前面的搜索结果，只保留最后一条。
        if tag == "div" and "tgme_widget_message" in css_class and attrs_map.get("data-post"):
            if self._message:
                self.messages.append(self._message)
            self._message = {"text": [], "links": [], "published_at": "", "post": attrs_map["data-post"]}
            self._depth = 1
            self._in_message_text = 0
            self._in_time = 0
            return

        if not self._message:
            return

        if tag not in self._VOID_TAGS:
            self._depth += 1
        if tag == "div" and "tgme_widget_message_text" in css_class:
            self._in_message_text += 1
        if tag == "time":
            self._in_time += 1
            self._message["published_at"] = attrs_map.get("datetime", "")
        if tag == "a":
            href = attrs_map.get("href", "").strip()
            if href:
                self._message["links"].append(href)

    def handle_startendtag(self, tag: str, attrs: Sequence[tuple]) -> None:
        """自闭合标签不应参与消息容器深度计算。"""
        self.handle_starttag(tag, attrs)

    def handle_data(self, data: str) -> None:
        if self._message and self._in_message_text:
            self._message["text"].append(data)

    def handle_endtag(self, tag: str) -> None:
        if not self._message:
            return
        if tag == "div" and self._in_message_text:
            self._in_message_text -= 1
        if tag == "time" and self._in_time:
            self._in_time -= 1
        if tag in self._VOID_TAGS:
            return
        self._depth -= 1
        if self._depth == 0:
            self.messages.append(self._message)
            self._message = None

    def close(self) -> None:
        super().close()
        # 页面截断或异常 HTML 时尽量保留已开始解析的最后一条消息。
        if self._message:
            self.messages.append(self._message)
            self._message = None


class _PageTextAndLinksParser(HTMLParser):
    """提取 Telegraph 正文的可见文本和全部链接。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text_parts: List[str] = []
        self.links: List[str] = []

    def handle_starttag(self, tag: str, attrs: Sequence[tuple]) -> None:
        if tag == "a":
            href = dict(attrs).get("href", "").strip()
            if href:
                self.links.append(href)

    def handle_data(self, data: str) -> None:
        self.text_parts.append(data)


class TelegramWebClient:
    """经 Telegram 公开网页检索频道，并只返回 115 分享候选。"""

    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131 Safari/537.36"
    )
    _115_HOSTS = {"115.com", "115cdn.com", "anxia.com"}
    _QUARK_HOSTS = {"pan.quark.cn"}
    _URL_RE = re.compile(r"https?://[^\s<>\"'，。；;]+", re.IGNORECASE)
    _OFFLINE_RE = re.compile(r"(?:ed2k://\|file\|[^\s<>\"']+?\|/|magnet:\?[^\s<>\"']+)", re.IGNORECASE)
    _SEEDHUB_MOVIE_RE = re.compile(r"^https://sidhub\.cc/movies/\d+/?$", re.IGNORECASE)
    _TRAILING_URL_CHARS = ".,，。;；:：!！?？)]}〉》\"'"

    def __init__(
        self,
        channels: Iterable[str],
        proxy: Any = None,
        timeout: int = 20,
        max_results_per_channel: int = 10,
        max_telegraph_pages: int = 3,
        telegraph_delay: float = 0.5,
    ) -> None:
        self.channels = self.normalize_channels(channels)
        self.timeout = max(5, min(int(timeout or 20), 60))
        self.max_results_per_channel = max(1, min(int(max_results_per_channel or 10), 20))
        self.max_telegraph_pages = max(0, min(int(max_telegraph_pages or 3), 10))
        self.telegraph_delay = max(0.0, min(float(telegraph_delay or 0), 5.0))
        self._api_call_count = 0
        self._page_cache: Dict[str, str] = {}
        self._search_stats = {"raw_candidates": 0, "duplicates_merged": 0}
        self._proxies = proxy if isinstance(proxy, dict) else ({"http": proxy, "https": proxy} if proxy else None)
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": self.USER_AGENT, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"})

    @staticmethod
    def normalize_channels(channels: Iterable[str]) -> List[str]:
        """接受用户名、t.me URL 或每行一个频道的文本，返回去重用户名。"""
        if isinstance(channels, str):
            values = re.split(r"[\n,，]+", channels)
        else:
            values = list(channels or [])

        normalized: List[str] = []
        for raw in values:
            value = str(raw or "").strip()
            if not value or value.startswith("#"):
                continue
            value = value.rstrip("/")
            if value.startswith("@"):
                value = value[1:]
            parsed = urlsplit(value if "://" in value else f"https://t.me/{value}")
            if parsed.netloc.lower() in {"t.me", "www.t.me", "telegram.me", "www.telegram.me"}:
                parts = [unquote(part) for part in parsed.path.split("/") if part]
                if parts and parts[0].lower() == "s":
                    parts = parts[1:]
                value = parts[0] if parts else ""
            if re.fullmatch(r"[A-Za-z0-9_]{5,64}", value or "") and value.lower() not in {item.lower() for item in normalized}:
                normalized.append(value)
        return normalized

    @classmethod
    def _is_115_url(cls, url: str) -> bool:
        try:
            host = urlsplit(url).hostname or ""
            host = host.lower()
            return any(host == allowed or host.endswith(f".{allowed}") for allowed in cls._115_HOSTS)
        except Exception:
            return False

    @classmethod
    def _is_quark_url(cls, url: str) -> bool:
        try:
            host = (urlsplit(url).hostname or "").lower()
            return any(host == allowed or host.endswith(f".{allowed}") for allowed in cls._QUARK_HOSTS)
        except Exception:
            return False

    @classmethod
    def _is_telegraph_url(cls, url: str) -> bool:
        try:
            host = (urlsplit(url).hostname or "").lower()
            return host == "telegra.ph" or host.endswith(".telegra.ph")
        except Exception:
            return False

    @classmethod
    def _clean_url(cls, url: str) -> str:
        value = html.unescape(str(url or "").strip()).strip(cls._TRAILING_URL_CHARS)
        if "#" in value:
            value = value.split("#", 1)[0]
        return value.rstrip("&")

    @classmethod
    def _extract_links(cls, text: str, links: Iterable[str], kinds: Sequence[str]) -> List[str]:
        candidates = list(links or []) + cls._URL_RE.findall(html.unescape(text or ""))
        output: List[str] = []
        seen = set()
        want_115 = "115" in kinds
        want_quark = "quark" in kinds
        for raw in candidates:
            url = cls._clean_url(raw)
            is_115 = want_115 and cls._is_115_url(url)
            is_quark = want_quark and cls._is_quark_url(url)
            if not is_115 and not is_quark:
                continue
            key = url.lower()
            if key not in seen:
                seen.add(key)
                output.append(url)
        return output

    @classmethod
    def _extract_urls(cls, text: str, links: Iterable[str] = ()) -> List[str]:
        """仅提取 115 分享链接（兼容既有调用与测试）。"""
        return cls._extract_links(text, links, ("115",))

    @classmethod
    def _extract_quark_urls(cls, text: str, links: Iterable[str] = ()) -> List[str]:
        """仅提取 pan.quark.cn 分享链接。"""
        return cls._extract_links(text, links, ("quark",))

    @classmethod
    def _extract_offline_urls(cls, text: str, links: Iterable[str] = ()) -> List[str]:
        """提取公开 Telegram 消息直接包含的 ED2K / 磁力，不访问第三方资源页。"""
        output: List[str] = []
        seen = set()
        candidates = list(links or []) + cls._OFFLINE_RE.findall(html.unescape(str(text or "")))
        for raw in candidates:
            url = html.unescape(str(raw or "").strip()).rstrip(".,，。;；")
            if not cls._OFFLINE_RE.fullmatch(url):
                continue
            key = url.casefold()
            if key and key not in seen:
                seen.add(key)
                output.append(url)
        return output

    @classmethod
    def _extract_seedhub_movie_urls(cls, text: str, links: Iterable[str] = ()) -> List[str]:
        """仅提取 SeedHub 公开电影页，不处理搜索页、link_start 或其他第三方链接。"""
        output: List[str] = []
        seen = set()
        for raw in list(links or []) + cls._URL_RE.findall(html.unescape(str(text or ""))):
            url = cls._clean_url(raw)
            if cls._SEEDHUB_MOVIE_RE.fullmatch(url) and url.casefold() not in seen:
                seen.add(url.casefold())
                output.append(url)
        return output

    @classmethod
    def _extract_telegraph_urls(cls, links: Iterable[str]) -> List[str]:
        output: List[str] = []
        seen = set()
        for raw in links or []:
            url = cls._clean_url(raw)
            if cls._is_telegraph_url(url) and url.lower() not in seen:
                seen.add(url.lower())
                output.append(url)
        return output

    def reset_api_call_count(self) -> None:
        self._api_call_count = 0
        self._page_cache.clear()
        self._search_stats = {"raw_candidates": 0, "duplicates_merged": 0}

    def get_search_stats(self) -> Dict[str, int]:
        """返回本同步轮 Telegram 候选统计，不含链接或提取码。"""
        return dict(self._search_stats)

    def _get(self, url: str) -> Optional[str]:
        cached = self._page_cache.get(url)
        if cached is not None:
            return cached
        try:
            self._api_call_count += 1
            response = self._session.get(url, timeout=self.timeout, proxies=self._proxies)
            if response.status_code != 200:
                logger.warning(f"Telegram 公开页请求失败：HTTP {response.status_code}")
                return None
            self._page_cache[url] = response.text
            return response.text
        except requests.RequestException as exc:
            logger.warning(f"Telegram 公开页请求失败：{exc}")
            return None

    @staticmethod
    def _message_url(channel: str, post: str) -> str:
        parts = [part for part in str(post or "").split("/") if part]
        message_id = parts[-1] if parts else ""
        return f"https://t.me/{channel}/{message_id}" if message_id else f"https://t.me/{channel}"

    @staticmethod
    def _message_matches_title(message: TelegramMessage, required_title: str) -> bool:
        """仅保留明确包含订阅标题的消息，避免宽泛搜索词被无关年份结果占满。"""
        title = str(required_title or "").strip()
        text = str(message.text or "").strip()
        if not title:
            return True
        if not text:
            return False

        def compact(value: str) -> str:
            normalized = unicodedata.normalize("NFKC", value).casefold()
            # \W 会移除中文，不能用它清理标题；只移除明确的分隔符和空白。
            return re.sub(r"[\s\-_./:：()（）\[\]【】{}]+", "", normalized)

        expected = compact(title)
        actual = compact(text)
        return bool(expected) and expected in actual

    @staticmethod
    def _message_matches_episodes(message: TelegramMessage, season: int, episodes: Sequence[int]) -> bool:
        """仅用于候选排序：优先保留标题明确标注待补季集的消息。"""
        targets = {int(episode) for episode in episodes or [] if str(episode).isdigit() and int(episode) > 0}
        if not targets:
            return False
        text = unicodedata.normalize("NFKC", str(message.text or ""))
        for episode in targets:
            if re.search(rf"[Ss]\s*0*{int(season)}\s*[Ee]\s*0*{episode}(?!\d)", text, re.IGNORECASE):
                return True
            if re.search(rf"第\s*0*{episode}\s*[集话話](?!\d)", text, re.IGNORECASE):
                return True
        return False

    def search_messages(self, channel: str, keyword: str, required_title: str = "",
                        preferred_season: int = 0, preferred_episodes: Sequence[int] = (),
                        prefer_recent: bool = False) -> List[TelegramMessage]:
        """从一个公开频道的搜索页面提取消息；不执行 Telegraph 二跳。"""
        channel = self.normalize_channels([channel])[0] if self.normalize_channels([channel]) else ""
        keyword = str(keyword or "").strip()
        if not channel or not keyword:
            return []

        url = f"https://t.me/s/{quote(channel, safe='_')}?q={quote(keyword)}"
        page = self._get(url)
        if not page:
            return []

        parser = _TelegramSearchPageParser()
        try:
            parser.feed(page)
            parser.close()
        except Exception as exc:
            logger.warning(f"解析 Telegram 频道 {channel} 搜索页失败：{exc}")
            return []

        messages: List[TelegramMessage] = []
        # 先按订阅标题过滤；若当前有明确待补集数，再将对应单集消息提前，避免
        # 旧连载集占满“每频道最多检查消息数”而漏掉后续新集。
        for raw in parser.messages:
            post = str(raw.get("post") or "")
            message_id = post.rsplit("/", 1)[-1] if "/" in post else ""
            links = [self._clean_url(item) for item in raw.get("links") or []]
            text = " ".join("".join(raw.get("text") or []).split())
            message = TelegramMessage(
                channel=channel,
                message_id=message_id,
                message_url=self._message_url(channel, post),
                text=text,
                published_at=str(raw.get("published_at") or ""),
                links=links,
                telegraph_links=self._extract_telegraph_urls(links),
            )
            if required_title and not self._message_matches_title(message, required_title):
                continue
            messages.append(message)
        # 追更型订阅按发布时间倒序截取窗口；补档型保留 Telegram 原始顺序，让历史
        # 资源仍有机会进入候选。明确命中待补集的消息始终优先于其他消息。
        if prefer_recent:
            messages.sort(key=lambda message: message.published_at or "", reverse=True)
        if preferred_episodes:
            messages.sort(
                key=lambda message: not self._message_matches_episodes(
                    message, int(preferred_season or 1), preferred_episodes
                )
            )
        return messages[:self.max_results_per_channel]

    def _extract_telegraph_page(self, url: str, kind: str) -> Tuple[List[str], str]:
        page = self._get(url)
        if not page:
            return [], ""
        parser = _PageTextAndLinksParser()
        try:
            parser.feed(page)
            parser.close()
        except Exception as exc:
            logger.warning(f"解析 Telegraph 资源页失败：{exc}")
            return [], ""
        text = " ".join("".join(parser.text_parts).split())
        extractor = self._extract_urls if kind == "115" else self._extract_quark_urls
        return extractor(text, parser.links), text

    def _extract_telegraph_links(self, url: str, kind: str) -> List[str]:
        links, _ = self._extract_telegraph_page(url, kind)
        return links

    def _extract_telegraph_115_links(self, url: str) -> List[str]:
        """兼容既有调用：仅提取 Telegraph 中的 115 链接。"""
        return self._extract_telegraph_links(url, "115")

    @staticmethod
    def _message_matches_keyword(message: TelegramMessage, keyword: str) -> bool:
        """Telegraph 二跳前先确认消息文本包含搜索关键词，避免无关页面请求。"""
        expected = re.sub(r"[\W_]+", "", str(keyword or "").casefold())
        actual = re.sub(r"[\W_]+", "", str(message.text or "").casefold())
        return bool(expected) and expected in actual

    @classmethod
    def _quark_share_key(cls, url: str, text: str = "") -> Tuple[str, str]:
        """生成运行期去重键；同分享保留不同访问码，优先保留带访问码版本。"""
        cleaned = cls._clean_url(url)
        match = re.search(r"pan\.quark\.cn/s/([A-Za-z0-9]+)", cleaned, re.IGNORECASE)
        if not match:
            return cleaned.casefold(), ""
        query = urlsplit(cleaned).query
        password = ""
        for key in ("pwd", "passcode", "code"):
            values = parse_qs(query).get(key) or []
            if values and str(values[0]).strip():
                password = str(values[0]).strip()
                break
        if not password:
            password_match = re.search(
                r"(?:提取码|访问码|密码|passcode|code)\s*[：:=]?\s*([A-Za-z0-9]{4,16})",
                str(text or ""), re.IGNORECASE,
            )
            password = password_match.group(1) if password_match else ""
        return match.group(1).casefold(), password.casefold()

    def search_115_resources(self, keyword: str, required_title: str = "", preferred_season: int = 0,
                             preferred_episodes: Sequence[int] = (), prefer_recent: bool = False) -> List[Dict[str, str]]:
        """搜索所有已配置频道，返回标题已初筛的 115 资源格式。"""
        return self._search_links(
            keyword, required_title, "115", preferred_season, preferred_episodes, prefer_recent
        )

    def search_quark_resources(self, keyword: str, required_title: str = "", prefer_recent: bool = False) -> List[Dict[str, str]]:
        """搜索所有已配置频道，返回标题已初筛的 pan.quark.cn 资源格式。"""
        return self._search_links(keyword, required_title, "quark", prefer_recent=prefer_recent)

    def search_offline_resources(self, keyword: str, required_title: str = "", preferred_season: int = 0,
                                 preferred_episodes: Sequence[int] = (), prefer_recent: bool = False) -> List[Dict[str, str]]:
        """只搜索 Telegram 公开消息正文中直接发布的 ED2K / 磁力候选。"""
        if not self.channels:
            return []
        results: List[Dict[str, str]] = []
        seen = set()
        requested_channels = 0
        for channel in self.channels:
            requested_channels += 1
            messages = self.search_messages(
                channel, keyword, required_title=required_title,
                preferred_season=preferred_season, preferred_episodes=preferred_episodes,
                prefer_recent=prefer_recent,
            )
            if not messages:
                continue
            for message in messages:
                for url in self._extract_offline_urls(message.text, message.links):
                    key = url.casefold()
                    if key in seen:
                        continue
                    seen.add(key)
                    self._search_stats["raw_candidates"] += 1
                    results.append({
                        "url": url, "title": message.text or keyword, "text": message.text or "",
                        "update_time": message.published_at, "channel": message.channel,
                        "message_id": message.message_id, "message_url": message.message_url,
                        "kind": "ed2k" if url.casefold().startswith("ed2k:") else "magnet",
                    })
        logger.info(
            f"Telegram 公开频道搜索“{keyword}”完成，请求 {requested_channels}/{len(self.channels)} 个频道，"
            f"找到 {len(results)} 个 ED2K/磁力候选"
        )
        return results

    def search_seedhub_movie_pages(self, keyword: str, required_title: str = "", channel: str = "seedhub_pro",
                                   prefer_recent: bool = False) -> List[Dict[str, str]]:
        """仅从指定公开频道提取 SeedHub /movies/<id>/ 索引页。"""
        normalized = self.normalize_channels([channel])
        if not normalized:
            return []
        results: List[Dict[str, str]] = []
        seen = set()
        for message in self.search_messages(
            normalized[0], keyword, required_title=required_title, prefer_recent=prefer_recent
        ):
            for movie_url in self._extract_seedhub_movie_urls(message.text, message.links):
                if movie_url.casefold() in seen:
                    continue
                seen.add(movie_url.casefold())
                self._search_stats["raw_candidates"] += 1
                results.append({
                    "url": movie_url, "title": message.text or keyword, "text": message.text or "",
                    "update_time": message.published_at, "channel": message.channel,
                    "message_id": message.message_id, "message_url": message.message_url,
                    "kind": "seedhub_movie",
                })
        logger.info(f"Telegram 公开频道 {normalized[0]} 搜索“{keyword}”完成，找到 {len(results)} 个 SeedHub 页面")
        return results

    def _search_links(self, keyword: str, required_title: str, kind: str, preferred_season: int = 0,
                      preferred_episodes: Sequence[int] = (), prefer_recent: bool = False) -> List[Dict[str, str]]:
        """按资源类型（115/quark）搜索全部频道并返回候选。"""
        if not self.channels:
            logger.warning("Telegram 搜索源未配置公开频道")
            return []

        extractor = self._extract_urls if kind == "115" else self._extract_quark_urls
        results: List[Dict[str, str]] = []
        requested_channels = 0
        # 115 仍按完整链接去重；夸克按“分享 ID + 访问码”去重，避免无访问码
        # 的搬运消息覆盖后续携带正确访问码的同一分享。
        seen_keys = set()
        for channel in self.channels:
            requested_channels += 1
            messages = self.search_messages(
                channel, keyword, required_title=required_title,
                preferred_season=preferred_season, preferred_episodes=preferred_episodes,
                prefer_recent=prefer_recent,
            )
            if not messages:
                logger.info(f"Telegram 频道 {channel} 未找到关键词“{keyword}”的消息")
                continue

            telegraph_used = 0
            for message in messages:
                direct_links = extractor(message.text, message.links)
                link_texts = {self._clean_url(link).lower(): message.text for link in direct_links}
                if (
                    not direct_links
                    and message.telegraph_links
                    and self._message_matches_keyword(message, keyword)
                    and telegraph_used < self.max_telegraph_pages
                ):
                    for telegraph_url in message.telegraph_links:
                        if telegraph_used >= self.max_telegraph_pages:
                            break
                        telegraph_used += 1
                        page_links, page_text = self._extract_telegraph_page(telegraph_url, kind)
                        for page_link in page_links:
                            direct_links.append(page_link)
                            link_texts[self._clean_url(page_link).lower()] = " ".join(
                                value for value in (message.text, page_text) if value
                            )
                        if self.telegraph_delay:
                            time.sleep(self.telegraph_delay)

                for share_url in direct_links:
                    normalized_url = self._clean_url(share_url)
                    candidate_text = link_texts.get(normalized_url.lower(), message.text or "")
                    if kind == "quark":
                        dedup_key = self._quark_share_key(normalized_url, candidate_text)
                    else:
                        dedup_key = (normalized_url.casefold(), "")
                    self._search_stats["raw_candidates"] += 1
                    if dedup_key in seen_keys:
                        self._search_stats["duplicates_merged"] += 1
                        continue
                    seen_keys.add(dedup_key)
                    results.append({
                        "url": normalized_url,
                        "title": message.text or keyword,
                        "update_time": message.published_at,
                        "channel": message.channel,
                        "message_id": message.message_id,
                        "message_url": message.message_url,
                        "text": candidate_text,
                    })

        logger.info(
            f"Telegram 公开频道搜索“{keyword}”完成，请求 {requested_channels}/{len(self.channels)} 个频道，"
            f"找到 {len(results)} 个 {kind} 分享链接"
        )
        return results
