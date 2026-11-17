"""Camera and object orientation, kept separate from the object description."""
import re
PERSPECTIVES = {
 '': '',
 'rpg': 'Orthographic camera slightly above the object, aligned with the map axes. Show the vertical surface selected by the object direction and a narrow top surface. Camera elevation does not determine object facing. Parallel edges remain parallel. No isometric or diagonal camera rotation.',
 'top': 'Strict orthographic TOP-DOWN camera, looking vertically downward. Show the top of the object. No horizon, no perspective convergence.',
 'level': 'Strict orthographic elevation at object height. Zero camera pitch, yaw and roll. Camera looks horizontally, perpendicular to the vertical surface selected by the object direction. Horizontal edges are perfectly horizontal; vertical edges are perfectly vertical. Camera rays are parallel to horizontal surfaces. Every horizontal top plane is seen EDGE-ON and collapses into a straight horizontal line: show its vertical thickness only, never a filled upper surface. The far edge is hidden directly behind the near edge, not drawn above it. Apply this to whichever parts the object actually has: a tabletop, seat, mattress, shelf, cabinet top or lid. Preserve the actual object structure and silhouette; do not add these parts to objects that do not have them. Vertical faces remain visible. Flat architectural elevation, no perspective convergence, no elevated or three-quarter view.',
 'isometric': 'Isometric camera elevated above the object, with the map axes projected diagonally. Parallel edges remain parallel.'
}
DIRECTIONS = {
 '': '',
 'front': 'Object facing DOWN toward the viewer: straight FRONT view, showing its front surface or seating opening.',
 'back': 'Object facing UP away from the viewer: straight REAR view, showing its outside back panel. The front surface or seating opening faces away and is hidden.',
 'left': 'Rotate the reference object 90 degrees around its vertical axis. Object front faces the LEFT image edge. Strict LEFT-FACING SIDE PROFILE: show the outer side panel instead of the broad front panel. Front edge at image LEFT, rear edge at image RIGHT. The original front panel is edge-on and not visible as a broad rectangle.',
 'right': 'Rotate the reference object 90 degrees around its vertical axis in the opposite direction. Object front faces the RIGHT image edge. Strict RIGHT-FACING SIDE PROFILE: show the outer side panel instead of the broad front panel. Front edge at image RIGHT, rear edge at image LEFT. The original front panel is edge-on and not visible as a broad rectangle.'
}
def validate_viewpoint(data):
 for field,choices in [('perspective',PERSPECTIVES),('direction',DIRECTIONS)]:
  value=data.get(field,'')
  if not isinstance(value,str) or value not in choices:raise ValueError('Неверное поле '+field)
  data[field]=value
 return data

def generation_prompt(data):
 style=data['style'];perspective=data.get('perspective','');direction=data.get('direction','')
 # Existing cards retain their exact legacy prompt until an explicit camera is selected.
 if perspective or direction:
  camera_words=r'orthographic|isometric|perspective|camera|three.quarter|front view|rear view|side view|side face|top surface|horizontal edges|vertical edges'
  style=' '.join(s.strip() for s in re.split(r'(?<=[.!?])\s+',style) if not re.search(camera_words,s,re.I))
 text=style+' '+data['prompt']
 if perspective=='level':
  identity=(data.get('id','')+' '+data.get('label','')).lower().replace('_',' ')
  surface='horizontal top surface'
  groups=[(('sink','раковин','мойк'),'sink rim'),(('stove','cooker','плит'),'cooktop'),(('chair','stool','стул','табурет','кресл','sofa','диван'),'seat'),(('bed','кроват'),'mattress'),(('table','desk','стол'),'tabletop'),(('cabinet','шкаф','комод','сервант'),'cabinet top'),(('bin','бак','ведро'),'lid')]
  # Identity takes precedence over unrelated objects mentioned in the prompt.
  # Exclude sentences introducing negative lists such as "no bedside table".
  positive=' '.join(part for part in re.split(r'[.!?]',data['prompt'].lower()) if not re.search(r'\bno\b|without|без ',part))
  for description in (identity,positive):
   found=False
   for words,name in groups:
    if any(re.search(r'(?<![a-zа-яё])'+re.escape(word),description) for word in words):surface=name;found=True;break
   if found:break
  facing={'front':'Strict FRONT orthographic elevation.','back':'Strict REAR orthographic elevation.','left':'Strict LEFT-FACING SIDE orthographic elevation.','right':'Strict RIGHT-FACING SIDE orthographic elevation.'}.get(direction,'Strict orthographic elevation.')
  camera=f"Camera exactly at {surface.upper()} HEIGHT, looking horizontally, parallel to the {surface}. The {surface} is seen EDGE-ON: its upper surface collapses into one straight horizontal line. Show its vertical thickness only. The far edge is hidden directly behind the near edge. No perspective, no visible top plane, no overhead angle, no three-quarter view."
  if surface=='sink rim':camera+=' The basin interior and drain are hidden behind the front rim. The faucet remains visible above the rim; do not tilt the camera to show the bowl.'
  elif surface=='cooktop':camera+=' Burners behind the front cooktop edge are occluded in this level view; do not tilt the camera to reveal them. The front controls and oven door remain visible.'
  return facing+' '+data['prompt']+' '+camera+' '+style
 if perspective or direction:
  text+=' CAMERA AND ORIENTATION SETTINGS (override any conflicting view instructions above; preserve the object design): '
  if perspective:text+='Camera: '+PERSPECTIVES[perspective]+' '
  if direction:text+='Object direction in image coordinates: '+DIRECTIONS[direction]+' '
 return text
