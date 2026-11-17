import trash
import tiled_export
"""Local-only application server. No GPU work until the user starts the queue."""
import argparse,fcntl,json,mimetypes,sys
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote,urlparse,parse_qs
from store import Workshop,Conflict
from semantic import SemanticIndex
from animations import Animations
from reconstruction import Reconstruction
import animation_crops
WEB=Path(__file__).resolve().parent

class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 @property
 def app(self):return self.server.app
 def host_ok(self):return self.headers.get('Host') in (f'localhost:{self.server.server_port}',f'127.0.0.1:{self.server.server_port}')
 def send(self,code,data,mime='application/json; charset=utf-8',download=None):
  if not isinstance(data,bytes):data=json.dumps(data,ensure_ascii=False).encode()
  self.send_response(code);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
  if download:self.send_header('Content-Disposition',f'attachment; filename="{download}"')
  self.end_headers();self.wfile.write(data)
 def do_GET(self):
  if not self.host_ok():return self.send(403,{'error':'Localhost only'})
  parsed=urlparse(self.path);path=unquote(parsed.path);query=parse_qs(parsed.query)
  try:
   if path=='/api/3d/state':return self.send(200,self.server.reconstruction.snapshot(query.get('key',[''])[0]))
   if path=='/api/3d/file':
    file=self.server.reconstruction.file(query.get('job',[''])[0],query.get('kind',[''])[0]);return self.send(200,file.read_bytes(),mimetypes.guess_type(file.name)[0] or 'application/octet-stream',file.name if file.suffix=='.glb' else None)
   if path=='/api/animations/state':return self.send(200,self.server.animations.snapshot(query.get('project',[None])[0]))
   if path=='/api/animations/frame':return self.send(200,self.server.animations.image({k:v[0] for k,v in query.items()}),'image/png')
   if path=='/api/animations/export-file':
    file=self.server.animations.export_file(query.get('project',[''])[0],query.get('export',[''])[0],query.get('kind',[''])[0]);return self.send(200,file.read_bytes(),mimetypes.guess_type(file.name)[0] or 'application/octet-stream',file.name)
   if path=='/api/trash':return self.send(200,{'entries':trash.entries(self.app)})
   if path=='/api/state':return self.send(200,self.app.snapshot())
   if path=='/api/semantic/status':return self.send(200,self.server.semantic.status())
   if path=='/api/settings':return self.send(200,self.app.export_settings(),download='sprite-workshop-settings.json')
   if path=='/reference':return self.send(200,self.app.reference_file(query.get('id',[''])[0]).read_bytes(),'image/png')
   if path=='/api/history':return self.send(200,self.app.history(query.get('key',[''])[0]))
   if path=='/history':return self.send(200,self.app.history_file(query.get('key',[''])[0],query.get('version',[''])[0]).read_bytes(),'image/png')
   if path=='/api/example':return self.send(200,{'version':1,'assets':[{'id':'blue_mug','label':'Синяя кружка','category':'Кухня','prompt':'One blue enamel mug with a white rim and handle.','mode':'prop','width':32,'height':32,'seed':42,'auto_process':True},{'id':'wood_floor','label':'Деревянный пол','category':'Полы','prompt':'Old warm wooden floor boards.','mode':'tile','width':32,'height':32,'seed':43,'auto_process':True}]},download='sprite-prompts-example.json')
   if path in ('/thumb','/raw','/png'):
    key=query.get('key',[''])[0];raw,_=self.app.paths(key)
    if path=='/thumb':return self.send(200,self.app.thumbnail(key,query.get('processed')==['1']),'image/png')
    if path=='/png':
     a=self.app.asset(key)
     if not a['output']:raise ValueError('Сначала соберите предмет')
     raw=self.app.root/a['output']['files']['sprite']
    if not raw.exists():raise ValueError('Нет изображения')
    return self.send(200,raw.read_bytes(),'image/png',raw.name if path=='/raw' else self.app.metadata(key)['id']+'.png')
   files={'/crop.js':('crop.js','text/javascript; charset=utf-8'),'/crop-geometry.js':('crop-geometry.js','text/javascript; charset=utf-8'),'/crop.css':('crop.css','text/css; charset=utf-8'),'/animations':('animations.html','text/html; charset=utf-8'),'/animations.js':('animations.js','text/javascript; charset=utf-8'),'/animations.css':('animations.css','text/css; charset=utf-8'),'/':('index.html','text/html; charset=utf-8'),'/app.js':('app.js','text/javascript; charset=utf-8'),'/style.css':('style.css','text/css; charset=utf-8')}
   if path in files:
    file,mime=files[path];return self.send(200,(WEB/file).read_bytes(),mime)
   if path in ('/i18n.js','/i18n-static.js','/i18n-ui.js'):
    return self.send(200,(WEB/path[1:]).read_bytes(),'text/javascript; charset=utf-8')
   if path=='/reconstruction.js':return self.send(200,(WEB/'reconstruction.js').read_bytes(),'text/javascript; charset=utf-8')
   orientation_files={'/orientation':('orientation.html','text/html; charset=utf-8'),'/orientation-viewer.js':('orientation-viewer.js','text/javascript; charset=utf-8'),'/orientation.css':('orientation.css','text/css; charset=utf-8')}
   if path in orientation_files:
    file,mime=orientation_files[path];return self.send(200,(WEB/file).read_bytes(),mime)
   if path.startswith('/vendor/three/') and path.rsplit('/',1)[-1] in ('three.module.js','GLTFLoader.js','OrbitControls.js','BufferGeometryUtils.js') and path.count('/')==3:
    return self.send(200,(WEB/'vendor/three'/path.rsplit('/',1)[-1]).read_bytes(),'text/javascript; charset=utf-8')
   return self.send(404,{'error':'Not found'})
  except (ValueError,KeyError,FileNotFoundError) as exc:return self.send(400,{'error':str(exc)})
  except Exception as exc:return self.send(500,{'error':str(exc)})
 def do_POST(self):
  if not self.host_ok():return self.send(403,{'error':'Localhost only'})
  if self.headers.get('Origin') not in (None,f'http://127.0.0.1:{self.server.server_port}',f'http://localhost:{self.server.server_port}'):return self.send(403,{'error':'Invalid origin'})
  if self.headers.get_content_type()!='application/json':return self.send(415,{'error':'JSON required'})
  try:
   size=int(self.headers.get('Content-Length','0'))
   if not 0<size<=(12_000_000 if self.path in ('/api/reference','/api/directions/manual') else 4_000_000):raise ValueError('Неверный размер запроса')
   data=json.loads(self.rfile.read(size))
   if not isinstance(data,dict):raise ValueError('Нужен JSON-объект')
   elif self.path=='/api/3d/create':result=self.server.reconstruction.start(data)
   elif self.path=='/api/3d/render':result=self.server.reconstruction.start(data,rerender=True)
   elif self.path=='/api/3d/apply':result=self.server.reconstruction.apply(data)
   elif self.path=='/api/3d/orientation':result=self.server.reconstruction.confirm_orientation(data)
   elif self.path=='/api/animations/crop-preview':result=animation_crops.preview(self.server.animations,data)
   elif self.path=='/api/animations/crop':result=animation_crops.commit(self.server.animations,data)
   elif self.path=='/api/animations/create':result=self.server.animations.create(data)
   elif self.path=='/api/animations/update':result=self.server.animations.update(data)
   elif self.path=='/api/animations/reference-frame':result=self.server.animations.reference_from_frame(data)
   elif self.path=='/api/animations/enqueue':result=self.server.animations.enqueue(data)
   elif self.path=='/api/animations/start':self.server.animations.start();result={'ok':True}
   elif self.path=='/api/animations/pause':self.server.animations.pause();result={'ok':True}
   elif self.path=='/api/animations/cancel':self.server.animations.cancel(data.get('id'));result={'ok':True}
   elif self.path=='/api/animations/recover':self.server.animations.recover(data.get('id'));result={'ok':True}
   elif self.path=='/api/animations/export':result=self.server.animations.export(data['project'])
   elif self.path=='/api/semantic/build':self.server.semantic.build();result={'ok':True}
   elif self.path=='/api/semantic/search':result=self.server.semantic.search(data.get('query'),data.get('mode','hybrid'),data.get('limit',12),data.get('category'))
   elif self.path=='/api/reference':result=self.app.upload_reference(data.get('data'))
   elif self.path=='/api/directions/manual':result=self.app.manual_direction(data)
   elif self.path=='/api/directions':result={'keys':self.app.direction_variants(data.get('key'),data.get('revision'),data.get('perspective'))}
   elif self.path=='/api/tiled/export':result=tiled_export.export(self.app)
   elif self.path=='/api/add':result={'keys':self.app.add(data.get('assets'))}
   elif self.path=='/api/trash/remove':result=trash.remove(self.app,data)
   elif self.path=='/api/trash/restore':result=trash.restore(self.app,data)
   elif self.path=='/api/asset':result=self.app.save_asset(data.get('key'),data.get('patch'),data.get('revision'))
   elif self.path=='/api/category':result={'category':self.app.create_category(data.get('name'))}
   elif self.path=='/api/enqueue':self.app.enqueue(data.get('keys'),data.get('kind'));result={'ok':True}
   elif self.path=='/api/start':self.app.start();result={'ok':True}
   elif self.path=='/api/pause':self.app.pause();result={'ok':True}
   elif self.path=='/api/cancel':self.app.cancel(data.get('id'));result={'ok':True}
   elif self.path=='/api/recover':result={'ok':True,'status':self.app.recover(data.get('id'))}
   elif self.path=='/api/import-settings':result={'imported':self.app.import_settings(data)}
   else:return self.send(404,{'error':'Not found'})
   return self.send(200,result)
  except Conflict as exc:return self.send(409,{'error':str(exc)})
  except (ValueError,KeyError,TypeError) as exc:return self.send(400,{'error':str(exc)})
  except Exception as exc:return self.send(500,{'error':str(exc)})

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--workspace',type=Path,default=WEB.parent/'workspace');p.add_argument('--port',type=int,default=8767);args=p.parse_args()
 args.workspace.mkdir(parents=True,exist_ok=True)
 with (args.workspace/'.app.lock').open('a') as lock:
  try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:raise SystemExit('Эта мастерская уже запущена')
  server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler);server.app=Workshop(args.workspace);server.semantic=SemanticIndex(server.app);server.animations=Animations(server.app)
  server.reconstruction=Reconstruction(server.app)
  print(f'Мастерская спрайтов: http://127.0.0.1:{args.port}/',flush=True)
  try:server.serve_forever()
  except KeyboardInterrupt:server.app.pause();server.server_close()
