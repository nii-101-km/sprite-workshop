"""Run one workshop image operation in an isolated process."""
import inspect
import sys
from pathlib import Path
from adapter import read,write
import sprite_backend
if __name__=='__main__':
 request=read(Path(sys.argv[1]));root=Path(request['runtime']);root.mkdir(parents=True,exist_ok=True)
 try:
  operations={'sprite_generate':sprite_backend.sprite_generate,'sprite_edit':sprite_backend.sprite_edit}
  function=operations.get(request.get('function'))
  if function is None:raise ValueError('Неизвестная операция генератора')
  arguments=request.get('arguments')
  if not isinstance(arguments,dict):raise ValueError('Неверные параметры генератора')
  inspect.signature(function).bind(**arguments)
  sprite_backend.configure(root)
  result=function(**arguments)
  write(Path(request['response']),{'result':result})
 except BaseException as exc:
  write(Path(request['response']),{'error':str(exc)})
  raise
