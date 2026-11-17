from .base import ComfyGraphAdapter


def _node(kind, **inputs):
    return {'class_type': kind, 'inputs': inputs}


class KleinAdapter(ComfyGraphAdapter):
    """FLUX3 Image Klein distilled. Prompt is passed verbatim, no hidden enhancer."""
    model_id = 'klein3_distilled'
    native_output = 'RGB with Flux2 VAE; background removal is a separate CPU operation'
    requires_full_scene_caption = True
    sampling = {'steps': 16, 'cfg': 1.0, 'sampler': 'euler', 'schedule': 'simple'}
    model_files = {'diffusion': 'flux3_image_klein_sd_int8_convrot.safetensors',
                   'encoder': 'qwen3vl_4b_int8_convrot.safetensors', 'vae': 'flux2-vae.safetensors'}

    def build_graph(self, prompt: str, seed: int, reference_filename: str | None = None) -> dict:
        graph = {
            '1': _node('UNETLoader', unet_name=self.model_files['diffusion'], weight_dtype='default'),
            '2': _node('CLIPLoader', clip_name=self.model_files['encoder'], type='flux3', device='default'),
            '3': _node('VAELoader', vae_name=self.model_files['vae']),
            '4': _node('CLIPTextEncode', text=prompt, clip=['2', 0]),
            '5': _node('ConditioningZeroOut', conditioning=['4', 0]),
            '6': _node('EmptyFlux2LatentImage', width=1024, height=1024, batch_size=1),
            '7': _node('KSampler', model=['1', 0], positive=['4', 0], negative=['5', 0],
                       latent_image=['6', 0], seed=seed, steps=16, cfg=1.0,
                       sampler_name='euler', scheduler='simple', denoise=1.0),
            '8': _node('VAEDecode', samples=['7', 0], vae=['3', 0]),
            '9': _node('SaveImage', filename_prefix='sprite-pack', images=['8', 0]),
        }
        if reference_filename is not None:
            del graph['6']
            graph['10'] = _node('LoadImage', image=reference_filename)
            graph['11'] = _node('ReferenceMultiLatent', positive=['4', 0], negative=['5', 0],
                                vae=['3', 0], resolution='resize',
                                **{'resolution.megapixels': 1.0, 'images.image0': ['10', 0]})
            graph['7']['inputs'].update(positive=['11', 0], negative=['11', 1], latent_image=['11', 2])
        return graph
