"""Bot手动接收：用户指定类型，仅投递接收根目录，媒体识别交给外部整理。"""
import base64
import re
from urllib.parse import urlsplit, parse_qs, unquote


class ManualInputError(ValueError):
    """允许直接回复Bot的固定安全提示，不包含原始链接或底层响应。"""


def parse_link(text):
    """验证单条115分享或离线协议，不访问任意远程URL。"""
    value = str(text or '').strip()
    if not value or len(value) > 16384 or any(c.isspace() for c in value):
        raise ManualInputError('每次仅支持一条链接，链接内空格须URL编码。')
    if value.lower().startswith(('ed2k:', 'magnet:')):
        offline_info(value)
        return value
    try:
        parsed = urlsplit(value)
        valid = (parsed.scheme == 'https' and parsed.hostname in {'115.com', '115cdn.com', 'anxia.com'}
                 and not parsed.username and not parsed.password and not parsed.port
                 and re.fullmatch(r'/s/[A-Za-z0-9]+/?', parsed.path))
    except ValueError:
        valid = False
    if not valid:
        raise ManualInputError('支持HTTPS 115分享、标准ED2K文件链接及BTIH磁力。')
    return value


def offline_info(url):
    """提取离线内容标识用于去重，名称可空，不做媒体识别。"""
    if any(c.isspace() for c in url):
        raise ManualInputError('链接内空格须URL编码。')
    if url.lower().startswith('ed2k:'):
        match = re.fullmatch(r'ed2k://\|file\|([^|]+)\|(\d+)\|([a-fA-F0-9]{32})\|/', url, re.I)
        if not match or int(match[2]) <= 0:
            raise ManualInputError('ED2K文件链接格式无效。')
        name, key = unquote(match[1]), f'ed2k:{match[3].lower()}:{int(match[2])}'
    else:
        parsed = urlsplit(url)
        if parsed.scheme.lower() != 'magnet' or parsed.netloc or parsed.path:
            raise ManualInputError('磁力链接格式无效。')
        args = parse_qs(parsed.query)
        hashes = [v[9:] for v in args.get('xt', []) if v.lower().startswith('urn:btih:')]
        if len(hashes) != 1 or not re.fullmatch(r'[a-fA-F0-9]{40}|[A-Z2-7a-z]{32}', hashes[0]):
            raise ManualInputError('仅支持单一BTIH内容标识的磁力，不支持BTMH-only。')
        digest = hashes[0].lower() if len(hashes[0]) == 40 else base64.b32decode(hashes[0].upper()).hex()
        name, key = next(iter(args.get('dn', [])), ''), f'btih:{digest}'
    if any(ord(c) < 32 for c in name) or len(name) > 1024:
        raise ManualInputError('链接名称含不支持的字符或过长。')
    return name, key


def _target(kind, root):
    """只允许使用配置的绝对接收目录，命令不能注入目标路径。"""
    if kind not in {'tv', 'movie'} or not str(root).startswith('/') or '..' in str(root).split('/'):
        raise ManualInputError('媒体类型或接收根目录配置无效。')
    return str(root).rstrip('/') or '/'


def _dedup(manager, key, path, submitted):
    """检查持久化哈希记录，不持久化分享链接或访问码。"""
    token = manager.offline_resource_key(f'{key}|{path}')
    if token in submitted:
        raise ManualInputError('该资源已成功提交过，未重复执行；请检查115任务和接收目录。')
    if len(submitted) >= 1000:
        raise ManualInputError('手动导入去重记录已达1000条，请人工核查，不自动淘汰重投。')
    return token


def run_offline(manager, url, kind, root, dry_run, submitted, save_submitted):
    """提交至接收根目录；提交与下载、整理完成严格区分。"""
    _, key = offline_info(url)
    path = _target(kind, root)
    token = _dedup(manager, key, path, submitted)
    # 只核验目标路径，不逐视频查重；查询异常须在写入前传播。
    manager.get_pid_by_path(path, mkdir=False)
    if dry_run:
        return f'测试模式：离线资源将提交到 {path}；未创建目录或提交任务。'
    if not manager.submit_offline_task(url, path):
        return '离线任务未确认提交成功；请检查115任务列表，避免盲目重复提交。'
    save_submitted([*submitted, token])
    return f'离线任务已提交至 {path}。尚未确认下载完成；识别与整理由外部监控负责，未修改订阅。'


def run_manual(manager, url, kind, root, dry_run, limit, batch_size, submitted, save_submitted):
    """仅列分享顶层并转存顶层项目，保留目录结构，不调用媒体识别。"""
    path = _target(kind, root)
    info = manager.extract_share_info(url)
    key = 'share:' + str(info.get('share_code') or '') + ':' + str(info.get('receive_code') or '')
    token = _dedup(manager, key, path, submitted)
    status = manager.check_share_status(url)
    if not status.is_valid:
        raise ManualInputError('分享无法访问或暂时不能核验，未执行转存。')
    items = manager.list_share_files(url, max_depth=1)
    if items is None:
        raise ManualInputError('分享目录读取失败，未执行转存。')
    ids = list(dict.fromkeys(str(item.get('id') or '') for item in items))
    if not ids or '' in ids:
        raise ManualInputError('分享为空或顶层项目缺少文件ID，未执行转存。')
    if len(ids) > limit:
        raise ManualInputError(f'分享顶层项目超过本次上限{limit}，请拆分分享。')
    manager.get_pid_by_path(path, mkdir=False)
    if dry_run:
        return f'测试模式：将保留目录结构转存{len(ids)}个顶层项目到 {path}；未写入网盘。目录内可能含多个文件，不核验媒体身份。'
    ok, bad = manager.transfer_files_batch(url, ids, path, batch_size=batch_size)
    if len(ok) == len(ids) and not bad:
        save_submitted([*submitted, token])
    return (f'顶层项目转存成功{len(ok)}个、失败{len(bad)}个，接收目录：{path}。'
            '识别与整理由已配置的外部监控负责，本消息不代表整理完成；未修改订阅。'
            + ('部分失败请先核查目录，重发可能重复转存。' if bad else ''))
