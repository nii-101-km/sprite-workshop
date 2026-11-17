"""Non-destructive conversion of workshop source images into pixel sprites."""
import hashlib,json,math,time
from PIL import Image
from adapter import read,write,sha

def processing_signature(d,facts):
 payload={k:d[k] for k in ('width','height','scale','palette','mode')}
 payload.update(source_sha256=facts['source_sha256'],pipeline_version=1)
 return hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()

def process(root,key,d,raw,facts):
 if facts is None:raise ValueError('Нет исходника')
 if not facts['alpha_ok']:raise ValueError('Альфа не соответствует режиму: исходник сохранён, цвет фона не удаляется')
 if not facts['crop_bbox']:raise ValueError('Пустой исходник')
 if d.get('raw_sha256') and facts['source_sha256']!=d['raw_sha256']:raise ValueError('Исходник изменён вне программы. Нужна повторная приёмка.')
 signature=processing_signature(d,facts);base=root/'output'/d['category']/d['id'];resultfile=base/'result.json'
 if resultfile.exists():
  old=read(resultfile)
  if old.get('signature')==signature and all((root/p).exists() and sha(root/p)==old['checksums'][k] for k,p in old['files'].items()):return old
 # Every build uses a separate directory. Earlier exports are preserved.
 dest=base/('v-'+str(time.time_ns()));dest.mkdir(parents=True,exist_ok=False)
 width=max(1,math.floor(d['width']*d['scale']+.5));height=max(1,math.floor(d['height']*d['scale']+.5))
 with Image.open(raw) as loaded:im=loaded.convert('RGBA').crop(facts['crop_bbox'])
 ratio=min(width/im.width,height/im.height);content=[max(1,math.floor(im.width*ratio+.5)),max(1,math.floor(im.height*ratio+.5))]
 small=im.resize(content,Image.Resampling.BOX)
 alpha=small.getchannel('A').point(lambda a:255 if a>128 else 0);small.putalpha(alpha)
 if not alpha.getbbox():raise ValueError('Предмет исчез на выбранном размере. Увеличьте масштаб.')
 rgb=small.convert('RGB').quantize(colors=d['palette'],method=Image.Quantize.MEDIANCUT,dither=Image.Dither.NONE).convert('RGBA');rgb.putalpha(alpha)
 sprite=Image.new('RGBA',(width,height));sprite.paste(rgb,((width-content[0])//2,height-content[1]))
 sprite.save(dest/'sprite.png');sprite.resize((width*4,height*4),Image.Resampling.NEAREST).save(dest/'preview-x4.png')
 files={k:str(p.relative_to(root)) for k,p in [('sprite',dest/'sprite.png'),('preview',dest/'preview-x4.png')]}
 result=dict(signature=signature,key=key,source_sha256=facts['source_sha256'],crop_bbox=facts['crop_bbox'],target_box_px=[width,height],content_size_px=content,palette_colors=d['palette'],alpha_values=[i for i,n in enumerate(sprite.getchannel('A').histogram()) if n],files=files,checksums={k:sha(root/p) for k,p in files.items()},created_at=time.time(),visual_acceptance='not_reviewed',seamless_acceptance='not_reviewed' if d['mode']=='tile' else 'not_applicable')
 write(dest/'metadata.json',result);write(resultfile,result);return result
