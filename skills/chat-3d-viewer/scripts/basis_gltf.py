"""Transcode KHR_texture_basisu at export time. The HTML only needs PNG."""
import io
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile

from PIL import Image

EXTENSION = 'KHR_texture_basisu'
MAGIC = b'\xabKTX 20\xbb\r\n\x1a\n'


def basis_images(doc):
    """Use optional PNG/JPEG fallbacks directly when the model supplies them."""
    images = doc.get('images', [])
    ids = set()
    required = EXTENSION in doc.get('extensionsRequired', [])
    for texture in doc.get('textures', []):
        extension = texture.get('extensions', {}).pop(EXTENSION, None)
        if extension is None:
            continue
        if required or 'source' not in texture:
            index = extension.get('source')
            if not isinstance(index, int) or not 0 <= index < len(images):
                raise ValueError('Invalid KHR_texture_basisu image reference')
            texture['source'] = index
            ids.add(index)
        if not texture['extensions']:
            del texture['extensions']
    for field in ('extensionsUsed','extensionsRequired'):
        if EXTENSION in doc.get(field, []):
            doc[field].remove(EXTENSION)
            if not doc[field]:
                del doc[field]
    return ids


def png_texture(raw, max_texture):
    if len(raw) < 80 or raw[:12] != MAGIC:
        raise ValueError('KHR_texture_basisu image is not a KTX2 container')
    vk_format, _, width, height, depth, layers, faces, levels, _ = struct.unpack_from('<9I', raw, 12)
    if vk_format or not width or not height or depth or layers or faces != 1 or not levels:
        raise ValueError('KHR_texture_basisu requires a two-dimensional Basis Universal texture')
    if width * height * 4 > 512 * 1024 * 1024:
        raise ValueError('Decoded KTX2 texture exceeds 512 MiB')
    node = shutil.which('node')
    if not node:
        raise ValueError('KTX2/Basis glTF requires Node.js on PATH during HTML conversion')
    script = Path(__file__).resolve().parent / 'basis' / 'decode.cjs'
    with tempfile.TemporaryDirectory(prefix='chat-3d-basis-') as folder:
        source = Path(folder) / 'input.ktx2'
        pixels = Path(folder) / 'pixels.rgba'
        source.write_bytes(raw)
        result = subprocess.run([node, str(script), str(source), str(pixels)], capture_output=True, text=True)
        if result.returncode:
            raise ValueError('KTX2/Basis transcoding failed: ' + result.stderr[-1000:].strip())
        if pixels.stat().st_size != width * height * 4:
            raise ValueError('Incomplete KTX2 RGBA data')
        image = Image.frombytes('RGBA', (width,height), pixels.read_bytes())
    if max(width, height) > max_texture:
        image.thumbnail((max_texture, max_texture), Image.Resampling.LANCZOS)
    encoded = io.BytesIO()
    image.save(encoded, 'PNG')
    return encoded.getvalue()
