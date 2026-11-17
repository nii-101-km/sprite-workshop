import base64,io,tempfile,unittest
from pathlib import Path
from PIL import Image
from store import Workshop

class ReferenceTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.w=Workshop(Path(self.temp.name))
 def upload(self):
  out=io.BytesIO();Image.new('RGBA',(24,32),(120,20,40,128)).save(out,'PNG')
  return self.w.upload_reference(base64.b64encode(out.getvalue()).decode())['reference']
 def test_roundtrip_persist_and_route(self):
  ref=self.upload();key=self.w.add([dict(id='cap',category='A',prompt='cap',reference=ref)])[0]
  d=self.w.metadata(key);self.assertEqual(d['reference'],ref)
  runtime=self.w.root/'runtime';function,args=self.w.generation_request(d,runtime)
  self.assertEqual(function,'sprite_edit');self.assertEqual((runtime/args['reference_path']).read_bytes(),self.w.reference_file(ref).read_bytes())
  self.assertFalse(args['postprocess']);self.assertEqual(args['model'],'qwen21_turbo')
  d=self.w.save_asset(key,{'reference':None},d['revision']);self.assertIsNone(d['reference'])
  function,args=self.w.generation_request(d,runtime);self.assertEqual(function,'sprite_generate');self.assertNotIn('reference_path',args)
  self.assertTrue(self.w.reference_file(ref).exists())
 def test_bad_data_and_foreign_paths_rejected(self):
  for data in ('garbage','',base64.b64encode(b'not an image').decode()):
   with self.assertRaises(ValueError):self.w.upload_reference(data)
  for ref in ('../../etc/passwd','f'*64,'/tmp/test.png'):
   with self.assertRaises(ValueError):self.w.validate(dict(id='a',reference=ref))
 def test_dedup_and_integrity(self):
  ref=self.upload();self.assertEqual(ref,self.upload());self.assertEqual(len(list((self.w.root/'references').glob('*.png'))),1)
  self.w.reference_file(ref).write_bytes(b'changed')
  with self.assertRaises(ValueError):self.w.reference_file(ref)
