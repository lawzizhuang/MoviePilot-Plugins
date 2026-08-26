"""夸克订阅追更链路的离线契约测试：候选校验→转存→二次确认→订阅闭环→SmartStrm 入队。"""
import importlib.util
import sys
import types
from pathlib import Path

BASE = Path(__file__).parent


class _Logger:
    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def warn(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass

    def debug(self, *args, **kwargs):
        pass


# ---------- MoviePilot 模块桩 ----------
sys.modules.setdefault("app", types.ModuleType("app"))
for name, attrs in {
    "app.core.metainfo": {"MetaInfo": None},  # 下方填充
    "app.chain.download": {"DownloadChain": None},
    "app.db.downloadhistory_oper": {"DownloadHistoryOper": None},
    "app.db.subscribe_oper": {"SubscribeOper": None},
    "app.log": {"logger": _Logger()},
    "app.schemas": {"MediaInfo": object},
    "app.schemas.types": {
        "MediaType": None,
        "NotificationType": type("NotificationType", (), {}),
    },
    "app.utils.string": {"StringUtils": None},
}.items():
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules[name] = module


class FakeMeta:
    def __init__(self, name=""):
        self.title = str(name or "")
        self.year = None
        self.begin_season = None
        self.begin_episode = None
        self.end_episode = None
        self.type = None


class FakeMediaInfo:
    def __init__(self, meta):
        self.title = meta.title
        self.year = getattr(meta, "year", None)
        self.tmdb_id = None
        self.imdb_id = None
        self.tvdb_id = None
        self.douban_id = None
        self.type = type("T", (), {"value": "MOVIE" if meta.type == MediaType.MOVIE else "TV"})()

    @property
    def title_year(self):
        return f"{self.title} ({self.year})" if self.year else self.title

    def get_poster_image(self):
        return ""


class MediaTypeStub:
    MOVIE = type("V", (), {"value": "MOVIE"})()
    TV = type("V", (), {"value": "TV"})()


MediaType = MediaTypeStub


sys.modules["app.core.metainfo"].MetaInfo = FakeMeta
sys.modules["app.schemas.types"].MediaType = MediaTypeStub


class StringUtilsStub:
    @staticmethod
    def format_ep(episodes):
        episodes = sorted(episodes)
        return ",".join(f"E{e:02d}" for e in episodes)


sys.modules["app.utils.string"].StringUtils = StringUtilsStub


class FakeNotExistInfo:
    def __init__(self, episodes):
        self.episodes = list(episodes)
        self.total_episode = len(self.episodes)
        self.start_episode = min(self.episodes) if self.episodes else 1


class FakeDownloadChain:
    def get_no_exists_info(self, meta=None, mediainfo=None, totals=None):
        total = next(iter((totals or {}).values()), 0) or 0
        episodes = list(range(1, total + 1))
        season = getattr(meta, "begin_season", None) or 1
        mediakey = mediainfo.tmdb_id or mediainfo.douban_id
        return False, {mediakey: {season: FakeNotExistInfo(episodes)}} if mediakey else {}


sys.modules["app.chain.download"].DownloadChain = FakeDownloadChain


class FakeDownloadHistory:
    calls = []

    def add(self, **kwargs):
        self.calls.append(kwargs)


sys.modules["app.db.downloadhistory_oper"].DownloadHistoryOper = FakeDownloadHistory


class FakeSubscribeOper:
    def update(self, subscribe_id, data):
        return True


sys.modules["app.db.subscribe_oper"].SubscribeOper = FakeSubscribeOper


# ---------- 包模块树 ----------
PKG = "p115tgsub_quark_sync_test"
package = types.ModuleType(PKG)
package.__path__ = []
sys.modules[PKG] = package

utils = types.ModuleType(f"{PKG}.utils")
sys.modules[utils.__name__] = utils
utils_path = BASE / "utils" / "file_matcher.py"
utils_spec = importlib.util.spec_from_file_location(f"{PKG}.utils.file_matcher", utils_path)
utils_mod = importlib.util.module_from_spec(utils_spec)
sys.modules[utils_spec.name] = utils_mod
utils_spec.loader.exec_module(utils_mod)
utils.FileMatcher = utils_mod.FileMatcher
utils.SubscribeFilter = utils_mod.SubscribeFilter
utils.resource_year_matches = lambda expected, *values, **kwargs: True
utils.sanitize_resource_text = lambda value, limit=160: str(value or "")[:limit]

clients = types.ModuleType(f"{PKG}.clients")
sys.modules[clients.__name__] = clients
quark_spec = importlib.util.spec_from_file_location(f"{PKG}.clients.quark", BASE / "clients" / "quark.py")
quark_mod = importlib.util.module_from_spec(quark_spec)
sys.modules[quark_spec.name] = quark_mod
quark_spec.loader.exec_module(quark_mod)
clients.QuarkShareClient = quark_mod.QuarkShareClient
QuarkShareClient = quark_mod.QuarkShareClient

handlers = types.ModuleType(f"{PKG}.handlers")
handlers.__path__ = []
sys.modules[handlers.__name__] = handlers

# search / subscribe 桩模块：占位，exec quark_sync 前填充真实 fake 类
search_mod = types.ModuleType(f"{PKG}.handlers.search")
sys.modules[search_mod.__name__] = search_mod
subscribe_mod = types.ModuleType(f"{PKG}.handlers.subscribe")
sys.modules[subscribe_mod.__name__] = subscribe_mod

strm_queue_spec = importlib.util.spec_from_file_location(
    f"{PKG}.handlers.strm_queue", BASE / "handlers" / "strm_queue.py"
)
strm_queue_mod = importlib.util.module_from_spec(strm_queue_spec)
sys.modules[strm_queue_spec.name] = strm_queue_mod
strm_queue_spec.loader.exec_module(strm_queue_mod)
handlers.StrmQueue = strm_queue_mod.StrmQueue


class FakeSearchHandler:
    def __init__(self, candidates=None):
        self.candidates = candidates or []
        self.searches = []

    def search_quark_resources(self, mediainfo, media_type, season=None):
        self.searches.append((mediainfo.title, media_type, season))
        return list(self.candidates)


class FakeSubscribeHandler:
    def __init__(self):
        self.finished = []

    def check_and_finish_subscribe(self, subscribe, mediainfo, success_episodes):
        self.finished.append(list(success_episodes))


class FakeChain:
    def recognize_media(self, meta=None, mtype=None, tmdbid=None, doubanid=None, cache=False):
        return FakeMediaInfo(meta)


class FakeQuarkClient(QuarkShareClient):
    """离线夸克客户端：share 内容由文件列表决定，转存/确认全部成功。"""

    def __init__(self, share_files=None, confirm_fail=False, preexisting_names=None):
        super().__init__("test-cookie", min_interval=0.0)
        self.share_files = share_files or []
        self.transferred = []
        self.confirm_fail = confirm_fail
        self.confirmed_names = set(preexisting_names or [])

    def check_login(self):
        return True

    @property
    def transfer_risk_blocked(self):
        return False

    def check_share_status(self, share_url, password=""):
        return type("S", (), {
            "is_valid": True, "status_text": "有效", "file_count": 1,
            "share_info": {},
        })()

    def list_share_files(self, share_url, password="", max_depth=3, target_season=None):
        return self.share_files

    def transfer_files_batch(self, share_url, file_ids, save_path, password="", batch_size=5):
        ids = list(file_ids)
        self.transferred.extend(ids)
        self.confirmed_names.update(
            str(item.get("name") or "") for item in self.share_files if item.get("id") in ids
        )
        return ids, []

    def confirm_files_exist(self, save_path, file_names, retries=3, interval=0.0):
        if self.confirm_fail:
            return set()
        return set(file_names) & self.confirmed_names

    def get_pid_by_path(self, path, mkdir=True):
        return -1

    def list_files(self, path):
        return []


class FakeStrmClient:
    def __init__(self, success=True):
        self.success = success
        self.calls = []

    @property
    def configured(self):
        return True

    def trigger_incremental(self, strmtask, savepath, xlist_path_fix=""):
        self.calls.append({"strmtask": strmtask, "savepath": savepath})
        return {"success": self.success, "message": ""}


class MemoryData:
    def __init__(self):
        self.store = {}

    def get(self, key, default=None):
        return self.store.get(key, default)

    def save(self, key, value):
        self.store[key] = value


def _make_subscribe(name="测试剧集", mtype=MediaTypeStub.TV, season=1, start=1, total=2, lack=2):
    return type(
        "Subscribe",
        (),
        {
            "id": 1, "name": name, "year": 2026, "type": mtype.value,
            "tmdbid": 1, "doubanid": None, "season": season,
            "start_episode": start, "total_episode": total, "lack_episode": lack,
            "quality": "", "resolution": "", "effect": "", "best_version": 0,
            "note": [],
        },
    )()


def _make_handler(quark_client, search_handler, subscribe_handler, data, **kwargs):
    sys.modules[f"{PKG}.handlers.search"].SearchHandler = FakeSearchHandler
    sys.modules[f"{PKG}.handlers.subscribe"].SubscribeHandler = FakeSubscribeHandler
    spec = importlib.util.spec_from_file_location(
        f"{PKG}.handlers.quark_sync", BASE / "handlers" / "quark_sync.py"
    )
    qs_mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = qs_mod
    spec.loader.exec_module(qs_mod)
    handlers.QuarkSyncHandler = qs_mod.QuarkSyncHandler
    kwargs.setdefault("max_transfer_per_sync", 20)
    kwargs.setdefault("batch_size", 10)
    kwargs.setdefault("dry_run", False)
    kwargs.setdefault("strm_enabled", True)
    kwargs.setdefault("strm_client", FakeStrmClient())
    kwargs.setdefault("strm_task", "tv")
    return qs_mod.QuarkSyncHandler(
        quark_client=quark_client,
        search_handler=search_handler,
        subscribe_handler=subscribe_handler,
        chain=FakeChain(),
        save_path="/夸克接收/TV",
        movie_save_path="/夸克接收/Movie",
        post_message_func=lambda **kw: None,
        get_data_func=data.get,
        save_data_func=data.save,
        **kwargs,
    )


def test_movie_quark_fallback_transfers_and_finishes():
    data = MemoryData()
    subscribe = _make_subscribe(name="测试电影", mtype=MediaTypeStub.MOVIE, lack=0)
    search = FakeSearchHandler([{
        "url": "https://pan.quark.cn/s/Qk123456",
        "title": "测试电影 (2026)",
        "text": "测试电影 (2026) 1080p",
    }])
    quark = FakeQuarkClient([{"id": "f1", "name": "测试电影.2026.1080p.mkv", "is_dir": False, "size": 2 * 1024 * 1024 * 1024}])
    subscribe_handler = FakeSubscribeHandler()
    strm_client = FakeStrmClient()
    handler = _make_handler(quark, search, subscribe_handler, data, strm_client=strm_client)

    count = handler.process_movie_subscribe(subscribe, [], [], 0)

    assert count == 1
    assert quark.transferred == ["f1"]
    assert subscribe_handler.finished == [[1]]
    assert strm_client.calls and "/夸克接收/Movie/测试电影 (2026)" in strm_client.calls[0]["savepath"]
    assert len(data.get("strm_queue") or []) == 0  # 成功后出队


def test_tv_skips_115_transferred_episodes():
    data = MemoryData()
    subscribe = _make_subscribe()
    # history 中 E01 已由 115 链路成功（不双盘重复转存）
    history = [
        {"title": "测试剧集", "season": 1, "episode": 1, "status": "成功", "cloud": "p115"},
        # 异常旧记录不得中断 E02 的夸克兜底。
        {"title": "测试剧集", "season": 1, "episode": "E03", "status": "成功", "cloud": "p115"},
    ]
    search = FakeSearchHandler([{
        "url": "https://pan.quark.cn/s/Qk123456",
        "title": "测试剧集 (2026)",
        "text": "测试剧集 (2026) S01",
    }])
    quark = FakeQuarkClient([
        {"id": "f1", "name": "测试剧集.S01E01.1080p.mkv", "is_dir": False, "size": 1024},
        {"id": "f2", "name": "测试剧集.S01E02.1080p.mkv", "is_dir": False, "size": 1024},
    ])
    subscribe_handler = FakeSubscribeHandler()
    handler = _make_handler(quark, search, subscribe_handler, data)

    count = handler.process_tv_subscribe(subscribe, history, [], 0, set())

    assert count == 1
    assert quark.transferred == ["f2"]
    assert subscribe_handler.finished == [[2]]


def test_dry_run_quark_never_transfers():
    data = MemoryData()
    subscribe = _make_subscribe()
    search = FakeSearchHandler([{
        "url": "https://pan.quark.cn/s/Qk123456",
        "title": "测试剧集 (2026)",
        "text": "测试剧集 (2026) S01",
    }])
    quark = FakeQuarkClient([
        {"id": "f1", "name": "测试剧集.S01E01.1080p.mkv", "is_dir": False, "size": 1024},
    ])
    subscribe_handler = FakeSubscribeHandler()
    strm_client = FakeStrmClient()
    handler = _make_handler(
        quark, search, subscribe_handler, data, dry_run=True, strm_client=strm_client
    )

    count = handler.process_tv_subscribe(subscribe, [], [], 0, set())

    assert count == 0
    assert quark.transferred == []
    assert subscribe_handler.finished == []
    assert strm_client.calls == []
    assert (data.get("strm_queue") or []) == []


def test_confirmed_files_control_subscribe_update():
    data = MemoryData()
    subscribe = _make_subscribe()
    search = FakeSearchHandler([{
        "url": "https://pan.quark.cn/s/Qk123456",
        "title": "测试剧集 (2026)",
        "text": "测试剧集 (2026) S01",
    }])
    # 任务提交成功但目标目录二次确认失败 → 不得更新订阅
    quark = FakeQuarkClient([
        {"id": "f1", "name": "测试剧集.S01E01.1080p.mkv", "is_dir": False, "size": 1024},
    ], confirm_fail=True)
    subscribe_handler = FakeSubscribeHandler()
    handler = _make_handler(quark, search, subscribe_handler, data)

    count = handler.process_tv_subscribe(subscribe, [], [], 0, set())

    assert count == 0
    assert subscribe_handler.finished == []
    assert (data.get("strm_queue") or []) == []


def test_best_version_history_does_not_finish_movie_subscribe():
    data = MemoryData()
    subscribe = _make_subscribe(name="测试电影", mtype=MediaTypeStub.MOVIE, lack=1)
    subscribe.best_version = 1
    history = [{
        "title": "测试电影", "year": 2026, "type": "电影", "status": "成功",
        "filter_score": 0, "perfect_match": False,
    }]
    search = FakeSearchHandler([])
    quark = FakeQuarkClient()
    subscribe_handler = FakeSubscribeHandler()
    handler = _make_handler(quark, search, subscribe_handler, data)

    assert handler.process_movie_subscribe(subscribe, history, [], 0) == 0
    assert subscribe_handler.finished == []
    assert search.searches == []


def test_existing_movie_file_recovers_subscription_without_retransfer():
    data = MemoryData()
    subscribe = _make_subscribe(name="测试电影", mtype=MediaTypeStub.MOVIE, lack=1)
    filename = "测试电影.2026.1080p.mkv"
    search = FakeSearchHandler([{
        "url": "https://pan.quark.cn/s/Qk123456", "title": "测试电影 (2026)",
        "text": "测试电影 (2026)",
    }])
    quark = FakeQuarkClient(
        [{"id": "f1", "name": filename, "is_dir": False, "size": 2 * 1024 * 1024 * 1024}],
        preexisting_names={filename},
    )
    subscribe_handler = FakeSubscribeHandler()
    handler = _make_handler(quark, search, subscribe_handler, data)

    assert handler.process_movie_subscribe(subscribe, [], [], 0) == 0
    assert quark.transferred == []
    assert subscribe_handler.finished == [[1]]


class _TimeoutButSavedQuarkClient(FakeQuarkClient):
    """模拟任务回执失败/超时、但文件稍后已在目标目录可见。"""

    def transfer_files_batch(self, share_url, file_ids, save_path, password="", batch_size=5):
        ids = list(file_ids)
        self.transferred.extend(ids)
        self.confirmed_names.update(
            str(item.get("name") or "") for item in self.share_files if item.get("id") in ids
        )
        return [], ids


def test_movie_confirmation_recovers_after_task_timeout():
    data = MemoryData()
    subscribe = _make_subscribe(name="测试电影", mtype=MediaTypeStub.MOVIE, lack=1)
    filename = "测试电影.2026.1080p.mkv"
    search = FakeSearchHandler([{
        "url": "https://pan.quark.cn/s/Qk123456", "title": "测试电影 (2026)",
        "text": "测试电影 (2026)",
    }])
    quark = _TimeoutButSavedQuarkClient([
        {"id": "f1", "name": filename, "is_dir": False, "size": 2 * 1024 * 1024 * 1024},
    ])
    subscribe_handler = FakeSubscribeHandler()
    handler = _make_handler(quark, search, subscribe_handler, data)

    assert handler.process_movie_subscribe(subscribe, [], [], 0) == 1
    assert subscribe_handler.finished == [[1]]


if __name__ == "__main__":
    test_movie_quark_fallback_transfers_and_finishes()
    test_tv_skips_115_transferred_episodes()
    test_dry_run_quark_never_transfers()
    test_confirmed_files_control_subscribe_update()
    test_best_version_history_does_not_finish_movie_subscribe()
    test_existing_movie_file_recovers_subscription_without_retransfer()
    test_movie_confirmation_recovers_after_task_timeout()
    print("quark sync handler tests: OK")
