"""Round-trip real Draco bytes through the source converter and HTML builder."""
import base64
import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from build_viewer import build
from gltf_scene import prepare_gltf
from draco_gltf import EXTENSION
from test_build_viewer import scene_from_html

try:
    import DracoPy
except ImportError:
    DracoPy = None


@unittest.skipIf(DracoPy is None, 'DracoPy optional dependency')
class DracoTests(unittest.TestCase):
    def test_colors_uv_indices_skin_and_mesh_profile(self):
        pos = np.array([[0.,0,0],[1,0,0],[1,1,0],[0,1,0]])
        faces = np.array([[0,1,2],[0,2,3]])
        uv = pos[:,:2].copy()
        color = np.array([[9,17,3,255],[4,33,16,40],[7,8,9,20],[10,11,12,50]], dtype='u1')
        joints = np.tile(np.array([[1,0,0,0]], dtype='u2'), (4,1))
        weights = np.tile([[.75,.25,0.,0.]], (4,1))
        encoded = DracoPy.encode(pos, faces, colors=color, tex_coord=uv,
                                 generic_attributes={8:joints, 14:weights}, preserve_order=True)
        decoded = DracoPy.decode(encoded)
        accessors = []
        attributes, ids = {}, {}
        sources = [
            ('POSITION', pos, 5126, decoded.get_attribute_by_type(0)['unique_id']),
            ('TEXCOORD_0', uv, 5126, decoded.get_attribute_by_type(3)['unique_id']),
            ('COLOR_0', color, 5121, decoded.get_attribute_by_type(2)['unique_id']),
            ('JOINTS_0', joints, 5123, 8), ('WEIGHTS_0', weights, 5126, 14)]
        for name, values, component, attrib_id in sources:
            attributes[name] = len(accessors)
            ids[name] = attrib_id
            accessors.append(dict(count=4,type='VEC'+str(values.shape[1]),componentType=component))
        accessors[2]['normalized'] = True
        accessors[0].update(min=pos.min(axis=0).tolist(), max=pos.max(axis=0).tolist())
        accessors.append(dict(count=6,type='SCALAR',componentType=5123))
        primitive = dict(attributes=attributes,indices=5,extensions={EXTENSION:dict(bufferView=0,attributes=ids)})
        doc = dict(asset=dict(version='2.0'), buffers=[dict(byteLength=len(encoded),uri='mesh.bin')],
                   bufferViews=[dict(buffer=0,byteLength=len(encoded))], accessors=accessors,
                   meshes=[dict(primitives=[primitive])], nodes=[dict(mesh=0,skin=0),dict(children=[2]),{}],
                   scene=0, scenes=[dict(nodes=[0,1])], skins=[dict(joints=[1,2])],
                   extensionsUsed=[EXTENSION], extensionsRequired=[EXTENSION])
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)
            path=folder/'mesh.gltf'
            path.write_text(json.dumps(doc))
            (folder/'mesh.bin').write_bytes(encoded)
            packed, stats = prepare_gltf(path)
            self.assertEqual(stats['triangles'],2)
            size = struct.unpack_from('<I', packed, 12)[0]
            plain = json.loads(packed[20:20+size])
            binary = packed[28+size:]
            self.assertNotIn(EXTENSION, json.dumps(plain))
            self.assertNotIn(encoded, binary)
            prim = plain['meshes'][0]['primitives'][0]
            self.assertTrue(plain['accessors'][prim['attributes']['COLOR_0']]['normalized'])
            def read(index, dtype, shape):
                accessor = plain['accessors'][index]
                view = plain['bufferViews'][accessor['bufferView']]
                return np.frombuffer(binary[view['byteOffset']:][:view['byteLength']], dtype).reshape(shape)
            for name, values, component, _ in sources:
                actual = read(prim['attributes'][name], {5126:'<f4',5121:'u1',5123:'<u2'}[component], values.shape)
                np.testing.assert_allclose(actual, values, atol=.001)
            np.testing.assert_array_equal(read(prim['indices'],'<u2',(2,3)), faces)
            result = build(path, folder/'animated.html')
            self.assertEqual(result['runtimeProfile'],'gltf')
            self.assertEqual(scene_from_html(folder/'animated.html')['original']['triangles'],2)
            del doc['skins']
            del doc['nodes'][0]['skin']
            for semantic in ('JOINTS_0','WEIGHTS_0','TEXCOORD_0'):
                del attributes[semantic]
                del ids[semantic]
            path.write_text(json.dumps(doc))
            result = build(path, folder/'static.html')
            self.assertEqual((result['runtimeProfile'],result['triangles']),('mesh',2))
            mesh = scene_from_html(folder/'static.html')['meshes'][0]
            proxy_positions = np.frombuffer(base64.b64decode(mesh['positions']),'<f4').reshape(-1,3)
            self.assertGreater(float(np.ptp(proxy_positions[:,0])),.9)
            self.assertIn('colors', mesh)
            uncompressed_colors = np.frombuffer(base64.b64decode(mesh['colors']),'u1').reshape(-1,4)
            np.testing.assert_array_equal(uncompressed_colors, color)
            primitive['mode'] = 5
            path.write_text(json.dumps(doc))
            with self.assertRaisesRegex(ValueError, 'triangle-strip'):
                build(path, folder/'strip.html')
