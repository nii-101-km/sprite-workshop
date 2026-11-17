import math, json, sys, argparse
from orientation import rotation_matrix, model_scale
from pathlib import Path
import numpy as np
import moderngl
from PIL import Image
from plyfile import PlyData
from scipy.spatial.transform import Rotation

def render(ply,out,elevation=35,yaw=0,orientation=None,scale=None):
 v=PlyData.read(ply)['vertex'].data
 xyz=np.column_stack([v[k] for k in ('x','y','z')]); rot=np.column_stack([v[k] for k in ('rot_1','rot_2','rot_3','rot_0')]); scales=np.exp(np.column_stack([v[k] for k in ('scale_0','scale_1','scale_2')])); opacity=1/(1+np.exp(-v['opacity'])); colors=np.clip(.5+0.2820947918*np.column_stack([v['f_dc_0'],v['f_dc_1'],v['f_dc_2']]),0,1)
 m=Rotation.from_quat(rot).as_matrix(); cov=(m*scales[:,None,:]) @ (m*scales[:,None,:]).transpose(0,2,1)
 factors=np.asarray(model_scale(scale or [100,100,100]))/100
 transform=np.asarray(rotation_matrix(orientation or [0,0,0,1]))[:3,:3] @ np.diag(factors)
 xyz=xyz @ transform.T; cov=transform @ cov @ transform.T
 print('bounds',xyz.min(axis=0),xyz.max(axis=0),flush=True)
 c=(xyz.max(0)+xyz.min(0))/2; xyz-=c; span=np.linalg.norm(xyz.max(0)-xyz.min(0))*1.1
 ctx=moderngl.create_standalone_context(backend='egl'); prog=ctx.program(vertex_shader='''#version 330
 in vec2 quad; in vec2 center; in vec4 basis; in vec4 rgba; out vec2 uv; out vec4 col;
 void main(){uv=quad*3.; col=rgba; vec2 offset=mat2(basis)*uv; gl_Position=vec4(center+offset,0.,1.);}
 ''',fragment_shader='''#version 330
 in vec2 uv; in vec4 col; out vec4 result; void main(){float a=col.a*exp(-.5*dot(uv,uv)); if(a<0.0039)discard; result=vec4(col.rgb,a);}''')
 quad=ctx.buffer(np.array([[-1,-1],[1,-1],[-1,1],[1,1]],dtype='f4').tobytes()); output=Path(out); output.mkdir(exist_ok=True,parents=True)
 for face,deg in {'front':180,'back':0,'left':270,'right':90}.items():
  az=math.radians(deg+yaw); pitch=math.radians(elevation); forward=np.array([math.sin(az)*math.cos(pitch),math.sin(pitch),math.cos(az)*math.cos(pitch)]); up=np.array([0,1,0]);
  if abs(forward@up)>.999: up=np.array([0.,0.,-1.])
  right=np.cross(up,forward); right/=np.linalg.norm(right); up=np.cross(forward,right); proj=np.stack([right,up])*2/span
  centers=xyz@proj.T; projected=np.einsum('ij,njk,lk->nil',proj,cov,proj); projected[:,0,0]+=1/512**2; projected[:,1,1]+=1/512**2
  vals,vecs=np.linalg.eigh(projected); vals=np.maximum(vals,1e-12); basis=vecs*np.sqrt(vals)[:,None,:]
  depth=xyz@forward; order=np.argsort(depth); data=np.column_stack([centers,basis[:,0,0],basis[:,1,0],basis[:,0,1],basis[:,1,1],colors,opacity])[order].astype('f4'); buf=ctx.buffer(data.tobytes()); vao=ctx.vertex_array(prog,[(quad,'2f','quad'),(buf,'2f 4f 4f /i','center','basis','rgba')]); fbo=ctx.simple_framebuffer((512,512),components=4); fbo.use(); fbo.clear(0,0,0,0); ctx.enable(moderngl.BLEND); ctx.blend_func=(moderngl.SRC_ALPHA,moderngl.ONE_MINUS_SRC_ALPHA,moderngl.ONE,moderngl.ONE_MINUS_SRC_ALPHA); vao.render(moderngl.TRIANGLE_STRIP,vertices=4,instances=len(v)); arr=np.frombuffer(fbo.read(components=4),dtype=np.uint8).reshape(512,512,4).copy(); alpha=arr[:,:,3].astype(float); arr[:,:,:3]=np.clip(arr[:,:,:3].astype(float)*255/np.maximum(alpha[:,:,None],1),0,255).astype('uint8'); Image.fromarray(arr).transpose(Image.Transpose.FLIP_TOP_BOTTOM).save(output/(face+'.png')); print(face,flush=True); vao.release();buf.release();fbo.release()
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('ply');p.add_argument('output');p.add_argument('--elevation',type=float,default=35);p.add_argument('--yaw',type=float,default=0);p.add_argument('--orientation');a=p.parse_args()
 settings=json.loads(Path(a.orientation).read_text()) if a.orientation else {}
 render(a.ply,a.output,a.elevation,a.yaw,settings.get('quaternion'),settings.get('model_scale'))
