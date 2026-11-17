"""Directory based local sprite workshop, durable queue and non-destructive exports."""
import base64,binascii,hashlib,io,json,math,re,shutil,threading,time,uuid,urllib.request
from pathlib import Path
from PIL import Image
import sprite_processing
from workshop_queue import WorkshopQueue
from viewpoint import validate_viewpoint,generation_prompt
from adapter import read,write,sha,gpu_idle

STYLE='Hand-crafted pixel art game asset. Crisp pixel clusters, thin dark outline, muted earthy colors, warm light from upper left. '
ALPHA=' Single complete isolated object. Transparent background, real RGBA alpha cutout: alpha=0 in all empty space. No colored background, no checkerboard, no ground, no cast shadow, no scenery, no text, no sprite sheet. Output transparent PNG.'
TILE=' Seamless square repeating texture, flat orthographic material view, fills the entire canvas edge to edge, fully opaque. Opposite edges must tile seamlessly. No border, no transparent pixels, no objects, no text.'

class Conflict(ValueError):pass

def name(value):
 if not isinstance(value,str) or not value.strip() or value in ('.','..') or len(value)>80 or any(c in value for c in '/\\\x00') or any(ord(c)<32 for c in value):raise ValueError('Некорректное имя папки')
 return value.strip()
def ident(value):
 if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}',value):raise ValueError('ID: латинские буквы, цифры, дефис и подчёркивание')
 return value

def integer(value,lo,hi,label):
 if type(value) is not int or not lo<=value<=hi:raise ValueError(f'{label}: {lo}–{hi}')
 return value

def scale_value(value):
 if type(value) not in (int,float) or not math.isfinite(value) or not .1<=value<=4:raise ValueError('Масштаб: 0.1–4')
 return round(value,2)

class Workshop(WorkshopQueue):
 def __init__(self,root):
  self.root=Path(root).resolve();self.lock=threading.RLock();self.thread=None;self.paused=True;self.cache={}
  for d in ('raw','output','history','runtime','queue','references'): (self.root/d).mkdir(parents=True,exist_ok=True)
  self.qpath=self.root/'queue/jobs.json';self.jobs=read(self.qpath) if self.qpath.exists() else []
  # A running backend may outlive this server. Never resubmit it on restart.
  for job in self.jobs:
   if job['status']=='running':job.update(status='unknown',error='Программа перезапущена. Проверьте результат; повтор автоматически не отправлен.')
  self.persist()
 def persist(self):write(self.qpath,self.jobs)
 def categories(self):return sorted(p.name for p in (self.root/'raw').iterdir() if p.is_dir() and not p.is_symlink())
 def create_category(self,category):
  category=name(category);p=self.root/'raw'/category
  if p.is_symlink():raise ValueError('Ссылки на внешние папки не поддерживаются')
  p.mkdir(exist_ok=True);return category
 def paths(self,key):
  if not isinstance(key,str) or len(key.split('/'))!=2:raise ValueError('Некорректный предмет')
  category,asset_id=key.split('/');category=name(category);asset_id=ident(asset_id)
  p=self.root/'raw'/category/(asset_id+'.png')
  if not p.resolve().is_relative_to(self.root/'raw'):raise ValueError('Путь вне мастерской')
  return p,p.with_suffix('.asset.json')
 def metadata(self,key):
  raw,meta=self.paths(key)
  if meta.exists():return read(meta)
  if not raw.exists():raise ValueError('Предмет не найден')
  return dict(id=raw.stem,key=key,label=raw.stem,category=raw.parent.name,prompt='',style=STYLE,mode='prop',width=64,height=64,scale=1,palette=32,reviewed=False,revision=0,seed=42,auto_process=True)
 def keys(self):
  keys=[]
  for category in self.categories():
   for p in (self.root/'raw'/category).iterdir():
    asset_id=p.name[:-11] if p.name.endswith('.asset.json') else p.stem if p.suffix.lower()=='.png' else None
    if asset_id and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}',asset_id):keys.append(category+'/'+asset_id)
  return sorted(set(keys))
 def validate(self,data,base=None):
  if not isinstance(data,dict):raise ValueError('Ожидается объект задания')
  d=dict(base or {});d.update({k:v for k,v in data.items() if k in ('id','label','category','prompt','style','mode','width','height','scale','palette','seed','auto_process','reviewed','reference','perspective','direction','parent_key')})
  validate_viewpoint(d)
  if d.get('parent_key'):
   self.paths(d['parent_key'])
  reference=d.get('reference')
  if reference is not None:self.reference_file(reference)
  d['reference']=reference
  d['id']=ident(d.get('id',''));d['category']=name(d.get('category','Общее'));d['key']=d['category']+'/'+d['id']
  for field,default,limit in [('label',d['id'],200),('prompt','',12000),('style',STYLE,4000)]:
   value=d.get(field,default)
   if not isinstance(value,str) or len(value)>limit:raise ValueError('Неверное поле '+field)
   d[field]=value.strip()
  if d.get('mode','prop') not in ('prop','tile'):raise ValueError('Неизвестный режим')
  d['mode']=d.get('mode','prop');d['width']=integer(d.get('width',64),8,256,'Ширина');d['height']=integer(d.get('height',64),8,256,'Высота')
  if d['mode']=='tile' and d['width']!=d['height']:raise ValueError('У тайла ширина и высота должны совпадать')
  d['palette']=integer(d.get('palette',32),2,256,'Палитра');d['seed']=integer(d.get('seed',42),0,2**53-1,'Seed');d['scale']=scale_value(d.get('scale',1))
  for field,default in [('reviewed',False),('auto_process',True)]:
   if type(d.get(field,default)) is not bool:raise ValueError('Неверное поле '+field)
   d[field]=d.get(field,default)
  if max(round(d['width']*d['scale']),round(d['height']*d['scale']))>1024:raise ValueError('Результат не должен превышать 1024 px')
  return d
 def reference_file(self,reference):
  if not isinstance(reference,str) or not re.fullmatch(r'[0-9a-f]{64}',reference):raise ValueError('Некорректный референс')
  path=self.root/'references'/(reference+'.png')
  if path.is_symlink() or not path.is_file() or sha(path)!=reference:raise ValueError('Референс не найден или повреждён. Загрузите картинку заново.')
  return path
 def upload_reference(self,data):
  if not isinstance(data,str) or len(data)>11_200_000:raise ValueError('Референс: не более 8 МБ')
  try:raw=base64.b64decode(data,validate=True)
  except (ValueError,binascii.Error):raise ValueError('Неверные данные изображения')
  if not raw or len(raw)>8_000_000:raise ValueError('Референс: не более 8 МБ')
  try:
   with Image.open(io.BytesIO(raw)) as source:
    if source.format not in ('PNG','JPEG','WEBP') or source.width*source.height>16_000_000:raise ValueError('Нужна PNG, JPEG или WebP до 16 мегапикселей')
    from PIL import ImageOps
    im=ImageOps.exif_transpose(source).convert('RGBA');out=io.BytesIO();im.save(out,format='PNG');content=out.getvalue()
  except (OSError,Image.DecompressionBombError):raise ValueError('Не удалось прочитать изображение')
  reference=hashlib.sha256(content).hexdigest();path=self.root/'references'/(reference+'.png')
  with self.lock:
   if not path.exists():
    import tempfile,os
    with tempfile.NamedTemporaryFile(dir=path.parent,delete=False) as f:f.write(content);temporary=f.name
    os.replace(temporary,path)
  return dict(reference=reference,width=im.width,height=im.height)
 def generation_request(self,d,runtime):
  arguments=dict(prompt=generation_prompt(d)+(TILE if d['mode']=='tile' else ALPHA),model='qwen21_turbo',seed=d['seed'],postprocess=False)
  function='sprite_generate'
  if d.get('reference'):
   source=self.reference_file(d['reference']);target=runtime/'references'/source.name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
   arguments['reference_path']=str(target.relative_to(runtime));function='sprite_edit'
  return function,arguments
 def save_asset(self,key,patch,revision):
  with self.lock:
   current=self.metadata(key)
   if revision!=current.get('revision',0):raise Conflict('Предмет изменился в другой вкладке. Обновите карточку.')
   if any(j['key']==key and j['status']=='running' for j in self.jobs):raise Conflict('Предмет сейчас обрабатывается. Дождитесь завершения.')
   d=self.validate(patch,current)
   if d['key']!=key:raise ValueError('Нельзя переименовать папку или ID через настройки предмета')
   raw,meta=self.paths(key)
   if d['reviewed'] and not raw.exists():raise ValueError('Сначала сгенерируйте предмет')
   if any(d.get(k)!=current.get(k) for k in ('width','height','scale','mode')) and 'reviewed' not in patch:d['reviewed']=False
   d['revision']=current.get('revision',0)+1;write(meta,d);self.clear_cache(key);return self.asset(key)
 def add(self,items):
  if not isinstance(items,list) or not 1<=len(items)<=500:raise ValueError('Пакет: от 1 до 500 заданий')
  valid=[self.validate(item) for item in items]
  if any(not d['prompt'] for d in valid):raise ValueError('Для генерации нужен промпт каждого предмета')
  if len({d['key'] for d in valid})!=len(valid):raise ValueError('Повторяющийся ID в одной категории')
  with self.lock:
   existing=set(self.keys())
   if any(d['key'] in existing for d in valid):raise ValueError('Предмет с таким ID уже существует. Используйте «Перегенерировать».')
   for d in valid:
    self.create_category(d['category']);d['revision']=1;raw,meta=self.paths(d['key']);write(meta,d)
    self._enqueue(d['key'],'generate')
   self.persist()
  return [d['key'] for d in valid]
 def direction_variants(self,key,revision,perspective):
  with self.lock:
   base=self.asset(key)
   if revision!=base['revision']:raise Conflict('Предмет изменился. Обновите карточку.')
   if base.get('parent_key'):raise ValueError('Выберите основной предмет')
   if not base['available']:raise ValueError('Сначала сгенерируйте основной образец')
   if any(j['key']==key and j['status'] in ('running','queued','unknown') for j in self.jobs):raise ValueError('Основной предмет сейчас в очереди')
   camera=perspective or base.get('perspective') or 'rpg'
   validate_viewpoint(dict(perspective=camera))
   raw,_=self.paths(key);source=self.root/base['output']['files']['sprite'] if base['output_current'] else raw
   reference=self.upload_reference(base64.b64encode(source.read_bytes()).decode())['reference']
   direction=base.get('direction') or 'front'
   labels={'front':'спереди','back':'сзади','left':'слева','right':'справа'}
   prefix='view_'+hashlib.sha256(key.encode()).hexdigest()[:16]
   items=[]
   for face in labels:
    if face==direction:continue
    item={k:base[k] for k in ('category','style','width','height','scale','palette','auto_process')}
    item.update(id=prefix+'_'+face,label=base['label']+' · '+labels[face],parent_key=key,reference=reference,perspective=camera,direction=face,seed=uuid.uuid4().int%(2**32),reviewed=False,mode='prop',prompt='One identical object to the reference, rotated to the requested direction. Preserve its exact design, material, color, proportions and wear. The reference defines the object identity, not the viewing direction. Show the whole object. No room or extra objects.')
    item=self.validate(item);items.append(item)
   for item in items:
    if any(j['key']==item['key'] and j['status'] in ('queued','running','unknown') for j in self.jobs):raise ValueError('Ракурсы уже в очереди. Дождитесь результата.')
   for item in items:
    _,meta=self.paths(item['key']);old=read(meta) if meta.exists() else {};item['revision']=old.get('revision',0)+1;write(meta,item);self.clear_cache(item['key']);self._enqueue(item['key'],'generate')
   self.persist();return [item['key'] for item in items]
 def manual_direction(self,data):
  from PIL import ImageOps
  with self.lock:
   base=self.asset(data.get('key'));face=data.get('direction')
   if base.get('parent_key'):raise ValueError('Выберите основной предмет')
   if data.get('revision')!=base['revision']:raise Conflict('Предмет изменился. Откройте ракурсы заново.')
   if face not in ('front','back','left','right'):raise ValueError('Выберите направление')
   if base['mode']!='prop':raise ValueError('Ракурсы доступны для предметов')
   source_key=data.get('mirror_from');source=None
   if source_key:
    source=self.asset(source_key)
    if source_key!=base['key'] and source.get('parent_key')!=base['key']:raise ValueError('Источник относится к другому предмету')
    if source.get('revision')!=data.get('source_revision'):raise Conflict('Исходный ракурс изменился')
    if {'left':'right','right':'left'}.get(source.get('direction') or 'front')!=face:raise ValueError('Отражение создаёт противоположный боковой вид')
    if not source['available']:raise ValueError('Нет изображения для отражения')
   target_key=base['key'] if (base.get('direction') or 'front')==face else base['category']+'/view_'+hashlib.sha256(base['key'].encode()).hexdigest()[:16]+'_'+face
   existing=target_key in self.keys();target=self.metadata(target_key) if existing else None
   if existing and data.get('target_revision')!=(target.get('revision',0)):raise Conflict('Целевой ракурс изменился. Откройте его заново.')
   busy_keys={base['key'],target_key,source_key}
   if any(j['key'] in busy_keys and j['status'] in ('queued','running','unknown') for j in self.jobs):raise ValueError('Дождитесь завершения заданий этих ракурсов')
   if source:
    path,_=self.paths(source_key)
    with Image.open(path) as im:mirrored=ImageOps.mirror(im.convert('RGBA'));buf=io.BytesIO();mirrored.save(buf,format='PNG')
    ref=self.upload_reference(base64.b64encode(buf.getvalue()).decode())['reference']
   else:ref=self.upload_reference(data.get('data'))['reference']
   image=self.reference_file(ref)
   if not existing:
    label={'front':'спереди','back':'сзади','left':'слева','right':'справа'}[face]
    target={k:base[k] for k in ('category','style','width','height','scale','palette','auto_process')}
    target.update(id=target_key.split('/')[1],label=base['label']+' · '+label,prompt='Same object as the reference.',mode='prop',parent_key=base['key'],perspective=base.get('perspective') or 'rpg',direction=face,reference=None,revision=0)
    target=self.validate(target);_,meta=self.paths(target_key);write(meta,target)
   result=dict(operation='mirror' if source else 'manual_import',source_key=source_key,reference_sha256=ref,created_at=time.time())
   self.install_raw(target_key,image,result)
   warning=None
   try:self.process(target_key)
   except ValueError as exc:warning=str(exc)
   return dict(asset=self.asset(target_key),warning=warning)
 def inspect(self,key):
  raw,_=self.paths(key)
  if not raw.exists():return None
  stat=raw.stat();cachekey=(key,stat.st_mtime_ns,stat.st_size)
  if cachekey in self.cache:return self.cache[cachekey]
  d=self.metadata(key)
  with Image.open(raw) as source:
   im=source.convert('RGBA');hist=im.getchannel('A').histogram();bbox=(0,0,*im.size) if d['mode']=='tile' else im.getchannel('A').point(lambda x:255 if x>128 else 0).getbbox()
   ok=(hist[255]==im.width*im.height if d['mode']=='tile' else hist[0]>0 and sum(hist[129:])>0)
   result=dict(source_sha256=sha(raw),raw_size=list(im.size),crop_bbox=list(bbox) if bbox else None,alpha_ok=ok,transparent_pixels=hist[0],opaque_pixels=hist[255])
  # Mode changes affect crop policy, so cache raw facts only for this metadata revision.
  self.cache={k:v for k,v in self.cache.items() if k[0]!=key};self.cache[cachekey]=result
  return result
 def clear_cache(self,key):self.cache={k:v for k,v in self.cache.items() if k[0]!=key}
 def asset(self,key):
  d=self.metadata(key);facts=self.inspect(key);active=[j for j in self.jobs if j['key']==key and j['status'] in ('queued','running','unknown')]
  manifest=self.root/'output'/d['category']/d['id']/'result.json';out=read(manifest) if manifest.exists() else None
  expected=self.processing_signature(d,facts) if facts else None
  return d|dict(available=facts is not None,image=facts,output=out,output_current=bool(out and out.get('signature')==expected),job=active[-1] if active else None,
                history_count=len(list((self.root/'history'/d['category']/d['id']).glob('*/raw.png'))))
 def snapshot(self):
  with self.lock:
   return dict(categories=self.categories(),assets=[self.asset(k) for k in self.keys()],jobs=self.jobs[-500:],running=bool(self.thread and self.thread.is_alive()),paused=self.paused,root=str(self.root),adapter='qwen21_turbo',style=STYLE)
 def prepare_generation_gpu(self):
  def ensure_idle_queue():
   with urllib.request.urlopen('http://127.0.0.1:8188/queue',timeout=5) as response:queue=json.load(response)
   if queue.get('queue_running') or queue.get('queue_pending'):raise ValueError('В ComfyUI выполняется или ожидает задание. Дождитесь завершения; оно не прерывалось.')
  ensure_idle_queue()
  try:gpu_idle();return
  except RuntimeError:pass
  # Only the idle ComfyUI model cache is released. No processes are stopped.
  ensure_idle_queue()
  request=urllib.request.Request('http://127.0.0.1:8188/free',data=json.dumps({'unload_models':True,'free_memory':True}).encode(),headers={'Content-Type':'application/json'})
  with urllib.request.urlopen(request,timeout=30) as response:response.read()
  for attempt in range(20):
   try:gpu_idle();return
   except RuntimeError:
    if attempt==19:raise ValueError('После освобождения кэша ComfyUI видеопамять всё ещё занята. Закройте использующее её приложение и повторите генерацию.')
    time.sleep(.5)
 def install_raw(self,key,source,result):
  raw,meta=self.paths(key);d=self.metadata(key)
  if raw.exists():
   history=self.root/'history'/d['category']/d['id']/(str(time.time_ns())+'-'+uuid.uuid4().hex[:8]);history.mkdir(parents=True)
   shutil.copy2(raw,history/'raw.png')
   if meta.exists():shutil.copy2(meta,history/'settings.json')
  temporary=raw.with_suffix('.pending.png');shutil.copyfile(source,temporary);temporary.replace(raw)
  d.update(raw_sha256=sha(raw),generation=result,reviewed=False,revision=d.get('revision',0)+1);write(meta,d);self.clear_cache(key)
 def processing_signature(self,d,facts):
  return sprite_processing.processing_signature(d,facts)
 def process(self,key):
  with self.lock:
   d=self.metadata(key);raw,_=self.paths(key);facts=self.inspect(key)
   return sprite_processing.process(self.root,key,d,raw,facts)
 def history(self,key):
  d=self.metadata(key);root=self.root/'history'/d['category']/d['id'];rows=[]
  for path in sorted(root.glob('*/raw.png'),reverse=True):
   settings=read(path.parent/'settings.json') if (path.parent/'settings.json').exists() else {}
   rows.append(dict(version=path.parent.name,scale=settings.get('scale',1),width=settings.get('width'),height=settings.get('height')))
  return rows
 def history_file(self,key,version):
  d=self.metadata(key)
  if not isinstance(version,str) or not re.fullmatch(r'[0-9]+-[a-f0-9]{8}',version):raise ValueError('Неизвестная версия')
  p=self.root/'history'/d['category']/d['id']/version/'raw.png'
  if not p.resolve().is_relative_to(self.root/'history') or not p.is_file():raise ValueError('Версия не найдена')
  return p
 def thumbnail(self,key,processed=False):
  raw,_=self.paths(key)
  if processed:
   a=self.asset(key)
   if not a['output']:raise ValueError('Нет готового PNG')
   raw=self.root/a['output']['files']['preview']
  if not raw.exists():raise ValueError('Нет изображения')
  with Image.open(raw) as loaded:
   im=loaded.convert('RGBA')
   if not processed:
    facts=self.inspect(key)
    if facts['crop_bbox']:im=im.crop(facts['crop_bbox'])
   im.thumbnail((512,512),Image.Resampling.NEAREST if processed else Image.Resampling.LANCZOS);buf=io.BytesIO();im.save(buf,format='PNG');return buf.getvalue()
 def export_settings(self):
  with self.lock:return dict(version=1,application='sprite-workshop',saved_at=time.time(),assets=[self.metadata(k) for k in self.keys()])
 def import_settings(self,data):
  if not isinstance(data,dict) or data.get('application')!='sprite-workshop' or not isinstance(data.get('assets'),list):raise ValueError('Нужен JSON настроек этой мастерской')
  with self.lock:
   updates=[]
   for item in data['assets']:
    key=item.get('key');old=self.metadata(key);new=self.validate(item,old)
    if new['key']!=key:raise ValueError('Не совпадает ID')
    raw,_=self.paths(key)
    if item.get('raw_sha256') and (not raw.exists() or sha(raw)!=item['raw_sha256']):raise ValueError('Исходник изменился: '+key)
    if any(j['key']==key and j['status']=='running' for j in self.jobs):raise Conflict('Предмет обрабатывается: '+key)
    updates.append((key,new,old.get('revision',0)))
   for key,new,revision in updates:
    raw,meta=self.paths(key);new['revision']=revision+1;write(meta,new);self.clear_cache(key)
   return len(updates)
