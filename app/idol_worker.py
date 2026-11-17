"""Run IDOL with the local original DINOv3 image encoder."""
import os, sys, time
from pathlib import Path
from reconstruction_engines import idol_runtime
root = idol_runtime()
os.environ['HF_HUB_OFFLINE'] = '1'
os.environ['TRANSFORMERS_OFFLINE'] = '1'
sys.path.insert(0, str(root / 'source'))
import numpy as np
from PIL import Image
import idol.pipeline as pipeline
from idol.conditioning import ImageEncoder
from idol_input import prepare_idol_source

class LocalEncoder(ImageEncoder):
    def __init__(self, dinov3_repo, flux2_vae_repo, dinov3_dtype='bf16', device='cuda'):
        super().__init__(str(root/'experiments/dinov3-original'), str(root/'flux2'), dinov3_dtype=dinov3_dtype, device=device)
    def _dinov3_tokens(self, images):
        print('Running DINOv3 encoder on GPU', flush=True)
        return super()._dinov3_tokens(images)

pipeline.ImageEncoder = LocalEncoder
print('Loading Idol', flush=True)
model = pipeline.IdolPipeline.from_pretrained(str(root/'weights'), optimize=False)
print('Generating', flush=True)
threshold = int(sys.argv[3]) if len(sys.argv) > 3 else 8
with Image.open(sys.argv[1]) as source:
    prepared_source = prepare_idol_source(source, threshold)
out = model(prepared_source, mode='synthetic', num_gaussians=262144, steps=50, verbose=True)
folder = Path(sys.argv[2])
folder.mkdir(exist_ok=True)
out.gaussian.save_ply(str(folder/'splat.ply'))
out.preprocessed_image.save(folder/'input.png')
print('Saved', folder, flush=True)

# Point cloud is used only as an orientation guide; final images use the full splats.
from plyfile import PlyData
import trimesh
v=PlyData.read(str(folder/'splat.ply'))['vertex'].data
xyz=np.column_stack([v[k] for k in ('x','y','z')])
colors=np.clip(.5 + 0.2820947918*np.column_stack([v['f_dc_0'],v['f_dc_1'],v['f_dc_2']]),0,1)
alpha=1/(1+np.exp(-v['opacity']))
keep=alpha > .05
rgba=np.column_stack([colors[keep],alpha[keep]])
trimesh.PointCloud(xyz[keep], colors=(rgba*255).astype('uint8')).export(str(folder/'mesh.glb'))
