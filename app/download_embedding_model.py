"""Explicit opt-in setup only; the running app never downloads model files."""
from pathlib import Path
import json
from huggingface_hub import snapshot_download
root=Path(__file__).resolve().parent.parent
lock=json.loads((root/'embedding-model-lock.json').read_text())
snapshot_download(lock['model_id'],revision=lock['revision'],token=False,local_dir=str(root/'.embedding-model'),allow_patterns=['*.json','*.safetensors','*.jinja','tokenizer.model'],max_workers=3)
print('Модель скачана:',root/'.embedding-model')
