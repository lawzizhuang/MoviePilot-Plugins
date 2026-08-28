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
        self.directory_items = {"0": []}  # parent_id -> [raw items]
        self.path_fids = {"/": "0"}

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
        if endpoint == "file/info/path_list":
            paths = kwargs["json_data"]["file_path"]
            entries = [
                {"fid": self.path_fids[path], "file_path": path, "dir": True}
                for path in paths if path in self.path_fids
            ]
            return {"status": 2000000, "code": 0, "data": entries}
        if endpoint == "file/sort":
            parent_id = str(kwargs["params"].get("pdir_fid") or "0")
            return {"status": 2000000, "code": 0, "data": {"list": self.directory_items.get(parent_id, [])}}
        if endpoint == "file":
            payload = kwargs["json_data"]
            assert payload["pdir_fid"] == "0"
            assert payload["file_name"] == ""
            path = payload["dir_path"]
            fid = self.path_fids.setdefault(path, f"dir-{len(self.path_fids)}")
            self.directory_items.setdefault(fid, [])
            return {
                "status": 2000000, "code": 0,
                "data": {"fid": fid, "file_path": path, "dir": True},
            }
        if endpoint == "share/sharepage/save":
            self.saved_payloads.append(kwargs["json_data"])
            target = str(kwargs["json_data"]["to_pdir_fid"])
            for fid in kwargs["json_data"]["fid_list"]:
                self.directory_items.setdefault(target, []).append(
                    {"fid": fid, "file_name": f"测试剧集.S01E01.1080p.mkv" if fid == "video-1" else f"file-{fid}.mkv", "file_type": 1, "size": 1024}
                )
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
    detail_call = next(call for call in client.calls if call[1] == "share/sharepage/detail")
    assert detail_call[2]["params"]["ver"] == "2"
    assert detail_call[2]["params"]["_size"] == 1
    assert detail_call[2]["retries"] == 0
    token_call = next(call for call in client.calls if call[1] == "share/sharepage/token")
    assert token_call[2]["retries"] == 0
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
    assert payload["pdir_fid"] == "0"


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


def test_get_pid_list_files_and_confirm_exist():
    client = _FakeQuarkClient()
    url = "https://pan.quark.cn/s/AbC123?pwd=aB12"
    # 完整路径解析/创建（兼容 FileMatcher.check_existing_episodes 的 -1 语义）
    assert client.get_pid_by_path("/不存在/目录", mkdir=False) == -1
    dir_id = client.get_pid_by_path("/夸克接收/TG/TV", mkdir=True)
    assert dir_id and dir_id != -1
    path_call = next(call for call in client.calls if call[1] == "file/info/path_list")
    assert path_call[2]["json_data"] == {"file_path": ["/不存在/目录"], "namespace": "0"}
    mkdir_call = next(call for call in client.calls if call[1] == "file")
    assert mkdir_call[2]["json_data"]["dir_path"] == "/夸克接收/TG/TV"
    assert client.list_files("/夸克接收/TG/TV") == []
    # 转存后二次确认
    success, failed = client.transfer_files_batch(url, ["video-1"], "/夸克接收/TG/TV")
    assert success == ["video-1"]
    confirmed = client.confirm_files_exist("/夸克接收/TG/TV", ["测试剧集.S01E01.1080p.mkv"])
    assert confirmed == {"测试剧集.S01E01.1080p.mkv"}
    files = client.list_files("/夸克接收/TG/TV")
    assert files[0]["n"] == "测试剧集.S01E01.1080p.mkv"
    assert files[0]["fid"] != "0"


def test_confirm_files_exist_unconfirmed_returns_empty():
    client = _FakeQuarkClient()
    # 未转存过任何文件时，二次确认返回空集合
    confirmed = client.confirm_files_exist("/不存在/目录", ["不存在.mkv"], retries=1)
    assert confirmed == set()


def test_empty_response_is_not_success():
    assert not QuarkShareClient._is_success({})
    assert QuarkShareClient._is_success({"status": 2000000, "code": 0, "data": {}})


def test_skip_other_season_directory():
    assert QuarkShareClient._should_skip_season_dir("Season 2", 1)
    assert not QuarkShareClient._should_skip_season_dir("Season 1", 1)
    assert not QuarkShareClient._should_skip_season_dir("合集", 1)


class _PagedQuarkClient(_FakeQuarkClient):
    def _request(self, method, endpoint, **kwargs):
        if endpoint == "file/sort":
            page = int(kwargs["params"].get("_page") or 1)
            return {
                "status": 2000000, "code": 0,
                "data": {"list": [{"fid": f"file-{page}", "file_name": f"f{page}.mkv", "file_type": 1}]},
                "metadata": {"_total": 2},
            }
        return super()._request(method, endpoint, **kwargs)


def test_explicit_dir_field_overrides_file_type_fallback():
    directory = QuarkShareClient._to_file({"fid": "d", "file_name": "目录", "dir": True, "file_type": 1})
    file_item = QuarkShareClient._to_file({"fid": "f", "file_name": "文件.mkv", "dir": False, "file_type": 0})
    assert directory["is_dir"] is True
    assert file_item["is_dir"] is False


def test_metadata_total_drives_pagination():
    client = _PagedQuarkClient()
    entries = client._list_personal_directory("0")
    assert [entry["name"] for entry in entries] == ["f1.mkv", "f2.mkv"]


def test_empty_page_stops_even_when_server_total_is_incorrect():
    response = {"status": 2000000, "code": 0, "data": {"list": []}, "metadata": {"_total": 99}}
    assert not QuarkShareClient._has_more_pages(response, received=0, loaded=0, page_size=50)


def test_http_error_response_is_never_success():
    assert not QuarkShareClient._is_success({"status": 500, "code": 500, "data": {}})


class _HttpErrorSession:
    class Response:
        status_code = 429
        text = '{"status": 2000000, "code": 0, "message": "请求频繁"}'

        @staticmethod
        def json():
            return {"status": 2000000, "code": 0, "message": "请求频繁"}

    def request(self, *args, **kwargs):
        return self.Response()


def test_http_error_body_cannot_become_success():
    client = QuarkShareClient("test-cookie", min_interval=0.0)
    client._session = _HttpErrorSession()
    response = client._request("GET", "member", retries=0)
    assert response["status"] == 429 and response["code"] == 429
    assert not client._is_success(response)


def test_share_failure_categories_are_safe_and_specific():
    assert QuarkShareClient._classify_share_error({"status": -1, "code": -1}) == "network_error"
    assert QuarkShareClient._classify_share_error({"status": 403, "message": "提取码错误"}) == "password_invalid"
    assert QuarkShareClient._classify_share_error({"status": 404, "message": "分享不存在"}) == "share_expired"
    assert QuarkShareClient._classify_share_error({"status": 429, "message": "请求频繁"}) == "risk_limited"


if __name__ == "__main__":
    test_extract_share_info()
    test_read_and_save_selected_file()
    test_risk_response_stops_remaining_batches()
    test_get_pid_list_files_and_confirm_exist()
    test_confirm_files_exist_unconfirmed_returns_empty()
    test_empty_response_is_not_success()
    test_skip_other_season_directory()
    test_explicit_dir_field_overrides_file_type_fallback()
    test_metadata_total_drives_pagination()
    test_empty_page_stops_even_when_server_total_is_incorrect()
    test_http_error_response_is_never_success()
    test_http_error_body_cannot_become_success()
    test_share_failure_categories_are_safe_and_specific()
    print("quark share client tests: OK")
