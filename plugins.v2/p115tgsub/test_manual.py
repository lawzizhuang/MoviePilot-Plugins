"""Bot导入模拟测试；不使用网盘、机器人或真实媒体识别。"""
import sys
import types
import importlib.util
from pathlib import Path
import re

kind = types.SimpleNamespace(TV='tv', MOVIE='movie')
class Meta:
    def __init__(self, name):
        self.name = 'Show'
        match = re.search(r'S(\d+)E(\d+)', name)
        self.begin_season = int(match[1]) if match else None
        self.begin_episode = int(match[2]) if match else None
        self.end_episode = None
class Chain:
    def recognize_media(self, **kwargs):
        return types.SimpleNamespace(tmdb_id=1, type=kwargs['mtype'], title='Show', year=2026)
for name, attrs in {
    'app': {}, 'app.chain': {'ChainBase': Chain}, 'app.core': {},
    'app.core.metainfo': {'MetaInfo': Meta}, 'app.schemas': {},
    'app.schemas.types': {'MediaType': kind}, 'manual_test': {},
    'manual_test.handlers': {}, 'manual_test.utils': {},
    'manual_test.utils.file_matcher': {'FileMatcher': types.SimpleNamespace(
        VIDEO_EXTENSIONS={'.mkv'},
        _movie_path_matches_title=lambda parts, title: any(title.lower() in part.lower() for part in parts),
        match_movie_file=lambda files, title, **kw: next((f for f in files if title in f.get('name', '')), None))},
}.items():
    obj = types.ModuleType(name)
    obj.__dict__.update(attrs)
    sys.modules[name] = obj
spec = importlib.util.spec_from_file_location('manual_test.handlers.manual', Path(__file__).parent/'handlers/manual.py')
manual = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manual)
class Manager:
    def __init__(self):
        self.writes = []
        self.files = []
    def check_share_status(self, url):
        return types.SimpleNamespace(is_valid=True)
    def list_share_files(self, *args, **kwargs):
        return [{'id': '1', 'name': 'Show.S01E01.mkv', 'is_dir': False}]
    def list_files(self, path):
        return self.files
    def transfer_files_batch(self, url, ids, path, **kwargs):
        self.writes.append((ids, path))
        return ids, []

def test_manual():
    for url in ['http://115.com/s/abc', 'https://evil.test/s/abc', 'https://115.com.evil.test/s/abc', 'https://115.com/s/abc extra']:
        try:
            manual.parse_link(url)
        except ValueError:
            pass
        else:
            raise AssertionError(url)
    url = manual.parse_link('https://115.com/s/abc?password=1234')
    manager = Manager()
    manual.run_manual(manager, url, 'tv', '/TV', True, 20, 10)
    assert not manager.writes
    manual.run_manual(manager, url, 'tv', '/TV', False, 20, 10)
    assert manager.writes == [(['1'], '/TV/Show (2026)/Season 1')]
    manager.writes.clear()
    manager.files = [{'n': 'Show.S01E01.mkv'}]
    manual.run_manual(manager, url, 'tv', '/TV', True, 20, 10)
    assert not manager.writes
    try:
        manual.run_manual(manager, url, 'movie', '/Movies', False, 20, 10)
    except ValueError:
        pass
    else:
        raise AssertionError('错类型必须拒绝')
    assert not manager.writes
    manager.list_files = lambda path: (_ for _ in ()).throw(RuntimeError('query failed'))
    try:
        manual.run_manual(manager, url, 'tv', '/TV', False, 20, 10)
    except RuntimeError:
        pass
    else:
        raise AssertionError('查询异常须停止')
    assert not manager.writes

def test_movie_and_multiseason():
    manager = Manager()
    manager.list_share_files = lambda *a, **k: [{'id': '2', 'name': 'Show.2026.mkv'}]
    manual.run_manual(manager, 'https://115.com/s/abc', 'movie', '/Movies', False, 20, 10)
    assert manager.writes == [(['2'], '/Movies/Show (2026)')]
    manager.writes.clear()
    manager.files = [{'fid': '2', 'n': 'Show.2026.other.mkv'}]
    manual.run_manual(manager, 'https://115.com/s/abc', 'movie', '/Movies', False, 20, 10)
    assert not manager.writes
    manager.files = []
    manager.list_share_files = lambda *a, **k: [
        {'id': '1', 'name': 'Show.S01E01.mkv'}, {'id': '2', 'name': 'Show.S02E01.mkv'}]
    manual.run_manual(manager, 'https://115.com/s/abc', 'tv', '/TV', False, 20, 10)
    assert [path for ids, path in manager.writes] == ['/TV/Show (2026)/Season 1', '/TV/Show (2026)/Season 2']
    manager.writes.clear()
    original = Chain.recognize_media
    count = iter([1, 2])
    Chain.recognize_media = lambda self, **kw: types.SimpleNamespace(tmdb_id=next(count), type=kw['mtype'], title='Show', year=2026)
    try:
        try:
            manual.run_manual(manager, 'https://115.com/s/abc', 'tv', '/TV', False, 20, 10)
        except ValueError:
            pass
        else:
            raise AssertionError('混合媒体必须在写入前拒绝')
        assert not manager.writes
    finally:
        Chain.recognize_media = original


def test_command_authorization_and_busy_guard():
    import ast
    from threading import Lock
    source = ast.parse((Path(__file__).parent/'__init__.py').read_text(encoding='utf-8-sig'))
    cls = next(node for node in source.body if isinstance(node, ast.ClassDef))
    method = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == 'remote_manual')
    method.decorator_list = []
    method.args.args[1].annotation = None
    replies = []
    scope = {'run_state_lock': Lock(), '__name__': 'manual_test.plugin', '__package__': 'manual_test'}
    sys.modules['manual_test.handlers.manual'] = manual
    exec(compile(ast.Module(body=[method], type_ignores=[]), '<remote_manual>', 'exec'), scope)
    plugin = types.SimpleNamespace(_bot_transfer_users='123', _enabled=True,
                                  _bot_transfer_enabled=True, _sync_running=True,
                                  _progress_repair_running=False,
                                  post_message=lambda **kw: replies.append(kw))
    def event(user):
        return types.SimpleNamespace(event_data={'action': 'p115_manual_tv', 'user': user,
                                    'channel': 'Telegram', 'arg_str': 'https://115.com/s/abc'})
    scope['remote_manual'](plugin, event('other'))
    assert not replies
    scope['remote_manual'](plugin, event('123'))
    assert '运行' in replies[-1]['text']
    plugin._bot_transfer_enabled = False
    scope['remote_manual'](plugin, event('123'))
    assert '启用' in replies[-1]['text']


def test_offline_links():
    import hashlib
    ed = 'ed2k://|file|Show.S01E01.mkv|123|' + 'a'*32 + '|/'
    magnet = 'magnet:?xt=urn:btih:' + 'a'*40 + '&dn=Show.S01E01.mkv'
    assert manual.parse_link(ed) == ed
    assert manual.parse_link(magnet) == magnet
    for bad in ['magnet:?xt=urn:btih:'+'a'*40, 'ed2k://|file|x|0|'+'a'*32+'|/', magnet+' extra']:
        try:
            manual.parse_link(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(bad)
    manager = Manager()
    manager.offline_resource_key = lambda key: hashlib.sha256(key.encode()).hexdigest()
    calls = []
    manager.submit_offline_task = lambda url, path: calls.append(path) or True
    records = []
    manual.run_offline(manager, ed, 'tv', '/TV', True, records, lambda data: None)
    assert not calls and not records
    manual.run_offline(manager, ed, 'tv', '/TV', False, records, lambda data: None)
    assert calls == ['/TV/Show (2026)/Season 1'] and len(records) == 1
    manual.run_offline(manager, ed, 'tv', '/TV', False, records, lambda data: None)
    assert len(calls) == 1
    assert ed not in str(records)


if __name__ == '__main__':
    test_manual()
    test_movie_and_multiseason()
    test_command_authorization_and_busy_guard()
    test_offline_links()
    print('manual import tests: OK')
