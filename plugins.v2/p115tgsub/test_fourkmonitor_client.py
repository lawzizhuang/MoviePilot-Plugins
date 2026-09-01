"""4K Monitor 匿名免费资源客户端最小回归测试。"""
import importlib.util
import json
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
app_schemas = types.ModuleType("app.schemas")
app_schemas_types = types.ModuleType("app.schemas.types")


class _MediaType:
    MOVIE = "movie"
    TV = "tv"


app_schemas_types.MediaType = _MediaType
sys.modules.setdefault("app.schemas", app_schemas)
sys.modules.setdefault("app.schemas.types", app_schemas_types)

MODULE_PATH = Path(__file__).parent / "clients" / "fourkmonitor.py"
spec = importlib.util.spec_from_file_location("fourkmonitor_test", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
FourKMonitorClient = module.FourKMonitorClient


def _free_item(**overrides):
    item = {
        "id": 101, "tmdb_id": 1471168, "tmdb_type": "movie",
        "title": "测试电影 (2026) 2160p WEB-DL", "tmdb_name": "测试电影",
        "tmdb_original_name": "Test Movie", "detail_url": "/detail/101-test-movie-2026-4k",
        "access_tier": "free", "credit_cost": 0, "is_locked": False, "access_allowed": True,
        "source_type": "Web-DL", "quality_tier": "4K", "hdr_format": "HDR",
        "audio_format": "DDP", "video_codec": "HEVC", "file_size": "10 GB",
        "file_size_bytes": 10 * 1024 ** 3, "seeders": 5,
    }
    item.update(overrides)
    return item


def test_only_exact_tmdb_free_unlocked_candidate_is_normalized():
    client = FourKMonitorClient(max_candidates=3)
    resource = client._normalize_resource(_free_item(), 1471168, "movie")
    assert resource["source"] == "4kmonitor"
    assert resource["resource_id"] == "101"
    assert resource["match_titles"] == ["测试电影 (2026) 2160p WEB-DL", "测试电影", "Test Movie"]
    assert client._normalize_resource(_free_item(credit_cost=3, is_locked=True), 1471168, "movie") is None
    assert client._normalize_resource(_free_item(tmdb_id=1), 1471168, "movie") is None
    assert client._normalize_resource(_free_item(tmdb_type="tv"), 1471168, "movie") is None
    assert client._normalize_resource(_free_item(detail_url="https://evil.example/detail/101"), 1471168, "movie") is None


class _Response:
    def __init__(self, status_code, *, json_data=None, text="", headers=None):
        self.status_code = status_code
        self._json_data = json_data
        self.text = text
        self.headers = headers or {}

    def json(self):
        return self._json_data


class _Session:
    def __init__(self, responses):
        self.headers = {}
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


def test_access_limit_stops_remaining_requests():
    client = FourKMonitorClient()
    client._session = _Session([_Response(429)])
    client._pace = lambda: None
    assert client._get("/api/resources") is None
    assert client.blocked
    assert client._get("/api/resources") is None
    assert len(client._session.calls) == 1


def test_magnet_is_resolved_only_after_detail_reconfirms_free_access():
    token = "/m/signed-token"
    detail = {
        "resourceId": 101, "magnetActionUrl": token,
        "initialAccess": {"access_tier": "free", "credit_cost": 0, "is_locked": False, "access_allowed": True},
    }
    client = FourKMonitorClient()
    client._session = _Session([
        _Response(200, text=f'<script id="detail-bootstrap" type="application/json">{json.dumps(detail)}</script>'),
        _Response(302, headers={"Location": "magnet:?xt=urn:btih:abc&dn=test"}),
    ])
    client._pace = lambda: None
    resource = client._normalize_resource(_free_item(), 1471168, "movie")
    assert client.resolve_magnet(resource).startswith("magnet:?")
    assert len(client._session.calls) == 2


if __name__ == "__main__":
    test_only_exact_tmdb_free_unlocked_candidate_is_normalized()
    test_access_limit_stops_remaining_requests()
    test_magnet_is_resolved_only_after_detail_reconfirms_free_access()
    print("4kmonitor client tests: OK")
