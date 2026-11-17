import tempfile,unittest
from pathlib import Path
from PIL import Image
from store import Workshop
from semantic import SemanticIndex,unit,rank

def vector(n):return [1. if i==n else 0. for i in range(768)]
class FakeWorker:
 def __init__(self):self.calls=[];self.hook=None
 def request(self,p):
  self.calls.append(p)
  if self.hook:self.hook()
  if p['op']=='query':return [vector(0)]
  return [vector(0 if 'cap' in p['text'] else 1),vector(0 if 'cap' in p['text'] else 1)]
class Tests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.app=Workshop(self.root);self.worker=FakeWorker();self.index=SemanticIndex(self.app,self.worker)
 def add(self,ident='cap',category='A'):
  key=self.app.add([dict(id=ident,label=ident,category=category,prompt=ident,width=32,height=32)])[0];self.app.cancel(self.app.jobs[-1]['id']);raw,_=self.app.paths(key);im=Image.new('RGBA',(20,20));im.paste((255,0,0,255),(5,5,15,15));im.save(raw);return key
 def build(self):
  self.index.build();self.index.thread.join(5);self.assertFalse(self.index.thread.is_alive());self.assertEqual(self.index.progress['phase'],'ready',self.index.progress)
 def test_direction_children_never_enter_index_or_search(self):
  parent=self.add('sofa');child=self.add('sofa_back');self.build()
  self.app.save_asset(child,{'parent_key':parent},1)
  self.assertNotIn(child,self.index.documents());self.assertEqual(self.index.status()['total'],1)
  self.assertNotIn(child,[r['key'] for r in self.index.search('sofa')['matches']])
  self.worker.calls.clear();self.build();self.assertNotIn(child,self.index.index['entries']);self.assertEqual(len(self.worker.calls),0)
 def test_normalization_and_nan(self):
  self.assertEqual(unit([3,4]),[.6,.8])
  for v in ([0,0],[float('nan'),1],[float('inf')],[]):
   with self.assertRaises(ValueError):unit(v)
 def test_incremental_rebuild_avoids_model_calls(self):
  self.add();self.build();self.build();self.assertEqual(len(self.worker.calls),1);self.assertEqual(self.index.status()['ready'],1)
 def test_only_changed_source_reindexed(self):
  a=self.add();self.add('mug');self.build();raw,_=self.app.paths(a);Image.new('RGBA',(21,21),(0,255,0,255)).save(raw);self.assertEqual(self.index.status()['stale'],1);self.build();self.assertEqual(len(self.worker.calls),3)
 def test_stale_source_not_returned(self):
  key=self.add();self.add('mug');self.build();self.app.save_asset(key,{'prompt':'new description'},1);result=self.index.search('cap');self.assertEqual(result['stale'],1);self.assertNotIn(key,[m['key'] for m in result['matches']])
 def test_query_cached_and_category_filter(self):
  self.add();self.add('mug',category='B');self.build();first=self.index.search('крышечка');self.assertEqual(first['matches'][0]['key'],'A/cap');self.index.search('крышечка');self.assertEqual(sum(c['op']=='query' for c in self.worker.calls),1);self.assertEqual(self.index.search('крышечка',category='B')['searched'],1)
 def test_index_survives_restart_without_loading_model(self):
  self.add();self.build();new=SemanticIndex(self.app,self.worker);self.assertEqual(new.status()['ready'],1);self.assertEqual(len(self.worker.calls),1)
 def test_processing_switches_to_actual_sprite(self):
  key=self.add();self.build();self.assertEqual(self.index.documents()[key]['rendition'],'raw');self.app.process(key);self.assertEqual(self.index.documents()[key]['rendition'],'sprite');self.assertEqual(self.index.status()['stale'],1)
 def test_prepare_crop_composite_and_original_untouched(self):
  key=self.add();raw,_=self.app.paths(key);before=raw.read_bytes();d=self.index.documents()[key];p=self.index.prepare(d)
  with Image.open(p) as image:self.assertEqual(image.mode,'RGB');self.assertEqual(image.size,(512,512));self.assertEqual(image.getpixel((0,0)),(232,229,219))
  self.assertEqual(raw.read_bytes(),before)
 def test_midflight_change_not_committed(self):
  key=self.add()
  def modify():self.app.save_asset(key,{'prompt':'changed'},self.app.metadata(key)['revision'])
  self.worker.hook=modify;self.build();self.assertNotIn(key,self.index.index['entries']);self.assertEqual(self.index.status()['stale'],1)
 def test_model_failure_preserves_partial_progress(self):
  self.add();self.add('mug')
  def hook():
   if len(self.worker.calls)==2:raise RuntimeError('model failure')
  self.worker.hook=hook;self.index.build();self.index.thread.join(5);self.assertEqual(self.index.progress['phase'],'error');self.assertEqual(len(self.index.index['entries']),1);self.assertTrue(self.index.path.exists())
 def test_rank_modes_and_bad_dimension(self):
  entries={'visual':dict(image_vector=vector(0),text_vector=vector(1)),'text':dict(image_vector=vector(1),text_vector=vector(0))};self.assertEqual(rank(vector(0),entries,'image')[0]['key'],'visual');self.assertEqual(rank(vector(0),entries,'hybrid')[0]['key'],'visual')
  with self.assertRaises(ValueError):rank([1,0],entries)
 def test_missing_and_invalid_index_do_not_fake_results(self):
  self.add()
  with self.assertRaisesRegex(ValueError,'Нет актуального индекса'):self.index.search('cap')
  for q in ('',' '*4,'a'*1001):
   with self.assertRaises(ValueError):self.index.search(q)
if __name__=='__main__':unittest.main()
