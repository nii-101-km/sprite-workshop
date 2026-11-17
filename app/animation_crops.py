"""Non-destructive rectangle imports from complete animation sheets."""
import base64,io,shutil,time
from PIL import Image
from adapter import sha,write
from store import integer
from animations import uid,fit,cutout

def prepare(manager,data):
 p=manager.load(data['project']);manager.check(p,data['revision']);target=manager.track(p,data['track'])
 if manager.busy(p['id'],target['id']):raise ValueError('Дождитесь задания этого действия или уберите его из очереди')
 source=data.get('source')
 if not isinstance(source,dict):raise ValueError('Выберите исходный лист')
 if source.get('reference'):
  path=manager.app.reference_file(source['reference'])
 else:
  _,f=manager.frame(p,source.get('frame'));v=manager.version(f,source.get('version'));path=manager.local(p,v.get('reference_raw',v['raw']))
 rectangles=data.get('rectangles');start=integer(data.get('start',0),0,11,'Начальный кадр')
 if not isinstance(rectangles,list) or not 1<=len(rectangles)<=12 or start+len(rectangles)>12:raise ValueError('Выберите от 1 до 12 прямоугольников, не выходя за 12 кадров')
 for f in target['frames'][start:start+len(rectangles)]:
  if f['accepted']:raise ValueError('Среди заменяемых кадров есть принятые. Снимите приёмку с них или выберите другие позиции.')
 crops=[];boxes=[]
 with Image.open(path) as image:
  for row in rectangles:
   if not isinstance(row,list) or len(row)!=4:raise ValueError('Прямоугольник: x, y, ширина, высота')
   x=integer(row[0],0,image.width-1,'X');y=integer(row[1],0,image.height-1,'Y');w=integer(row[2],2,image.width,'Ширина');h=integer(row[3],2,image.height,'Высота')
   if x+w>image.width or y+h>image.height:raise ValueError('Прямоугольник выходит за границы листа')
   crop=image.convert('RGBA').crop((x,y,x+w,y+h));cutout(crop);crops.append(crop);boxes.append(row)
 # One shared scale across the import preserves relative character size and bob.
 silhouettes=[cutout(crop) for crop in crops];ratio=min(p['size'][0]/max(im.width for im in silhouettes),p['size'][1]/max(im.height for im in silhouettes));sprites=[fit(crop,p['size'],ratio) for crop in crops]
 return p,target,path,boxes,crops,sprites,start

def preview(manager,data):
 with manager.lock:
  p,t,path,boxes,crops,sprites,start=prepare(manager,data);images=[]
  for sprite in sprites:
   out=io.BytesIO();sprite.save(out,'PNG');images.append(base64.b64encode(out.getvalue()).decode())
  return dict(images=images,size=p['size'],start=start,count=len(images),source_sha256=sha(path))

def commit(manager,data):
 with manager.lock:
  p,t,path,boxes,crops,sprites,start=prepare(manager,data)
  if data.get('source_sha256') and data['source_sha256']!=sha(path):raise ValueError('Лист изменился после предпросмотра. Откройте его заново.')
  batch=uid();folder=manager.folder(p['id'])/'sheets'/batch;folder.mkdir(parents=True);shutil.copy2(path,folder/'source.png');source_sha=sha(folder/'source.png');records=[]
  # Complete validation and all image processing happen before project metadata changes.
  while len(t['frames'])<start+len(boxes):t['frames'].append(dict(id=uid(),versions=[],version=None,accepted=False,scale=1,x=0,y=0))
  for offset,(rect,raw,sprite) in enumerate(zip(boxes,crops,sprites)):
   version=uid();dest=manager.folder(p['id'])/'versions'/version;dest.mkdir(parents=True);raw.save(dest/'raw.png');sprite.save(dest/'sprite.png');relative=lambda filename:str((dest/filename).relative_to(manager.folder(p['id'])))
   f=t['frames'][start+offset];f['versions'].append(dict(id=version,raw=relative('raw.png'),sprite=relative('sprite.png'),sha256=sha(dest/'raw.png'),created_at=time.time(),crop=dict(sheet=batch,rectangle=rect,source_sha256=source_sha)))
   f.update(version=version,accepted=False,scale=1,x=0,y=0);records.append(dict(frame=f['id'],version=version,index=start+offset,rectangle=rect))
  write(folder/'slicing.json',dict(source=data['source'],source_sha256=source_sha,track=t['id'],frames=records,created_at=time.time()))
  manager.save(p);return dict(project=p,count=len(records),track=t['id'],frames=[r['frame'] for r in records],sheet=batch)
