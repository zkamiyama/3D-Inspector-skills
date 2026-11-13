import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL/'scripts'))
from build_viewer import build
from test_build_viewer import scene_from_html


@unittest.skipUnless(importlib.util.find_spec('OCP'), 'Open CASCADE is optional')
class CadTests(unittest.TestCase):
    def test_tessellated_box_and_sheet_faces(self):
        from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
        from OCP.BRepTools import BRepTools
        from OCP.IGESControl import IGESControl_Writer
        from OCP.STEPControl import STEPControl_Writer, STEPControl_AsIs
        from OCP.IFSelect import IFSelect_RetDone
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            box = BRepPrimAPI_MakeBox(3, 5, 7).Shape()
            self.assertTrue(BRepTools.Write_s(box, str(root/'cube.brep')))
            iges = IGESControl_Writer(); iges.AddShape(box)
            self.assertTrue(iges.Write(str(root/'cube.iges')))
            step = STEPControl_Writer(); step.Transfer(box, STEPControl_AsIs)
            self.assertEqual(step.Write(str(root/'cube.step')), IFSelect_RetDone)
            for source in sorted(root.glob('cube.*')):
                with self.subTest(suffix=source.suffix):
                    target = root/'preview.html'
                    result = build(source, target)
                    self.assertEqual((result['runtimeProfile'], result['triangles']), ('mesh', 12))
                    asset = scene_from_html(target)
                    self.assertEqual(asset['bounds'], {'min':[0,0,-5], 'max':[3,7,0]})
