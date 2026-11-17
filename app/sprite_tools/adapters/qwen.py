from .base import ComfyGraphAdapter

def _build_qwen21_turbo_graph(prompt: str, seed: int) -> dict:
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "qwen_image_2.1_turbo_int8_convrot.safetensors", "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen3vl_8b_int8_convrot.safetensors", "type": "qwen_image", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "qwen_image_2.1_vae_bf16.safetensors"}},
        "4": {"class_type": "TextEncodeQwenImage21", "inputs": {"clip": ["2", 0], "prompt": prompt, "negative_prompt": "", "resolution": 1024}},
        "5": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
        "6": {"class_type": "ManualSigmas", "inputs": {"sigmas": "1.0, 0.978453, 0.95418, 0.926626, 0.89508, 0.845148, 0.704534, 0.414568, 0.0"}},
        "7": {"class_type": "SamplerCustom", "inputs": {"model": ["1", 0], "add_noise": True, "noise_seed": seed, "cfg": 1.0, "positive": ["4", 0], "negative": ["4", 1], "sampler": ["5", 0], "sigmas": ["6", 0], "latent_image": ["4", 2]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["7", 0], "vae": ["3", 0]}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": "sprite-pack"}},
    }


class QwenAdapter(ComfyGraphAdapter):
    model_id="qwen21_turbo"
    native_output="RGBA-capable; inspect actual alpha"
    requires_full_scene_caption=False
    sampling={"steps":8,"cfg":1.0,"sampler":"euler","schedule":"explicit ManualSigmas"}
    model_files={"diffusion":"qwen_image_2.1_turbo_int8_convrot.safetensors","encoder":"qwen3vl_8b_int8_convrot.safetensors","vae":"qwen_image_2.1_vae_bf16.safetensors"}
    def build_graph(self,prompt:str,seed:int,reference_filename:str|None=None)->dict:
        graph=_build_qwen21_turbo_graph(prompt,seed)
        if reference_filename is not None:
            graph["10"]={"class_type":"LoadImage","inputs":{"image":reference_filename}}
            graph["4"]["inputs"].update({"vae":["3",0],"images.image_1":["10",0]})
        return graph
