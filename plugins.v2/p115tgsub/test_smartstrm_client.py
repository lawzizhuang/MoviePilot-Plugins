"""SmartStrm Webhook 客户端的离线契约测试，不访问真实 Webhook。"""
import importlib.util
import sys
import types
from pathlib import Path


class _Logger:
    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
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

MODULE_PATH = Path(__file__).parent / "clients" / "smartstrm.py"
spec = importlib.util.spec_from_file_location("smartstrm", MODULE_PATH)
smartstrm = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = smartstrm
spec.loader.exec_module(smartstrm)
SmartStrmClient = smartstrm.SmartStrmClient


class _Response:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self.text = body

    def json(self):
        import json
        return json.loads(self.text)


class _Session:
    def __init__(self):
        self.requests = []

    def get(self, url, **kwargs):
        self.requests.append(("GET", url))
        return _Response(200, '{"success": true, "version": "0.9.9"}')

    def post(self, url, json=None, **kwargs):
        self.requests.append(("POST", url, json))
        return _Response(200, '{"success": true, "task": {"name": "tv", "storage_path": "/quark/TG"}}')


def test_connection_detection():
    session = _Session()
    client = SmartStrmClient("https://smartstrm.example/api/webhook/abc")
    client._session = session
    result = client.check_connection()
    assert result["success"] is True
    assert session.requests[0][0] == "GET"
    # 描述信息不包含 token
    description = client._describe()
    assert "abc" not in description and "token" not in description


def test_trigger_incremental_payload():
    session = _Session()
    client = SmartStrmClient("https://smartstrm.example/api/webhook/abc", timeout=10)
    client._session = session
    result = client.trigger_incremental(strmtask="tv,movie", savepath="/夸克接收/MoviePilot-TG/TV/剧集 (2026)/Season 1")
    assert result["success"] is True
    method, url, payload = session.requests[-1]
    assert method == "POST"
    assert url == "https://smartstrm.example/api/webhook/abc"
    assert payload["event"] == "qas_strm"
    assert payload["data"]["strmtask"] == "tv,movie"
    assert "夸克接收" in payload["data"]["savepath"]
    assert payload["data"]["xlist_path_fix"] == ""


def test_trigger_requires_task_and_path():
    client = SmartStrmClient("https://smartstrm.example/api/webhook/abc")
    assert client.trigger_incremental(strmtask="", savepath="/x")["success"] is False
    assert client.trigger_incremental(strmtask="tv", savepath="")["success"] is False
    assert SmartStrmClient("").trigger_incremental(strmtask="tv", savepath="/x")["success"] is False


if __name__ == "__main__":
    test_connection_detection()
    test_trigger_incremental_payload()
    test_trigger_requires_task_and_path()
    print("smartstrm client tests: OK")
