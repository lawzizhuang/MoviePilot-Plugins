"""115 云下载指定目录的最小离线契约测试。"""
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

MODULE_PATH = Path(__file__).parent / "clients" / "p115.py"
spec = importlib.util.spec_from_file_location("p115_offline_test", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
P115ClientManager = module.P115ClientManager


class _Limiter:
    def wait(self):
        return None


class _Client:
    def __init__(self):
        self.payloads = []

    def clouddownload_task_add_url(self, payload):
        self.payloads.append(payload)
        return {"state": True}


class _ShareClient:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = 0

    def share_snap(self, payload):
        self.calls += 1
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


def _query_manager(client):
    manager = object.__new__(P115ClientManager)
    manager.client = client
    manager.rate_limiter = _Limiter()
    manager._api_call_count = 0
    manager._web_query_405_count = 0
    manager._web_query_blocked = False
    manager._share_info_cache = {}
    return manager


def test_offline_task_uses_configured_directory_cid():
    client = _Client()
    manager = object.__new__(P115ClientManager)
    manager.client = client
    manager.rate_limiter = _Limiter()
    manager._api_call_count = 0
    manager.get_pid_by_path = lambda path, mkdir=True: 987654

    ed2k = "ed2k://|file|测试剧集.S01E01.mkv|1024|0123456789abcdef0123456789abcdef|/"
    assert manager.submit_offline_task(ed2k, "/inbox/Follow/测试剧集 (2026)/Season 1")
    assert client.payloads == [{"url": ed2k, "wp_path_id": 987654}]
    assert manager.get_api_call_count() == 1
    assert ed2k not in manager.offline_resource_key(ed2k)


def test_share_status_retries_405_and_does_not_mark_share_invalid():
    manager = _query_manager(_ShareClient([Exception("HTTP Error 405: Method Not Allowed"), Exception("HTTP Error 405: Method Not Allowed")]))
    manager.extract_share_info = lambda url: {"share_code": "test", "receive_code": "code"}
    manager.READ_RETRY_DELAY = 0

    status = manager.check_share_status("https://115.com/s/redacted")

    assert status.is_valid is False
    assert status.is_transient_error is True
    assert status.error_kind == "transient_405"
    assert manager.client.calls == 2


def test_share_status_405_circuit_breaker_stops_followup_queries():
    manager = _query_manager(_ShareClient([Exception("HTTP Error 405: Method Not Allowed")] * 3))
    manager.extract_share_info = lambda url: {"share_code": "test", "receive_code": "code"}
    manager.READ_RETRY_ATTEMPTS = 1

    manager.check_share_status("https://115.com/s/redacted-a")
    manager.check_share_status("https://115.com/s/redacted-b")
    status = manager.check_share_status("https://115.com/s/redacted-c")

    assert manager.web_query_blocked is True
    assert status.is_transient_error is True
    assert manager.client.calls == 3


def test_circuit_breaker_blocks_all_web_read_queries():
    manager = _query_manager(_ShareClient([]))
    manager._web_query_blocked = True
    try:
        manager._read_query("path_id", lambda: {"id": 1})
    except RuntimeError as exc:
        assert "熔断" in str(exc)
    else:
        raise AssertionError("熔断后不应继续调用 Web 查询")


if __name__ == "__main__":
    test_offline_task_uses_configured_directory_cid()
    test_share_status_retries_405_and_does_not_mark_share_invalid()
    test_share_status_405_circuit_breaker_stops_followup_queries()
    test_circuit_breaker_blocks_all_web_read_queries()
    print("p115 offline client tests: OK")
