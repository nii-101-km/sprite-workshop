import base64
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from adapter import sha, write
from reconstruction import Reconstruction, job_progress
from store import Workshop, Conflict


class ReconstructionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.app = Workshop(Path(self.tmp.name))
        self.key = self.app.add([dict(id='sofa',category='A',prompt='Sofa',direction='front',width=24,height=16,scale=1.25)])[0]
        self.app.jobs = []
        image = Image.new('RGBA',(40,30));image.paste((100,60,20,255),(3,5,36,28))
        buf = io.BytesIO();image.save(buf,'PNG')
        self.app.manual_direction(dict(key=self.key,revision=1,direction='front',target_revision=1,data=base64.b64encode(buf.getvalue()).decode()))
        self.rec = Reconstruction(self.app)
        runtime_patch = patch.object(self.rec, 'runtime', return_value=Path(self.tmp.name)/'isolated-runtime')
        runtime_patch.start(); self.addCleanup(runtime_patch.stop)
        self.job = dict(id='a'*32,key=self.key,engine='idol',status='complete',source_sha256=sha(self.app.paths(self.key)[0]),camera=dict(elevation=35,yaw=0),orientation=[0,0,0,1],orientation_confirmed=True)
        self.rec.jobs.append(self.job);self.rec.persist()
        folder=self.rec.root/self.job['id'];(folder/'views').mkdir(parents=True)
        (folder/'mesh.glb').write_bytes(b'test mesh')
        for face in ('front','back','left','right'):
            other=Image.new('RGBA',(40,30));other.paste((30,80,90,255),(5,7,30,28));other.save(folder/'views'/(face+'.png'))

    def test_axis_scale_roundtrip_and_reset(self):
        with patch.object(self.rec,'ready',return_value=True), patch('reconstruction.threading.Thread'):
            result=self.rec.start(dict(key=self.key,revision=self.app.asset(self.key)['revision'],job=self.job['id'],model_scale=[150,80,120]),rerender=True)
            self.assertEqual(result['model_scale'],[150,80,120])
            self.app.sf3d_busy=False
            result['status']='complete'
            next(j for j in self.rec.jobs if j['id']==result['id'])['status']='complete'
            self.rec.confirm_orientation(dict(key=self.key,job=result['id'],revision=self.app.asset(self.key)['revision'],orientation_revision=0))
            self.assertEqual(Reconstruction(self.app).orientations[self.key]['model_scale'],[150,80,120])
            reset=self.rec.start(dict(key=self.key,revision=self.app.asset(self.key)['revision'],job=result['id'],model_scale=[100,100,100]),rerender=True)
            self.assertEqual(reset['model_scale'],[100,100,100])
            self.assertEqual((self.rec.root/reset['id']/'mesh.glb').read_bytes(),b'test mesh')

    def test_invalid_scale_is_atomic(self):
        with patch.object(self.rec,'ready',return_value=True):
            for value in ([0,100,100],[-1,100,100],[100,float('nan'),100],[100,100],None):
                with self.assertRaises(ValueError):self.rec.start(dict(key=self.key,revision=self.app.asset(self.key)['revision'],job=self.job['id'],model_scale=value),rerender=True)
        self.assertEqual(len(self.rec.jobs),1)

    def apply(self, face):
        base=self.app.asset(self.key)
        target=base if face=='front' else next((self.app.asset(k) for k in self.app.keys() if self.app.metadata(k).get('parent_key')==self.key and self.app.metadata(k).get('direction')==face),None)
        return self.rec.apply(dict(key=self.key,job=self.job['id'],direction=face,revision=base['revision'],target_revision=target['revision'] if target else None))

    def test_selected_import_archives_front_and_preserves_scale(self):
        original=self.app.paths(self.key)[0].read_bytes()
        result=self.apply('left')['asset']
        self.assertEqual(self.app.paths(self.key)[0].read_bytes(),original)
        self.assertEqual(result['parent_key'],self.key)
        self.assertEqual(result['scale'],1.25)
        self.assertTrue(result['output_current'])
        self.apply('front')
        self.assertGreater(self.app.asset(self.key)['history_count'],0)
        self.assertTrue(self.apply('back')['asset']['output_current'])

    def test_stale_source_and_cross_asset_cannot_import(self):
        raw=self.app.paths(self.key)[0]
        Image.new('RGBA',(10,10),'red').save(raw)
        with self.assertRaises(Conflict):self.apply('left')
        with self.assertRaises(ValueError):self.rec.apply(dict(key='A/other',job=self.job['id'],direction='left'))

    def test_ready_and_camera_and_restart(self):
        self.assertFalse(self.rec.ready())
        with self.assertRaises(ValueError):self.rec.camera(dict(elevation=float('nan')))
        with self.assertRaises(ValueError):self.rec.file(self.job['id'],'../../secret')
        self.job['status']='running';self.rec.persist()
        self.assertEqual(Reconstruction(self.app).jobs[0]['status'],'interrupted')

    def test_confirmation_persists_and_checks_revision(self):
        self.job['height_offset']=-4.5
        self.job['orientation_confirmed']=False
        revision=self.app.asset(self.key)['revision']
        result=self.rec.confirm_orientation(dict(key=self.key,job=self.job['id'],revision=revision,orientation_revision=0))
        self.assertEqual(result['revision'],1)
        self.assertTrue(self.job['orientation_confirmed'])
        loaded=Reconstruction(self.app)
        self.assertEqual(loaded.orientations[self.key]['quaternion'],[0,0,0,1])
        self.assertEqual(loaded.orientations[self.key]['height_offset'],-4.5)
        with self.assertRaises(Conflict):self.rec.confirm_orientation(dict(key=self.key,job=self.job['id'],revision=revision,orientation_revision=0))
        self.assertTrue(self.apply('left')['asset']['output_current'])

    def test_ready_view_can_be_applied_without_confirming_orientation(self):
        self.job['orientation_confirmed']=False
        original=self.app.paths(self.key)[0].read_bytes()
        result=self.apply('left')['asset']
        self.assertTrue(result['output_current'])
        self.assertEqual(self.app.paths(self.key)[0].read_bytes(),original)
        self.assertFalse(self.job['orientation_confirmed'])

    def test_rerender_uses_original_mesh_and_saved_orientation(self):
        with patch.object(self.rec,'ready',return_value=True), patch('reconstruction.threading.Thread'):
            q=[0,1,0,0]
            result=self.rec.start(dict(key=self.key,revision=self.app.asset(self.key)['revision'],job=self.job['id'],quaternion=q,height_offset=-3.5),rerender=True)
        self.assertFalse(result['orientation_confirmed'])
        self.assertEqual(result['orientation'],q)
        self.assertEqual(result['height_offset'],-3.5)
        self.assertEqual((self.rec.root/result['id']/'mesh.glb').read_bytes(),b'test mesh')
        self.assertEqual(self.job['orientation'],[0,0,0,1])

    def test_invalid_orientation_fails_before_creating_job(self):
        with patch.object(self.rec,'ready',return_value=True):
            with self.assertRaises(ValueError):self.rec.start(dict(key=self.key,revision=self.app.asset(self.key)['revision'],job=self.job['id'],quaternion=[0,0,float('nan'),1]),rerender=True)
        self.assertEqual(len(self.rec.jobs),1)

    def test_invalid_height_rejected_before_creating_job(self):
        with patch.object(self.rec,'ready',return_value=True):
            for value in [float('nan'),51,-51,True,'2']:
                with self.assertRaises(ValueError):
                    self.rec.start(dict(key=self.key,revision=self.app.asset(self.key)['revision'],job=self.job['id'],height_offset=value),rerender=True)
        self.assertEqual(len(self.rec.jobs),1)

    def test_idol_is_default_for_new_jobs(self):
        with patch.object(self.rec,'ready',return_value=True), patch('reconstruction.threading.Thread'):
            job=self.rec.start(dict(key=self.key,revision=self.app.asset(self.key)['revision']))
        self.assertEqual(job['engine'],'idol')
        self.assertEqual((self.rec.root/job['id']/'source.png').read_bytes(),self.app.paths(self.key)[0].read_bytes())

    def test_idol_threshold_is_validated_and_carried_to_rerender(self):
        revision=self.app.asset(self.key)['revision']
        with patch.object(self.rec,'ready',return_value=True), patch('reconstruction.threading.Thread'):
            for value in (-1,255,1.5,True,'8'):
                with self.assertRaises(ValueError):
                    self.rec.start(dict(key=self.key,revision=revision,alpha_threshold=value))
            job=self.rec.start(dict(key=self.key,revision=revision,alpha_threshold=17))
            self.assertEqual(job['alpha_threshold'],17)
            self.app.sf3d_busy=False
            saved=self.rec.job(job['id']);saved['status']='complete'
            rerender=self.rec.start(dict(key=self.key,revision=revision,job=job['id'],alpha_threshold=44),rerender=True)
            self.assertEqual(rerender['alpha_threshold'],17)

    def test_old_model_views_remain_usable_without_old_engine(self):
        self.job['engine']='spar3d'
        with self.assertRaisesRegex(ValueError, 'старый движок удалён'):
            self.rec.start(dict(key=self.key,revision=self.app.asset(self.key)['revision'],job=self.job['id']),rerender=True)
        result=self.apply('left')
        generation=self.app.metadata(result['asset']['key'])['generation']
        self.assertEqual(generation['operation'],'spar3d')
        self.assertEqual(generation['model'],'zimengxiong/Modelr-SPAR3D')
        self.assertEqual(self.rec.file(self.job['id'],'mesh').read_bytes(),b'test mesh')

    def test_idol_rerender_preserves_splats(self):
        self.job['engine']='idol'
        (self.rec.root/self.job['id']/'splat.ply').write_bytes(b'test splats')
        with patch.object(self.rec,'ready',return_value=True), patch('reconstruction.threading.Thread'):
            job=self.rec.start(dict(key=self.key,revision=self.app.asset(self.key)['revision'],job=self.job['id']),rerender=True)
        self.assertEqual(job['engine'],'idol')
        self.assertEqual((self.rec.root/job['id']/'splat.ply').read_bytes(),b'test splats')

    def test_idol_progress_reports_latest_sampling_step_and_estimate(self):
        job=dict(id='b'*32,engine='idol',status='running')
        folder=self.rec.root/job['id'];folder.mkdir()
        log=folder/'worker.log'
        log.write_text('Loading Idol\nRunning DINOv3 encoder on GPU\nSampling:  20%|xx | 10/50 [00:24<01:39, 2.48s/it]\rSampling:  40%|xxxx | 20/50 [00:49<01:14, 2.49s/it]\r')
        self.assertEqual(job_progress(job,self.rec.root),dict(stage='Построение 3D',current=20,total=50,remaining_seconds=74))
        log.write_text('Loading Idol\nRunning DINOv3 encoder on GPU\n')
        self.assertEqual(job_progress(job,self.rec.root),dict(stage='Анализ изображения'))
        log.write_text('Sampling: 100%|xxx | 50/50 [02:00<00:00, 2.4s/it]\nSaved output\n')
        self.assertEqual(job_progress(job,self.rec.root),dict(stage='Подготовка ракурсов'))
        job['status']='complete'
        self.assertIsNone(job_progress(job,self.rec.root))

    def test_gpu_work_is_mutually_exclusive(self):
        self.app.sf3d_busy=True
        with self.assertRaises(ValueError):self.app.start()
        with patch.object(self.rec,'ready',return_value=True):
            with self.assertRaises(ValueError):self.rec.start(dict(key=self.key,revision=self.app.asset(self.key)['revision']))


if __name__ == '__main__':
    unittest.main()
