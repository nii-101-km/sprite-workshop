import unittest
from viewpoint import generation_prompt
class LevelCamera(unittest.TestCase):
 def test_level_camera_applies_to_any_object_and_direction(self):
  for name in ['small wooden table','worn single bed','closed wooden cabinet','round trash bin']:
   for direction in ['front','back','left','right']:
    p=generation_prompt(dict(style='Muted warm colors.',prompt=name,perspective='level',direction=direction))
    self.assertIn(name,p)
    self.assertIn('EDGE-ON',p)
    self.assertIn('far edge is hidden',p)
    self.assertNotIn('facing DOWN',p)
    self.assertNotIn('facing UP',p)
 def test_other_cameras_and_legacy_prompts_unchanged(self):
  data=dict(style='Pixel art.',prompt='Table',perspective='',direction='')
  self.assertEqual(generation_prompt(data),'Pixel art. Table')
  for camera in ['rpg','top','isometric']:
   self.assertNotIn('far edge is hidden',generation_prompt({**data,'perspective':camera}))

 def test_specific_surface(self):
  for name,surface in [('wooden chair','SEAT HEIGHT'),('small table','TABLETOP HEIGHT'),('single bed','MATTRESS HEIGHT')]:
   self.assertIn(surface,generation_prompt(dict(style='',prompt=name,perspective='level',direction='front')))

 def test_bed_does_not_become_table_from_negative_prompt(self):
  p=generation_prompt(dict(id='gothic_bed',label='Готическая кровать',style='',prompt='One gothic bed. No bedside table.',perspective='level',direction='front'))
  self.assertIn('MATTRESS HEIGHT',p)
  self.assertNotIn('TABLETOP HEIGHT',p)

 def test_stool_uses_seat(self):
  p=generation_prompt(dict(id='kitchen_stool',style='',prompt='kitchen stool',perspective='level',direction='front'))
  self.assertIn('SEAT HEIGHT',p)

 def test_sink_and_stove_occlusion(self):
  for name,term in [('kitchen_sink','SINK RIM HEIGHT'),('gas_stove','COOKTOP HEIGHT')]:
   p=generation_prompt(dict(id=name,style='',prompt=name,perspective='level',direction='front'))
   self.assertIn(term,p)
   self.assertIn('do not tilt the camera',p)
