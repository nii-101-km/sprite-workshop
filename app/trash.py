"""Reversible removal of workshop assets and their direction variants."""
import re
import shutil
import time
import uuid
from adapter import read, write
from store import Conflict


def entries(app):
    root = app.root/'trash'
    with app.lock:
        return sorted([read(p) for p in root.glob('*/entry.json') if p.is_file()], key=lambda e:e['deleted_at'], reverse=True)


def remove(app, data):
    with app.lock:
        key = data.get('key')
        if key not in app.keys():raise ValueError('Предмет не найден.')
        asset = app.asset(key)
        if data.get('revision') != asset['revision']:
            raise Conflict('Предмет изменился. Обновите список.')
        keys = [key] + [k for k in app.keys() if app.metadata(k).get('parent_key') == key]
        if getattr(app,'sf3d_busy',False) or any(j['key'] in keys and j['status'] in ('queued','running','unknown') for j in app.jobs):
            raise ValueError('Сначала завершите или отмените задания этого предмета.')
        entry = dict(id=uuid.uuid4().hex,key=key,label=asset['label'],keys=keys,deleted_at=time.time(),files=[])
        for k in keys:
            raw, meta = app.paths(k)
            category, asset_id = k.split('/')
            for path in [raw,meta,app.root/'output'/category/asset_id,app.root/'history'/category/asset_id]:
                if path.exists():
                    if path.is_symlink() or not path.resolve().is_relative_to(app.root):
                        raise ValueError('Ссылки на внешние файлы не поддерживаются.')
                    entry['files'].append(str(path.relative_to(app.root)))
        folder = app.root/'trash'/entry['id']
        write(folder/'entry.json',entry)
        moved=[]
        try:
            for relative in entry['files']:
                target=folder/'files'/relative;target.parent.mkdir(parents=True,exist_ok=True)
                shutil.move(str(app.root/relative),str(target));moved.append(relative)
        except Exception:
            for relative in reversed(moved):
                target=app.root/relative;target.parent.mkdir(parents=True,exist_ok=True)
                shutil.move(str(folder/'files'/relative),str(target))
            (folder/'entry.json').unlink()
            raise
        for k in keys:app.clear_cache(k)
        return entry


def restore(app,data):
    with app.lock:
        entry_id=data.get('id')
        if not isinstance(entry_id,str) or not re.fullmatch('[0-9a-f]{32}',entry_id):
            raise ValueError('Неверная запись корзины.')
        folder=app.root/'trash'/entry_id
        if not (folder/'entry.json').is_file():raise ValueError('Запись корзины не найдена.')
        entry=read(folder/'entry.json')
        if getattr(app,'sf3d_busy',False):raise ValueError('Дождитесь завершения работы с 3D.')
        for k in entry['keys']:
            raw,meta=app.paths(k)
            if raw.exists() or meta.exists():raise Conflict('Предмет с таким ID уже существует. Он не будет заменён.')
        for relative in entry['files']:
            target=app.root/relative
            if not target.resolve().is_relative_to(app.root) or target.exists():raise Conflict('Путь восстановления уже занят.')
            if not (folder/'files'/relative).exists():raise ValueError('Файл в корзине не найден.')
        moved=[]
        try:
            for relative in entry['files']:
                target=app.root/relative;target.parent.mkdir(parents=True,exist_ok=True)
                shutil.move(str(folder/'files'/relative),str(target));moved.append(relative)
            for k in entry['keys']:
                _,meta=app.paths(k)
                if meta.exists():
                    settings=read(meta);settings['revision']=settings.get('revision',0)+1;write(meta,settings)
                app.clear_cache(k)
        except Exception:
            for relative in reversed(moved):
                target=folder/'files'/relative;target.parent.mkdir(parents=True,exist_ok=True)
                shutil.move(str(app.root/relative),str(target))
            raise
        (folder/'entry.json').unlink()
        return dict(keys=entry['keys'])
