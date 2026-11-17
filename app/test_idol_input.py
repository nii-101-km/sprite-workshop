import unittest
from PIL import Image
from idol_input import prepare_idol_source


class IdolInputTests(unittest.TestCase):
    def test_invisible_noise_removed_without_changing_soft_edges_or_source(self):
        source = Image.new('RGBA', (100, 100), (30, 10, 70, 1))
        source.paste((40, 70, 80, 255), (30, 20, 70, 80))
        source.putpixel((0, 0), (40, 70, 80, 4))
        source.putpixel((1, 0), (40, 70, 80, 8))
        source.putpixel((29, 30), (40, 70, 80, 9))
        source.putpixel((29, 31), (40, 70, 80, 32))
        before = source.tobytes()
        result = prepare_idol_source(source)
        self.assertEqual(result.getchannel('A').getbbox(), (29, 20, 70, 80))
        self.assertEqual(result.getpixel((0, 0))[3], 0)
        self.assertEqual(result.getpixel((1, 0))[3], 0)
        self.assertEqual(result.getpixel((29, 30))[3], 9)
        self.assertEqual(result.getpixel((29, 31))[3], 32)
        self.assertEqual(source.tobytes(), before)

    def test_empty_rejected_and_rgb_preserved(self):
        with self.assertRaises(ValueError):
            prepare_idol_source(Image.new('RGBA', (10, 10), (1, 2, 3, 1)))
        self.assertEqual(prepare_idol_source(Image.new('RGB', (10, 10))).mode, 'RGB')

    def test_custom_threshold_and_validation(self):
        source=Image.new('RGBA',(3,1),(1,2,3,0))
        source.putpixel((1,0),(1,2,3,8))
        source.putpixel((2,0),(1,2,3,100))
        self.assertEqual(prepare_idol_source(source,0).getpixel((1,0))[3],8)
        self.assertEqual(prepare_idol_source(source,8).getpixel((1,0))[3],0)
        self.assertEqual(prepare_idol_source(source,8).getpixel((2,0))[3],100)
        for invalid in (-1,255,1.5,True,'8'):
            with self.assertRaises(ValueError): prepare_idol_source(source,invalid)
