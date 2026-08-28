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


if __name__ == "__main__":
    test_offline_task_uses_configured_directory_cid()
    print("p115 offline client tests: OK")
