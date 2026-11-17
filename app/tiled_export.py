"""Stable, local Tiled image-collection export; variants share their object's folder."""
import hashlib,json,os,tempfile
from pathlib import Path
from PIL import Image
from adapter import write

def atomic_image(source,target):
 target.parent.mkdir(parents=True,exist_ok=True)
 if target.is_symlink():raise ValueError('Ссылка вместо PNG экспорта')
 with tempfile.NamedTemporaryFile(dir=target.parent,delete=False) as f:
  temporary=Path(f.name);f.write(source.read_bytes())
 os.replace(temporary,target)

def export(app):
 with app.lock:
  root=app.root/'exports/tiled';root.mkdir(parents=True,exist_ok=True)
  if root.is_symlink() or not root.resolve().is_relative_to(app.root.resolve()):raise ValueError('Папка экспорта не должна быть ссылкой')
  manifest_path=root/'manifest.json'
  manifest=json.loads(manifest_path.read_text()) if manifest_path.exists() else {'version':1,'categories':{}}
  assets={k:app.asset(k) for k in app.keys()};skipped=[];updated=0
  for category in manifest['categories'].values():
   for record in category['entries'].values():record['active']=False
  for key,a in sorted(assets.items()):
   parent=a.get('parent_key') or key
   if parent not in assets:skipped.append(dict(key=key,reason='Нет основного предмета'));continue
   if not a['output_current']:
    skipped.append(dict(key=key,reason='Нет актуальной сборки PNG'));continue
   source=(app.root/a['output']['files']['sprite']).resolve()
   if not source.is_relative_to(app.root.resolve()) or not source.is_file():raise ValueError('Недоступен PNG: '+key)
   base=assets[parent];name=base['category'];cat_id=hashlib.sha256(name.encode()).hexdigest()[:12]
   category=manifest['categories'].setdefault(name,dict(folder=name+'-'+cat_id,entries={},next_id=0))
   folder=root/category['folder'];folder.mkdir(exist_ok=True)
   if folder.is_symlink() or not folder.resolve().is_relative_to(root.resolve()):raise ValueError('Недопустимая папка категории')
   object_id=base['id']+'-'+hashlib.sha256(parent.encode()).hexdigest()[:8]
   obj=folder/object_id;obj.mkdir(exist_ok=True)
   if obj.is_symlink() or not obj.resolve().is_relative_to(folder.resolve()):raise ValueError('Недопустимая папка предмета')
   filename=('main' if parent==key else a.get('direction') or a['id'])+'.png'
   target=obj/filename;atomic_image(source,target)
   with Image.open(target) as im:width,height=im.size
   entry=category['entries'].get(key)
   if entry is None:
    entry={'id':category['next_id']};category['next_id']+=1;category['entries'][key]=entry
   entry.update(image=target.relative_to(folder).as_posix(),width=width,height=height,label=base['label'],parent=parent,direction=a.get('direction',''),active=True,revision=a['revision'])
   updated+=1
  # Reserve IDs durably before publishing any new tileset.
  write(manifest_path,manifest)
  files=[]
  for name,c in manifest['categories'].items():
   folder=root/c['folder'];tiles=[]
   for key,e in sorted(c['entries'].items(),key=lambda pair:pair[1]['id']):
    tiles.append(dict(id=e['id'],image=e['image'],imagewidth=e['width'],imageheight=e['height'],properties=[dict(name='asset_key',type='string',value=key),dict(name='object_key',type='string',value=e['parent']),dict(name='label',type='string',value=e['label']),dict(name='direction',type='string',value=e['direction']),dict(name='current',type='bool',value=e['active'])]))
   ts=dict(type='tileset',version='1.10',name=name,tilewidth=max((t['imagewidth'] for t in tiles),default=16),tileheight=max((t['imageheight'] for t in tiles),default=16),tilecount=c['next_id'],columns=0,objectalignment='bottom',tiles=tiles)
   path=folder/'collection.tsj';write(path,ts);files.append(str(path))
  write(manifest_path,manifest)
  (root/'README.txt').write_text('В Tiled: добавить внешний набор тайлов → выбрать collection.tsj нужной категории.\nКаждый предмет хранится в своей папке: main.png и направления.\nОбновление: кнопка «Обновить для Tiled» в мастерской. Номера элементов и пути сохраняются.\nУдалённые или устаревшие предметы сохраняют последний экспорт с current=false, чтобы не ломать карты.\nНе удаляйте manifest.json и не перемещайте отдельные PNG. Карты этой операцией не меняются.\nЭкспорт предназначен для вашего проекта; условия сторонних наборов продолжают действовать.\n')
  return dict(root=str(root),tilesets=files,exported=updated,skipped=skipped,retained=sum(not e['active'] for c in manifest['categories'].values() for e in c['entries'].values()))
