import tempfile,unittest
from pathlib import Path
from store import Workshop,STYLE,ALPHA
class ViewpointTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.w=Workshop(Path(self.tmp.name))
 def test_legacy_request_unchanged(self):
  d=self.w.validate(dict(id='sofa',prompt='Brown sofa.'))
  _,a=self.w.generation_request(d,self.w.root/'runtime');self.assertEqual(a['prompt'],STYLE.strip()+' Brown sofa.'+ALPHA)
 def test_saved_orientation_used_in_actual_request_and_export(self):
  key=self.w.add([dict(id='sofa',prompt='Brown fabric sofa.',perspective='rpg',direction='back')])[0]
  d=self.w.metadata(key);_,args=self.w.generation_request(d,self.w.root/'runtime')
  self.assertIn('REAR view',args['prompt']);self.assertNotIn('Orthographic three-quarter',args['prompt']);self.assertIn('Brown fabric sofa.',args['prompt'])
  exported=self.w.export_settings();self.assertEqual(exported['assets'][0]['direction'],'back');self.w.import_settings(exported);self.assertEqual(self.w.metadata(key)['perspective'],'rpg')
 def test_invalid_direction_rejected_before_enqueue(self):
  with self.assertRaises(ValueError):self.w.add([dict(id='bad',prompt='sofa',direction='sideways')])
  self.assertEqual(self.w.jobs,[])
 def test_three_views_share_reference_and_preserve_original(self):
  from PIL import Image
  key=self.w.add([dict(id='sofa',category='A',prompt='Brown sofa.',perspective='rpg',direction='front')])[0]
  self.w.jobs=[];raw,_=self.w.paths(key);Image.new('RGBA',(32,24),(100,70,40,255)).save(raw);original=raw.read_bytes()
  keys=self.w.direction_variants(key,1,'rpg');self.assertEqual(len(keys),3)
  rows=[self.w.metadata(k) for k in keys];self.assertEqual({d['direction'] for d in rows},{'back','left','right'});self.assertEqual(len({d['reference'] for d in rows}),1);self.assertTrue(all(d['parent_key']==key for d in rows));self.assertEqual(raw.read_bytes(),original)
  with self.assertRaises(ValueError):self.w.direction_variants(key,1,'rpg')
  self.assertEqual(len(self.w.jobs),3)

 def test_rpg_camera_never_demands_front_when_side_selected(self):
  for direction in ['back','left','right']:
   d=self.w.validate(dict(id='bin',prompt='Blue steel dumpster.',perspective='rpg',direction=direction))
   _,args=self.w.generation_request(d,self.w.root/'runtime')
   self.assertNotIn('front-facing vertical surface',args['prompt'])
   self.assertIn('surface selected by the object direction',args['prompt'])
   if direction in ['left','right']:self.assertIn('SIDE PROFILE',args['prompt'])
