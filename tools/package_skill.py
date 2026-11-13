#!/usr/bin/env python3
"""Create an installable, reproducible Chat 3D Inspector Skill ZIP.

Run this from anywhere: python tools/package_skill.py
The ZIP contains one chat-3d-viewer/ directory and no node_modules or caches.
"""
from pathlib import Path
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]
SKILL=ROOT/'skills'/'chat-3d-viewer'
OUTPUT=ROOT/'chat-3d-viewer-skill.zip'
INCLUDE=[
    'SKILL.md',
    'README.md',
    'LICENSE',
    'requirements.txt',
    'agents/openai.yaml',
    'assets/viewer.html',
    'assets/native-runtime.bundle.js',
    'assets/native-runtime.cdn.mjs',
    'assets/THIRD_PARTY_LICENSES.txt',
    'scripts/build_viewer.py',
]
def main():
    for name in INCLUDE:
        path=SKILL/name
        if not path.is_file() or not path.stat().st_size:
            raise SystemExit('Missing required Skill file: '+str(path))
    with zipfile.ZipFile(OUTPUT,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for name in INCLUDE:
            data=(SKILL/name).read_bytes()
            info=zipfile.ZipInfo('chat-3d-viewer/'+name,date_time=(2026,1,1,0,0,0))
            info.compress_type=zipfile.ZIP_DEFLATED
            info.external_attr=(0o644<<16)
            z.writestr(info,data,compress_type=zipfile.ZIP_DEFLATED,compresslevel=9)
    with zipfile.ZipFile(OUTPUT) as z:
        assert len(z.namelist())==len(INCLUDE)
        assert z.testzip() is None
    print('Created:',OUTPUT,'(',OUTPUT.stat().st_size,'bytes )')
    return 0

if __name__=='__main__':
    sys.exit(main())
