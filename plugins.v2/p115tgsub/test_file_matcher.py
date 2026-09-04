"""P115TGSub 文件身份匹配的最小回归测试。"""
import importlib.util
import sys
import types
from pathlib import Path


class _Logger:
    def info(self, *args, **kwargs):
        pass


sys.modules.setdefault("app", types.ModuleType("app"))
app_log = types.ModuleType("app.log")
app_log.logger = _Logger()
sys.modules.setdefault("app.log", app_log)
app_core = types.ModuleType("app.core")
sys.modules.setdefault("app.core", app_core)
metainfo = types.ModuleType("app.core.metainfo")
metainfo.MetaInfo = type("MetaInfo", (), {})
sys.modules.setdefault("app.core.metainfo", metainfo)
schemas = types.ModuleType("app.schemas")
schemas.MediaInfo = object
sys.modules.setdefault("app.schemas", schemas)

MODULE_PATH = Path(__file__).parent / "utils" / "file_matcher.py"
spec = importlib.util.spec_from_file_location("file_matcher", MODULE_PATH)
file_matcher = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = file_matcher
spec.loader.exec_module(file_matcher)
FileMatcher = file_matcher.FileMatcher


_GIB = 1024 * 1024 * 1024


def test_movie_file_rejects_unrelated_large_video():
    files = [{
        "name": "凡人修仙传.S01E189.2160p.WEB-DL.mkv",
        "is_dir": False,
        "size": 3 * _GIB,
    }]
    assert FileMatcher.match_movie_file(files, "新世界") is None


def test_movie_file_accepts_target_title_in_file_name():
    files = [{
        "name": "新世界.2013.2160p.BluRay.mkv",
        "is_dir": False,
        "size": 3 * _GIB,
    }]
    assert FileMatcher.match_movie_file(files, "新世界") == files[0]


def test_movie_file_accepts_target_title_in_parent_directory():
    video = {
        "name": "New.World.2013.2160p.BluRay.mkv",
        "is_dir": False,
        "size": 3 * _GIB,
    }
    files = [{"name": "新世界 (2013)", "is_dir": True, "children": [video]}]
    assert FileMatcher.match_movie_file(files, "新世界") == video


if __name__ == "__main__":
    test_movie_file_rejects_unrelated_large_video()
    test_movie_file_accepts_target_title_in_file_name()
    test_movie_file_accepts_target_title_in_parent_directory()
    print("p115tgsub file matcher tests: OK")
