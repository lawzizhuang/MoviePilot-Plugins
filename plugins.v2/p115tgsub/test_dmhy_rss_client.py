"""DMHY RSS安全解析回归；不访问网络。"""
import importlib.util
import sys
import types
from pathlib import Path

class Logger:
    def info(self, *args, **kwargs): pass
    def warning(self, *args, **kwargs): pass
sys.modules.setdefault('app', types.ModuleType('app'))
log = types.ModuleType('app.log'); log.logger = Logger(); sys.modules['app.log'] = log
spec = importlib.util.spec_from_file_location('dmhy_test', Path(__file__).parent/'clients/dmhy_rss.py')
mod = importlib.util.module_from_spec(spec); sys.modules[spec.name] = mod; spec.loader.exec_module(mod)
Client = mod.DMHYRSSClient

XML = b'''<?xml version="1.0"?><rss><channel>
<item><title> [Group] Test Anime S02 - 03 </title><link>https://share.dmhy.org/topics/view/123_Test_Anime.html</link><pubDate>Thu, 10 Sep 2026 10:00:00 +0800</pubDate><enclosure url="magnet:?xt=urn:btih:ABCDEFGHIJKLMNOPQRSTUVWXYZ234567&amp;tr=https%3A%2F%2Fevil"/></item>
<item><title>duplicate</title><link>https://share.dmhy.org/topics/view/124_Test.html</link><enclosure url="magnet:?xt=urn:btih:ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"/></item>
<item><title>wrong link</title><link>https://evil.example/x</link><enclosure url="magnet:?xt=urn:btih:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"/></item>
<item><title>no hash</title><link>https://share.dmhy.org/topics/view/125_Test.html</link><enclosure url="magnet:?dn=x"/></item>
</channel></rss>'''
class Response:
    def __init__(self, status, content=b''): self.status_code, self.content = status, content
class Session:
    def __init__(self, responses): self.headers, self.responses, self.calls = {}, list(responses), []
    def get(self, url, **kwargs): self.calls.append(url); return self.responses.pop(0)

def test_parse_minimizes_and_deduplicates():
    rows = Client._parse(XML, 'anime')
    assert len(rows) == 1
    assert rows[0]['title'] == '[Group] Test Anime S02 - 03'
    assert rows[0]['magnet'] == 'magnet:?xt=urn:btih:ABCDEFGHIJKLMNOPQRSTUVWXYZ234567'
    assert rows[0]['published_at'].startswith('2026-09-10T02:00:00')
    assert 'evil' not in str(rows)

def test_cache_and_limits():
    client = Client(); client._pace = lambda: None; client._session = Session([Response(200, XML)])
    first, second = client.list_feed('anime'), client.list_feed('anime')
    assert len(first) == len(second) == 1 and len(client._session.calls) == 1
    try: client.list_feed('bad')
    except ValueError: pass
    else: raise AssertionError('未知分类不得请求')
    try: Client._parse(b'x'*(Client.MAX_BYTES+1), 'anime')
    except ValueError: pass
    else: raise AssertionError('超大正文不得解析')

def test_status_and_xml_failure_trip_circuit():
    client = Client(); client._pace = lambda: None; client._session = Session([Response(429)])
    assert client.list_feed('anime') == [] and client.blocked
    client = Client(); client._pace = lambda: None; client._session = Session([Response(200, b'<broken')])
    assert client.list_feed('anime') == [] and client.blocked

if __name__ == '__main__':
    test_parse_minimizes_and_deduplicates()
    test_cache_and_limits()
    test_status_and_xml_failure_trip_circuit()
    print('dmhy rss client tests: OK')
