"""Offline CPU-only EmbeddingGemma 2 worker. JSON lines on stdin/stdout."""
import contextlib,json,os,sys,traceback
from pathlib import Path

def main():
 model_path=Path(sys.argv[1]).resolve()
 # Only protocol messages go to stdout; library progress stays in the worker log.
 with contextlib.redirect_stdout(sys.stderr):
  import torch
  from sentence_transformers import SentenceTransformer
  torch.set_num_threads(min(8,os.cpu_count() or 1))
  model=SentenceTransformer(str(model_path),device='cpu',config_kwargs={'audio_config':None},model_kwargs={'torch_dtype':torch.float32},local_files_only=True,trust_remote_code=False)
 print(json.dumps({'ready':True,'device':'cpu','dimension':768}),flush=True)
 for line in sys.stdin:
  try:
   request=json.loads(line)
   with contextlib.redirect_stdout(sys.stderr):
    if request['op']=='query':vectors=model.encode([request['query']],prompt_name='SearchQuery',normalize_embeddings=True,convert_to_numpy=True,show_progress_bar=False,batch_size=1)
    elif request['op']=='asset':
     image=model.encode([{'image':request['image']}],normalize_embeddings=True,convert_to_numpy=True,show_progress_bar=False,batch_size=1)
     text=model.encode([request['text']],prompt='',normalize_embeddings=True,convert_to_numpy=True,show_progress_bar=False,batch_size=1)
     vectors=[image[0],text[0]]
    else:raise ValueError('Unsupported operation')
   print(json.dumps({'vectors':[v.tolist() for v in vectors]},allow_nan=False),flush=True)
  except Exception as exc:
   traceback.print_exc(file=sys.stderr);print(json.dumps({'error':str(exc)}),flush=True)
if __name__=='__main__':main()
