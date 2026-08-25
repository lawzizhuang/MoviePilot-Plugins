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
utils.FileMatcher = type("FileMatcher", (), {})
utils.SubscribeFilter = type("SubscribeFilter", (), {})
sys.modules[utils.__name__] = utils
handlers = types.ModuleType(f"{package_name}.handlers")
handlers.__path__ = []
sys.modules[handlers.__name__] = handlers
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


if __name__ == "__main__":
    test_single_character_title_is_not_removed_by_normalization()
    test_unrelated_single_character_title_is_rejected()
    test_multi_character_title_remains_matched_after_normalization()
    test_zero_start_episode_falls_back_to_episode_one()
    print("sync handler tests: OK")
