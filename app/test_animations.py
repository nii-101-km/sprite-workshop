import base64,io,json,tempfile,threading,unittest,zipfile
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from store import Workshop,Conflict
from animations import Animations,fit
from adapter import write,sha
class AnimationTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);self.app=Workshop(self.root);self.a=Animations(self.app)
  buf=io.BytesIO();im=Image.new('RGBA',(80,100));im.paste((150,70,90,255),(20,10,60,100));im.save(buf,'PNG');self.raw=buf.getvalue();self.reference=self.app.upload_reference(base64.b64encode(self.raw).decode())['reference']
  self.p=self.a.create(dict(id='hero',label='Герой',prompt='One hero',reference=self.reference))
 def reload(self):self.p=self.a.load('hero');return self.p
 def update(self,operation,**kwargs):self.p=self.a.update(dict(project='hero',revision=self.p['revision'],operation=operation,**kwargs));return self.p
 def install(self,t=None,index=0):
  t=t or self.p['tracks'][0];f=t['frames'][index];version='test'+str(index)+t['id'];folder=self.a.folder('hero')/'versions'/version;folder.mkdir(parents=True,exist_ok=True);(folder/'raw.png').write_bytes(self.raw);fit(Image.open(io.BytesIO(self.raw)),self.p['size']).save(folder/'sprite.png');f.update(version=version,versions=[dict(id=version,raw=str((folder/'raw.png').relative_to(self.a.folder('hero'))),sprite=str((folder/'sprite.png').relative_to(self.a.folder('hero'))))]);self.a.save(self.p);return f
 def enqueue(self,t=None,f=None):
  t=t or self.p['tracks'][0];return self.a.enqueue(dict(project='hero',revision=self.p['revision'],track=t['id'],**({'frame':f['id']} if f else {})))
 def test_create_is_cpu_only_and_provides_20_slots(self):
  self.assertEqual(sum(len(t['frames']) for t in self.p['tracks']),20);self.assertEqual(len(self.p['tracks']),8);self.assertFalse(self.a.jobs);self.assertFalse(self.a.snapshot()['running'])
 def test_revision_and_path_validation(self):
  with self.assertRaises(Conflict):self.a.update(dict(project='hero',revision=0,operation='project',prompt='other'))
  for key in ('../bad','/tmp','a/b'):
   with self.assertRaises(ValueError):self.a.folder(key)
  with self.assertRaises(ValueError):self.a.local(self.p,'../../jobs.json')
 def test_accepted_frames_protected_and_offsets_reset_approval(self):
  f=self.install();self.update('frame',frame=f['id'],accepted=True)
  with self.assertRaises(ValueError):self.enqueue()
  self.update('frame',frame=f['id'],x=2);self.assertFalse(self.p['tracks'][0]['frames'][0]['accepted']);self.enqueue();self.assertEqual(self.a.jobs[0]['status'],'queued')
  with self.assertRaises(ValueError):self.update('frame',frame=f['id'],accepted=True)
 def test_rear_prompt_does_not_require_preserving_visible_face(self):
  for action in ('idle','walk'):
   rear=self.a.make_prompt(self.p,self.a.track(self.p,action+'_up'),0)
   self.assertNotIn('Preserve EXACT reference identity, face, hair',rear)
   self.assertIn('Eyes, mouth, chest lettering and front pockets are hidden',rear)
   front=self.a.make_prompt(self.p,self.a.track(self.p,action+'_down'),0)
   self.assertIn('Preserve EXACT reference identity, face, hair',front)
 def test_square_reference_and_prompts_pinned(self):
  self.enqueue();j=self.a.jobs[0];im=Image.open(self.app.reference_file(j['reference']));self.assertEqual(im.size,(1024,1024));im.close();self.assertIn('ONE complete',j['prompt']);self.assertEqual(j['status'],'queued');self.update('project',prompt='changed');self.assertNotIn('changed',j['prompt'])
  with self.assertRaises(ValueError):self.enqueue()
 def test_single_frame_only_queue_and_cancel(self):
  t=self.p['tracks'][4];f=t['frames'][2];self.enqueue(t,f);self.assertEqual(len(self.a.jobs),1);self.assertEqual(self.a.jobs[0]['frame'],f['id']);self.a.cancel(self.a.jobs[0]['id']);self.assertEqual(self.a.jobs[0]['status'],'cancelled')
 def test_export_complete_tracks_and_positions(self):
  f=self.install();self.update('frame',frame=f['id'],accepted=True);before=self.a.render(self.p,self.p['tracks'][0]['frames'][0]);result=self.a.export('hero');self.reload();path=self.a.export_file('hero',result['id'],'animation-pack.zip')
  with zipfile.ZipFile(path) as z:
   self.assertIsNone(z.testzip());m=json.loads(z.read('animations.json'));self.assertEqual(len(m['animations']),1);self.assertEqual(m['anchor'],[16,64]);self.assertEqual(len(m['missing_tracks']),7);self.assertTrue(m['animations']['idle_down']['accepted']);im=Image.open(io.BytesIO(z.read('frames/idle_down-00.png')));self.assertEqual(im.tobytes(),before.tobytes())
 def test_version_selection_and_reference_from_frame(self):
  f=self.install();old=f['version'];f['versions'].append(dict(f['versions'][0],id='v2'));f['version']='v2';f['accepted']=True;self.a.save(self.p);self.update('frame',frame=f['id'],version=old);self.assertFalse(self.p['tracks'][0]['frames'][0]['accepted']);self.p=self.a.reference_from_frame(dict(project='hero',revision=self.p['revision'],track=self.p['tracks'][0]['id'],frame=f['id']));self.assertTrue(self.p['tracks'][0]['reference'])
 def test_accept_result_preserves_history_and_checks_sha(self):
  f=self.install();old=f['version'];self.enqueue();j=self.a.jobs[0];runtime=self.app.root/'runtime';runtime.mkdir(exist_ok=True);(runtime/'raw.png').write_bytes(self.raw);response=self.a.root/'jobs/result.json';write(response,{'result':{'status':'success','cleanup_confirmed':True,'raw_path':'raw.png','raw_sha256':sha(runtime/'raw.png'),'job_id':'backend'}});self.a.accept_result(j,response);self.reload();versions=self.p['tracks'][0]['frames'][0]['versions'];self.assertEqual(len(versions),2);self.assertEqual(versions[0]['id'],old);self.assertEqual(j['status'],'complete');self.a.accept_result(j,response);self.reload();self.assertEqual(len(self.p['tracks'][0]['frames'][0]['versions']),2)
 def test_opaque_failure_retains_raw_and_old_version(self):
  f=self.install();old=f['version'];self.enqueue();j=self.a.jobs[0];runtime=self.app.root/'runtime';runtime.mkdir(exist_ok=True);Image.new('RGBA',(50,100),(12,34,56,255)).save(runtime/'raw.png');response=self.a.root/'jobs/result.json';write(response,{'result':{'status':'success','cleanup_confirmed':True,'raw_path':'raw.png','raw_sha256':sha(runtime/'raw.png'),'job_id':'backend'}})
  with self.assertRaises(ValueError):self.a.accept_result(j,response)
  self.assertTrue((self.a.folder('hero')/'versions'/j['id']/'raw.png').exists());self.reload();self.assertEqual(self.p['tracks'][0]['frames'][0]['version'],old)
 def test_restart_unknown_no_repeat_and_shared_queue_gate(self):
  self.enqueue();self.a.jobs[0]['status']='running';self.a.persist();other=Animations(self.app);self.assertEqual(other.jobs[0]['status'],'unknown')
  with self.assertRaises(ValueError):self.app.start()
  with self.assertRaises(ValueError):other.start()
 def test_queue_worker_install_and_release_gate(self):
  self.enqueue()
  def fake(j):j['status']='complete';self.a.persist()
  with patch.object(self.a,'generate',side_effect=fake):self.a.start();self.a.thread.join(3)
  self.assertFalse(self.app.animation_busy);self.assertEqual(self.a.jobs[0]['status'],'complete')
 def test_collection_and_animation_cannot_start_concurrently(self):
  blocker=threading.Event();self.app.thread=threading.Thread(target=blocker.wait);self.app.thread.start()
  try:
   with self.assertRaises(ValueError):self.a.start()
  finally:blocker.set();self.app.thread.join()
 def test_track_validation_and_custom_action(self):
  self.update('add-track',action='run',direction='left',count=6);self.assertEqual(len(self.p['tracks'][-1]['frames']),6)
  with self.assertRaises(ValueError):self.update('add-track',action='run',direction='left',count=6)
  with self.assertRaises(ValueError):self.update('track',track=self.p['tracks'][0]['id'],fps=100)

 def test_recovery_backend_failed_releases_busy_without_repeat(self):
  self.enqueue();j=self.a.jobs[0];j['status']='unknown';self.app.animation_busy=True
  folder=self.a.root/'jobs'/j['id'];folder.mkdir();write(folder/'response.json',{'result':{'status':'failed','cleanup_confirmed':True}})
  with self.assertRaises(ValueError):self.a.recover(j['id'])
  self.assertEqual(j['status'],'failed');self.assertFalse(self.app.animation_busy);self.assertEqual(len(self.a.jobs),1)

 def test_recovery_matches_job_after_worker_error(self):
  self.enqueue();j=self.a.jobs[0];j['status']='unknown';self.app.animation_busy=True
  runtime=self.root/'runtime';source=runtime/'raw.png';source.write_bytes(self.raw);folder=self.a.root/'jobs'/j['id'];folder.mkdir()
  write(folder/'response.json',{'error':'worker interrupted'})
  write(runtime/'results/jobs/unrelated.json',{'workshop_job_id':'other','status':'success'})
  write(runtime/'results/jobs/backend.json',{'workshop_job_id':j['id'],'job_id':'backend','status':'success','cleanup_confirmed':True,'result':{'raw_path':'raw.png','raw_sha256':sha(source)}})
  self.a.recover(j['id']);self.assertEqual(j['status'],'complete');self.assertFalse(self.app.animation_busy)
  self.reload();self.assertEqual(self.p['tracks'][0]['frames'][0]['version'],j['id'])

 def test_recovery_rejects_unmatched_and_ambiguous_results(self):
  self.enqueue();j=self.a.jobs[0];j['status']='unknown';self.app.animation_busy=True
  jobs=self.root/'runtime/results/jobs';write(jobs/'other.json',{'workshop_job_id':'other','status':'success','cleanup_confirmed':True})
  with self.assertRaisesRegex(ValueError,'однозначного'):self.a.recover(j['id'])
  for name in ('first','second'):write(jobs/(name+'.json'),{'workshop_job_id':j['id'],'status':'success','cleanup_confirmed':True})
  with self.assertRaisesRegex(ValueError,'однозначного'):self.a.recover(j['id'])
  self.assertEqual(j['status'],'unknown');self.assertTrue(self.app.animation_busy)

 def test_unchanged_alignment_and_version_keep_approval(self):
  f=self.install();self.update('frame',frame=f['id'],accepted=True)
  self.update('frame',frame=f['id'],scale=1,x=0,y=0);self.assertTrue(self.p['tracks'][0]['frames'][0]['accepted'])
  self.update('frame',frame=f['id'],version=f['version']);self.assertTrue(self.p['tracks'][0]['frames'][0]['accepted'])
 def test_frame_reference_can_be_global_without_overwriting_overrides(self):
  f=self.install();self.update('frame',frame=f['id'],accepted=True);self.update('track',track='idle_up',reference=self.reference);self.update('project',reference=None)
  p=self.a.reference_from_frame(dict(project='hero',revision=self.p['revision'],frame=f['id'],scope='project'))
  self.assertTrue(p['reference']);self.assertEqual(p['reference_source']['frame'],f['id']);self.assertEqual(self.a.track(p,'idle_up')['reference'],self.reference);self.assertTrue(p['tracks'][0]['frames'][0]['accepted'])
 def test_frame_reference_can_target_another_action_and_direction(self):
  f=self.install();p=self.a.reference_from_frame(dict(project='hero',revision=self.p['revision'],frame=f['id'],track='walk_left'))
  target=self.a.track(p,'walk_left');self.assertTrue(target['reference']);self.assertEqual(target['reference_source']['frame'],f['id']);self.assertIsNone(p['tracks'][0]['reference'])

 def test_side_prompts_use_screen_direction_instead_of_anatomical_side(self):
  left=self.a.make_prompt(self.p,self.a.track(self.p,'idle_left'),0);right=self.a.make_prompt(self.p,self.a.track(self.p,'idle_right'),0)
  self.assertIn('LEFT edge of the image',left);self.assertIn('RIGHT edge of the image',right)
  self.assertIn('boot toes point RIGHT',right);self.assertIn('takes priority over the reference pose',right)
