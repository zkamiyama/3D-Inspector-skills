"""Codec fixture produced by meshoptimizer 1.1 MeshoptEncoder.encodeGltfBuffer."""
import base64
import json
import shutil
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from build_viewer import build
from gltf_scene import prepare_gltf
from test_build_viewer import scene_from_html

POSITION = base64.b64decode('oAAAATMAAAD//wEzAAAAfn0AAAEMAAAA/wEMAAAAfgAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA==')
INDEX = base64.b64decode('4fAAAHaHVmd4qYZliWiYAWkAAA==')
POINTS = np.array([[0,0,0],[1,0,0],[1,1,0],[0,1,0]], dtype='<f4')
FACES = np.array([0,1,2,0,2,3], dtype='<u2')


def fixture(directory, ext):
    (directory/'compressed.bin').write_bytes(POSITION + INDEX)
    doc = dict(asset=dict(version='2.0'), scene=0, scenes=[dict(nodes=[0])], nodes=[dict(mesh=0)],
               meshes=[dict(primitives=[dict(attributes={'POSITION':0},indices=1)])],
               accessors=[dict(bufferView=0,componentType=5126,type='VEC3',count=4,min=[0,0,0],max=[1,1,0]),
                          dict(bufferView=1,componentType=5123,type='SCALAR',count=6)],
               buffers=[dict(byteLength=len(POSITION+INDEX),uri='compressed.bin'),dict(byteLength=60)],
               bufferViews=[], extensionsUsed=[ext],extensionsRequired=[ext])
    start = fallback = 0
    for data, count, stride, mode in ((POSITION,4,12,'ATTRIBUTES'),(INDEX,6,2,'TRIANGLES')):
        length = count * stride
        encoded = dict(buffer=0,byteOffset=start,byteLength=len(data),byteStride=stride,count=count,mode=mode)
        doc['bufferViews'].append(dict(buffer=1,byteOffset=fallback,byteLength=length,extensions={ext:encoded}))
        start += len(data)
        fallback += length
    return doc


class MeshoptTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'),'Node.js required for meshopt source decoding')
    def test_required_meshopt(self):
        for ext in ('KHR_meshopt_compression', 'EXT_meshopt_compression'):
            with self.subTest(ext=ext), tempfile.TemporaryDirectory() as folder:
                root=Path(folder)
                doc=fixture(root,ext)
                path=root/'quad.gltf'
                path.write_text(json.dumps(doc))
                packed, stats = prepare_gltf(path)
                self.assertIsNone(stats)
                size = struct.unpack_from('<I',packed,12)[0]
                self.assertNotIn(ext.encode(), packed[:20+size])
                np.testing.assert_array_equal(np.frombuffer(packed[28+size:][:48],'<f4').reshape(-1,3),POINTS)
                np.testing.assert_array_equal(np.frombuffer(packed[-12:],'<u2'),FACES)
                result=build(path,root/'quad.html')
                self.assertEqual((result['runtimeProfile'],result['triangles']),('mesh',2))
                raw=scene_from_html(root/'quad.html')['meshes'][0]['positions']
                np.testing.assert_array_equal(np.frombuffer(base64.b64decode(raw),'<f4').reshape(-1,3),POINTS)
                doc['bufferViews'][0]['extensions'][ext]['count']=5
                path.write_text(json.dumps(doc))
                with self.assertRaisesRegex(ValueError,'stride'):
                    prepare_gltf(path)

    def test_fallback_geometry_requires_no_node(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            doc = fixture(root,'EXT_meshopt_compression')
            del doc['extensionsRequired']
            doc['buffers'][1]['uri'] = 'fallback.bin'
            (root/'fallback.bin').write_bytes(POINTS.tobytes() + FACES.tobytes())
            path = root/'quad.gltf'
            path.write_text(json.dumps(doc))
            with patch('shutil.which',return_value=None):
                result = build(path,root/'quad.html')
            self.assertEqual(result['triangles'],2)
