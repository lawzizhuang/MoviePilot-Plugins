"""SearchHandler 缺集定向 Telegram 关键词回归测试。"""
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
sys.modules["app.log"] = app_log
schemas = types.ModuleType("app.schemas")
schemas.MediaInfo = object
sys.modules["app.schemas"] = schemas
types_module = types.ModuleType("app.schemas.types")
types_module.MediaType = types.SimpleNamespace(TV="电视剧", MOVIE="电影")
sys.modules["app.schemas.types"] = types_module

MODULE_PATH = Path(__file__).parent / "handlers" / "search.py"
spec = importlib.util.spec_from_file_location("p115tgsub_search_test", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
SearchHandler = module.SearchHandler
MediaType = types_module.MediaType


def test_tv_missing_episode_keywords_are_prioritized():
    media = types.SimpleNamespace(title="师兄太稳健", year="2026")
    assert SearchHandler._build_keywords(media, MediaType.TV, 1, [25]) == [
        "师兄太稳健 S01E25", "师兄太稳健 2026", "师兄太稳健"
    ]


def test_tv_many_missing_episodes_uses_generic_keywords_only():
    media = types.SimpleNamespace(title="测试剧", year="2026")
    assert SearchHandler._build_keywords(media, MediaType.TV, 1, [5, 1, 3, 4]) == [
        "测试剧 2026", "测试剧"
    ]


if __name__ == "__main__":
    test_tv_missing_episode_keywords_are_prioritized()
    test_tv_many_missing_episodes_uses_generic_keywords_only()
    print("p115tgsub search handler tests: OK")
