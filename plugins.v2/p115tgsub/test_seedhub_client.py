"""SeedHub 公开页面解析最小回归测试。"""
import base64
import importlib.util
import sys
import types
from pathlib import Path


class _Logger:
    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass


sys.modules.setdefault("app", types.ModuleType("app"))
app_log = types.ModuleType("app.log")
app_log.logger = _Logger()
sys.modules.setdefault("app.log", app_log)

requests_stub = types.ModuleType("requests")
requests_stub.RequestException = Exception
requests_stub.Session = lambda: None
sys.modules.setdefault("requests", requests_stub)

MODULE_PATH = Path(__file__).parent / "clients" / "seedhub.py"
spec = importlib.util.spec_from_file_location("seedhub_test", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
SeedHubClient = module.SeedHubClient


def test_seed_list_and_base64_magnet_contract():
    html = '''
    <ul class="seeds"><li>
      <a title="测试剧集[全12集].Test.Show.S01.2026.2160p.WEB-DL.H265.DV" href="/link_start/?seed_id=12345&amp;movie_title=测试">测试</a>
      <code class="size">12GB</code><code class="seed-feature">4K</code><code class="seed-feature">杜比</code>
      <span class="create-time">2026-08-30 00:01</span>
    </li></ul>'''
    items = SeedHubClient.parse_seed_list(html, "9988")
    assert items == [{
        "source": "seedhub", "movie_id": "9988", "seed_id": "12345",
        "title": "测试剧集[全12集].Test.Show.S01.2026.2160p.WEB-DL.H265.DV",
        "file_name": "测试剧集[全12集].Test.Show.S01.2026.2160p.WEB-DL.H265.DV",
        "size": "12GB", "features": ["4K", "杜比"], "updated_at": "2026-08-30 00:01",
        "link_path": "/link_start/?seed_id=12345&movie_title=测试",
    }]
    magnet = "magnet:?xt=urn:btih:abcdef&dn=Test.Show.S01E01-E12"
    data = base64.b64encode(magnet.encode()).decode()
    assert SeedHubClient.parse_magnet_page(f'<script>const data = "{data}";</script>') == magnet
    assert SeedHubClient.parse_magnet_page('<script>const data = "aHR0cHM6Ly9leGFtcGxlLmNvbS8=";</script>') == ""


def test_only_public_numeric_movie_page_is_accepted():
    assert SeedHubClient.movie_id_from_url("https://sidhub.cc/movies/127534/") == "127534"
    assert SeedHubClient.movie_id_from_url("https://sidhub.cc/link_start/?seed_id=1") == ""
    assert SeedHubClient.movie_id_from_url("https://evil.example/movies/127534/") == ""


class _Response:
    def __init__(self, status_code, text=""):
        self.status_code = status_code
        self.text = text


class _Session:
    def __init__(self, response):
        self.headers = {}
        self.response = response
        self.calls = 0

    def get(self, *args, **kwargs):
        self.calls += 1
        return self.response


def test_seedhub_access_limit_stops_remaining_requests():
    client = object.__new__(SeedHubClient)
    client.timeout = 20
    client._proxies = None
    client._page_cache = {}
    client._blocked = False
    client._blocked_status = 0
    session = _Session(_Response(429))
    client._session = session
    assert client._get("https://sidhub.cc/movies/1/") is None
    assert client.blocked
    assert client._get("https://sidhub.cc/movies/2/") is None
    assert session.calls == 1


if __name__ == "__main__":
    test_seed_list_and_base64_magnet_contract()
    test_only_public_numeric_movie_page_is_accepted()
    test_seedhub_access_limit_stops_remaining_requests()
    print("seedhub client tests: OK")
