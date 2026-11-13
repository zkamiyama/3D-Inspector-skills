"""Expand KHR_draco_mesh_compression before the model reaches the browser."""
import numpy as np

EXTENSION = 'KHR_draco_mesh_compression'
DTYPES = {5120:'i1', 5121:'u1', 5122:'<i2', 5123:'<u2', 5125:'<u4', 5126:'<f4'}
WIDTHS = {'SCALAR':1, 'VEC2':2, 'VEC3':3, 'VEC4':4}


def expand(doc, merged, append):
    primitives = [p for mesh in doc.get('meshes', []) for p in mesh.get('primitives', [])
                  if EXTENSION in p.get('extensions', {})]
    if not primitives:
        return
    accessors = doc['accessors']
    views = doc['bufferViews']
    compressed_views = {p['extensions'][EXTENSION]['bufferView'] for p in primitives}
    if EXTENSION not in doc.get('extensionsRequired', []):
        # A conforming optional extension supplies equivalent uncompressed bytes.
        use_plain = all(
            'bufferView' in accessors[index] or 'sparse' in accessors[index]
            for p in primitives for index in [*p['attributes'].values(), *([p['indices']] if 'indices' in p else [])])
        if use_plain:
            for p in primitives:
                p['extensions'].pop(EXTENSION)
            primitives = []

    def write_accessor(definition, values, target):
        # Do not change an existing accessor that another primitive might share.
        accessor = dict(definition)
        size = WIDTHS[accessor['type']]
        dtype = np.dtype(DTYPES[accessor['componentType']])
        data = np.asarray(values)
        if data.shape != (accessor['count'], size) or not data.size or not np.isfinite(data).all():
            raise ValueError('Draco geometry disagrees with its glTF accessor')
        if dtype.kind in 'iu':
            limits = np.iinfo(dtype)
            if data.min() < limits.min or data.max() > limits.max or (
                    data.dtype.kind == 'f' and not np.equal(data, np.trunc(data)).all()):
                raise ValueError('Draco integer attribute exceeds its glTF component type')
        typed = np.asarray(data, dtype=dtype)
        if target == 34962 and typed.strides[0] % 4:
            # glTF vertex attributes must start on four-byte boundaries, even
            # when tightly packed RGB bytes or halfword triples would not.
            packed = np.zeros((len(typed), (typed.dtype.itemsize * size + 3) // 4 * 4), dtype='u1')
            packed[:, :typed.dtype.itemsize * size] = np.ascontiguousarray(typed).view('u1').reshape(len(typed), -1)
            raw = packed.tobytes()
            stride = packed.shape[1]
        else:
            raw = typed.tobytes()
            stride = None
        offset = append(raw)
        accessor.update(bufferView=len(views), byteOffset=0)
        accessor.pop('sparse', None)
        for name, reduction in [('min', np.min), ('max', np.max)]:
            if name in accessor:
                accessor[name] = reduction(typed, axis=0).tolist()
        views.append(dict(buffer=0, byteOffset=offset, byteLength=len(raw), target=target))
        if stride is not None:
            views[-1]['byteStride'] = stride
        accessors.append(accessor)
        return len(accessors) - 1

    if primitives:
        try:
            from DracoPy import decode
        except ImportError as exc:
            from viewer_dependencies import MissingViewerDependency
            raise MissingViewerDependency('DracoPy') from exc
    for primitive in primitives:
        if primitive.get('mode', 4) != 4:
            raise ValueError('Draco triangle-strip primitives are unsupported; export TRIANGLES')
        ext = primitive['extensions'].pop(EXTENSION)
        view = views[ext['bufferView']]
        offset = view.get('byteOffset', 0)
        mesh = decode(bytes(merged[offset:offset + view['byteLength']]))
        attrs = primitive['attributes']
        for semantic, unique_id in ext['attributes'].items():
            attr = mesh.get_attribute_by_unique_id(unique_id)
            if attr is None or attr.get('data') is None:
                raise ValueError(f'Missing Draco attribute {semantic} (ID {unique_id})')
            attrs[semantic] = write_accessor(accessors[attrs[semantic]], attr['data'], 34962)
        faces = getattr(mesh, 'faces', None)
        if faces is None or not faces.size or faces.min() < 0 or faces.max() >= accessors[attrs['POSITION']]['count']:
            raise ValueError('Invalid Draco triangle indices')
        index_def = (accessors[primitive['indices']] if 'indices' in primitive else
                     dict(componentType=5125, type='SCALAR', count=faces.size))
        primitive['indices'] = write_accessor(index_def, faces.reshape(-1, 1), 34963)

    for key in ('extensionsUsed', 'extensionsRequired'):
        if EXTENSION in doc.get(key, []):
            doc[key].remove(EXTENSION)
            if not doc[key]:
                del doc[key]

    # Repack the original compressed buffer views. Keep every other view at
    # its existing index so sparse accessors, morph targets, images and
    # extension-specific references continue to resolve. A one-byte stub
    # keeps view indices valid without shipping duplicate compressed bytes.
    def referenced_views(obj):
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key == 'bufferView' and isinstance(value, int):
                    yield value
                else:
                    yield from referenced_views(value)
        elif isinstance(obj, list):
            for value in obj:
                yield from referenced_views(value)

    discard = compressed_views.difference(referenced_views(doc))
    if discard:
        original = bytes(merged)
        merged.clear()
        for index, view in enumerate(views):
            start = view.get('byteOffset', 0)
            data = b'\0' if index in discard else original[start:start + view['byteLength']]
            view.update(byteOffset=append(data), byteLength=len(data))
