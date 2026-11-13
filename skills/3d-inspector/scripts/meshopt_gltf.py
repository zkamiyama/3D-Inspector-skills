"""Replace glTF meshopt buffer views with ordinary bytes during conversion."""
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

NAMES = ('KHR_meshopt_compression', 'EXT_meshopt_compression')


def decode_views(doc, buffers, limit):
    required = set(doc.get('extensionsRequired', []))
    jobs = []
    view_ids = []
    total_input = total_output = 0
    for index, view in enumerate(doc.get('bufferViews', [])):
        extensions = view.get('extensions', {})
        name = next((key for key in NAMES if key in extensions), None)
        if name is None:
            continue
        ext = extensions[name]
        fallback = buffers[view['buffer']]
        if name not in required and fallback is not None:
            continue
        src = buffers[ext['buffer']]
        offset, length = ext.get('byteOffset',0), ext['byteLength']
        count, stride = ext['count'], ext['byteStride']
        mode, filt = ext['mode'], ext.get('filter','NONE')
        if (src is None or offset < 0 or length < 1 or offset + length > len(src)
                or count < 1 or stride != view.get('byteStride', stride)
                or count * stride != view['byteLength']):
            raise ValueError('Invalid meshopt buffer range or stride')
        if mode not in ('ATTRIBUTES','INDICES','TRIANGLES'):
            raise ValueError(f'Unknown meshopt mode {mode}')
        if mode == 'ATTRIBUTES':
            valid = 4 <= stride <= 256 and stride % 4 == 0
            valid &= filt in ('NONE','OCTAHEDRAL','QUATERNION','EXPONENTIAL','COLOR')
            if filt in ('OCTAHEDRAL','COLOR'):
                valid &= stride in (4,8)
            if filt == 'QUATERNION':
                valid &= stride == 8
        else:
            valid = stride in (2,4) and filt == 'NONE' and (mode != 'TRIANGLES' or count % 3 == 0)
        total_output += count * stride
        if not valid or total_output > limit or total_input + length > limit:
            raise ValueError('Unsupported meshopt layout or decoded size exceeds 512 MiB')
        jobs.append(dict(offset=total_input, length=length, count=count, stride=stride, mode=mode, filter=filt))
        view_ids.append((index, memoryview(src)[offset:offset+length]))
        total_input += length

    output = {}
    if jobs:
        node = shutil.which('node')
        if not node:
            raise ValueError('Meshopt-compressed glTF requires Node.js on PATH during conversion')
        script = Path(__file__).resolve().parent / 'meshopt' / 'expand.mjs'
        with tempfile.TemporaryDirectory(prefix='3d-inspector-meshopt-') as folder:
            root = Path(folder)
            with (root/'input.bin').open('wb') as source:
                for _, data in view_ids:
                    source.write(data)
            (root/'jobs.json').write_text(json.dumps(jobs), encoding='utf8')
            result = subprocess.run([node, str(script), str(root/'jobs.json'), str(root/'input.bin'), str(root/'output.bin')],
                                    capture_output=True, text=True)
            if result.returncode:
                raise ValueError('Meshopt decompression failed: ' + result.stderr[-1200:])
            with (root/'output.bin').open('rb') as data:
                for (index,_), job in zip(view_ids, jobs):
                    output[index] = data.read(job['count'] * job['stride'])
                    if len(output[index]) != job['count'] * job['stride']:
                        raise ValueError('Truncated meshopt decoder output')
    for key in ('extensionsUsed','extensionsRequired'):
        if key in doc:
            doc[key] = [name for name in doc[key] if name not in NAMES]
            if not doc[key]:
                del doc[key]
    return output
