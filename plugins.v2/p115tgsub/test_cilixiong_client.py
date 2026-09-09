"""磁力熊客户端解析与熔断回归；不访问真实站点。"""
import importlib.util
import sys
import types
from pathlib import Path

class Logger:
    def info(self, *args, **kwargs): pass
    def warning(self, *args, **kwargs): pass

sys.modules.setdefault('app', types.ModuleType('app'))
log = types.ModuleType('app.log'); log.logger = Logger(); sys.modules['app.log'] = log
types_mod = types.ModuleType('app.schemas.types')
class MediaType: MOVIE = 'movie'; TV = 'tv'
types_mod.MediaType = MediaType
sys.modules.setdefault('app.schemas', types.ModuleType('app.schemas'))
sys.modules['app.schemas.types'] = types_mod
spec = importlib.util.spec_from_file_location('cilixiong_test', Path(__file__).parent/'clients/cilixiong.py')
module = importlib.util.module_from_spec(spec); sys.modules[spec.name] = module; spec.loader.exec_module(module)
Client = module.CiLiXiongClient

class Response:
    def __init__(self, status, text=''): self.status_code, self.text = status, text
class Session:
    def __init__(self, values): self.values, self.headers, self.calls = list(values), {}, []
    def request(self, method, url, **kwargs): self.calls.append((method, url, kwargs)); return self.values.pop(0)
class Media:
    title = '测试电影'; original_title = 'Test Movie'; year = 2026

CARDS = '''<a href="/movie/12.html"><h2>测试电影</h2><li>2026</li></a>
<a href="/drama/13.html"><h2>测试剧集</h2><li>2026</li></a>'''
DETAIL = '''<h1>测试电影</h1><p>上映日期：2026-01-01</p>
<a href="magnet:?xt=urn:btih:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA">One</a>'''

def test_parse_only_expected_type_and_title_year():
    client = Client(max_candidates=3); client._pace = lambda: None
    client._session = Session([Response(200, CARDS), Response(200, DETAIL)])
    rows = client.list_resources(Media(), MediaType.MOVIE)
    assert len(rows) == 1 and rows[0]['detail_path'] == '/movie/12.html'
    assert rows[0]['magnets'][0]['btih'] == 'a'*40
    assert len(client._session.calls) == 2

def test_reject_wrong_year_and_block_stops_requests():
    client = Client(); client._pace = lambda: None
    client._session = Session([Response(200, CARDS.replace('2026', '2025'))])
    assert client.list_resources(Media(), MediaType.MOVIE) == []
    client = Client(); client._pace = lambda: None; client._session = Session([Response(429)])
    assert client._request('GET', '/') is None and client.blocked
    assert client._request('GET', '/') is None and len(client._session.calls) == 1

def test_reject_cross_type_and_unrelated_detail():
    assert Client._parse_cards(CARDS, MediaType.TV) == [('/drama/13.html', '测试剧集', 2026)]
    client = Client(); client._pace = lambda: None
    client._session = Session([Response(200, CARDS), Response(200, DETAIL.replace('测试电影', '其他电影'))])
    assert client.list_resources(Media(), MediaType.MOVIE) == []

if __name__ == '__main__':
    test_parse_only_expected_type_and_title_year()
    test_reject_wrong_year_and_block_stops_requests()
    test_reject_cross_type_and_unrelated_detail()
    print('cilixiong client tests: OK')
