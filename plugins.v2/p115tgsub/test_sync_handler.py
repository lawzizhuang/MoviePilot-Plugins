"""P115TGSub 同步逻辑的最小回归测试。"""
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


class _MediaInfo:
    def __init__(self, title):
        self.title = title


# 仅桩化导入 SyncHandler 所需的 MoviePilot 模块；测试目标是纯标题匹配与订阅集数回退逻辑。
sys.modules.setdefault("app", types.ModuleType("app"))
for name, attrs in {
    "app.core.config": {"global_vars": object()},
    "app.core.metainfo": {"MetaInfo": type("MetaInfo", (), {})},
    "app.chain.download": {"DownloadChain": type("DownloadChain", (), {})},
    "app.db": {"SessionFactory": object()},
    "app.db.subscribe_oper": {"SubscribeOper": type("SubscribeOper", (), {})},
    "app.db.downloadhistory_oper": {"DownloadHistoryOper": type("DownloadHistoryOper", (), {})},
    "app.log": {"logger": _Logger()},
    "app.schemas": {"MediaInfo": _MediaInfo},
    "app.schemas.types": {
        "MediaType": type("MediaType", (), {}),
        "NotificationType": type("NotificationType", (), {}),
    },
    "app.utils.string": {"StringUtils": type("StringUtils", (), {})},
}.items():
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules[name] = module

package_name = "p115tgsub_test"
package = types.ModuleType(package_name)
package.__path__ = []
sys.modules[package_name] = package
utils = types.ModuleType(f"{package_name}.utils")
class _FileMatcher:
    @staticmethod
    def _contains_other_season(file_name, target_season):
        import re
        match = re.search(r"[Ss](\d{1,2})(?:[Ee]|\.)", str(file_name))
        return bool(match and int(match.group(1)) != int(target_season))


utils.FileMatcher = _FileMatcher
utils.SubscribeFilter = type("SubscribeFilter", (), {})
utils.resource_year_matches = lambda expected, *values: True
utils.sanitize_resource_text = lambda value, limit=160: str(value or "")[:limit]
sys.modules[utils.__name__] = utils
handlers = types.ModuleType(f"{package_name}.handlers")
handlers.__path__ = []
sys.modules[handlers.__name__] = handlers
offline_spec = importlib.util.spec_from_file_location(
    f"{package_name}.handlers.offline_queue", Path(__file__).parent / "handlers" / "offline_queue.py"
)
offline_module = importlib.util.module_from_spec(offline_spec)
sys.modules[offline_spec.name] = offline_module
offline_spec.loader.exec_module(offline_module)
search = types.ModuleType(f"{package_name}.handlers.search")
search.SearchHandler = type("SearchHandler", (), {})
sys.modules[search.__name__] = search
subscribe = types.ModuleType(f"{package_name}.handlers.subscribe")
subscribe.SubscribeHandler = type("SubscribeHandler", (), {})
sys.modules[subscribe.__name__] = subscribe

module_path = Path(__file__).parent / "handlers" / "sync.py"
spec = importlib.util.spec_from_file_location(f"{package_name}.handlers.sync", module_path)
sync = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = sync
spec.loader.exec_module(sync)
SyncHandler = sync.SyncHandler


def test_single_character_title_is_not_removed_by_normalization():
    assert SyncHandler._resource_title_matches(
        _MediaInfo("蝉"),
        "📺 蝉 (2026) 第1季 更新至第10集",
    )


def test_unrelated_single_character_title_is_rejected():
    assert not SyncHandler._resource_title_matches(
        _MediaInfo("蝉"),
        "📺 春风 (2026) 第1季 更新至第10集",
    )


def test_multi_character_title_remains_matched_after_normalization():
    assert SyncHandler._resource_title_matches(
        _MediaInfo("花开锦绣"),
        "花开锦绣.S01E30.第30集.2160p.WEB-DL",
    )


def test_zero_start_episode_falls_back_to_episode_one():
    subscribe_obj = type("Subscribe", (), {"start_episode": 0, "total_episode": 21})()
    assert SyncHandler._fallback_missing_episodes_from_subscribe(subscribe_obj) == list(range(1, 22))


def test_history_sensitive_url_migration_helper_contract():
    # 主类发布审查保证旧历史中的 URL 可被移除；同步处理器新增记录已改用 share_code。
    source = (Path(__file__).parent / "handlers" / "sync.py").read_text(encoding="utf8")
    assert '"share_url": share_url' not in source
    assert 'note={"source": f"Subscribe|{subscribe.name}", "share_url": share_url}' not in source


def test_explicit_wrong_year_is_rejected_by_helper_contract():
    path = Path(__file__).parent / "utils" / "resource_match.py"
    spec = importlib.util.spec_from_file_location("resource_match", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.resource_year_matches(2026, "测试影片 (2026)", title="测试影片")
    assert not module.resource_year_matches(2026, "测试影片 (2025)", title="测试影片")
    assert module.resource_year_matches(2026, "测试影片.2026.1080p", title="测试影片")
    assert not module.resource_year_matches(2026, "测试影片.2025.1080p", title="测试影片")
    # 正文发布日期不是资源年份，不能误伤合法候选。
    assert module.resource_year_matches(2026, "测试影片 更新于 2025-08-01", title="测试影片")


def test_seedhub_episode_range_requires_clear_complete_season():
    assert SyncHandler._seedhub_episode_range("测试剧[全36集].S01.2026.2160p", 1) == set(range(1, 37))
    assert SyncHandler._seedhub_episode_range("Test.Show.2026.EP01-12.1080p", 1) == set(range(1, 13))
    assert SyncHandler._seedhub_episode_range("Test.Show.S02.EP01-12", 1) == set()
    assert SyncHandler._seedhub_episode_range("Test.Show.S01E07.1080p", 1) == set()


def test_library_episodes_are_normalized_and_invalid_values_are_ignored():
    handler = object.__new__(SyncHandler)
    original_download_chain = sync.DownloadChain

    class _Media:
        title = "测试剧"
        title_year = "测试剧 (2026)"

    class _Exists:
        seasons = {1: [1, "2", 0, "invalid", -1, 3]}

    class _DownloadChain:
        def media_exists(self, mediainfo):
            return _Exists()

    sync.DownloadChain = _DownloadChain
    try:
        assert handler._existing_tv_episodes(_Media(), 1) == {1, 2, 3}
    finally:
        sync.DownloadChain = original_download_chain


def test_progress_plan_only_adds_confirmed_episodes_and_never_regresses():
    subscribe_obj = type("Subscribe", (), {
        "start_episode": 0, "total_episode": 5, "lack_episode": 4,
        "note": [1, "3", 0, "invalid"],
    })()
    assert SyncHandler._progress_from_confirmed_episodes(subscribe_obj, {2, 3, 7}) == {
        "current_note": [1, 3], "proposed_note": [1, 2, 3],
        "current_lack": 4, "proposed_lack": 2, "confirmed": [2, 3],
    }


def test_progress_plan_never_increases_existing_lack_episode():
    subscribe_obj = type("Subscribe", (), {
        "start_episode": 1, "total_episode": 5, "lack_episode": 1, "note": [1],
    })()
    progress = SyncHandler._progress_from_confirmed_episodes(subscribe_obj, {1})
    assert progress["proposed_lack"] == 1


def test_progress_plan_rejects_invalid_subscription_range():
    subscribe_obj = type("Subscribe", (), {
        "start_episode": 3, "total_episode": 2, "lack_episode": 0, "note": [],
    })()
    assert SyncHandler._progress_from_confirmed_episodes(subscribe_obj, {1, 2}) is None


def test_sync_prioritizes_telegram_candidate_with_missing_episode():
    resource_old = {"title": "测试剧 (2026) S01E10"}
    resource_target = {"title": "测试剧 (2026) S01E25"}
    assert SyncHandler._telegram_resource_matches_missing_episode(resource_target, 1, {25})
    assert not SyncHandler._telegram_resource_matches_missing_episode(resource_old, 1, {25})


if __name__ == "__main__":
    test_single_character_title_is_not_removed_by_normalization()
    test_unrelated_single_character_title_is_rejected()
    test_multi_character_title_remains_matched_after_normalization()
    test_zero_start_episode_falls_back_to_episode_one()
    test_history_sensitive_url_migration_helper_contract()
    test_explicit_wrong_year_is_rejected_by_helper_contract()
    test_seedhub_episode_range_requires_clear_complete_season()
    test_library_episodes_are_normalized_and_invalid_values_are_ignored()
    test_progress_plan_only_adds_confirmed_episodes_and_never_regresses()
    test_progress_plan_never_increases_existing_lack_episode()
    test_progress_plan_rejects_invalid_subscription_range()
    test_sync_prioritizes_telegram_candidate_with_missing_episode()
    print("sync handler tests: OK")
