"""Generate deterministic browser acceptance inputs, including textured animated glTF."""
import json
import math
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'skills/chat-3d-viewer'
sys.path.insert(0, str(SKILL / 'scripts'))
from build_viewer import build
from gltf_scene import _document


def animated_fixture(out):
    document, binary = _document(SKILL / 'tests/fixtures/material_study.glb')
    data = bytearray(binary)
    def accessor(values, shape, count, **limits):
        data.extend(b'\0' * (-len(data) % 4))
        packed = struct.pack('<' + str(len(values)) + 'f', *values)
        view = len(document['bufferViews'])
        document['bufferViews'].append(dict(buffer=0, byteOffset=len(data), byteLength=len(packed)))
        data.extend(packed)
        document['accessors'].append(dict(bufferView=view, componentType=5126, count=count, type=shape, **limits))
        return len(document['accessors']) - 1
    times = accessor([0, .5, 1], 'SCALAR', 3, min=[0], max=[1])
    scales = accessor([1,1,1, .35,1.8,.35, 1,1,1], 'VEC3', 3)
    node = next(i for i, n in enumerate(document['nodes']) if 'mesh' in n)
    document['animations'] = [dict(name='Pulse', samplers=[dict(input=times, output=scales)],
        channels=[dict(sampler=0, target=dict(node=node, path='scale'))])]
    document['buffers'] = [dict(uri='motion.bin', byteLength=len(data))]
    path = out / 'animated.gltf'
    (out / 'motion.bin').write_bytes(data)
    path.write_text(json.dumps(document))
    return path


def splat_fixtures(out):
    # One anisotropic Gaussian rotated 90 degrees about Z: from the front its
    # long axis must stand vertically, and from above it becomes a small disc.
    splat = out / 'gaussian.splat'
    splat.write_bytes(struct.pack('<6f8B', 0, 0, 0, .45, .045, .045,
                                  220, 100, 60, 240, 218, 128, 128, 218))
    ply = out / 'gaussian.ply'
    fields = ('x y z scale_0 scale_1 scale_2 rot_0 rot_1 rot_2 rot_3 '
              'f_dc_0 f_dc_1 f_dc_2 opacity').split() + [f'f_rest_{i}' for i in range(9)]
    values = [0, 0, 0, math.log(.45), math.log(.045), math.log(.045),
              .70710678, 0, 0, .70710678, 1., .5, .2, 4.] + [.1] * 9
    ply.write_text('ply\nformat ascii 1.0\nelement vertex 1\n'
                   + ''.join(f'property float {key}\n' for key in fields)
                   + 'end_header\n' + ' '.join(map(str, values)) + '\n')
    return [(splat, 'gaussian'), (ply, 'gaussian-ply')]


if __name__ == '__main__':
    out = ROOT / '.test-output'
    out.mkdir(exist_ok=True)
    cloud = out / 'cloud.xyz'
    cloud.write_text(''.join(f'{math.cos(a*.1)*math.sin(b*.05)} {math.cos(b*.05)} {math.sin(a*.1)*math.sin(b*.05)} 100 200 220\n' for a in range(63) for b in range(64)))
    for path, name in [*splat_fixtures(out), (animated_fixture(out),'animated'), (cloud, 'cloud'),
            (SKILL/'tests/fixtures/synthetic.box.zip','synthetic-native'),
            (SKILL/'tests/fixtures/material_study.glb','material-native')]:
        print(build(path, out/(name+'.html'))['file'])
