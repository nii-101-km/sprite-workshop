"""Shared storage and GPU checks for the workshop."""
import hashlib,json,os,subprocess,tempfile
from pathlib import Path

def read(path):return json.loads(path.read_text())
def write(path,data):
 path.parent.mkdir(parents=True,exist_ok=True)
 with tempfile.NamedTemporaryFile(mode='w',dir=path.parent,delete=False,encoding='utf-8') as f:
  json.dump(data,f,ensure_ascii=False,indent=2);f.write('\n');f.flush();os.fsync(f.fileno());temporary=f.name
 os.replace(temporary,path)
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def gpu_idle():
 result=subprocess.run(['nvidia-smi','--query-gpu=memory.used','--format=csv,noheader,nounits'],capture_output=True,text=True,check=True,timeout=10)
 if any(int(row.strip())>=1900 for row in result.stdout.splitlines() if row.strip()):
  raise RuntimeError('GPU already occupied: pause/unload the owning application first; this script never stops it.')
