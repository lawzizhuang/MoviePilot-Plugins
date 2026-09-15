"""Bot多行导入：整批格式预检、单线程执行、逐条保存成功记录。"""
from .manual import ManualInputError, parse_link, offline_info, _target, run_manual, run_offline


def parse_batch(text):
    # MoviePilot命令链可能用split/join把换行折叠为空格；链接内空格必须URL编码。
    lines = list(enumerate(str(text or '').split(), 1))
    if not 1 <= len(lines) <= 10:
        raise ManualInputError('每批支持1至10条链接，每行一条；本批未执行。')
    output = []
    for n, line in lines:
        try:
            output.append(parse_link(line))
        except ValueError:
            raise ManualInputError(f'第{n}条链接格式无效；本批未执行。请检查协议、哈希和URL编码。') from None
    return output


def run_batch(manager, links, kind, root, dry_run, limit, batch_size, load, save):
    # 执行入口也预检，避免调用方跳过协议检查。
    links = parse_batch('\n'.join(links))
    path = _target(kind, root)
    records = {key: list(load(key) or []) for key in ('manual_offline_submitted', 'manual_share_submitted')}
    seen, plans = set(), []
    for index, url in enumerate(links, 1):
        offline = url.lower().startswith(('ed2k:', 'magnet:'))
        if offline:
            _, identity = offline_info(url)
            dedup_identity = identity
        else:
            info = manager.extract_share_info(url)
            code, password = info.get('share_code'), info.get('receive_code')
            if not code:
                raise ManualInputError(f'第{index}条分享标识无效，本批未执行。')
            identity = f'share:{code}:{password or ""}'
            dedup_identity = f'share:{code}'
        store = 'manual_offline_submitted' if offline else 'manual_share_submitted'
        token = manager.offline_resource_key(f'{identity}|{path}')
        duplicate = dedup_identity in seen or token in records[store]
        seen.add(dedup_identity)
        plans.append((index, url, offline, store, duplicate))
    report = []
    for position, (index, url, offline, store, duplicate) in enumerate(plans):
        if duplicate:
            report.append(f'第{index}条：重复／历史已提交，跳过。')
            continue
        if getattr(manager, 'web_query_blocked', False):
            report.append(f'115读取已熔断，剩余{len(plans)-position}条未执行。')
            break
        persisted = False
        def persist(values):
            nonlocal persisted
            save(store, values)  # 保存失败向上抛出，绝不继续下一条
            records[store] = list(values)
            persisted = True
        try:
            if not offline:
                status = manager.check_share_status(url)
                if not status.is_valid:
                    if getattr(status, 'error_code', 0) in {4100010, 4100018}:
                        report.append(f'第{index}条：分享已取消或过期，跳过。')
                        continue
                    raise RuntimeError('share status unknown')
            if offline:
                result = run_offline(manager, url, kind, path, dry_run, records[store], persist)
            else:
                result = run_manual(manager, url, kind, path, dry_run, limit, batch_size, records[store], persist, checked_status=status)
            if dry_run:
                report.append(f'第{index}条：{result}')
            elif persisted:
                report.append(f'第{index}条：' + ('离线已提交。' if offline else '分享转存成功。'))
            else:
                raise RuntimeError('submission unconfirmed')
        except Exception:
            report.append(f'第{index}条：未确认完整成功，可能已有部分写入；后续{len(plans)-position-1}条未执行。请核查115任务与接收目录，勿盲目重发。')
            break
    return '\n'.join(report) + '\n未修改订阅；离线提交不代表下载完成，识别整理由外部监控负责。'
