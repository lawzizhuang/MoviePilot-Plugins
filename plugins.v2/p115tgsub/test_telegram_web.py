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

    def get(self, url, **kwargs):
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


if __name__ == "__main__":
    test_direct_and_telegraph_115_links_are_extracted()
    test_mixed_cloud_links_only_keep_115()
    test_parser_keeps_multiple_messages_with_void_tags()
    test_title_filter_runs_before_result_limit()
    print("telegram_web parser tests: OK")
