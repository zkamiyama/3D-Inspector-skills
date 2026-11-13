import base64
import io
from pathlib import Path
import struct
import sys
import tempfile
import unittest

import numpy as np
from trimesh.exchange.ply import load_ply

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from splat_scene import REQUIRED, SPLAT_ROW, gaussian_ply, read_splats
from build_viewer import build


class SplatTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_splat_decimation_keeps_whole_records_and_bounds(self):
        path = self.root / 'model.splat'
        records = np.zeros(6, SPLAT_ROW)
        records['position'][:, 0] = np.arange(6)
        records['scale'] = [.1, .5, .2]
        records['rgba'] = np.arange(24, dtype='u1').reshape(6, 4)
        records['rotation'] = [255, 128, 128, 128]
        path.write_bytes(records.tobytes())
        sample = read_splats(path, 3, True)
        self.assertEqual(sample['original']['vertices'], 6)
        self.assertEqual(base64.b64decode(sample['nativeSplat']['bytes']), records[[0, 2, 5]].tobytes())
        np.testing.assert_allclose(sample['bounds']['min'], [-1, -1, -1])
        np.testing.assert_allclose(sample['bounds']['max'], [6, 1, 1])
        self.assertEqual(sample['meshes'][0]['primitive'], 'points')
        self.assertEqual(base64.b64decode(sample['meshes'][0]['colors']), records['rgba'][[0,2,5]].tobytes())
        self.assertNotIn('nativeSplat', read_splats(path, 3, False))
        stats = build(path, self.root/'viewer.html', max_points=3, runtime_source='cdn')
        self.assertEqual((stats['runtimeProfile'],stats['vertices'],stats['triangles']), ('splat',3,0))
        viewer = (self.root/'viewer.html').read_text()
        self.assertIn('SPLATLoader.js', viewer)
        self.assertNotIn('GaussianSplatPLYLoader.js', viewer)
        self.assertNotIn('three-impostor@', viewer)

    def test_ply_decimation_preserves_higher_order_sh_and_opacity(self):
        path = self.root / 'model.ply'
        fields = REQUIRED + [f'f_rest_{i}' for i in range(45)]
        header = 'ply\nformat binary_big_endian 1.0\nelement vertex 5\n' + ''.join(
            f'property float {f}\n' for f in fields) + 'end_header\n'
        rows = np.zeros((5, len(fields)), dtype='>f4')
        rows[:, 0] = np.arange(5)
        rows[:, 6] = 1
        rows[:, 13] = [-2,-1,0,1,2]
        rows[:, 14:] = np.linspace(-.8, .8, 225).reshape(5,45)
        path.write_bytes(header.encode() + rows.tobytes())
        self.assertTrue(gaussian_ply(path))
        out = read_splats(path, 2, True)
        self.assertEqual(out['shDegree'], 3)
        blob = base64.b64decode(out['nativeSplat']['bytes'])
        vertex = load_ply(io.BytesIO(blob))['metadata']['_ply_raw']['vertex']
        for i, key in enumerate(fields):
            np.testing.assert_array_equal(vertex['data'][key].ravel(), rows[[0,4], i])
        stats = build(path, self.root/'viewer.html', max_points=2, runtime_source='cdn')
        self.assertEqual(stats['runtimeProfile'], 'splat-ply')
        viewer = (self.root/'viewer.html').read_text()
        self.assertIn('GaussianSplatPLYLoader.js', viewer)
        self.assertNotIn('/SPLATLoader.js', viewer)

    def test_corrupt_splat_rejected(self):
        path = self.root / 'model.splat'
        path.write_bytes(b'bad')
        with self.assertRaisesRegex(ValueError, '32-byte'):
            read_splats(path, 4, True)
        path.write_bytes(struct.pack('<6f8B', 0,0,0, 1,-1,1, *(255,) * 8))
        with self.assertRaisesRegex(ValueError, 'scale'):
            read_splats(path, 4, True)
