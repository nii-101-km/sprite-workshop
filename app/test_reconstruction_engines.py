import tempfile
import unittest
import json
from pathlib import Path
from unittest.mock import Mock, patch
from reconstruction_engines import ENGINES, get_engine

class EngineTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name);self.runtime=self.folder/'runtime'
        self.job={'camera':{'elevation':35,'yaw':90},'alpha_threshold':17}
        self.memory=Mock();self.log=Mock();self.env={'HF_HUB_OFFLINE':'1'}

    def test_model_specific_generation_and_render(self):
        with patch('reconstruction_engines.subprocess.run') as run, patch('reconstruction_engines.idol_python',return_value=self.runtime/'runtime/bin/python'):
            idol=get_engine('idol');idol.generate(self.runtime,self.folder,self.job,self.env,self.log)
            command=run.call_args.args[0]
            self.assertTrue(command[0].endswith('runtime/bin/python'))
            self.assertTrue(command[1].endswith('idol_worker.py'))
            self.assertEqual(command[-1],'17')
            idol.render(self.runtime,self.folder,self.job,self.env,self.log)
            command=run.call_args.args[0]
            self.assertTrue(command[1].endswith('idol_render.py'))
            self.assertEqual(command[2],str(self.folder/'splat.ply'))
            self.assertIn('90',command)

    def test_idol_runtime_uses_local_configuration(self):
        web=self.folder/'app';web.mkdir();model=self.folder/'custom-model'
        (self.folder/'idol-runtime.json').write_text(json.dumps({'root':str(model)}))
        with patch('reconstruction_engines.WEB',web):
            self.assertEqual(get_engine('idol').runtime(),model)

    def test_ready_requires_original_dinov3_weights(self):
        files=('weights/denoiser.safetensors','weights/decoder.safetensors','weights/decoder_gs.safetensors','weights/birefnet.safetensors','weights/config.json','flux2/vae/config.json','flux2/vae/diffusion_pytorch_model.safetensors','experiments/dinov3-original/config.json','experiments/dinov3-original/model.safetensors')
        for name in files:
            path=self.runtime/name;path.parent.mkdir(parents=True,exist_ok=True);path.touch()
        python=self.folder/'python';python.touch()
        with patch('reconstruction_engines.idol_python',return_value=python),patch('reconstruction_engines.python_ready',return_value=True):
            self.assertTrue(get_engine('idol').ready(self.runtime))
            (self.runtime/files[-1]).unlink()
            self.assertFalse(get_engine('idol').ready(self.runtime))

    def test_threshold_and_removed_engines(self):
        self.assertEqual(get_engine('idol').settings({},None),{'alpha_threshold':8})
        self.assertEqual(get_engine('idol').settings({'alpha_threshold':9},{'alpha_threshold':4}),{'alpha_threshold':4})
        with self.assertRaises(ValueError):get_engine('idol').settings({'alpha_threshold':255},None)
        with self.assertRaises(ValueError):get_engine('unknown')
        self.assertEqual(set(ENGINES),{'idol'})
        for name in ('sf3d','spar3d'):
            with self.assertRaises(ValueError):get_engine(name)

if __name__=='__main__':
    unittest.main()
