"""Non-destructive 3D candidates, with explicit per-view import into the workshop."""
import base64
import json
import math
import os
import re
from pathlib import Path
import shutil
import threading
import time
import uuid
import urllib.error
import urllib.request
import errno
from adapter import read, write, sha, gpu_idle
from store import Conflict
from orientation import quaternion, height_offset, model_scale
from reconstruction_engines import ENGINES, get_engine

WEB = Path(__file__).resolve().parent
FACES = ('front', 'back', 'left', 'right')

def job_progress(job, root):
    """Report real sampling steps; other phases have no measurable percentage."""
    if job.get('status') != 'running':
        return None
    if job.get('rerender'):
        return dict(stage='Съёмка ракурсов')
    if job.get('engine') != 'idol':
        return dict(stage='Построение 3D')
    path = root/job['id']/'worker.log'
    try:
        with path.open('rb') as log:
            log.seek(0, os.SEEK_END)
            log.seek(max(0, log.tell()-32768))
            text = log.read().decode('utf-8', errors='replace')
    except OSError:
        return dict(stage='Подготовка')
    if 'Saved ' in text:
        return dict(stage='Подготовка ракурсов')
    matches = list(re.finditer(r'Sampling:\s*\d+%[^\r\n]*?\b(\d+)/(\d+)\s*\[([^\]]+)\]', text))
    if matches:
        match = matches[-1]
        current, total = int(match.group(1)), int(match.group(2))
        if total and current < total:
            result = dict(stage='Построение 3D', current=current, total=total)
            remaining = re.search(r'<(\d{1,2}:\d{2}(?::\d{2})?)', match.group(3))
            if remaining:
                seconds = 0
                for part in remaining.group(1).split(':'):
                    seconds = seconds*60 + int(part)
                result['remaining_seconds'] = seconds
            return result
        return dict(stage='Подготовка ракурсов')
    if 'Running DINOv3 encoder' in text:
        return dict(stage='Анализ изображения')
    if 'Generating' in text:
        return dict(stage='Подготовка изображения')
    return dict(stage='Загрузка модели')


def prepare_3d_gpu(app):
    try:
        with urllib.request.urlopen('http://127.0.0.1:8188/queue', timeout=5) as response:
            queue = json.load(response)
        if queue.get('queue_running') or queue.get('queue_pending'):
            raise ValueError('В ComfyUI есть задания. Дождитесь завершения.')
    except urllib.error.URLError as error:
        if not isinstance(error.reason, ConnectionRefusedError) and getattr(error.reason, 'errno', None) != errno.ECONNREFUSED:
            raise
        gpu_idle()
    else:
        app.prepare_generation_gpu()


class Reconstruction:
    def __init__(self, workshop):
        self.app = workshop
        self.root = workshop.root/'reconstruction'
        self.root.mkdir(exist_ok=True)
        self.thread = None
        self.path = self.root/'jobs.json'
        self.orientation_path = self.root/'orientations.json'
        self.orientations = read(self.orientation_path) if self.orientation_path.exists() else {}
        self.jobs = read(self.path) if self.path.exists() else []
        for job in self.jobs:
            if job['status'] == 'running':
                job.update(status='interrupted', error='Мастерская перезапущена. Исходники сохранены. Новое построение автоматически не запускалось.')
        self.persist()

    def persist(self):
        write(self.path, self.jobs)

    def runtime(self, engine=None):
        return get_engine(engine or 'idol').runtime()

    def ready(self, engine=None):
        return get_engine(engine or 'idol').ready(self.runtime(engine))

    def snapshot(self, key):
        with self.app.lock:
            self.app.paths(key)
            jobs=[]
            for job in [j for j in self.jobs if j['key'] == key][-20:]:
                item=job.copy()
                item['progress']=job_progress(job,self.root)
                jobs.append(item)
            return dict(ready=self.ready('idol'),default_engine='idol',engines={engine:self.ready(engine) for engine in ENGINES},orientation=self.orientations.get(key),jobs=jobs)

    def job(self, job_id):
        job = next((j for j in self.jobs if j['id'] == job_id), None)
        if job is None:
            raise ValueError('3D-результат не найден')
        return job

    def file(self, job_id, kind):
        self.job(job_id)
        if kind not in (*FACES, 'mesh', 'input', 'splat'):
            raise ValueError('Неизвестный файл')
        folder = self.root/job_id
        path = folder/'views'/(kind+'.png') if kind in FACES else folder/({'mesh':'mesh.glb','input':'input.png','splat':'splat.ply'}[kind])
        if not path.is_file():
            raise ValueError('Файл ещё не готов')
        return path

    @staticmethod
    def camera(data):
        result = {}
        for key, default, low, high in [('elevation',35,0,90), ('yaw',0,0,359)]:
            value = data.get(key, default)
            if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
                raise ValueError('Проверьте угол камеры')
            result[key] = value
        return result

    def start(self, data, rerender=False):
        with self.app.lock:
            if getattr(self.app, 'sf3d_busy', False) or getattr(self.app, 'animation_busy', False) or (self.app.thread and self.app.thread.is_alive()):
                raise ValueError('Дождитесь завершения текущей очереди')
            if any(j['status'] in ('queued','running','unknown') for j in self.app.jobs):
                raise ValueError('Сначала завершите или проверьте очередь предметов')
            asset = self.app.asset(data.get('key'))
            if asset.get('parent_key') or asset['mode'] != 'prop' or not asset['available']:
                raise ValueError('Выберите основной предмет с исходником')
            if asset['revision'] != data.get('revision'):
                raise Conflict('Предмет изменился. Откройте ракурсы заново.')
            if not asset['image']['alpha_ok']:
                raise ValueError('Для 3D нужен исходник с настоящей прозрачностью')
            camera = self.camera(data)
            parent = None
            if rerender:
                parent = self.job(data.get('job'))
                if parent['key'] != asset['key'] or parent['status'] != 'complete':
                    raise ValueError('Нет готовой модели этого предмета')
            engine = parent.get('engine','sf3d') if parent else data.get('engine','idol')
            if engine != 'idol':
                raise ValueError('Этот старый движок удалён. Готовые ракурсы доступны для применения и скачивания.')
            handler = get_engine(engine)
            if not self.ready(engine):
                raise ValueError('3D-модель ещё не подготовлена. Дождитесь окончания установки и проверки.')
            settings = handler.settings(data, parent)
            default_orientation = list(handler.default_orientation)
            q = quaternion(data.get('quaternion',parent.get('orientation',default_orientation) if parent else default_orientation))
            height = height_offset(data.get('height_offset',parent.get('height_offset',0) if parent else 0))
            scale = model_scale(data.get('model_scale',parent.get('model_scale',[100,100,100]) if parent else [100,100,100]))
            if rerender:
                source,_ = self.app.paths(asset['key'])
                if sha(source) != parent.get('accepted_source_sha256',parent['source_sha256']):
                    raise Conflict('Исходник изменился после построения модели. Постройте новую модель.')
            job_id = uuid.uuid4().hex
            folder = self.root/job_id; folder.mkdir()
            source, _ = self.app.paths(asset['key'])
            shutil.copy2(source, folder/'source.png')
            job = dict(id=job_id,key=asset['key'],status='running',created_at=time.time(),source_sha256=sha(source),camera=camera,rerender=rerender)
            job.update(engine=engine,orientation=q,model_scale=scale,height_offset=height,orientation_confirmed=False)
            job.update(settings)
            write(folder/'orientation.json',dict(quaternion=q,model_scale=scale,height_offset=height))
            if parent:
                for name in ('mesh.glb', 'splat.ply', 'input.png', 'mesh-info.json'):
                    old = self.root/parent['id']/name
                    if old.exists():
                        shutil.copy2(old, folder/name)
                job['source_sha256'] = parent['source_sha256']
                if parent.get('accepted_source_sha256'):
                    job['accepted_source_sha256'] = parent['accepted_source_sha256']
            self.jobs.append(job); self.persist()
            self.app.sf3d_busy = True
            self.thread = threading.Thread(target=self.run, args=(job,), daemon=True)
            self.thread.start()
            return job.copy()

    def run(self, job):
        folder = self.root/job['id']; engine = job.get('engine','sf3d'); runtime = self.runtime(engine)
        env = os.environ.copy()
        env.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', HF_HOME=str(runtime/'cache'), CUDA_DEVICE_ORDER='PCI_BUS_ID', CUDA_VISIBLE_DEVICES='0', OMP_NUM_THREADS='8')
        handler = get_engine(engine)
        try:
            if not job['rerender']:
                prepare_3d_gpu(self.app)
            with (folder/'worker.log').open('w') as log:
                if not job['rerender']:
                    handler.generate(runtime, folder, job, env, log)
                handler.render(runtime, folder, job, env, log)
            with self.app.lock:
                job.update(status='complete',finished_at=time.time());self.persist()
        except Exception as error:
            with self.app.lock:
                detail = str(error)
                log = folder/'worker.log'
                if log.exists():
                    detail += '\n' + log.read_text(errors='replace')[-1500:]
                job.update(status='failed',error=detail,finished_at=time.time());self.persist()
        finally:
            with self.app.lock:
                self.app.sf3d_busy = False

    def apply(self, data):
        with self.app.lock:
            job = self.job(data.get('job'))
            if job['status'] != 'complete' or job['key'] != data.get('key'):
                raise ValueError('Ракурсы ещё не готовы')
            source, _ = self.app.paths(job['key'])
            if sha(source) != job.get('accepted_source_sha256', job['source_sha256']):
                raise Conflict('Основной исходник изменился после построения 3D. Постройте новую модель.')
            face = data.get('direction')
            if face not in FACES:
                raise ValueError('Выберите направление')
            body = {k:data.get(k) for k in ('key','revision','target_revision','direction')}
            body['data'] = base64.b64encode(self.file(job['id'], face).read_bytes()).decode()
            result = self.app.manual_direction(body)
            target_key = result['asset']['key']
            metadata = self.app.metadata(target_key)
            engine=job.get('engine','sf3d')
            metadata['generation'].update(operation=engine, model={'idol':'speridlabs/idol','sf3d':'stabilityai/stable-fast-3d','spar3d':'zimengxiong/Modelr-SPAR3D'}.get(engine,engine), job=job['id'], camera=job['camera'],orientation=job.get('orientation'),height_offset=job.get('height_offset',0),model_scale=job.get('model_scale',[100,100,100]))
            if engine == 'idol' and 'alpha_threshold' in job:
                metadata['generation']['alpha_threshold'] = job['alpha_threshold']
            write(self.app.paths(target_key)[1], metadata)
            result['asset'] = self.app.asset(target_key)
            if result['asset']['key'] == job['key']:
                job['accepted_source_sha256'] = sha(source)
                self.persist()
            return result

    def confirm_orientation(self, data):
        with self.app.lock:
            job=self.job(data.get('job'));key=data.get('key')
            if job['key']!=key or job['status']!='complete' or 'orientation' not in job:
                raise ValueError('Сначала получите пробные виды с выбранным положением модели')
            asset=self.app.asset(key)
            if asset['revision']!=data.get('revision'):
                raise Conflict('Предмет изменился. Откройте ориентацию заново.')
            if getattr(self.app,'sf3d_busy',False) or asset.get('job'):
                raise ValueError('Дождитесь завершения задания')
            raw,_=self.app.paths(key)
            if sha(raw)!=job.get('accepted_source_sha256',job['source_sha256']):
                raise Conflict('Исходник изменился после построения модели')
            previous=self.orientations.get(key,{})
            if data.get('orientation_revision')!=previous.get('revision',0):
                raise Conflict('Положение модели изменилось в другой вкладке. Откройте окно заново.')
            record=dict(model_scale=model_scale(job.get('model_scale',[100,100,100])),quaternion=quaternion(job['orientation']),height_offset=height_offset(job.get('height_offset',0)),mesh_sha256=sha(self.file(job['id'],'mesh')),job=job['id'],revision=previous.get('revision',0)+1,confirmed_at=time.time(),camera=job['camera'])
            self.orientations[key]=record;write(self.orientation_path,self.orientations)
            job['orientation_confirmed']=True;self.persist()
            return record
