"""Local versioned animation projects using the workshop image generator."""
import io,json,math,os,shutil,subprocess,sys,threading,time,uuid,urllib.request,zipfile
from pathlib import Path
from PIL import Image,ImageOps
from adapter import read,write,sha,gpu_idle
from store import ident,integer,Conflict,STYLE
DIRECTIONS={'down':'К нам','left':'Влево','up':'От нас','right':'Вправо'}
VIEWS={'down':'Front view, facing viewer.','left':'Face toward SCREEN LEFT, the LEFT edge of the image. Facial features and boot toes point LEFT; the back of the head, lowered hood and boot heels are on the RIGHT. This is an image-space direction, not the anatomical left side.','up':'BACK VIEW facing away. No face, chest, front buttons or front belt buckle. Preserve the long rear costume coverage.','right':'Face toward SCREEN RIGHT, the RIGHT edge of the image. Facial features and boot toes point RIGHT; the back of the head, lowered hood and boot heels are on the LEFT. This is an image-space direction, not the anatomical right side.'}
ACTIONS={'idle':'Neutral standing idle, feet planted, arms relaxed.','walk':'Walking loop. Alternate left and right leg contact and passing poses, opposite arm swing.','run':'Running loop with alternating legs, bent elbows and a visible airborne phase.'}
def uid():return uuid.uuid4().hex

def cutout(image):
 im=image.convert('RGBA');a=im.getchannel('A');hist=a.histogram()
 if not hist[0] or not sum(hist[129:]):raise ValueError('Нет пригодной прозрачности. Исходник сохранён; фон по цвету не вырезается.')
 box=a.point(lambda n:255 if n>128 else 0).getbbox()
 if not box:raise ValueError('Пустой кадр')
 return im.crop(box)

def fit(image,size,ratio=None):
 im=cutout(image);ratio=ratio or min(size[0]/im.width,size[1]/im.height)
 im=im.resize((max(1,round(im.width*ratio)),max(1,round(im.height*ratio))),Image.Resampling.BOX)
 alpha=im.getchannel('A').point(lambda n:255 if n>128 else 0)
 neutral=Image.new('RGBA',im.size,(30,30,30,255));neutral.alpha_composite(im)
 im=neutral.convert('RGB').quantize(colors=32,method=Image.Quantize.MEDIANCUT,dither=Image.Dither.NONE).convert('RGBA');im.putalpha(alpha);im.paste((0,0,0,0),mask=ImageOps.invert(alpha))
 canvas=Image.new('RGBA',size);canvas.paste(im,((size[0]-im.width)//2,size[1]-im.height));return canvas

class Animations:
 def __init__(self,workshop):
  self.app=workshop;self.root=workshop.root/'animations';self.root.mkdir(exist_ok=True)
  for folder in ('projects','jobs'): (self.root/folder).mkdir(exist_ok=True)
  self.lock=workshop.lock;self.thread=None;self.paused=True;self.jobs_path=self.root/'jobs.json';self.jobs=read(self.jobs_path) if self.jobs_path.exists() else []
  for j in self.jobs:
   if j['status']=='running':j.update(status='unknown',error='Перезапуск: проверьте результат, повтор не отправлен.')
  self.persist();self.app.animation_busy=any(j['status']=='unknown' for j in self.jobs)
 def persist(self):write(self.jobs_path,self.jobs)
 def folder(self,project):
  project=ident(project);p=self.root/'projects'/project
  if p.is_symlink() or not p.resolve().is_relative_to(self.root/'projects'):raise ValueError('Недопустимый проект')
  return p
 def load(self,project):return read(self.folder(project)/'project.json')
 def save(self,p):p['revision']=p.get('revision',0)+1;write(self.folder(p['id'])/'project.json',p);return p
 def track(self,p,key):
  track=next((t for t in p['tracks'] if t['id']==key),None)
  if track is None:raise ValueError('Действие не найдено')
  return track
 def frame(self,p,key):
  for t in p['tracks']:
   for f in t['frames']:
    if f['id']==key:return t,f
  raise ValueError('Кадр не найден')
 def version(self,f,version=None):
  v=next((v for v in f['versions'] if v['id']==(version or f.get('version'))),None)
  if v is None:raise ValueError('Кадр ещё не создан')
  return v
 def local(self,p,relative):
  path=(self.folder(p['id'])/relative).resolve()
  if not path.is_relative_to(self.folder(p['id']).resolve()) or not path.is_file():raise ValueError('Файл не найден')
  return path
 def check(self,p,revision):
  if p['revision']!=revision:raise Conflict('Проект изменился. Обновите страницу и повторите правку.')
 def busy(self,project,track):return any(j['project']==project and j['track']==track and j['status'] in ('queued','running','unknown') for j in self.jobs)
 def new_track(self,action,direction,count,prompt=''):
  ident(action)
  if direction not in DIRECTIONS:raise ValueError('Неизвестное направление')
  integer(count,1,12,'Кадров')
  return dict(id=action+'_'+direction,action=action,direction=direction,prompt=prompt,reference=None,fps=7,frames=[dict(id=uid(),versions=[],version=None,accepted=False,scale=1,x=0,y=0) for _ in range(count)])
 def create(self,data):
  with self.lock:
   project=ident(data.get('id',''));folder=self.folder(project)
   if folder.exists():raise ValueError('Проект с таким ID уже есть')
   label=data.get('label',project);prompt=data.get('prompt','');reference=data.get('reference')
   if not isinstance(label,str) or not 1<=len(label.strip())<=120 or not isinstance(prompt,str) or len(prompt)>12000:raise ValueError('Проверьте название и описание персонажа')
   if reference:self.app.reference_file(reference)
   size=[integer(data.get('width',32),16,256,'Ширина'),integer(data.get('height',64),16,256,'Высота')]
   folder.mkdir();p=dict(id=project,label=label.strip(),prompt=prompt,reference=reference,size=size,revision=0,tracks=[],exports=[])
   for action,count in [('idle',1),('walk',4)]:
    for direction in DIRECTIONS:p['tracks'].append(self.new_track(action,direction,count))
   return self.save(p)
 def snapshot(self,project=None):
  with self.lock:
   projects=[]
   for path in sorted((self.root/'projects').glob('*/project.json')):
    p=self.load(path.parent.name);frames=[f for t in p['tracks'] for f in t['frames']];projects.append(dict(id=p['id'],label=p['label'],ready=sum(bool(f['version']) for f in frames),accepted=sum(f['accepted'] for f in frames),total=len(frames)))
   return dict(projects=projects,project=self.load(project) if project else None,jobs=self.jobs[-100:],running=bool(self.thread and self.thread.is_alive()),paused=self.paused,directions=DIRECTIONS)
 def update(self,data):
  with self.lock:
   p=self.load(data['project']);self.check(p,data['revision']);operation=data['operation']
   if operation=='project':
    for field,limit in [('label',120),('prompt',12000)]:
     if field in data:
      if not isinstance(data[field],str) or not data[field].strip() or len(data[field])>limit:raise ValueError('Проверьте поле '+field)
      p[field]=data[field].strip()
    if 'reference' in data:
     if data['reference']:self.app.reference_file(data['reference'])
     p['reference']=data['reference'] or None
   elif operation=='add-track':
    if len(p['tracks'])>=40:raise ValueError('Не более 40 действий с направлениями')
    t=self.new_track(data['action'],data['direction'],data['count'])
    if any(old['id']==t['id'] for old in p['tracks']):raise ValueError('Это действие и направление уже добавлены')
    p['tracks'].append(t)
   elif operation=='track':
    t=self.track(p,data['track'])
    if self.busy(p['id'],t['id']):raise ValueError('Сначала дождитесь задания или уберите его из очереди')
    if 'fps' in data:t['fps']=integer(data['fps'],1,24,'Скорость')
    if 'prompt' in data:
     if not isinstance(data['prompt'],str) or len(data['prompt'])>6000:raise ValueError('Слишком длинный промпт')
     t['prompt']=data['prompt']
    if 'reference' in data:
     if data['reference']:self.app.reference_file(data['reference'])
     t['reference']=data['reference'] or None
   elif operation=='frame':
    t,f=self.frame(p,data['frame'])
    if self.busy(p['id'],t['id']):raise ValueError('Действие находится в очереди')
    if 'version' in data:
     self.version(f,data['version'])
     if f['version']!=data['version']:f['version']=data['version'];f['accepted']=False
    changed=False
    for field,lo,hi in [('x',-256,256),('y',-256,256)]:
     if field in data:
      value=integer(data[field],lo,hi,field);changed=changed or f[field]!=value;f[field]=value
    if 'scale' in data:
     v=data['scale']
     if type(v) not in (float,int) or not math.isfinite(v) or not .25<=v<=3:raise ValueError('Масштаб: 0.25–3')
     changed=changed or f['scale']!=round(v,2);f['scale']=round(v,2)
    if changed:f['accepted']=False
    if 'accepted' in data:
     if type(data['accepted']) is not bool:raise ValueError('Неверная приёмка')
     self.version(f);f['accepted']=data['accepted']
   else:raise ValueError('Неизвестная операция')
   return self.save(p)
 def reference_from_frame(self,data):
  with self.lock:
   p=self.load(data['project']);self.check(p,data['revision']);_,f=self.frame(p,data['frame']);v=self.version(f)
   source=self.local(p,v.get('reference_raw',v['raw']));result=self.app.upload_reference(__import__('base64').b64encode(source.read_bytes()).decode())
   if data.get('scope')=='project':
    p['reference']=result['reference'];p['reference_source']=dict(frame=f['id'],version=v['id'])
   else:
    target=self.track(p,data['track'])
    if self.busy(p['id'],target['id']):raise ValueError('Действие находится в очереди')
    target['reference']=result['reference'];target['reference_source']=dict(frame=f['id'],version=v['id'])
   return self.save(p)
 def render(self,p,f):
  v=self.version(f);base=Image.open(self.local(p,v['sprite'])).convert('RGBA');size=p['size'];scale=f['scale']
  if scale!=1:base=base.resize((max(1,round(size[0]*scale)),max(1,round(size[1]*scale))),Image.Resampling.NEAREST)
  canvas=Image.new('RGBA',tuple(size));canvas.paste(base,(round((size[0]-base.width)/2)+f['x'],size[1]-base.height+f['y']));return canvas
 def image(self,data):
  with self.lock:
   p=self.load(data['project']);_,f=self.frame(p,data['frame']);v=self.version(f,data.get('version'))
   kind=data.get('kind','frame')
   if kind=='raw':return self.local(p,v.get('reference_raw',v['raw'])).read_bytes()
   if kind!='frame':raise ValueError('Неизвестное изображение')
   f=dict(f,version=v['id']);out=io.BytesIO();self.render(p,f).save(out,'PNG');return out.getvalue()
 def make_prompt(self,p,t,index):
  action=t['action'];count=len(t['frames']);phase= ('Standing neutral, both boots planted.' if action=='idle' else f'Animation frame {index+1} of {count}. Phase {index/count:.3f} of one complete {action} cycle. '+ ['Left leg forward contact; right leg behind.','Passing pose: right knee lifted forward; left leg supports body.','Right leg forward contact; left leg behind.','Passing pose: left knee lifted forward; right leg supports body.'][index%4])
  if action not in ('idle','walk','run'):phase=f'Frame {index+1} of {count} of the requested action. Follow the action instructions exactly.'
  identity=('Preserve EXACT reference identity, outfit, materials and body proportions. Show ONLY the back of the head and body. Eyes, mouth, chest lettering and front pockets are hidden on the far side and must not appear on the back.' if t['direction']=='up' else 'Preserve EXACT reference identity, face, hair, outfit and body proportions.')
  return STYLE+' Create ONE complete full-body character sprite. '+p['prompt']+' '+VIEWS[t['direction']]+' '+ACTIONS.get(action,action)+' '+t['prompt']+' '+phase+' Use the reference for appearance, not its camera view or body orientation. The requested SCREEN direction takes priority over the reference pose. '+identity+' Orthographic game view slightly from above. Full head and boots visible. Only ONE character, no duplicate, no sprite sheet, no labels, no floor or cast shadow. Actual transparent RGBA background, alpha zero outside the character. No colored background or halo.'
 def enqueue(self,data):
  with self.lock:
   p=self.load(data['project']);self.check(p,data['revision']);t=self.track(p,data['track'])
   if self.busy(p['id'],t['id']):raise ValueError('Это действие уже в очереди')
   frames=t['frames'] if not data.get('frame') else [next((f for f in t['frames'] if f['id']==data['frame']),None)]
   if not all(frames):raise ValueError('Кадр не найден')
   if any(f['accepted'] for f in frames):raise ValueError('Принятые кадры защищены. Снимите приёмку только с кадров, которые нужно переделать.')
   reference=t.get('reference') or p.get('reference')
   if not reference:raise ValueError('Выберите референс персонажа или направления')
   # Canonical square reference prevents aspect-ratio distortion in Qwen.
   source=self.app.reference_file(reference)
   im=Image.open(source).convert('RGBA');im.thumbnail((850,850));square=Image.new('RGBA',(1024,1024));square.paste(im,((1024-im.width)//2,(1024-im.height)//2));buf=io.BytesIO();square.save(buf,'PNG');ref=self.app.upload_reference(__import__('base64').b64encode(buf.getvalue()).decode())['reference']
   for f in frames:
    index=t['frames'].index(f);self.jobs.append(dict(id=uid(),project=p['id'],track=t['id'],frame=f['id'],status='queued',prompt=self.make_prompt(p,t,index),reference=ref,seed=int.from_bytes(__import__('os').urandom(4),'big'),created_at=time.time()))
   self.persist();return self.snapshot(p['id'])
 def start(self):
  with self.lock:
   if getattr(self.app,'sf3d_busy',False):raise ValueError('Сейчас строятся 3D-ракурсы. Дождитесь завершения.')
   if self.thread and self.thread.is_alive():self.paused=False;return
   if self.app.thread and self.app.thread.is_alive():raise ValueError('Сейчас работает очередь предметов. Дождитесь завершения или поставьте её на паузу.')
   if any(j['status']=='unknown' for j in self.jobs) or any(j['status']=='unknown' for j in self.app.jobs):raise ValueError('Сначала проверьте неопределённое задание')
   self.app.animation_busy=True;self.paused=False;self.thread=threading.Thread(target=self.loop,daemon=True);self.thread.start()
 def pause(self):
  with self.lock:self.paused=True
 def cancel(self,job_id):
  with self.lock:
   j=next((j for j in self.jobs if j['id']==job_id),None)
   if not j or j['status']!='queued':raise ValueError('Можно убрать только ожидающее задание')
   j['status']='cancelled';self.persist()
 def loop(self):
  try:
   while True:
    with self.lock:
     if self.paused:return
     j=next((j for j in self.jobs if j['status']=='queued'),None)
     if j is None:return
     j.update(status='running',started_at=time.time());self.persist()
    try:self.generate(j)
    except Exception as exc:
     with self.lock:
      j.update(status='unknown' if j.get('submitted') and not j.get('backend_terminal') else 'failed',error=str(exc));self.paused=True;self.persist()
     return
  finally:
   with self.lock:self.app.animation_busy=any(j['status']=='unknown' for j in self.jobs)
 def generate(self,j):
  gpu_idle()
  with urllib.request.urlopen('http://127.0.0.1:8188/queue',timeout=5) as r:q=json.load(r)
  if q.get('queue_running') or q.get('queue_pending'):raise ValueError('ComfyUI занят. Чужая работа не прерывалась.')
  runtime=self.app.root/'runtime';runtime.mkdir(exist_ok=True);source=self.app.reference_file(j['reference']);dest=runtime/'references'/source.name;dest.parent.mkdir(exist_ok=True);shutil.copy2(source,dest)
  folder=self.root/'jobs'/j['id'];folder.mkdir(exist_ok=True);response=folder/'response.json';request=folder/'request.json'
  with self.lock:
   j['before_jobs']=[p.stem for p in (runtime/'results/jobs').glob('*.json')];j['submitted']=True;self.persist()
   write(request,dict(runtime=str(runtime),response=str(response),function='sprite_edit',arguments=dict(reference_path=str(dest.relative_to(runtime)),prompt=j['prompt'],seed=j['seed'],postprocess=False,model='qwen21_turbo')))
  with (folder/'worker.log').open('ab') as log:
   env=os.environ.copy();env['SPRITE_WORKSHOP_JOB_ID']=j['id']
   proc=subprocess.Popen([sys.executable,str(Path(__file__).with_name('worker.py')),str(request)],stdin=subprocess.DEVNULL,stdout=log,stderr=log,env=env)
   with self.lock:j['pid']=proc.pid;self.persist()
   proc.wait()
  self.accept_result(j,response)
 def accept_result(self,j,response):
  if not response.exists():raise ValueError('Ответ ещё не получен. Повтор не отправлен.')
  result=read(response).get('result',{})
  if result.get('status')=='failed' and result.get('cleanup_confirmed'):j['backend_terminal']=True
  if result.get('status')!='success' or not result.get('cleanup_confirmed'):raise ValueError('Генератор: '+str(result.get('status','неопределённый результат')))
  j['backend_terminal']=True;runtime=self.app.root/'runtime';source=(runtime/result['raw_path']).resolve()
  if not source.is_relative_to(runtime) or sha(source)!=result['raw_sha256']:raise ValueError('Исходник не прошёл проверку SHA')
  with self.lock:
   p=self.load(j['project']);_,f=self.frame(p,j['frame']);folder=self.folder(p['id'])/'versions'/j['id'];folder.mkdir(parents=True,exist_ok=True);shutil.copy2(source,folder/'raw.png')
   # Raw is retained even when alpha/processing fails.
   sprite=fit(Image.open(source),p['size']);sprite.save(folder/'sprite.png')
   if not any(v['id']==j['id'] for v in f['versions']):f['versions'].append(dict(id=j['id'],raw=str((folder/'raw.png').relative_to(self.folder(p['id']))),sprite=str((folder/'sprite.png').relative_to(self.folder(p['id']))),sha256=sha(source),created_at=time.time(),job_id=result['job_id']))
   f.update(version=j['id'],accepted=False);self.save(p);j.update(status='complete',backend_job_id=result['job_id'],finished_at=time.time());j.pop('error',None);self.persist()
 def recover(self,job_id):
  with self.lock:
   j=next((j for j in self.jobs if j['id']==job_id),None)
   if not j or j['status']!='unknown':raise ValueError('Нет задания для проверки')
   response=self.root/'jobs'/j['id']/'response.json'
   if not response.exists() or not read(response).get('result'):
    paths=[p for p in (self.app.root/'runtime/results/jobs').glob('*.json') if read(p).get('workshop_job_id')==j['id']]
    if len(paths)!=1:raise ValueError('Нет однозначного результата, повтор не отправлен')
    backend=read(paths[0])
    if backend.get('status') not in ('success','failed') or not backend.get('cleanup_confirmed'):raise ValueError('Генератор ещё не подтвердил успешное завершение')
    write(response,{'result':backend.get('result',{})|backend})
   try:self.accept_result(j,response)
   except Exception as exc:
    if j.get('backend_terminal'):j.update(status='failed',error=str(exc));self.persist();self.app.animation_busy=any(job['status']=='unknown' for job in self.jobs)
    raise
   self.app.animation_busy=any(job['status']=='unknown' for job in self.jobs)
 def export(self,project):
  with self.lock:
   p=self.load(project);tracks=[t for t in p['tracks'] if all(f['version'] for f in t['frames'])]
   if not tracks:raise ValueError('Сначала создайте все кадры хотя бы одного действия')
   folder=self.folder(project)/'exports'/uid();folder.mkdir(parents=True);w,h=p['size'];cols=max(len(t['frames']) for t in tracks);sheet=Image.new('RGBA',(cols*w,len(tracks)*h));manifest=dict(project=p['id'],label=p['label'],revision=p['revision'],image='spritesheet.png',frame_width=w,frame_height=h,columns=cols,rows=len(tracks),anchor=[w//2,h],animations={},missing_tracks=[t['id'] for t in p['tracks'] if t not in tracks]);framesdir=folder/'frames';framesdir.mkdir()
   for row,t in enumerate(tracks):
    images=[]
    for col,f in enumerate(t['frames']):
     im=self.render(p,f);im.save(framesdir/(t['id']+f'-{col:02}.png'));sheet.paste(im,(col*w,row*h));images.append(im)
    manifest['animations'][t['id']]=dict(action=t['action'],direction=t['direction'],frames=[row*cols+i for i in range(len(images))],fps=t['fps'],loop=True,accepted=all(f['accepted'] for f in t['frames']))
    images[0].save(folder/(t['id']+'.png'),save_all=len(images)>1,append_images=images[1:],duration=round(1000/t['fps']),loop=0,disposal=0,blend=0)
   sheet.save(folder/'spritesheet.png');write(folder/'animations.json',manifest)
   with zipfile.ZipFile(folder/'animation-pack.zip','w',zipfile.ZIP_DEFLATED) as z:
    for path in sorted(folder.rglob('*')):
     if path.is_file() and path.suffix in ('.png','.json'):z.write(path,path.relative_to(folder))
   result=dict(id=folder.name,created_at=time.time(),revision=p['revision'],tracks=len(tracks));p['exports'].append(result);self.save(p);return result
 def export_file(self,project,export,kind):
  if kind not in ('spritesheet.png','animations.json','animation-pack.zip'):raise ValueError('Неизвестный экспорт')
  p=self.load(project)
  if not any(e['id']==export for e in p['exports']):raise ValueError('Экспорт не найден')
  return self.local(p,'exports/'+ident(export)+'/'+kind)
