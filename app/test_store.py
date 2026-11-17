import copy,json,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from store import Workshop,Conflict
from adapter import write,sha
class WorkshopTests(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup);self.root=Path(self.t.name);self.w=Workshop(self.root)
 def add(self,**kwargs):
  item=dict(id='cap',label='Крышечка',category='Находки',prompt='One red cap',width=32,height=24,scale=1,palette=16,seed=43,auto_process=False);item.update(kwargs)
  self.w.add([item]);return item['category']+'/'+item['id']
 def source(self,key,opaque=False):
  raw,_=self.w.paths(key);im=Image.new('RGBA',(100,100),(10,20,30,255) if opaque else (0,0,0,0));im.paste((220,40,30,255),(20,40,80,70));im.save(raw);return raw
 def wait(self):
  self.w.thread.join(5);self.assertFalse(self.w.thread.is_alive())
 def test_batch_is_queued_not_started(self):
  key=self.add();self.assertEqual(self.w.jobs[0]['status'],'queued');self.assertIsNone(self.w.thread);self.assertFalse(self.w.asset(key)['available'])
 def test_duplicate_batch_no_partial_writes(self):
  item=dict(id='same',category='A',prompt='cap')
  with self.assertRaises(ValueError):self.w.add([item,item])
  self.assertEqual(self.w.keys(),[]);self.assertEqual(self.w.jobs,[])
 def test_invalid_second_item_no_first_saved(self):
  with self.assertRaises(ValueError):self.w.add([dict(id='a',prompt='cap'),dict(id='../oops',prompt='bad')])
  self.assertEqual(self.w.keys(),[])
 def test_folder_categories_and_manual_image(self):
  self.w.create_category('Кухня');p=self.root/'raw/Кухня/mug.png';Image.new('RGBA',(16,16)).save(p)
  self.assertEqual(self.w.keys(),['Кухня/mug']);self.assertEqual(self.w.asset('Кухня/mug')['label'],'mug')
 def test_path_validation(self):
  for key in ('../foo','hello/../../etc','A/b.png','A/'):
   with self.assertRaises(ValueError):self.w.paths(key)
 def test_revision_conflict(self):
  key=self.add();a=self.w.asset(key);self.w.save_asset(key,{'scale':.5},a['revision'])
  with self.assertRaises(Conflict):self.w.save_asset(key,{'scale':2},a['revision'])
  self.assertEqual(self.w.metadata(key)['scale'],.5)
 def test_mode_change_invalidates_crop_cache(self):
  key=self.add(width=32,height=32);self.source(key);self.assertEqual(self.w.inspect(key)['crop_bbox'],[20,40,80,70]);self.w.save_asset(key,{'mode':'tile'},1)
  self.assertEqual(self.w.inspect(key)['crop_bbox'],[0,0,100,100])
 def test_processing_preserves_source_and_fit(self):
  key=self.add();raw=self.source(key);before=raw.read_bytes();self.w.jobs.clear();r=self.w.process(key)
  self.assertEqual(r['target_box_px'],[32,24]);self.assertEqual(r['content_size_px'],[32,16]);self.assertEqual(r['alpha_values'],[0,255]);self.assertEqual(before,raw.read_bytes())
  with Image.open(self.root/r['files']['sprite']) as im:
   self.assertEqual(im.size,(32,24));self.assertEqual(im.getchannel('A').getbbox(),(0,8,32,24))
  self.assertEqual(r,self.w.process(key));self.assertTrue(self.w.asset(key)['output_current'])
 def test_scale_new_version_preserves_old_output(self):
  key=self.add();self.source(key);r1=self.w.process(key);self.w.save_asset(key,{'scale':2},1);self.assertFalse(self.w.asset(key)['output_current']);r2=self.w.process(key)
  self.assertNotEqual(r1['files'],r2['files']);self.assertTrue((self.root/r1['files']['sprite']).exists());self.assertEqual(r2['target_box_px'],[64,48])
 def test_refuse_opaque_prop_without_color_removal(self):
  key=self.add();self.source(key,True)
  with self.assertRaisesRegex(ValueError,'Альфа'):self.w.process(key)
  self.assertFalse((self.root/'output/Находки/cap/result.json').exists())
 def test_tile_entire_canvas(self):
  key=self.add(mode='tile',width=32,height=32);self.source(key,True);r=self.w.process(key)
  self.assertEqual(r['crop_bbox'],[0,0,100,100]);self.assertEqual(r['alpha_values'],[255])
 def test_regeneration_preserves_scale_and_archives(self):
  key=self.add(scale=.75);raw=self.source(key);old=raw.read_bytes();source=self.root/'new.png';Image.new('RGBA',(16,16),(1,2,3,255)).save(source)
  self.w.install_raw(key,source,dict(job_id='new'))
  self.assertEqual(self.w.metadata(key)['scale'],.75);self.assertFalse(self.w.metadata(key)['reviewed']);history=self.w.history(key);self.assertEqual(len(history),1);self.assertEqual(self.w.history_file(key,history[0]['version']).read_bytes(),old)
 def test_unknown_backend_no_retry(self):
  key=self.add();job=self.w.jobs[0];response=self.root/'queue/reply.json';write(response,{'result':{'status':'unknown','cleanup_confirmed':False,'job_id':'abc'}})
  with self.assertRaises(ValueError):self.w.accept_response(job,response)
  self.assertEqual(job['status'],'unknown')
  with self.assertRaises(ValueError):self.w.start()
  with self.assertRaises(ValueError):self.w.enqueue([key],'generate')
 def test_failed_without_cleanup_remains_unknown(self):
  self.add();job=self.w.jobs[0];response=self.root/'queue/reply.json';write(response,{'result':{'status':'failed','cleanup_confirmed':False,'job_id':'abc'}})
  with self.assertRaises(ValueError):self.w.accept_response(job,response)
  self.assertEqual(job['status'],'unknown')
  with self.assertRaises(ValueError):self.w.start()
 def test_restart_marks_running_unknown(self):
  self.add();self.w.jobs[0]['status']='running';self.w.persist();w=Workshop(self.root);self.assertEqual(w.jobs[0]['status'],'unknown');self.assertIsNone(w.thread)
 def test_recover_result_after_worker_error_uses_matching_job(self):
  key=self.add();job=self.w.jobs[0];job['status']='unknown';runtime=self.root/'runtime';source=runtime/'generated.png';Image.new('RGBA',(8,8),(255,0,0,255)).save(source)
  write(runtime/'results/jobs/unrelated.json',{'workshop_job_id':'another','status':'success'})
  write(runtime/'results/jobs/backend.json',{'workshop_job_id':job['id'],'job_id':'backend','status':'success','cleanup_confirmed':True,'result':{'raw_path':'generated.png','raw_sha256':sha(source)}})
  write(self.root/'queue'/(job['id']+'.response.json'),{'error':'worker interrupted'})
  self.assertEqual(self.w.recover(job['id']),'complete');self.assertEqual(job['status'],'complete');self.assertEqual(sha(self.w.paths(key)[0]),sha(source))
 def test_recover_rejects_unmatched_or_ambiguous_job(self):
  self.add();job=self.w.jobs[0];job['status']='unknown';jobs=self.root/'runtime/results/jobs'
  write(jobs/'other.json',{'workshop_job_id':'another','status':'success','cleanup_confirmed':True})
  with self.assertRaisesRegex(ValueError,'однозначно'):self.w.recover(job['id'])
  for n in ('one','two'):write(jobs/(n+'.json'),{'workshop_job_id':job['id'],'status':'success','cleanup_confirmed':True})
  with self.assertRaisesRegex(ValueError,'однозначно'):self.w.recover(job['id'])
  self.assertEqual(job['status'],'unknown')
 def test_recover_failure_is_reported_without_retry(self):
  self.add();job=self.w.jobs[0];job['status']='unknown'
  write(self.root/'runtime/results/jobs/backend.json',{'workshop_job_id':job['id'],'job_id':'backend','status':'failed','cleanup_confirmed':True})
  self.assertEqual(self.w.recover(job['id']),'failed');self.assertEqual(job['status'],'failed')
 def test_accept_same_result_twice_does_not_archive_itself(self):
  key=self.add();source=self.root/'runtime/generated.png';Image.new('RGBA',(8,8),(255,0,0,255)).save(source)
  response=self.root/'queue/reply.json';write(response,{'result':dict(status='success',cleanup_confirmed=True,job_id='backend',raw_path='generated.png',raw_sha256=sha(source))})
  self.w.accept_response(self.w.jobs[0],response);revision=self.w.metadata(key)['revision'];self.w.accept_response(self.w.jobs[0],response)
  self.assertEqual(self.w.metadata(key)['revision'],revision);self.assertEqual(self.w.history(key),[])
 def test_missing_legacy_module_recovery_marks_unsubmitted_job_failed(self):
  self.add();job=self.w.jobs[0];job['status']='unknown';job_id=job['id']
  write(self.root/'queue'/(job_id+'.response.json'),{'error':"No module named 'pavlusha_agent.functions'"})
  log=self.root/'queue'/(job_id+'.log');log.write_text("registry=make_registry(\nModuleNotFoundError: No module named 'pavlusha_agent.functions'\n")
  self.w.recover(job_id);self.assertEqual(job['status'],'failed')
  self.assertIn('не была отправлена',job['error'])
 def test_pause_after_current_does_not_start_next(self):
  self.add();self.add(id='second')
  def fake_generate(job):self.w.pause()
  with patch.object(self.w,'generate',fake_generate):self.w.start();self.wait()
  self.assertEqual([j['status'] for j in self.w.jobs],['complete','queued'])
 def test_queue_sequential_completion(self):
  self.add();self.add(id='second');seen=[]
  with patch.object(self.w,'generate',lambda j:seen.append(j['key'])):self.w.start();self.wait()
  self.assertEqual(seen,['Находки/cap','Находки/second']);self.assertTrue(all(j['status']=='complete' for j in self.w.jobs))
 def test_failure_pauses_next(self):
  self.add();self.add(id='second')
  def fail(j):raise RuntimeError('GPU busy')
  with patch.object(self.w,'generate',fail):self.w.start();self.wait()
  self.assertEqual([j['status'] for j in self.w.jobs],['failed','queued']);self.assertTrue(self.w.paused)
 def test_cancel_does_not_delete_asset(self):
  key=self.add();self.w.cancel(self.w.jobs[0]['id']);self.assertIn(key,self.w.keys());self.assertEqual(self.w.jobs[0]['status'],'cancelled')
 def test_settings_roundtrip_and_source_validation(self):
  key=self.add();raw=self.source(key);d=self.w.metadata(key);d['raw_sha256']=sha(raw);write(self.w.paths(key)[1],d);export=self.w.export_settings();export['assets'][0]['scale']=1.4;self.w.import_settings(export);self.assertEqual(self.w.metadata(key)['scale'],1.4)
  raw.write_bytes(b'changed')
  with self.assertRaises(ValueError):self.w.import_settings(export)
 def test_bulk_enqueue_rolls_back_duplicates(self):
  key=self.add();self.source(key);self.w.cancel(self.w.jobs[0]['id'])
  with self.assertRaises(ValueError):self.w.enqueue([key,key],'process')
  self.assertEqual(len(self.w.jobs),1)
 def test_success_response_installs_and_auto_processes(self):
  key=self.add(auto_process=True);runtime=self.root/'runtime';source=runtime/'generated.png';im=Image.new('RGBA',(32,32));im.paste((255,0,0,255),(8,8,24,24));im.save(source)
  response=self.root/'queue/reply.json';write(response,{'result':dict(status='success',cleanup_confirmed=True,job_id='backend',raw_path='generated.png',raw_sha256=sha(source))})
  self.w.accept_response(self.w.jobs[0],response);self.assertTrue(self.w.asset(key)['output_current']);self.assertTrue(self.w.jobs[0]['alpha_ok'])
 def test_idle_comfy_cache_released_before_gpu_submission(self):
  import io
  calls=[]
  def request(url,**kw):
   calls.append(url)
   return io.BytesIO(b'{}' if not isinstance(url,str) else b'{"queue_running":[],"queue_pending":[]}')
  with patch('store.urllib.request.urlopen',side_effect=request),patch('store.gpu_idle',side_effect=[RuntimeError('cache'),None]):self.w.prepare_generation_gpu()
  self.assertEqual(len(calls),3);self.assertEqual(calls[2].full_url,'http://127.0.0.1:8188/free');self.assertEqual(json.loads(calls[2].data),{'unload_models':True,'free_memory':True})
 def test_busy_comfy_never_unloaded(self):
  import io
  with patch('store.urllib.request.urlopen',return_value=io.BytesIO(b'{"queue_running":[1],"queue_pending":[]}')) as request,patch('store.gpu_idle') as gpu:
   with self.assertRaisesRegex(ValueError,'ComfyUI'):self.w.prepare_generation_gpu()
   self.assertEqual(request.call_count,1);gpu.assert_not_called()
if __name__=='__main__':unittest.main()
