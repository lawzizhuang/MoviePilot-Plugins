"""磁力熊公开页面候选客户端（开发分支，尚未接入追更流程）。

仅读取站内搜索与同源影视详情页，解析页面直接给出的BTIH磁力；不登录、
不记录搜索词、Cookie或磁力原文。没有TMDB索引，调用方必须继续验证标题、年份和季集。
"""
from __future__ import annotations

import html
import re
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlsplit

import requests

from app.log import logger
from app.schemas.types import MediaType


class CiLiXiongClient:
    BASE_URL = "https://www.cilixiong.org"
    SEARCH_PATH = "/e/search/index.php"
    USER_AGENT = "Mozilla/5.0 (compatible; P115TGSub/2.x; +https://github.com/lawzizhuang/MoviePilot-Plugins)"
    _PAGE_RE = re.compile(r'^/(movie|drama)/(\d+)\.html$', re.I)
    _CARD_RE = re.compile(
        r'<a\s+href=["\'](?P<path>/(?:movie|drama)/\d+\.html)["\'][^>]*>.*?'
        r'<h2[^>]*>\s*(?P<title>.*?)\s*</h2>.*?'
        r'<li[^>]*>\s*(?P<year>\d{4})\s*</li>', re.I | re.S,
    )
    _DETAIL_TITLE_RE = re.compile(r'<h1>\s*(.*?)\s*</h1>', re.I | re.S)
    _DETAIL_YEAR_RE = re.compile(r'上映日期：\s*(\d{4})', re.I)
    _MAGNET_RE = re.compile(r'<a\s+href=["\'](magnet:\?xt=urn:btih:([A-Fa-f0-9]{40}))', re.I)

    def __init__(self, proxy: Any = None, timeout: int = 20, max_candidates: int = 3,
                 min_interval_seconds: int = 3) -> None:
        self.timeout = max(5, min(int(timeout or 20), 60))
        self.max_candidates = max(1, min(int(max_candidates or 3), 5))
        self.min_interval_seconds = max(2, min(int(min_interval_seconds or 3), 30))
        self._proxies = proxy if isinstance(proxy, dict) else ({"http": proxy, "https": proxy} if proxy else None)
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": self.USER_AGENT, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"})
        self._blocked = False
        self._last_request_at = 0.0

    @property
    def blocked(self) -> bool:
        return self._blocked

    def begin_run(self) -> None:
        self._blocked = False

    def _pace(self) -> None:
        delay = self.min_interval_seconds - (time.monotonic() - self._last_request_at)
        if delay > 0:
            time.sleep(delay)
        self._last_request_at = time.monotonic()

    def _request(self, method: str, path: str, **kwargs) -> Optional[requests.Response]:
        if self._blocked:
            return None
        self._pace()
        try:
            response = self._session.request(method, f'{self.BASE_URL}{path}', timeout=self.timeout,
                                             proxies=self._proxies, allow_redirects=False, **kwargs)
        except requests.RequestException as exc:
            logger.warning(f'磁力熊请求失败：{type(exc).__name__}')
            return None
        if response.status_code in {403, 429} or response.status_code >= 500:
            self._blocked = True
            logger.warning(f'磁力熊访问受限或服务异常：HTTP {response.status_code}，本轮停止请求')
            return None
        if response.status_code != 200:
            logger.warning(f'磁力熊请求失败：HTTP {response.status_code}')
            return None
        return response

    @staticmethod
    def _text(value: str) -> str:
        return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', '', value or ''))).strip()

    @staticmethod
    def _type_path(media_type: MediaType) -> str:
        return 'drama' if media_type == MediaType.TV else 'movie'

    @classmethod
    def _parse_cards(cls, body: str, media_type: MediaType) -> List[Tuple[str, str, int]]:
        expected = cls._type_path(media_type)
        output, seen = [], set()
        for match in cls._CARD_RE.finditer(body or ''):
            path, title = match.group('path'), cls._text(match.group('title'))
            parsed = cls._PAGE_RE.fullmatch(path)
            if not parsed or parsed.group(1).lower() != expected or path in seen or not title:
                continue
            seen.add(path)
            output.append((path, title, int(match.group('year'))))
        return output

    @staticmethod
    def _title_matches(mediainfo, candidate: str) -> bool:
        def norm(value):
            return re.sub(r'[^\w\u4e00-\u9fff]+', '', str(value or '')).casefold()
        actual = norm(candidate)
        titles = {norm(getattr(mediainfo, field, '')) for field in ('title', 'original_title')}
        return any(title and (title in actual or actual in title) and min(len(title), len(actual)) >= 3 for title in titles)

    def list_resources(self, mediainfo, media_type: MediaType) -> List[Dict[str, Any]]:
        """低频搜索，并仅返回标题、年份、类型都可初步确认的详情页候选。"""
        if self._blocked:
            return []
        year = int(getattr(mediainfo, 'year', 0) or 0)
        terms, cards = [], []
        for value in (getattr(mediainfo, 'title', ''), getattr(mediainfo, 'original_title', '')):
            value = str(value or '').strip()
            if value and value.casefold() not in {term.casefold() for term in terms}:
                terms.append(value)
        for term in terms[:2]:
            response = self._request('POST', self.SEARCH_PATH, data={
                'classid': '1,2', 'show': 'title', 'tempid': '1', 'keyboard': term,
            })
            if not response:
                break
            cards.extend(self._parse_cards(response.text, media_type))
            if cards:
                break
        output, seen = [], set()
        for path, title, card_year in cards:
            if path in seen or not self._title_matches(mediainfo, title) or (year and card_year != year):
                continue
            seen.add(path)
            response = self._request('GET', path)
            if not response:
                break
            detail_title = self._text((self._DETAIL_TITLE_RE.search(response.text) or [None, ''])[1])
            detail_year = self._DETAIL_YEAR_RE.search(response.text)
            if not self._title_matches(mediainfo, detail_title) or (year and (not detail_year or int(detail_year.group(1)) != year)):
                continue
            magnets = []
            for match in self._MAGNET_RE.finditer(response.text):
                if match.group(2).lower() not in {item['btih'] for item in magnets}:
                    magnets.append({'magnet': match.group(1), 'btih': match.group(2).lower()})
            if magnets:
                output.append({'source': 'cilixiong', 'detail_path': path, 'title': detail_title,
                               'year': card_year, 'media_type': self._type_path(media_type), 'magnets': magnets})
            if len(output) >= self.max_candidates:
                break
        logger.info(f'磁力熊：初步匹配候选 {len(output)} 条')
        return output
