"""Telegram 公开页解析的最小回归测试。"""
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

class _RequestsSessionStub:
    def __init__(self):
        self.headers = {}


requests_stub = types.ModuleType("requests")
requests_stub.RequestException = Exception
requests_stub.Session = _RequestsSessionStub
sys.modules.setdefault("requests", requests_stub)

MODULE_PATH = Path(__file__).parent / "clients" / "telegram_web.py"
spec = importlib.util.spec_from_file_location("telegram_web", MODULE_PATH)
telegram_web = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = telegram_web
spec.loader.exec_module(telegram_web)
TelegramWebClient = telegram_web.TelegramWebClient


class _Response:
    status_code = 200

    def __init__(self, text):
        self.text = text


class _Session:
    headers = {}

    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(url)
        return _Response(self.pages[url])


def test_direct_and_telegraph_115_links_are_extracted():
    search_url = "https://t.me/s/QukanMovie?q=%E4%B8%89%E4%BD%93"
    telegraph_url = "https://telegra.ph/example-resource"
    search_html = '''
    <div class="tgme_widget_message_wrap">
      <div class="tgme_widget_message" data-post="QukanMovie/10">
        <div class="tgme_widget_message_text">三体 (2023) <a href="https://115cdn.com/s/direct?password=a1b2">链接</a></div>
        <time datetime="2026-01-01T00:00:00+00:00"></time>
      </div>
    </div>
    <div class="tgme_widget_message_wrap">
      <div class="tgme_widget_message" data-post="QukanMovie/11">
        <div class="tgme_widget_message_text">三体 资源 <a href="https://telegra.ph/example-resource">📎 查看资源</a></div>
      </div>
    </div>
    '''
    telegraph_html = "<article>资源链接 https://115cdn.com/s/telegraph?password=c3d4# 说明</article>"
    client = TelegramWebClient(["QukanMovie"], max_results_per_channel=10, max_telegraph_pages=2)
    client._session = _Session({search_url: search_html, telegraph_url: telegraph_html})

    results = client.search_115_resources("三体")

    assert [item["url"] for item in results] == [
        "https://115cdn.com/s/direct?password=a1b2",
        "https://115cdn.com/s/telegraph?password=c3d4",
    ]
    assert results[0]["message_url"] == "https://t.me/QukanMovie/10"


def test_mixed_cloud_links_only_keep_115():
    assert TelegramWebClient._extract_urls(
        "https://pan.quark.cn/s/abc https://115.com/s/xyz?password=1234"
    ) == ["https://115.com/s/xyz?password=1234"]


def test_parser_keeps_multiple_messages_with_void_tags():
    html = '''
    <div class="tgme_widget_message_wrap">
      <div class="tgme_widget_message" data-post="QukanMovie/10">
        <div class="tgme_widget_message_text">第一条 <a href="https://115.com/s/one">资源</a><img src="cover.jpg"></div>
      </div>
    </div>
    <div class="tgme_widget_message_wrap">
      <div class="tgme_widget_message" data-post="QukanMovie/11">
        <div class="tgme_widget_message_text">第二条 <a href="https://115.com/s/two">资源</a></div>
      </div>
    </div>
    '''
    parser = telegram_web._TelegramSearchPageParser()
    parser.feed(html)
    parser.close()

    assert [item["post"] for item in parser.messages] == ["QukanMovie/10", "QukanMovie/11"]
    assert [item["links"] for item in parser.messages] == [
        ["https://115.com/s/one"],
        ["https://115.com/s/two"],
    ]


def test_title_filter_runs_before_result_limit():
    search_url = "https://t.me/s/QukanMovie?q=%E5%A4%9C%E7%8E%8B%202026"
    search_html = '''
    <div class="tgme_widget_message_wrap"><div class="tgme_widget_message" data-post="QukanMovie/1">
      <div class="tgme_widget_message_text">昨夜将至 (2026) <a href="https://115.com/s/wrong">资源</a></div>
    </div></div>
    <div class="tgme_widget_message_wrap"><div class="tgme_widget_message" data-post="QukanMovie/2">
      <div class="tgme_widget_message_text">夜王 (2026) <a href="https://115.com/s/right">资源</a></div>
    </div></div>
    '''
    client = TelegramWebClient(["QukanMovie"], max_results_per_channel=1)
    client._session = _Session({search_url: search_html})

    results = client.search_115_resources("夜王 2026", required_title="夜王")

    assert [item["message_id"] for item in results] == ["2"]
    assert [item["url"] for item in results] == ["https://115.com/s/right"]


def test_quark_links_are_extracted_and_password_in_text():
    search_url = "https://t.me/s/QukanMovie?q=%E4%B8%89%E4%BD%93"
    search_html = '''
    <div class="tgme_widget_message_wrap"><div class="tgme_widget_message" data-post="QukanMovie/3">
      <div class="tgme_widget_message_text">三体 (2026) 提取码：aB12
        <a href="https://pan.quark.cn/s/Qk123456">夸克</a>
        <a href="https://115.com/s/ignore">115</a>
      </div>
    </div></div>
    '''
    client = TelegramWebClient(["QukanMovie"])
    client._session = _Session({search_url: search_html})

    results = client.search_quark_resources("三体", required_title="三体")

    assert len(results) == 1
    assert results[0]["url"] == "https://pan.quark.cn/s/Qk123456"
    assert "提取码：aB12" in results[0]["text"]
    # 115 源不受影响，且不包含夸克链接
    assert client.search_115_resources("三体", required_title="三体")[0]["url"] == "https://115.com/s/ignore"


def test_quark_url_with_query_password():
    client = TelegramWebClient(["QukanMovie"])
    assert client._extract_quark_urls("https://pan.quark.cn/s/Qk654321?pwd=cd34", []) == [
        "https://pan.quark.cn/s/Qk654321?pwd=cd34"
    ]
    assert client._extract_urls("https://pan.quark.cn/s/Qk654321?pwd=cd34", []) == []


def test_direct_ed2k_and_magnet_are_extracted_from_message_body():
    ed2k = "ed2k://|file|测试剧集.2026.S01E02.1080p.mkv|1024|0123456789abcdef0123456789abcdef|/"
    magnet = "magnet:?xt=urn:btih:abcdef&dn=%E6%B5%8B%E8%AF%95%E5%89%A7%E9%9B%86.S01E03.mkv"
    assert TelegramWebClient._extract_offline_urls(f"ED2K:{ed2k}\n{magnet}") == [ed2k, magnet]
    assert TelegramWebClient._extract_offline_urls("", [magnet]) == [magnet]


def test_quark_duplicate_keeps_access_code_variants_and_counts_merge():
    search_url_a = "https://t.me/s/Aaaaa?q=%E4%B8%89%E4%BD%93"
    search_url_b = "https://t.me/s/Bbbbb?q=%E4%B8%89%E4%BD%93"
    html_a = '''<div class="tgme_widget_message" data-post="Aaaaa/1">
      <div class="tgme_widget_message_text">三体 提取码：aB12 <a href="https://pan.quark.cn/s/Same123">链接</a></div></div>'''
    html_b = '''<div class="tgme_widget_message" data-post="Bbbbb/1">
      <div class="tgme_widget_message_text">三体 提取码：aB12 <a href="https://pan.quark.cn/s/Same123">链接</a></div></div>
      <div class="tgme_widget_message" data-post="Bbbbb/2">
      <div class="tgme_widget_message_text">三体 提取码：cD34 <a href="https://pan.quark.cn/s/Same123">链接</a></div></div>'''
    client = TelegramWebClient(["Aaaaa", "Bbbbb"])
    client._session = _Session({search_url_a: html_a, search_url_b: html_b})
    results = client.search_quark_resources("三体", required_title="三体")
    assert len(results) == 2
    assert client.get_search_stats() == {"raw_candidates": 3, "duplicates_merged": 1}


def test_seedhub_movie_page_is_extracted_from_designated_message():
    movie_url = "https://sidhub.cc/movies/127534/"
    assert TelegramWebClient._extract_seedhub_movie_urls("详情：" + movie_url) == [movie_url]
    assert TelegramWebClient._extract_seedhub_movie_urls("https://sidhub.cc/link_start/?seed_id=1") == []


def test_telegraph_quark_link_and_access_code_are_extracted():
    search_url = "https://t.me/s/QukanMovie?q=%E4%B8%89%E4%BD%93"
    telegraph_url = "https://telegra.ph/quark-resource"
    search_html = f'''
    <div class="tgme_widget_message_wrap"><div class="tgme_widget_message" data-post="QukanMovie/4">
      <div class="tgme_widget_message_text">三体 (2026) <a href="{telegraph_url}">查看资源</a></div>
    </div></div>
    '''
    telegraph_html = '''
    <article>访问码：Zx90 <a href="https://pan.quark.cn/s/QkTelegraph">夸克资源</a></article>
    '''
    client = TelegramWebClient(["QukanMovie"])
    session = _Session({search_url: search_html, telegraph_url: telegraph_html})
    client._session = session

    results = client.search_quark_resources("三体", required_title="三体")

    assert results[0]["url"] == "https://pan.quark.cn/s/QkTelegraph"
    assert "访问码：Zx90" in results[0]["text"]
    # 同步轮内随后搜索 115 时复用 Telegram 搜索页缓存，不重复发起该 URL 请求。
    client.search_115_resources("三体", required_title="三体")
    assert session.calls.count(search_url) == 1


def test_single_character_title_can_follow_telegraph():
    search_url = "https://t.me/s/QukanMovie?q=%E8%9D%89"
    telegraph_url = "https://telegra.ph/single-title"
    search_html = f'''
    <div class="tgme_widget_message_wrap"><div class="tgme_widget_message" data-post="QukanMovie/5">
      <div class="tgme_widget_message_text">蝉 (2026) <a href="{telegraph_url}">查看资源</a></div>
    </div></div>
    '''
    telegraph_html = '<a href="https://pan.quark.cn/s/QkSingle">夸克</a>'
    client = TelegramWebClient(["QukanMovie"])
    client._session = _Session({search_url: search_html, telegraph_url: telegraph_html})
    results = client.search_quark_resources("蝉", required_title="蝉")
    assert results[0]["url"] == "https://pan.quark.cn/s/QkSingle"


def test_search_logs_all_configured_channel_requests():
    first_url = "https://t.me/s/QukanMovie?q=%E4%B8%89%E4%BD%93"
    second_url = "https://t.me/s/regeng115?q=%E4%B8%89%E4%BD%93"
    html = '<div class="tgme_widget_message_wrap"><div class="tgme_widget_message" data-post="QukanMovie/1"><div class="tgme_widget_message_text">三体</div></div></div>'
    client = TelegramWebClient(["QukanMovie", "regeng115"])
    session = _Session({first_url: html, second_url: html})
    client._session = session
    assert client.search_offline_resources("三体", required_title="三体") == []
    assert session.calls == [first_url, second_url]


if __name__ == "__main__":
    test_direct_and_telegraph_115_links_are_extracted()
    test_mixed_cloud_links_only_keep_115()
    test_parser_keeps_multiple_messages_with_void_tags()
    test_title_filter_runs_before_result_limit()
    test_quark_links_are_extracted_and_password_in_text()
    test_quark_url_with_query_password()
    test_direct_ed2k_and_magnet_are_extracted_from_message_body()
    test_seedhub_movie_page_is_extracted_from_designated_message()
    test_quark_duplicate_keeps_access_code_variants_and_counts_merge()
    test_telegraph_quark_link_and_access_code_are_extracted()
    test_single_character_title_can_follow_telegraph()
    test_search_logs_all_configured_channel_requests()
    print("telegram_web parser tests: OK")
