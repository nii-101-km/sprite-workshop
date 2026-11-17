import base64,io,tempfile,unittest
from pathlib import Path
from PIL import Image,ImageOps
from store import Workshop,Conflict
class ManualDirections(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.w=Workshop(Path(self.tmp.name));self.key=self.w.add([dict(id='sofa',category='A',prompt='Brown sofa.',direction='front',width=16,height=16)])[0];self.w.jobs=[]
 def image(self,opaque=False):
  im=Image.new('RGBA',(20,20),(0,0,0,255) if opaque else (0,0,0,0));im.paste((100,60,20,255),(3,5,9,16));im.paste((20,40,200,255),(9,8,15,16));out=io.BytesIO();im.save(out,format='PNG');return base64.b64encode(out.getvalue()).decode()
 def test_import_pixelize_mirror_and_archive(self):
  result=self.w.manual_direction(dict(key=self.key,revision=1,direction='left',data=self.image()));a=result['asset'];self.assertIsNone(result['warning']);self.assertTrue(a['output_current']);self.assertEqual(a['parent_key'],self.key);self.assertEqual(self.w.jobs,[])
  raw,_=self.w.paths(a['key']);before=Image.open(raw).copy()
  r=self.w.manual_direction(dict(key=self.key,revision=1,direction='right',mirror_from=a['key'],source_revision=a['revision']));right=r['asset'];self.assertTrue(right['output_current']);rr,_=self.w.paths(right['key']);self.assertEqual(Image.open(rr).tobytes(),ImageOps.mirror(before).tobytes());self.assertEqual(Image.open(raw).tobytes(),before.tobytes())
  self.w.manual_direction(dict(key=self.key,revision=1,direction='left',target_revision=a['revision'],data=self.image()));self.assertEqual(self.w.asset(a['key'])['history_count'],1)
 def test_stale_target_and_busy_do_not_replace_raw(self):
  a=self.w.manual_direction(dict(key=self.key,revision=1,direction='left',data=self.image()))['asset'];raw,_=self.w.paths(a['key']);before=raw.read_bytes()
  with self.assertRaises(Conflict):self.w.manual_direction(dict(key=self.key,revision=1,direction='left',target_revision=0,data=self.image()))
  self.w.enqueue([a['key']],'generate')
  with self.assertRaises(ValueError):self.w.manual_direction(dict(key=self.key,revision=1,direction='left',target_revision=a['revision'],data=self.image()))
  self.assertEqual(raw.read_bytes(),before)
 def test_opaque_upload_kept_with_clear_warning(self):
  r=self.w.manual_direction(dict(key=self.key,revision=1,direction='left',data=self.image(True)));self.assertTrue(r['asset']['available']);self.assertFalse(r['asset']['output_current']);self.assertIn('Альфа',r['warning'])
