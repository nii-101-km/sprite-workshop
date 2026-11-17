import tempfile
import unittest
from pathlib import Path
from PIL import Image
from adapter import write, read
from store import Workshop, Conflict
import trash


class TrashTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.app=Workshop(Path(self.tmp.name));self.key=self.app.add([dict(id='sofa',category='A',prompt='Sofa')])[0]
        self.app.jobs=[]
        raw,meta=self.app.paths(self.key);Image.new('RGBA',(16,16),'red').save(raw)
        self.original=raw.read_bytes();self.revision=self.app.asset(self.key)['revision']

    def remove(self):return trash.remove(self.app,dict(key=self.key,revision=self.revision))

    def test_group_round_trip_preserves_png_outputs_history_and_settings(self):
        raw,meta=self.app.paths('A/side');Image.new('RGBA',(16,16),'blue').save(raw)
        d=self.app.metadata(self.key).copy();d.update(id='side',key='A/side',parent_key=self.key,direction='left');write(meta,d)
        out=self.app.root/'output/A/sofa/v-one';out.mkdir(parents=True);(out/'sprite.png').write_bytes(b'png')
        history=self.app.root/'history/A/sofa/v-one';history.mkdir(parents=True);(history/'raw.png').write_bytes(b'old')
        entry=self.remove();self.assertEqual(self.app.keys(),[]);self.assertEqual(len(trash.entries(self.app)),1)
        trash.restore(self.app,dict(id=entry['id']))
        self.assertEqual(set(self.app.keys()),{self.key,'A/side'})
        self.assertEqual(self.app.paths(self.key)[0].read_bytes(),self.original)
        self.assertEqual((out/'sprite.png').read_bytes(),b'png');self.assertEqual((history/'raw.png').read_bytes(),b'old')
        self.assertGreater(self.app.asset(self.key)['revision'],self.revision)
        self.assertEqual(trash.entries(self.app),[])

    def test_restore_does_not_overwrite_reused_id(self):
        entry=self.remove();self.app.add([dict(id='sofa',category='A',prompt='New sofa')])
        with self.assertRaises(Conflict):trash.restore(self.app,dict(id=entry['id']))
        self.assertEqual(self.app.metadata(self.key)['prompt'],'New sofa')
        self.assertEqual(len(trash.entries(self.app)),1)

    def test_busy_and_stale_are_rejected_without_moving_source(self):
        self.app.jobs=[dict(key=self.key,status='unknown')]
        with self.assertRaises(ValueError):self.remove()
        self.app.jobs=[]
        with self.assertRaises(Conflict):trash.remove(self.app,dict(key=self.key,revision=999))
        self.assertEqual(self.app.paths(self.key)[0].read_bytes(),self.original)
        with self.assertRaises(ValueError):trash.restore(self.app,dict(id='../raw'))
