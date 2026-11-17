"""Durable sprite-generation queue and recovery."""
import os,subprocess,sys,threading,time,uuid
from pathlib import Path
from adapter import read,write,sha

class WorkshopQueue:
 def _enqueue(self,key,kind,seed=None):
  if any(j['key']==key and j['status'] in ('queued','running','unknown') for j in self.jobs):raise ValueError('Для этого предмета уже есть задание; сначала завершите или проверьте его')
  d=self.metadata(key)
  if kind=='generate' and not d['prompt']:raise ValueError('Добавьте промпт перед генерацией')
  job=dict(id=uuid.uuid4().hex,key=key,kind=kind,status='queued',created_at=time.time(),seed=d['seed'] if seed is None else seed)
  self.jobs.append(job);return job
 def enqueue(self,keys,kind):
  if kind not in ('generate','process'):raise ValueError('Неизвестная операция')
  if not isinstance(keys,list) or not keys:raise ValueError('Не выбраны предметы')
  with self.lock:
   previous=len(self.jobs)
   try:
    for key in keys:
     if kind=='process' and self.inspect(key) is None:raise ValueError('Нет исходника: '+key)
     self._enqueue(key,kind)
    self.persist()
   except Exception:self.jobs=self.jobs[:previous];raise
 def cancel(self,job_id):
  with self.lock:
   j=next((j for j in self.jobs if j['id']==job_id),None)
   if not j or j['status']!='queued':raise ValueError('Отменить можно только ожидающее задание')
   j['status']='cancelled';self.persist()
 def start(self):
  with self.lock:
   if getattr(self,'sf3d_busy',False):raise ValueError('Сейчас строятся 3D-ракурсы. Дождитесь завершения.')
   if getattr(self,'animation_busy',False):raise ValueError('Сейчас работает очередь анимаций или есть неопределённый результат. Проверьте раздел «Анимации».')
   if self.thread and self.thread.is_alive():self.paused=False;return
   if any(j['status']=='unknown' for j in self.jobs):raise ValueError('Есть задание с неопределённым результатом. Сначала нажмите «Проверить результат».')
   self.paused=False;self.thread=threading.Thread(target=self._loop,daemon=True);self.thread.start()
 def pause(self):
  with self.lock:self.paused=True
 def _loop(self):
  while True:
   with self.lock:
    if self.paused:return
    job=next((j for j in self.jobs if j['status']=='queued'),None)
    if job is None:return
    job.update(status='running',started_at=time.time());self.persist()
   try:
    if job['kind']=='generate':self.generate(job)
    else:self.process(job['key'])
    with self.lock:job.update(status='complete',finished_at=time.time());self.persist()
   except Exception as exc:
    with self.lock:
     if job['status']=='running':job['status']='failed'
     job['error']=str(exc);self.paused=True;self.persist()
    return
 def generate(self,job):
  # The preflight never unloads or interrupts other applications.
  self.prepare_generation_gpu()
  with self.lock:
   d=self.metadata(job['key']);runtime=self.root/'runtime';response=self.root/'queue'/(job['id']+'.response.json');request=self.root/'queue'/(job['id']+'.request.json')
   job.update(before_jobs=[p.stem for p in (runtime/'results/jobs').glob('*.json')],submitted=True);self.persist()
   function,arguments=self.generation_request(d|{'seed':job['seed']},runtime)
   write(request,dict(runtime=str(runtime),response=str(response),function=function,arguments=arguments))
  with (self.root/'queue'/(job['id']+'.log')).open('ab') as log:
   env=os.environ.copy();env['SPRITE_WORKSHOP_JOB_ID']=job['id']
   child=subprocess.Popen([sys.executable,str(Path(__file__).parent/'worker.py'),str(request)],stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,env=env)
   job['pid']=child.pid
   with self.lock:self.persist()
   # No timeout kill: uncertainty must retain the backend request and its IDs.
   child.wait()
  self.accept_response(job,response)
 def accept_response(self,job,response):
  with self.lock:
   if not response.exists():job['status']='unknown';self.persist();raise ValueError('Рабочий процесс завершился без ответа. Повтор не отправлен.')
   envelope=read(response);result=envelope.get('result')
   if not result:
    job['status']='unknown';self.persist();raise ValueError(envelope.get('error','Нет ответа API'))
   job['backend_job_id']=result.get('job_id');job['backend_status']=result.get('status')
   if result.get('status')!='success' or not result.get('cleanup_confirmed'):
    job['status']='failed' if result.get('status')=='failed' and result.get('cleanup_confirmed') else 'unknown';self.persist();raise ValueError('Генератор: '+str(result.get('status'))+'. Результат требует проверки.')
   runtime=self.root/'runtime';source=(runtime/result['raw_path']).resolve()
   if not source.is_relative_to(runtime) or sha(source)!=result['raw_sha256']:raise ValueError('Исходник не прошёл проверку SHA')
   raw,_=self.paths(job['key']);existing=self.metadata(job['key'])
   if not (raw.exists() and existing.get('generation',{}).get('job_id')==result.get('job_id') and sha(raw)==result['raw_sha256']):self.install_raw(job['key'],source,result)
   d=self.metadata(job['key']);facts=self.inspect(job['key']);job['alpha_ok']=facts['alpha_ok']
   if d['auto_process']:
    if facts['alpha_ok']:
     try:self.process(job['key'])
     except Exception as exc:job['processing_error']=str(exc)
    else:job['processing_error']='Исходник сохранён. Альфа не соответствует режиму; автоматическая сборка пропущена.'
 def recover(self,job_id):
  with self.lock:
   job=next((j for j in self.jobs if j['id']==job_id),None)
   if not job or job['status']!='unknown':raise ValueError('Нет неопределённого задания')
   response=self.root/'queue'/(job['id']+'.response.json')
   log=self.root/'queue'/(job['id']+'.log')
   if response.exists() and read(response).get('error')=="No module named 'pavlusha_agent.functions'" and log.exists() and 'registry=make_registry(' in log.read_text(errors='replace') and "ModuleNotFoundError: No module named 'pavlusha_agent.functions'" in log.read_text(errors='replace'):
    job.update(status='failed',error='Генерация не была отправлена: отсутствовал модуль мастерской. Проблема исправлена; задание можно создать заново.',finished_at=time.time())
    self.persist()
    return
   if not response.exists() or not read(response).get('result'):
    paths=[p for p in (self.root/'runtime/results/jobs').glob('*.json') if read(p).get('workshop_job_id')==job['id']]
    if len(paths)!=1:raise ValueError('Не удалось однозначно найти задание. Повтор не отправлен; нужна ручная проверка.')
    backend=read(paths[0])
    if backend.get('status') not in ('success','failed') or not backend.get('cleanup_confirmed'):raise ValueError('Генератор ещё не подтвердил завершение и освобождение ресурсов')
    result=backend.get('result',{})|{k:backend[k] for k in ('status','job_id','cleanup_confirmed') if k in backend}
    write(response,{'result':result})
   try:self.accept_response(job,response)
   except ValueError:
    if job['status']!='failed':raise
    job.update(error='Генератор сообщил об ошибке. Повтор не отправлен.',finished_at=time.time());self.persist();return 'failed'
   job.update(status='complete',finished_at=time.time(),error='');self.persist();return 'complete'
