import tempfile,threading,json,unittest
from pathlib import Path
from PIL import Image
from tiled_export import export
class App:
 def __init__(self,root):self.root=root;self.lock=threading.RLock();self.assets={}
 def keys(self):return list(self.assets)
 def asset(self,key):return self.assets[key]
 def add(self,key,parent=None,direction='front',size=(16,32)):
  category,id=key.split('/');p=self.root/(id+'.png');Image.new('RGBA',size,'red').save(p)
  self.assets[key]=dict(category=category,id=id,label=id,parent_key=parent,direction=direction,output_current=True,output={'files':{'sprite':p.name}},revision=1)
class Export(unittest.TestCase):
 def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.app=App(Path(self.tmp.name))
 def manifest(self,r):return json.loads((Path(r['root'])/'manifest.json').read_text())
 def test_variants_share_object_folder_and_preserve_dimensions(self):
  self.app.add('Room/chair');self.app.add('Room/view_left','Room/chair','left',(8,32))
  r=export(self.app);c=self.manifest(r)['categories']['Room'];a,b=c['entries'].values()
  self.assertEqual(Path(a['image']).parent,Path(b['image']).parent);self.assertEqual(b['width'],8)
  ts=json.loads(Path(r['tilesets'][0]).read_text());self.assertEqual(ts['objectalignment'],'bottom')
 def test_ids_never_reassigned_and_deleted_images_remain(self):
  self.app.add('Room/z');r=export(self.app);first=self.manifest(r)['categories']['Room']['entries']['Room/z']
  self.app.add('Room/a');self.app.assets.pop('Room/z');r=export(self.app);c=self.manifest(r)['categories']['Room']
  self.assertEqual(c['entries']['Room/z']['id'],first['id']);self.assertNotEqual(c['entries']['Room/a']['id'],first['id'])
  self.assertTrue((Path(r['tilesets'][0]).parent/first['image']).is_file());self.assertFalse(c['entries']['Room/z']['active'])
 def test_stale_build_does_not_overwrite_export(self):
  self.app.add('Room/a');r=export(self.app);e=self.manifest(r)['categories']['Room']['entries']['Room/a'];p=Path(r['tilesets'][0]).parent/e['image'];before=p.read_bytes()
  self.app.assets['Room/a']['output_current']=False;Image.new('RGBA',(8,8),'blue').save(self.app.root/'a.png');r=export(self.app)
  self.assertEqual(p.read_bytes(),before);self.assertEqual(len(r['skipped']),1)
 def test_repeat_update_keeps_paths_and_ids(self):
  self.app.add('Room/a');r=export(self.app);before=self.manifest(r);r=export(self.app);self.assertEqual(self.manifest(r),before)
