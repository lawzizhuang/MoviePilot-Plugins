"""Bot单媒体115分享导入；不创建或修改订阅，不重复触发整理。"""
import re
from pathlib import PurePosixPath
from urllib.parse import urlsplit, parse_qs, unquote

from app.chain import ChainBase
from app.core.metainfo import MetaInfo
from app.schemas.types import MediaType
from ..utils.file_matcher import FileMatcher


def parse_link(text):
    """接受单条115分享、ED2K或BT磁力；不请求任意远程URL。"""
    value = str(text or '').strip()
    if value.lower().startswith(('ed2k:', 'magnet:')):
        offline_info(value)
        return value
    parts = value.split()
    if len(parts) != 1:
        raise ValueError('请仅发送一条115分享链接，访问码请包含在链接参数中。')
    url = parts[0]
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or parsed.hostname not in {'115.com', '115cdn.com', 'anxia.com'}
            or parsed.username or parsed.password or parsed.port
            or not re.fullmatch(r'/s/[A-Za-z0-9]+/?', parsed.path)):
        raise ValueError('只支持115、115cdn、anxia的HTTPS分享链接。')
    return url


def offline_info(url):
    """验证离线协议并提取文件名与稳定内容标识；裸磁力不猜测媒体。"""
    if any(c.isspace() for c in url):
        raise ValueError('离线链接中的空格须URL编码，且每次仅支持一条链接。')
    if url.lower().startswith('ed2k:'):
        match = re.fullmatch(r'ed2k://\|file\|([^|]+)\|(\d+)\|([a-fA-F0-9]{32})\|/', url, re.I)
        if not match or int(match[2]) <= 0:
            raise ValueError('ED2K文件链接格式无效。')
        name = unquote(match[1])
        key = f'ed2k:{match[3].lower()}:{int(match[2])}'
    else:
        parsed = urlsplit(url)
        if parsed.scheme.lower() != 'magnet' or parsed.netloc or parsed.path:
            raise ValueError('磁力链接格式无效。')
        args = parse_qs(parsed.query)
        hashes = [v[9:] for v in args.get('xt', []) if v.lower().startswith('urn:btih:')]
        if len(hashes) != 1 or not re.fullmatch(r'[a-fA-F0-9]{40}|[A-Z2-7a-z]{32}', hashes[0]):
            raise ValueError('首版磁力离线仅支持单一BTIH内容标识。')
        import base64
        digest = hashes[0].lower() if len(hashes[0]) == 40 else base64.b32decode(hashes[0].upper()).hex()
        names = args.get('dn', [])
        if len(names) != 1:
            raise ValueError('磁力须包含dn名称参数，裸磁力无法安全确定媒体目录。')
        name, key = names[0], f'btih:{digest}'
    if not name.strip() or any(ord(c) < 32 for c in name) or len(name) > 1024:
        raise ValueError('离线名称无效。')
    return name, key


def run_offline(manager, url, kind, root, dry_run, submitted, save_submitted):
    """命名离线资源按指定类型识别后提交；提交成功不冒称落盘或整理完成。"""
    name, key = offline_info(url)
    meta = MetaInfo(name)
    media_type = MediaType.TV if kind == 'tv' else MediaType.MOVIE
    season = meta.begin_season
    if kind == 'tv' and not season:
        raise ValueError('剧集离线名称须含明确季号，例如S01。')
    if kind == 'movie' and (season or meta.begin_episode):
        raise ValueError('电影命令不能导入剧集离线资源。')
    meta.type = media_type
    media = ChainBase().recognize_media(meta=meta, mtype=media_type, cache=True)
    if (not media or not getattr(media, 'tmdb_id', None) or media.type != media_type
            or not FileMatcher._movie_path_matches_title([name], media.title)):
        raise ValueError('离线资源名称无法可靠匹配媒体身份。')
    if not str(root).startswith('/'):
        raise ValueError('目标根目录配置无效。')
    folder = safe_component(f'{media.title} ({media.year})' if media.year else media.title)
    path = f'{root.rstrip("/")}/{folder}' + (f'/Season {season}' if kind == 'tv' else '')
    token = manager.offline_resource_key(f'{key}|{path}')
    if token in submitted:
        return '该离线资源已提交过；请检查115离线任务及目标文件，未重复提交。'
    existing = manager.list_files(path)
    if any((f.get('n') or f.get('name')) == name for f in existing):
        return '目标目录已存在同名文件，未提交离线任务。'
    if dry_run:
        return f'测试模式：已识别离线资源，目标目录：{path}；未创建目录或提交任务。'
    if len(submitted) >= 1000:
        raise ValueError('手动离线去重记录已达到1000条，请先人工核查记录。')
    if not manager.submit_offline_task(url, path):
        return '离线任务未确认提交成功；请先检查115任务列表，避免盲目重复提交。'
    submitted.append(token)
    save_submitted(submitted)
    return f'115离线任务已提交，目标目录：{path}。尚未确认下载完成；整理依赖外部监控，未修改订阅。'


def safe_component(value):
    """防止识别结果变成路径穿越或嵌套目录。"""
    value = re.sub(r'[\\/:*?"<>|\x00-\x1f]', '_', str(value or '')).strip(' .')
    if not value:
        raise ValueError('无法生成安全的媒体目录名。')
    return value


def run_manual(manager, url, kind, root, dry_run, limit, batch_size):
    """先完整生成单媒体计划并查重，再按既有批量接口执行。"""
    if kind not in {'tv', 'movie'} or not str(root).startswith('/'):
        raise ValueError('媒体类型或目标根目录配置无效。')
    status = manager.check_share_status(url)
    if not status.is_valid:
        raise ValueError('分享无法使用或暂时无法核验，请稍后重试。')
    tree = manager.list_share_files(url, max_depth=3)
    if tree is None:
        raise ValueError('分享读取失败，本次不执行转存。')
    videos = []
    def walk(items, parents=()):
        for item in items:
            name = item.get('name', '')
            if item.get('is_dir'):
                if 'children' not in item:
                    raise ValueError('分享超过目录深度预算，请改用较小的分享。')
                walk(item['children'], parents + (name,))
            elif PurePosixPath(name).suffix.lower() in FileMatcher.VIDEO_EXTENSIONS:
                videos.append((item, parents))
    walk(tree or [])
    if not videos or len(videos) > limit:
        raise ValueError(f'分享须包含1至{limit}个视频；超限请拆分分享。')
    media_type = MediaType.TV if kind == 'tv' else MediaType.MOVIE
    chain = ChainBase()
    identity = None
    groups = {}
    for item, parents in videos:
        name = item['name']
        meta = MetaInfo(name)
        # 优先文件名，片名缺失时使用最近的有片名目录；不猜测无季号剧集。
        season = meta.begin_season
        episode = meta.begin_episode
        if kind == 'tv':
            if season is None:
                for parent in reversed(parents):
                    match = re.search(r'(?:Season\s*|\bS)(\d+)(?!\d)|第([一二三四五六七八九十\d]+)季', parent, re.I)
                    if match:
                        number = match[1] or match[2]
                        chinese = {'一': 1, '二': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9, '十': 10}
                        season = int(number) if number.isdigit() else chinese.get(number)
                        break
            if not season or not episode or (meta.end_episode and meta.end_episode < episode):
                raise ValueError('剧集必须有明确季号和集号；未执行任何转存。')
        elif season or episode:
            raise ValueError('电影命令不能导入带明确季集的视频。')
        if not getattr(meta, 'name', None) or str(meta.name).isdigit():
            for parent in reversed(parents):
                candidate = MetaInfo(parent)
                if getattr(candidate, 'name', None) and not re.fullmatch(r'(?:Season\s*|S)\d+|第[一二三四五六七八九十\d]+季', parent, re.I):
                    meta = candidate
                    break
        meta.type = media_type
        media = chain.recognize_media(meta=meta, mtype=media_type, cache=True)
        if not media or not getattr(media, 'tmdb_id', None) or media.type != media_type:
            raise ValueError('无法可靠识别媒体类型和TMDB身份，未执行转存。')
        if not FileMatcher._movie_path_matches_title([name, *parents], media.title):
            raise ValueError('文件名或目录与识别片名无法确认一致，未执行转存。')
        item = dict(item)
        item['_episodes'] = set(range(episode, (MetaInfo(name).end_episode or episode) + 1)) if kind == 'tv' else set()
        key = str(media.tmdb_id)
        if identity is not None and identity != key:
            raise ValueError('首版只支持单部作品分享，不支持混合媒体。')
        identity = key
        folder = safe_component(f'{media.title} ({media.year})' if media.year else media.title)
        path = f'{root.rstrip("/")}/{folder}'
        if kind == 'tv':
            path += f'/Season {season}'
        groups.setdefault(path, []).append(item)
    plans = []
    skipped = 0
    for path, items in groups.items():
        existing = manager.list_files(path)
        existing = [dict(f, name=f.get('n') or f.get('name') or '',
                         size=f.get('s', f.get('size', 0)),
                         is_dir=f.get('is_dir', f.get('fid') in (0, '0')))
                    for f in existing]
        names = {f.get('n') or f.get('name') for f in existing}
        existing_episodes = set()
        if kind == 'tv':
            for f in existing:
                m = MetaInfo(f.get('n') or f.get('name') or '')
                if not f.get('is_dir') and PurePosixPath(f['name']).suffix.lower() in FileMatcher.VIDEO_EXTENSIONS and m.begin_episode and (m.begin_season is None or m.begin_season == int(path.rsplit(' ', 1)[1])):
                    existing_episodes.update(range(m.begin_episode, (m.end_episode or m.begin_episode) + 1))
        ids = []
        if kind == 'movie' and FileMatcher.match_movie_file(existing, media.title, min_size_mb=0):
            skipped += len(items)
            plans.append((path, ids))
            continue
        for index, item in enumerate(items):
            episodes = item['_episodes']
            if item['name'] in names or (episodes and episodes & existing_episodes):
                skipped += 1
                continue
            if not item.get('id'):
                raise ValueError('视频缺少文件ID，未执行转存。')
            ids.append(item['id'])
            names.add(item['name'])
            existing_episodes.update(episodes)
            if kind == 'movie':
                # 单部电影多个版本只选择一个，不批量导入重复版本。
                skipped += len(items) - index - 1
                break
        plans.append((path, ids))
    if dry_run:
        return f'测试模式：待转存{sum(len(ids) for _, ids in plans)}个视频，跳过{skipped}个；未写入网盘。'
    success = failed = 0
    for path, ids in plans:
        if not ids:
            continue
        ok, bad = manager.transfer_files_batch(url, ids, path, batch_size=batch_size)
        success += len(ok)
        failed += len(bad)
        if bad:
            break
    pending = sum(len(ids) for _, ids in plans) - success - failed
    return f'转存成功{success}个，失败{failed}个，未执行{pending}个，跳过{skipped}个。未创建或修改订阅；整理由已配置的外部监控处理，本消息不代表整理完成。'
