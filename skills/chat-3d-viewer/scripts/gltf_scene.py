"""Pack glTF scenes that need their node hierarchy into a self-contained GLB."""
import base64
import json
import mimetypes
import struct
from pathlib import Path
from urllib.parse import unquote, unquote_to_bytes, urlsplit

MAX_BYTES = 512 * 1024 * 1024
JSON_CHUNK = 0x4E4F534A
BIN_CHUNK = 0x004E4942


def _document(path):
    if path.stat().st_size > MAX_BYTES:
        raise ValueError('glTF exceeds 512 MiB')
    raw = path.read_bytes()
    if path.suffix.lower() == '.gltf':
        return json.loads(raw), b''
    if len(raw) < 20 or struct.unpack_from('<4sII', raw) != (b'glTF', 2, len(raw)):
        raise ValueError('Invalid GLB header')
    offset, document, binary = 12, None, b''
    while offset < len(raw):
        length, kind = struct.unpack_from('<II', raw, offset)
        offset += 8
        if offset + length > len(raw):
            raise ValueError('Truncated GLB chunk')
        if kind == JSON_CHUNK:
            document = json.loads(raw[offset:offset + length])
        elif kind == BIN_CHUNK:
            binary = raw[offset:offset + length]
        offset += length
    if not isinstance(document, dict):
        raise ValueError('GLB contains no JSON document')
    return document, binary


def _local_resource(uri, directory):
    parts = urlsplit(uri)
    name = unquote(parts.path)
    if parts.scheme or parts.netloc or parts.query or parts.fragment or '\\' in name or Path(name).is_absolute():
        raise ValueError(f'Expected a relative local glTF resource: {uri[:120]}')
    path = (directory / name).resolve()
    if not path.is_relative_to(directory) or not path.is_file():
        raise ValueError(f'Missing or out-of-directory glTF resource: {uri[:120]}')
    return path


def _resource(uri, directory, remaining):
    if uri.startswith('data:'):
        header, sep, data = uri.partition(',')
        if not sep:
            raise ValueError('Invalid glTF data URI')
        raw = base64.b64decode(data, validate=True) if header.endswith(';base64') else unquote_to_bytes(data)
        mime = header[5:].split(';')[0]
    else:
        file = _local_resource(uri, directory)
        if file.stat().st_size > remaining:
            raise ValueError('glTF resources exceed 512 MiB')
        raw = file.read_bytes()
        mime = mimetypes.guess_type(file.name)[0]
    if len(raw) > remaining:
        raise ValueError('glTF resources exceed 512 MiB')
    return raw, mime


def _scene_counts(doc):
    nodes, counts = doc.get('nodes', []), dict(meshes=0, vertices=0, triangles=0)
    scenes = doc.get('scenes', [])
    pending = list(scenes[doc.get('scene', 0)].get('nodes', [])) if scenes else []
    seen = set()
    while pending:
        index = pending.pop()
        if index in seen:
            raise ValueError('Duplicate or cyclic node in glTF scene')
        seen.add(index)
        node = nodes[index]
        pending.extend(node.get('children', []))
        if 'mesh' not in node:
            continue
        for primitive in doc['meshes'][node['mesh']]['primitives']:
            vertices = doc['accessors'][primitive['attributes']['POSITION']]['count']
            elements = doc['accessors'][primitive['indices']]['count'] if 'indices' in primitive else vertices
            mode = primitive.get('mode', 4)
            counts['meshes'] += 1
            counts['vertices'] += vertices
            counts['triangles'] += elements // 3 if mode == 4 else max(0, elements - 2) if mode in (5, 6) else 0
    return counts


def prepare_gltf(path, max_texture=2048):
    """Return packed bytes for conversion, and whether the native glTF runtime is needed."""
    from draco_gltf import EXTENSION as DRACO, expand
    from meshopt_gltf import NAMES as MESHOPT, decode_views
    doc, binary = _document(path)
    resources = [*doc.get('buffers', []), *doc.get('images', [])]
    for entry in resources:
        uri = entry.get('uri')
        if uri and not uri.startswith('data:'):
            _local_resource(uri, path.parent)
    from basis_gltf import EXTENSION as BASIS, basis_images, png_texture
    basis = any(BASIS in t.get('extensions', {}) for t in doc.get('textures', []))
    transcode = basis_images(doc) if basis else set()
    morphs = any(p.get('targets') for m in doc.get('meshes', []) for p in m.get('primitives', []))
    rich_material = any(k.startswith('KHR_materials_') for k in doc.get('extensionsUsed', []))
    native = bool(doc.get('animations') or doc.get('skins') or morphs or rich_material)
    draco = any(DRACO in p.get('extensions', {}) for mesh in doc.get('meshes', []) for p in mesh.get('primitives', []))
    meshopt = any(any(name in view.get('extensions', {}) for name in MESHOPT) for view in doc.get('bufferViews', []))
    if not (native or draco or meshopt or basis):
        return None, None

    merged = bytearray()
    buffers = []
    def append(data):
        merged.extend(b'\0' * (-len(merged) % 4))
        start = len(merged)
        if start + len(data) > MAX_BYTES:
            raise ValueError('glTF resources exceed 512 MiB')
        merged.extend(data)
        return start

    total = 0
    for i, buffer in enumerate(doc.get('buffers', [])):
        if 'uri' in buffer:
            data = _resource(buffer['uri'], path.parent, MAX_BYTES - total)[0]
        else:
            data = binary if i == 0 and binary else None
        length = buffer['byteLength']
        if data is None and meshopt:
            buffers.append(None)  # Missing backing storage for an extension-defined fallback.
            continue
        if data is None or length < 0 or length > len(data) or total + length > MAX_BYTES:
            raise ValueError('glTF buffer length mismatch or combined buffers exceed 512 MiB')
        buffers.append(memoryview(data)[:length])
        total += length
    decoded = decode_views(doc, buffers, MAX_BYTES) if meshopt else {}
    views = doc.setdefault('bufferViews', [])
    image_views = {doc['images'][i]['bufferView'] for i in transcode if 'bufferView' in doc['images'][i]}
    for index, view in enumerate(views):
        if index in decoded:
            data = decoded.pop(index)
        else:
            src = buffers[view['buffer']]
            offset, length = view.get('byteOffset', 0), view['byteLength']
            if src is None or offset < 0 or length < 0 or offset + length > len(src):
                raise ValueError('glTF buffer view is out of range')
            data = src[offset:offset + length]
        if index in image_views:
            data = png_texture(bytes(data), max_texture)
            view['byteLength'] = len(data)
        view.update(buffer=0, byteOffset=append(data))
        for name in MESHOPT:
            view.get('extensions', {}).pop(name, None)
    for i, image in enumerate(doc.get('images', [])):
        if 'uri' in image:
            data, mime = _resource(image.pop('uri'), path.parent, MAX_BYTES - len(merged))
            if i in transcode:
                data = png_texture(data, max_texture)
            image['bufferView'] = len(views)
            image['mimeType'] = image.get('mimeType') or mime
            views.append(dict(buffer=0, byteOffset=append(data), byteLength=len(data)))
        if i in transcode or image.get('bufferView') in image_views:
            image['mimeType'] = 'image/png'
    if draco:
        expand(doc, merged, append)
    if draco or meshopt or basis:
        # The compact mesh schema has one UV set and no custom attributes.
        # Retain native accessors when flattening would discard their data.
        primitives = [p for mesh in doc.get('meshes', []) for p in mesh.get('primitives', [])]
        for primitive in primitives:
            attrs = set(primitive.get('attributes', {}))
            if attrs - {'POSITION', 'NORMAL', 'TEXCOORD_0', 'COLOR_0'} or (
                    'COLOR_0' in attrs and 'TEXCOORD_0' in attrs):
                native = True
    doc['buffers'] = [dict(byteLength=len(merged))]
    manifest = json.dumps(doc, ensure_ascii=False, separators=(',', ':')).encode('utf8')
    manifest += b' ' * (-len(manifest) % 4)
    merged.extend(b'\0' * (-len(merged) % 4))
    chunks = struct.pack('<II', len(manifest), JSON_CHUNK) + manifest + struct.pack('<II', len(merged), BIN_CHUNK) + merged
    glb = struct.pack('<4sII', b'glTF', 2, 12 + len(chunks)) + chunks
    return glb, _scene_counts(doc) if native else None


def native_gltf_payload(path):
    glb, stats = prepare_gltf(path)
    return dict(glb=base64.b64encode(glb).decode('ascii'), stats=stats) if stats is not None else None
