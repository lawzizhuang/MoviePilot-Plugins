"""夸克分享适配层的离线契约测试，不访问真实账号或分享。"""
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


if "app" not in sys.modules:
    sys.modules["app"] = types.ModuleType("app")
if "app.log" not in sys.modules:
    module = types.ModuleType("app.log")
    module.logger = _Logger()
    sys.modules["app.log"] = module

MODULE_PATH = Path(__file__).parent / "clients" / "quark.py"
spec = importlib.util.spec_from_file_location("p115tgsub_quark_test", MODULE_PATH)
quark_module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = quark_module
spec.loader.exec_module(quark_module)
QuarkShareClient = quark_module.QuarkShareClient


class _FakeQuarkClient(QuarkShareClient):
    def __init__(self):
        super().__init__("test-cookie", min_interval=0.2)
        self.calls = []
        self.saved_payloads = []

    def _request(self, method, endpoint, **kwargs):
        self.calls.append((method, endpoint, kwargs))
        if endpoint == "member":
            return {"status": 200, "code": 0, "data": {}}
        if endpoint == "share/sharepage/token":
            assert kwargs["json_data"]["passcode"] == "aB12"
            return {"status": 2000000, "code": 0, "data": {"stoken": "runtime-token"}}
        if endpoint == "share/sharepage/detail":
            parent_id = str(kwargs["params"].get("pdir_fid") or "0")
            if parent_id == "0":
                return {
                    "status": 2000000,
                    "code": 0,
                    "data": {
                        "total": 2,
                        "title": "测试资源",
                        "list": [
                            {"fid": "dir-1", "file_name": "Season 1", "file_type": 0},
                            {
                                "fid": "video-1", "file_name": "测试剧集.S01E01.1080p.mkv",
                                "file_type": 1, "size": 1024, "share_fid_token": "file-token-1",
                            },
                        ],
                    },
                }
            return {"status": 2000000, "code": 0, "data": {"list": []}}
        if endpoint == "file/sort":
            return {"status": 2000000, "code": 0, "data": {"list": []}}
        if endpoint == "file":
            return {"status": 2000000, "code": 0, "data": {"fid": "target-1", "file_name": "TG-Test", "file_type": 0}}
        if endpoint == "share/sharepage/save":
            self.saved_payloads.append(kwargs["json_data"])
            return {"status": 2000000, "code": 0, "data": {"task_id": "task-1"}}
        if endpoint == "task":
            return {"status": 2000000, "code": 0, "data": {"status": 2}}
        raise AssertionError(f"unexpected endpoint: {endpoint}")


def test_extract_share_info():
    info = QuarkShareClient.extract_share_info(
        "https://pan.quark.cn/s/AbC123?pwd=aB12"
    )
    assert info == {"share_id": "AbC123", "password": "aB12"}
    assert QuarkShareClient.extract_share_info("https://example.com/s/AbC123") == {}
    assert QuarkShareClient.extract_password("提取码：aB12") == "aB12"


def test_read_and_save_selected_file():
    client = _FakeQuarkClient()
    url = "https://pan.quark.cn/s/AbC123?pwd=aB12"
    assert client.check_login()
    status = client.check_share_status(url)
    assert status.is_valid and status.file_count == 2
    files = client.list_share_files(url)
    assert files[0]["is_dir"] is True
    assert files[1]["id"] == "video-1"
    success, failed = client.transfer_files_batch(url, ["video-1"], "/TG-Test")
    assert success == ["video-1"] and failed == []
    assert len(client.saved_payloads) == 1
    payload = client.saved_payloads[0]
    assert payload["fid_list"] == ["video-1"]
    assert payload["fid_token_list"] == ["file-token-1"]
    assert payload["stoken"] == "runtime-token"


def test_risk_response_stops_remaining_batches():
    client = _FakeQuarkClient()
    url = "https://pan.quark.cn/s/AbC123?pwd=aB12"
    original_save = client._save_shared_files

    def _risk(*args, **kwargs):
        return {"status": 500, "code": 500, "message": "请求频繁，请稍后再试", "data": {}}

    client._save_shared_files = _risk
    success, failed = client.transfer_files_batch(url, ["video-1"], "/TG-Test")
    assert success == [] and failed == ["video-1"]
    assert client.transfer_risk_blocked
    client._save_shared_files = original_save


if __name__ == "__main__":
    test_extract_share_info()
    test_read_and_save_selected_file()
    test_risk_response_stops_remaining_batches()
    print("quark share client tests: OK")
