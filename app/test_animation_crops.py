import base64,io,json,tempfile,unittest
from pathlib import Path
from PIL import Image
from store import Workshop,Conflict
from animations import Animations
from adapter import sha
import animation_crops
class CropTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.app=Workshop(Path(self.tmp.name));self.a=Animations(self.app)
  im=Image.new('RGBA',(240,100))
  for i,color in enumerate([(230,70,50,255),(50,180,80,255),(70,90,220,255)]):im.paste(color,(i*80+20,15,i*80+60,95))
  out=io.BytesIO();im.save(out,'PNG');self.reference=self.app.upload_reference(base64.b64encode(out.getvalue()).decode())['reference'];self.p=self.a.create(dict(id='hero',label='Hero',prompt='Hero',reference=self.reference))
 def data(self,**kw):
  d=dict(project='hero',revision=self.p['revision'],track='walk_down',source={'reference':self.reference},rectangles=[[0,0,80,100],[80,0,80,100],[160,0,80,100]],start=0);d.update(kw);return d
 def test_preview_and_commit_preserve_order_and_source(self):
  source=self.app.reference_file(self.reference).read_bytes();data=self.data();preview=animation_crops.preview(self.a,data);self.assertEqual(len(preview['images']),3);self.assertEqual(self.a.load('hero')['revision'],self.p['revision'])
  result=animation_crops.commit(self.a,data|{'source_sha256':preview['source_sha256']});self.p=result['project'];t=self.a.track(self.p,'walk_down');self.assertEqual(len(t['frames']),4);self.assertFalse(t['frames'][3]['version']);self.assertEqual(self.app.reference_file(self.reference).read_bytes(),source)
  for f,bytes64 in zip(t['frames'],preview['images']):
   v=self.a.version(f);sprite=self.a.local(self.p,v['sprite']).read_bytes();self.assertEqual(sprite,base64.b64decode(bytes64));self.assertFalse(f['accepted'])
  meta=json.loads((self.a.folder('hero')/'sheets'/result['sheet']/'slicing.json').read_text());self.assertEqual(meta['frames'][1]['rectangle'],[80,0,80,100]);self.assertEqual(meta['source_sha256'],preview['source_sha256'])
 def test_histories_are_preserved_on_second_import(self):
  self.p=animation_crops.commit(self.a,self.data())['project'];old=self.a.track(self.p,'walk_down')['frames'][0]['version'];self.p=animation_crops.commit(self.a,self.data(rectangles=[[160,0,80,100]]))['project'];f=self.a.track(self.p,'walk_down')['frames'][0];self.assertEqual(len(f['versions']),2);self.assertNotEqual(f['version'],old);self.assertTrue(self.a.local(self.p,f['versions'][0]['raw']).exists())
 def test_accepted_target_and_stale_revision_rejected_without_writes(self):
  self.p=animation_crops.commit(self.a,self.data())['project'];t=self.a.track(self.p,'walk_down');t['frames'][0]['accepted']=True;self.a.save(self.p);before=json.dumps(self.a.load('hero'),sort_keys=True)
  with self.assertRaises(ValueError):animation_crops.commit(self.a,self.data())
  self.assertEqual(json.dumps(self.a.load('hero'),sort_keys=True),before)
  with self.assertRaises(Conflict):animation_crops.commit(self.a,self.data(revision=0))
 def test_bounds_empty_opaque_and_large_counts_rejected(self):
  bad=[[[239,0,80,100]],[[-1,0,80,100]],[[0,0,0,100]],[[0,0,15,15]],[[20,15,40,80]],[[0,0,80,100]]*13]
  before=self.a.load('hero')
  for boxes in bad:
   with self.assertRaises(ValueError):animation_crops.commit(self.a,self.data(rectangles=boxes))
  self.assertEqual(self.a.load('hero'),before);self.assertFalse((self.a.folder('hero')/'sheets').exists())
 def test_sheet_source_can_be_a_saved_frame_version(self):
  self.p=animation_crops.commit(self.a,self.data(rectangles=[[0,0,80,100]]))['project'];f=self.a.track(self.p,'walk_down')['frames'][0];source={'frame':f['id'],'version':f['version']}
  self.p=animation_crops.commit(self.a,self.data(source=source,track='walk_left',rectangles=[[0,0,80,100]]))['project'];self.assertTrue(self.a.track(self.p,'walk_left')['frames'][0]['version'])
 def test_can_extend_to_12_frames_without_losing_existing_history(self):
  result=animation_crops.commit(self.a,self.data(rectangles=[[0,0,80,100]]*12));self.assertEqual(len(self.a.track(result['project'],'walk_down')['frames']),12)
  with self.assertRaises(ValueError):animation_crops.commit(self.a,self.data(start=11))
 def test_busy_target_and_changed_source_rejected(self):
  self.a.jobs.append(dict(id='pending',project='hero',track='walk_down',status='queued'))
  with self.assertRaises(ValueError):animation_crops.commit(self.a,self.data())
  self.a.jobs=[]
  with self.assertRaises(ValueError):animation_crops.commit(self.a,self.data(source_sha256='bad'))
  self.assertFalse((self.a.folder('hero')/'sheets').exists())
 def test_common_scale_keeps_shorter_pose_shorter(self):
  im=Image.new('RGBA',(160,100));im.paste((100,80,60,255),(20,10,60,90));im.paste((100,80,60,255),(100,50,140,90));out=io.BytesIO();im.save(out,'PNG');ref=self.app.upload_reference(base64.b64encode(out.getvalue()).decode())['reference'];result=animation_crops.preview(self.a,self.data(source={'reference':ref},rectangles=[[0,0,80,100],[80,0,80,100]]));sizes=[]
  for blob in result['images']:
   im=Image.open(io.BytesIO(base64.b64decode(blob)));box=im.getchannel('A').getbbox();sizes.append(box[3]-box[1])
  self.assertAlmostEqual(sizes[0]/sizes[1],2,delta=.1)
