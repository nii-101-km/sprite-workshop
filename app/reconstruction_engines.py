"""Model-specific paths and execution for non-destructive 3D reconstruction."""
from pathlib import Path
import subprocess
from functools import lru_cache
from adapter import read

WEB = Path(__file__).resolve().parent
def idol_runtime():
    config = WEB.parent/'idol-runtime.json'
    return Path(read(config)['root']).expanduser().resolve() if config.exists() else WEB.parent/'models/idol'

def idol_python(runtime):
    config = WEB.parent/'idol-runtime.json'
    value = read(config).get('python') if config.exists() else None
    return Path(value).expanduser() if value else runtime/'runtime/bin/python'

@lru_cache(maxsize=8)
def python_ready(python, modified):
    code = "import importlib.util,sys; sys.exit(not all(importlib.util.find_spec(n) for n in ('torch','diffusers','transformers','tensordict','moderngl','scipy','plyfile','trimesh','safetensors')))"
    try:
        return subprocess.run([str(python), '-c', code], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


class IdolEngine:
    name = 'idol'
    model_id = 'speridlabs/idol'
    default_orientation = (1, 0, 0, 0)
    model_file = 'splat.ply'
    renderer = 'idol_render.py'
    python_path = 'runtime/bin/python'

    def runtime(self):
        return idol_runtime()

    def ready(self, runtime):
        python = idol_python(runtime)
        if not python.is_file() or not python_ready(str(python),python.stat().st_mtime_ns):return False
        return all((runtime/p).is_file() for p in ('weights/denoiser.safetensors',
            'weights/decoder.safetensors', 'weights/decoder_gs.safetensors', 'weights/birefnet.safetensors',
            'weights/config.json', 'flux2/vae/config.json', 'flux2/vae/diffusion_pytorch_model.safetensors',
            'experiments/dinov3-original/config.json', 'experiments/dinov3-original/model.safetensors'))

    def settings(self, data, parent):
        threshold = parent.get('alpha_threshold') if parent is not None else data.get('alpha_threshold', 8)
        if parent is None and (type(threshold) is not int or not 0 <= threshold <= 254):
            raise ValueError('Порог непрозрачности должен быть целым числом от 0 до 254')
        return {'alpha_threshold': threshold} if threshold is not None else {}

    def generate(self, runtime, folder, job, env, log):
        command = [str(idol_python(runtime)), str(WEB/'idol_worker.py'), str(folder/'source.png'),
                   str(folder), str(job.get('alpha_threshold', 8))]
        subprocess.run(command, env=env, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=1800)


    def render(self, runtime, folder, job, env, log):
        command = [str(idol_python(runtime)), str(WEB/self.renderer), str(folder/self.model_file), str(folder/'views'),
                   '--elevation', str(job['camera']['elevation']), '--yaw', str(job['camera']['yaw']),
                   '--orientation', str(folder/'orientation.json')]
        subprocess.run(command, env=env, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=180)


ENGINES = {engine.name: engine for engine in (IdolEngine(),)}


def get_engine(name):
    try:
        return ENGINES[name]
    except (KeyError, TypeError):
        raise ValueError('Неизвестная 3D-модель') from None
