"""Read fixed-row SPLAT and GraphDECO PLY, keeping complete sampled records."""
import base64
import numpy as np

REQUIRED = (['x', 'y', 'z'] + [f'scale_{i}' for i in range(3)]
            + [f'rot_{i}' for i in range(4)] + [f'f_dc_{i}' for i in range(3)] + ['opacity'])
SH_REST_COUNTS = (0, 9, 24, 45)
SPLAT_ROW = np.dtype([('position', '<f4', 3), ('scale', '<f4', 3),
                      ('rgba', 'u1', 4), ('rotation', 'u1', 4)])


def gaussian_ply(path):
    """Only claim scalar Gaussian vertex attributes, never a regular PLY mesh."""
    fields = set()
    element = None
    with path.open('rb') as stream:
        while stream.tell() < 1024 * 1024:
            line = stream.readline(4096)
            if not line:
                break
            parts = line.split()
            if parts[:1] == [b'element'] and len(parts) == 3:
                element = parts[1]
                if element == b'face' and int(parts[2]) > 0:
                    return False
            if parts[:1] == [b'property'] and element == b'vertex' and len(parts) == 3:
                fields.add(parts[2])
            if parts == [b'end_header']:
                return all(name.encode() in fields for name in REQUIRED)
    return False


def selection(count, limit):
    if count < 1:
        raise ValueError('Gaussian model has no splats')
    if count <= limit:
        return slice(None)
    return np.linspace(0, count - 1, limit, dtype=np.int64)


def ply_rows(path, limit):
    from trimesh.exchange.ply import load_ply
    with path.open('rb') as stream:
        vertex = load_ply(stream, skip_materials=True)['metadata']['_ply_raw']['vertex']
    source = vertex['data']
    count = vertex['length']
    take = selection(count, limit)
    rest = {key for key in vertex['properties'] if key.startswith('f_rest_')}
    n = len(rest)
    if n not in SH_REST_COUNTS or rest != {f'f_rest_{i}' for i in range(n)}:
        raise ValueError('Expected consecutive SH coefficients of degree 0, 1, 2 or 3')
    names = REQUIRED + [f'f_rest_{i}' for i in range(n)]
    # A compact, standard binary PLY carries precisely the fields the official
    # loader consumes, independent of the input endianness or ASCII encoding.
    rows = np.column_stack([np.asarray(source[key]).reshape(count)[take] for key in names]).astype('<f4')
    if not np.isfinite(rows).all():
        raise ValueError('Gaussian PLY attributes must be finite')
    scales = np.exp(rows[:, 3:6].astype(np.float64))
    rgb = np.rint(np.clip(.5 + .28209479177387814 * rows[:, 10:13], 0, 1) * 255)
    opacity = 255 / (1 + np.exp(-np.clip(rows[:, 13].astype(np.float64), -700, 700)))
    rgba = np.column_stack((rgb, np.rint(opacity))).astype('u1')
    header = ('ply\nformat binary_little_endian 1.0\nelement vertex ' + str(len(rows)) + '\n'
              + ''.join(f'property float {name}\n' for name in names) + 'end_header\n')
    return count, rows[:, :3], scales, rgba, header.encode() + rows.tobytes(), SH_REST_COUNTS.index(n)


def fixed_rows(path, limit):
    size = path.stat().st_size
    if not size or size % SPLAT_ROW.itemsize:
        raise ValueError('Expected complete 32-byte Gaussian SPLAT records')
    count = size // SPLAT_ROW.itemsize
    records = np.memmap(path, dtype=SPLAT_ROW, mode='r')
    rows = records[selection(count, limit)]
    return count, rows['position'], rows['scale'], rows['rgba'], rows.tobytes(), 0


def read_splats(path, limit, native):
    is_ply = path.suffix.lower() == '.ply'
    count, centers, scales, rgba, data, degree = (ply_rows if is_ply else fixed_rows)(path, limit)
    if (not np.isfinite(centers).all() or not np.isfinite(scales).all()
            or np.any(scales < 0) or np.max(scales) > np.sqrt(np.finfo('f4').max)):
        raise ValueError('Invalid Gaussian center or covariance scale')
    # Extend each center by two standard deviations along its largest axis.
    # This bounds every rotated ellipsoid, including single-splat scenes.
    radius = 2 * np.max(scales.astype(np.float64), axis=1, keepdims=True)
    bounds = ((centers - radius).min(axis=0), (centers + radius).max(axis=0))
    from build_viewer import finalize_scene, point_object
    mesh = point_object(path.stem, centers, rgba, limit)
    material = dict(name='Gaussian color and opacity', baseColor=[1,1,1,1], alphaMode='BLEND')
    scene = finalize_scene(path.stem, 'Gaussian PLY' if is_ply else 'SPLAT', [mesh], [material], [],
                           description='Gaussian splats' if native else 'Gaussian centers',
                           previewType='gaussian' if native else 'points', unit='model',
                           fixed_bounds=bounds, original=dict(vertices=count, triangles=0))
    scene['shDegree'] = degree
    if native:
        scene['nativeSplat'] = dict(profile='splat-ply' if is_ply else 'splat',
                                    bytes=base64.b64encode(data).decode('ascii'))
    return scene
