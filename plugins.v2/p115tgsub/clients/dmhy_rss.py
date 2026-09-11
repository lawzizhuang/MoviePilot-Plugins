"""动漫花园公开RSS受控读取客户端（开发分支，尚未接入追更流程）。

每轮每个固定Feed最多读取一次，仅解析标题、发布时间、主题链接与BTIH，
并将磁力收缩为最小BTIH形式。调用方仍须核验媒体身份、季集、订阅过滤器和
真实115落盘，不得把RSS命中直接视为下载完成。
"""
from __future__ import annotations

import email.utils
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode, urlsplit

import requests

from app.log import logger


class DMHYRSSClient:
    BASE_URL = 'https://share.dmhy.org'
    ANIME_PATH = '/topics/rss/rss.xml?keyword=&sort_id=2&team_id=0&order=date-desc'
    SEASON_PACK_PATH = '/topics/rss/rss.xml?keyword=&sort_id=31&team_id=0&order=date-desc'
    MAX_BYTES = 3 * 1024 * 1024
    MAX_ITEMS = 500
    _BTIH_RE = re.compile(r'(?:[?&]xt=urn:btih:)([A-Za-z2-7]{32}|[A-Fa-f0-9]{40})(?:[&#]|$)', re.I)
    _TOPIC_RE = re.compile(r'^/topics/view/\d+_[A-Za-z0-9_.-]+\.html$', re.I)

    def __init__(self, proxy: Any = None, timeout: int = 20, min_interval_seconds: int = 5,
                 max_keyword_queries_per_run: int = 6) -> None:
        self.timeout = max(5, min(int(timeout or 20), 60))
        self.min_interval_seconds = max(2, min(int(min_interval_seconds or 5), 60))
        self._proxies = proxy if isinstance(proxy, dict) else ({'http': proxy, 'https': proxy} if proxy else None)
        self._session = requests.Session()
        self._session.headers.update({'User-Agent': 'Mozilla/5.0 (compatible; P115TGSub/2.x)', 'Accept': 'application/rss+xml, application/xml, text/xml'})
        self._last_request_at = 0.0
        self._blocked = False
        self.max_keyword_queries_per_run = max(1, min(int(max_keyword_queries_per_run or 6), 20))
        self._keyword_queries = 0
        self._cache: Dict[str, List[Dict[str, Any]]] = {}

    @property
    def blocked(self) -> bool:
        return self._blocked

    def begin_run(self) -> None:
        self._blocked = False
        self._keyword_queries = 0
        self._cache.clear()

    def _pace(self) -> None:
        delay = self.min_interval_seconds - (time.monotonic() - self._last_request_at)
        if delay > 0:
            time.sleep(delay)
        self._last_request_at = time.monotonic()

    @classmethod
    def _minimal_magnet(cls, value: str) -> str:
        match = cls._BTIH_RE.search(str(value or ''))
        if not match:
            return ''
        digest = match.group(1).upper()
        return f'magnet:?xt=urn:btih:{digest}'

    @staticmethod
    def _pub_date(value: str) -> str:
        try:
            result = email.utils.parsedate_to_datetime(value)
            if result.tzinfo is None:
                result = result.replace(tzinfo=timezone.utc)
            return result.astimezone(timezone.utc).isoformat()
        except (TypeError, ValueError, IndexError):
            return ''

    @classmethod
    def _parse(cls, body: bytes, feed: str) -> List[Dict[str, Any]]:
        if not body or len(body) > cls.MAX_BYTES:
            raise ValueError('RSS响应为空或超过大小上限')
        try:
            root = ET.fromstring(body)
        except ET.ParseError as exc:
            raise ValueError('RSS XML无效') from exc
        output, seen = [], set()
        for item in root.findall('./channel/item')[:cls.MAX_ITEMS]:
            title = ' '.join((item.findtext('title') or '').split())
            link = (item.findtext('link') or '').strip()
            enclosure = item.find('enclosure')
            parsed = urlsplit(link)
            magnet = cls._minimal_magnet(enclosure.get('url') if enclosure is not None else '')
            if (not title or len(title) > 1024 or not magnet or parsed.scheme not in {'http', 'https'}
                    or parsed.netloc not in {'share.dmhy.org', 'www.dmhy.org'} or not cls._TOPIC_RE.fullmatch(parsed.path)):
                continue
            key = magnet.rsplit(':', 1)[-1]
            if key in seen:
                continue
            seen.add(key)
            output.append({'source': 'dmhy_rss', 'feed': feed, 'title': title, 'topic_url': link,
                           'published_at': cls._pub_date(item.findtext('pubDate') or ''), 'magnet': magnet,
                           'btih': key})
        return output

    def _fetch(self, cache_key: str, path: str, feed: str) -> List[Dict[str, Any]]:
        if cache_key in self._cache:
            return list(self._cache[cache_key])
        if self._blocked:
            return []
        self._pace()
        try:
            response = self._session.get(f'{self.BASE_URL}{path}', timeout=self.timeout, proxies=self._proxies)
        except requests.RequestException as exc:
            logger.warning(f'DMHY RSS请求失败：{type(exc).__name__}')
            return []
        if response.status_code in {403, 429} or response.status_code >= 500:
            self._blocked = True
            logger.warning(f'DMHY RSS访问受限或服务异常：HTTP {response.status_code}，本轮停止请求')
            return []
        if response.status_code != 200:
            logger.warning(f'DMHY RSS请求失败：HTTP {response.status_code}')
            return []
        try:
            rows = self._parse(response.content, feed)
        except ValueError as exc:
            self._blocked = True
            logger.warning(f'DMHY RSS响应无效：{exc}，本轮停止请求')
            return []
        self._cache[cache_key] = rows
        logger.info(f'DMHY RSS/{feed}：有效BTIH候选 {len(rows)} 条')
        return list(rows)

    def search_keyword(self, keyword: str) -> List[Dict[str, Any]]:
        """按作品名精确RSS检索；每轮全局限额，结果仅作后续本地严格核验。"""
        keyword = ' '.join(str(keyword or '').split())
        if not keyword or len(keyword) > 200 or self._blocked:
            return []
        key = f'keyword:{keyword.casefold()}'
        if key not in self._cache and self._keyword_queries >= self.max_keyword_queries_per_run:
            logger.info('DMHY RSS作品关键词请求已达本轮预算，保留至下轮')
            return []
        if key not in self._cache:
            self._keyword_queries += 1
        path = '/topics/rss/rss.xml?' + urlencode({
            'keyword': keyword, 'sort_id': '0', 'team_id': '0', 'order': 'date-desc',
        })
        return self._fetch(key, path, 'keyword')

    def list_feed(self, feed: str) -> List[Dict[str, Any]]:
        """每轮缓存固定Feed；异常与访问受限时停止继续读取。"""
        if feed not in {'anime', 'season_pack'}:
            raise ValueError('未知DMHY RSS分类')
        path = self.ANIME_PATH if feed == 'anime' else self.SEASON_PACK_PATH
        return self._fetch(feed, path, feed)
