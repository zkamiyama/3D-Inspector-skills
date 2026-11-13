import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(SKILL/'scripts'), str(SKILL.parents[1]/'tests')]
from gltf_scene import native_gltf_payload
from make_previews import animated_fixture
from build_viewer import build
from test_build_viewer import scene_from_html


class NativeGltfTests(unittest.TestCase):
    def test_motion_resources_and_compact_fallback(self):
        import base64
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            gltf = animated_fixture(out)
            result = build(gltf, out/'motion.html', max_triangles=1)
            self.assertEqual((result['runtimeProfile'],result['triangles']), ('gltf',428))
            self.assertLess(result['fallbackTriangles'], 10)
            asset = scene_from_html(out/'motion.html')['nativeGltf']
            glb = base64.b64decode(asset['glb'])
            length = struct.unpack_from('<I', glb, 12)[0]
            doc = json.loads(glb[20:20+length])
            self.assertEqual(doc['animations'][0]['name'], 'Pulse')
            self.assertNotIn('uri', doc['buffers'][0])
            self.assertTrue(all('bufferView' in im for im in doc['images']))
            (out/'motion.glb').write_bytes(glb)
            self.assertEqual(native_gltf_payload(out/'motion.glb')['stats'], asset['stats'])

    def test_static_uses_mesh_profile_and_validates_local_companions(self):
        self.assertIsNone(native_gltf_payload(SKILL/'tests/fixtures/material_study.glb'))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'model.gltf'
            for uri in ('https://example.test/model.bin', '../other.bin', 'missing.bin'):
                path.write_text(json.dumps({'buffers':[{'uri':uri,'byteLength':4}]}))
                with self.assertRaisesRegex(ValueError, 'resource'):
                    native_gltf_payload(path)
