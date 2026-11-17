"""Small incremental image/text embedding index; no ML imports in the web server."""
import hashlib,json,math,os,selectors,subprocess,threading,time
from pathlib import Path
from PIL import Image,ImageOps
from adapter import read,write,sha
MODEL_ID='google/embeddinggemma-2'
PIPELINE_VERSION=1

def unit(vector):
 if not isinstance(vector,list) or not vector or any(type(v) not in (float,int) or not math.isfinite(v) for v in vector):raise ValueError('Модель вернула некорректный вектор')
 length=math.sqrt(sum(v*v for v in vector))
 if length<1e-12:raise ValueError('Модель вернула пустой вектор')
 return [float(v/length) for v in vector]

def rank(query,entries,mode='hybrid',limit=12):
 if mode not in ('hybrid','image'):raise ValueError('Неизвестный режим поиска')
 q=unit(query);rows=[]
 for key,e in entries.items():
  iv=unit(e['image_vector']);tv=unit(e['text_vector'])
  if len(iv)!=len(q) or len(tv)!=len(q):raise ValueError('Размерности индекса и запроса не совпадают')
  visual=sum(a*b for a,b in zip(q,iv));text=sum(a*b for a,b in zip(q,tv));score=visual if mode=='image' else .7*visual+.3*text
  rows.append(dict(key=key,score=round(score,6),image_score=round(visual,6),text_score=round(text,6)))
 return sorted(rows,key=lambda r:(-r['score'],r['key']))[:limit]

class Worker:
 def __init__(self,python,model,log_path):self.python=Path(python);self.model=Path(model);self.log_path=Path(log_path);self.process=None;self.lock=threading.Lock();self.last_used=0
 def _read(self,timeout):
  selector=selectors.DefaultSelector()
  try:
   selector.register(self.process.stdout,selectors.EVENT_READ)
   if not selector.select(timeout):self.close();raise RuntimeError('Модель не ответила вовремя. Подробности в embedding-worker.log')
   line=self.process.stdout.readline()
  finally:selector.close()
  if not line:raise RuntimeError('Процесс модели завершился. Подробности в embedding-worker.log')
  try:result=json.loads(line)
  except ValueError:raise RuntimeError('Некорректный ответ модели. Подробности в embedding-worker.log')
  if result.get('error'):raise RuntimeError(result['error'])
  return result
 def request(self,payload):
  with self.lock:
   if self.process is not None and self.process.poll() is not None:self.process=None
   if self.process is None:
    if not self.python.is_file() or not (self.model/'model.safetensors').is_file():raise ValueError('Поиск не установлен: нужны окружение и модель. См. setup-search.sh')
    self.log_path.parent.mkdir(parents=True,exist_ok=True)
    env=dict(os.environ,HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',TOKENIZERS_PARALLELISM='false',HF_HUB_DISABLE_TELEMETRY='1',CUDA_VISIBLE_DEVICES='')
    with self.log_path.open('ab') as log:self.process=subprocess.Popen([str(self.python),'-u',str(Path(__file__).parent/'embedding_worker.py'),str(self.model)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=log,text=True,bufsize=1,env=env)
    ready=self._read(180)
    if not ready.get('ready'):raise RuntimeError('Модель не подтвердила готовность')
   self.process.stdin.write(json.dumps(payload,ensure_ascii=False)+'\n');self.process.stdin.flush();result=self._read(180);self.last_used=time.monotonic();return result['vectors']
 def close(self):
  # This is our CPU embedding worker, never ComfyUI or any unrelated process.
  if self.process is not None:
   if self.process.poll() is None:
    self.process.terminate()
    try:self.process.wait(timeout=5)
    except subprocess.TimeoutExpired:self.process.kill();self.process.wait(timeout=5)
   for stream in (self.process.stdin,self.process.stdout):
    if stream:stream.close()
   self.process=None

class SemanticIndex:
 def __init__(self,workshop,worker=None):
  self.app=workshop;self.root=self.app.root/'semantic';self.root.mkdir(exist_ok=True);self.path=self.root/'index.json';self.lock=threading.RLock();self.thread=None;self.progress={'phase':'idle','done':0,'total':0};self.query_cache={}
  project=Path(__file__).resolve().parent.parent;config=read(project/'embedding-runtime.json') if (project/'embedding-runtime.json').exists() else {}
  self.model=Path(os.environ.get('SPRITE_EMBEDDING_MODEL',config.get('model',str(project/'.embedding-model'))))
  self.python=Path(os.environ.get('SPRITE_EMBEDDING_PYTHON',config.get('python',str(project/'.embedding-venv/bin/python'))))
  lock=read(project/'embedding-model-lock.json') if (project/'embedding-model-lock.json').exists() else {}
  self.revision=lock.get('revision','unconfigured');self.worker=worker or Worker(self.python,self.model,self.root/'embedding-worker.log')
  self.index=read(self.path) if self.path.exists() else {'version':1,'model_id':MODEL_ID,'model_revision':self.revision,'entries':{}}
  if self.index.get('model_revision')!=self.revision:self.index={'version':1,'model_id':MODEL_ID,'model_revision':self.revision,'entries':{}}
  eligible=set(self.documents())
  if any(key not in eligible for key in self.index['entries']):
   self.index['entries']={key:e for key,e in self.index['entries'].items() if key in eligible};write(self.path,self.index)
 def documents(self):
  documents={}
  with self.app.lock:
   for key in self.app.keys():
    a=self.app.asset(key)
    if a.get('parent_key') or not a['available']:continue
    raw,_=self.app.paths(key);image=raw;image_sha=a['image']['source_sha256'];rendition='raw'
    if a['output_current']:
     candidate=self.app.root/a['output']['files']['sprite']
     if candidate.is_file():image=candidate;image_sha=sha(candidate);rendition='sprite'
    text=f"title: {a['label']} | text: {a['category']}. {a['prompt']}"
    if a.get('perspective') or a.get('direction'):text+=f" | camera: {a.get('perspective','')} | direction: {a.get('direction','')}"
    fields=dict(model_id=MODEL_ID,revision=self.revision,pipeline=PIPELINE_VERSION,image_sha256=image_sha,source_sha256=a['image']['source_sha256'],text=text,mode=a['mode'],rendition=rendition)
    fingerprint=hashlib.sha256(json.dumps(fields,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    documents[key]=dict(key=key,label=a['label'],category=a['category'],path=str(image),fingerprint=fingerprint,**fields)
  return documents
 def status(self):
  docs=self.documents()
  with self.lock:
   valid=sum(self.index['entries'].get(key,{}).get('fingerprint')==d['fingerprint'] for key,d in docs.items())
   return dict(self.progress,ready=valid,total=len(docs),stale=len(docs)-valid,indexed=len(self.index['entries']),running=bool(self.thread and self.thread.is_alive()),model=MODEL_ID,device='cpu',installed=self.python.is_file() and (self.model/'model.safetensors').is_file(),model_revision=self.revision)
 def prepare(self,d):
  dest=self.root/'previews'/(d['fingerprint']+'.png');dest.parent.mkdir(exist_ok=True)
  if dest.exists():return dest
  with Image.open(d['path']) as loaded:
   im=loaded.convert('RGBA')
   if d['mode']=='prop':
    bbox=im.getchannel('A').point(lambda a:255 if a>128 else 0).getbbox()
    if bbox:im=im.crop(bbox)
   method=Image.Resampling.NEAREST if d['rendition']=='sprite' else Image.Resampling.LANCZOS
   fitted=ImageOps.contain(im,(448,448),method=method);canvas=Image.new('RGB',(512,512),(232,229,219));canvas.paste(fitted,((512-fitted.width)//2,(512-fitted.height)//2),fitted.getchannel('A'));canvas.save(dest)
  return dest
 def build(self):
  with self.lock:
   if self.thread and self.thread.is_alive():return
   self.progress={'phase':'indexing','done':0,'total':0,'error':None};self.thread=threading.Thread(target=self._build,daemon=True);self.thread.start()
 def _build(self):
  try:
   docs=self.documents()
   with self.lock:self.progress['total']=len(docs)
   for key,d in docs.items():
    with self.lock:old=self.index['entries'].get(key)
    if not old or old.get('fingerprint')!=d['fingerprint']:
     preview=self.prepare(d);vectors=self.worker.request(dict(op='asset',image=str(preview),text=d['text']))
     if len(vectors)!=2:raise ValueError('Ожидались два вектора: картинка и описание')
     image_vector,text_vector=map(unit,vectors)
     if len(image_vector)!=768 or len(text_vector)!=768:raise ValueError('Ожидалась размерность 768')
     # Do not commit an embedding if generation/processing changed the source mid-flight.
     current=self.documents().get(key)
     if current and current['fingerprint']==d['fingerprint']:
      with self.lock:
       self.index['entries'][key]={k:v for k,v in d.items() if k!='path'}|dict(image_vector=image_vector,text_vector=text_vector);write(self.path,self.index)
    with self.lock:self.progress['done']+=1;self.progress['current']=d['label']
   latest=self.documents()
   with self.lock:
    self.index['entries']={key:e for key,e in self.index['entries'].items() if key in latest};self.index['updated_at']=time.time();write(self.path,self.index);self.progress.update(phase='ready',current=None)
  except Exception as exc:
   with self.lock:self.progress.update(phase='error',error=str(exc),current=None)
 def search(self,query,mode='hybrid',limit=12,category=None):
  if not isinstance(query,str) or not query.strip() or len(query)>1000:raise ValueError('Введите описание предмета длиной до 1000 символов')
  if type(limit) is not int or not 1<=limit<=50:raise ValueError('Число результатов: от 1 до 50')
  if mode not in ('hybrid','image'):raise ValueError('Неизвестный режим поиска')
  docs=self.documents()
  with self.lock:
   entries={key:e for key,e in self.index['entries'].items() if key in docs and e['fingerprint']==docs[key]['fingerprint'] and (not category or e['category']==category)}
   if self.thread and self.thread.is_alive():raise ValueError('Идёт индексация. Поиск станет доступен после её завершения.')
  if not entries:raise ValueError('Нет актуального индекса для выбранных предметов. Нажмите «Обновить индекс».')
  query=query.strip();cachekey=(self.revision,query)
  if cachekey not in self.query_cache:
   vectors=self.worker.request(dict(op='query',query=query));self.query_cache[cachekey]=unit(vectors[0])
   if len(self.query_cache)>100:self.query_cache.pop(next(iter(self.query_cache)))
  matches=rank(self.query_cache[cachekey],entries,mode,limit)
  return dict(query=query,mode=mode,matches=matches,searched=len(entries),stale=len(docs)-sum(self.index['entries'].get(k,{}).get('fingerprint')==d['fingerprint'] for k,d in docs.items()))
