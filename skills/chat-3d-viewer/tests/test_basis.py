import base64
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'scripts'))
from basis_gltf import EXTENSION, png_texture
from gltf_scene import prepare_gltf


class BasisTests(unittest.TestCase):
    # Original 8x8 image of three colored squares with different alpha.
    # Encoded using basisu 1.16.3 -ktx2 -q 255, no third-party sample data.
    image = (HERE/'fixtures/rgba8.ktx2').read_bytes()

    def test_etc1s_rgb_alpha_and_orientation(self):
        image = Image.open(io.BytesIO(png_texture(self.image, 8)))
        self.assertEqual(image.size, (8,8))
        for xy, expected in [((0,0),(240,25,15,36)), ((7,7),(20,25,230,213)), ((1,7),(15,212,20,123))]:
            self.assertTrue(all(abs(a-b) < 4 for a,b in zip(image.getpixel(xy), expected)))
        self.assertEqual(Image.open(io.BytesIO(png_texture(self.image, 4))).size, (4,4))

    def test_embedded_bin_view_replaced_once_for_shared_source(self):
        model = dict(asset={'version':'2.0'}, extensionsRequired=[EXTENSION], extensionsUsed=[EXTENSION],
                     buffers=[{'uri':'data:application/octet-stream;base64,'+base64.b64encode(self.image).decode(),
                               'byteLength':len(self.image)}],
                     bufferViews=[{'buffer':0,'byteOffset':0,'byteLength':len(self.image)}],
                     images=[{'bufferView':0, 'mimeType':'image/ktx2'}],
                     textures=[{'extensions':{EXTENSION:{'source':0}}} for _ in range(2)])
        with tempfile.TemporaryDirectory() as out:
            path = Path(out)/'test.gltf'
            path.write_text(json.dumps(model))
            glb, stats = prepare_gltf(path)
        n = struct.unpack_from('<I',glb,12)[0]
        doc = json.loads(glb[20:20+n])
        self.assertEqual(doc['textures'],[{'source':0},{'source':0}])
        self.assertNotIn('extensionsRequired',doc)
        self.assertEqual(doc['images'][0]['mimeType'],'image/png')
        self.assertNotIn(self.image, glb)
        self.assertIsNone(stats)
        self.assertEqual(len(doc['bufferViews']),1)
        self.assertEqual(Image.open(io.BytesIO(glb[28+n:])).getpixel((0,0)),(240,25,17,36))

    def test_optional_extension_uses_supplied_core_image_without_decoder(self):
        png = io.BytesIO()
        Image.new('RGB',(4,4),'teal').save(png,'PNG')
        model = dict(asset={'version':'2.0'}, extensionsUsed=[EXTENSION],
                     images=[{'uri':'data:image/png;base64,'+base64.b64encode(png.getvalue()).decode()},
                             {'uri':'data:image/ktx2;base64,'+base64.b64encode(self.image).decode()}],
                     textures=[{'source':0,'extensions':{EXTENSION:{'source':1}}}])
        with tempfile.TemporaryDirectory() as out, patch('basis_gltf.png_texture',side_effect=AssertionError):
            path = Path(out)/'optional.gltf'
            path.write_text(json.dumps(model))
            glb, _ = prepare_gltf(path)
        n = struct.unpack_from('<I',glb,12)[0]
        self.assertEqual(json.loads(glb[20:20+n])['textures'],[{'source':0}])

    def test_malformed_payload_fails_at_export(self):
        with self.assertRaisesRegex(ValueError,'KTX2 container'):
            png_texture(b'bad',8)
        with self.assertRaisesRegex(ValueError,'KTX2/Basis transcoding failed'):
            png_texture(self.image[:82],8)
