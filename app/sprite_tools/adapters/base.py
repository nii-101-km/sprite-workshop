"""Model workflow contract for the two implemented ComfyUI adapters."""
from abc import ABC,abstractmethod
class ComfyGraphAdapter(ABC):
    version=1
    @abstractmethod
    def build_graph(self,prompt:str,seed:int,reference_filename:str|None=None)->dict:
        """Build a fresh graph; no IO, no file-root or GPU ownership."""
    def capabilities(self)->dict:
        return {'model':self.model_id,'adapter_id':self.model_id,'adapter_version':self.version,
                'transport':'comfyui','operations':['generate','edit'],'max_references':1,
                'native_output':self.native_output,'alpha_guaranteed':False,
                'requires_full_scene_caption':self.requires_full_scene_caption,
                'prompt_upsampler':'not run; caller supplies prompt',
                'sampling':dict(self.sampling),'model_files':dict(self.model_files)}
