import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
import sprite_backend as backend

class SpriteBackendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        backend.configure(self.root)

    def patches(self):
        def download(history, dest):
            Image.new('RGBA', (8, 8), (50, 100, 150, 255)).save(dest)
        return patch.multiple(backend,
            _comfyui_check_queue=lambda: [],
            _comfyui_submit=lambda graph: 'prompt-123',
            _comfyui_poll=lambda prompt_id, timeout: {'status': {'completed': True}},
            _comfyui_download_image=download,
            _comfyui_upload_image=lambda path: 'references/input.png',
            _comfyui_release=lambda: {'status': 'ready', 'free_requested': True})

    def test_generate_and_edit_save_results_and_reference(self):
        with self.patches():
            result = backend.sprite_generate('a small wooden box', seed=12)
            self.assertEqual(result['status'], 'success')
            self.assertTrue(result['cleanup_confirmed'])
            self.assertTrue((self.root / result['raw_path']).is_file())
            reference = self.root / 'reference.png'
            Image.new('RGBA', (4, 4), 'red').save(reference)
            edited = backend.sprite_edit('reference.png', 'view from behind', seed=13)
            self.assertEqual(edited['status'], 'success')
            self.assertTrue((self.root / edited['reference_copy_path']).is_file())
            graph = json.loads((self.root / 'results/jobs' / edited['job_id'] / 'api_graph.json').read_text())
            self.assertEqual(graph['10']['inputs']['image'], 'references/input.png')

    def test_uncertain_submission_is_not_retried_or_marked_success(self):
        with patch.object(backend, '_comfyui_check_queue', return_value=[]), \
             patch.object(backend, '_comfyui_submit', side_effect=ConnectionError('lost response')):
            result = backend.sprite_generate('a box')
        self.assertEqual(result['status'], 'unknown')
        with patch.object(backend, '_comfyui_check_queue', return_value=[]), \
             patch.object(backend, '_comfyui_submit') as submit:
            with self.assertRaisesRegex(RuntimeError, 'unresolved'):
                backend.sprite_generate('a second box')
            submit.assert_not_called()

    def test_busy_queue_is_never_interrupted(self):
        with patch.object(backend, '_comfyui_check_queue', return_value=[{'id': 1}]), \
             patch.object(backend, '_comfyui_submit') as submit:
            with self.assertRaisesRegex(RuntimeError, 'queue is not empty'):
                backend.sprite_generate('a box')
            submit.assert_not_called()

    def test_worker_rejects_unknown_operation(self):
        request = self.root / 'request.json'
        response = self.root / 'response.json'
        request.write_text(json.dumps({'runtime': str(self.root / 'runtime'), 'response': str(response),
                                       'function': 'untrusted', 'arguments': {}}))
        process = subprocess.run([sys.executable, str(Path(__file__).with_name('worker.py')), str(request)],
                                 capture_output=True, text=True)
        self.assertNotEqual(process.returncode, 0)
        self.assertIn('Неизвестная операция', json.loads(response.read_text())['error'])

if __name__ == '__main__':
    unittest.main()
