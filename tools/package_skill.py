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
ESSENTIAL = {
    'SKILL.md', 'README.md', 'LICENSE', 'requirements.txt', 'view.py', 'agents/openai.yaml',
    'assets/viewer.html', 'assets/THIRD_PARTY_LICENSES.txt', 'scripts/build_viewer.py',
    'scripts/viewer_dependencies.py', 'scripts/gltf_scene.py', 'scripts/blender_export.py',
    'scripts/usd_scene.py', 'scripts/cad_scene.py', 'scripts/draco_gltf.py', 'scripts/meshopt_gltf.py',
    'scripts/basis/decode.cjs', 'scripts/basis/transcoder.cjs', 'scripts/basis/transcoder.wasm',
    'scripts/basis/LICENSE', 'scripts/basis/UPSTREAM.md', 'scripts/basis_gltf.py',
    'scripts/meshopt/expand.mjs', 'scripts/meshopt/decoder.mjs', 'scripts/meshopt/LICENSE', 'scripts/splat_scene.py'
}


def skill_files():
    files = set(ESSENTIAL)
    files.update(str(p.relative_to(SKILL).as_posix()) for p in (SKILL/'scripts').glob('*.py'))
    profiles = set()
    for asset in (SKILL/'assets').iterdir():
        name = asset.name
        if name in ('viewer.html', 'THIRD_PARTY_LICENSES.txt'):
            continue
        for suffix in ('-runtime.bundle.js', '-runtime.cdn.mjs'):
            if asset.is_file() and name.endswith(suffix):
                profiles.add(name.removesuffix(suffix))
                break
        else:
            raise ValueError('Unexpected file in Skill assets: ' + name)
    for profile in profiles | {'mesh', 'native', 'gltf', 'splat', 'splat-ply'}:
        for suffix in ('bundle.js', 'cdn.mjs'):
            files.add(f'assets/{profile}-runtime.{suffix}')
    for name in sorted(files):
        path = SKILL / name
        if not path.is_file() or not path.stat().st_size:
            raise ValueError('Missing required Skill file: ' + str(path))
    return sorted(files)


def main():
    files = skill_files()
    with zipfile.ZipFile(OUTPUT,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for name in files:
            data=(SKILL/name).read_bytes()
            info=zipfile.ZipInfo('chat-3d-viewer/'+name,date_time=(2026,1,1,0,0,0))
            info.compress_type=zipfile.ZIP_DEFLATED
            info.external_attr=(0o644<<16)
            z.writestr(info,data,compress_type=zipfile.ZIP_DEFLATED,compresslevel=9)
    with zipfile.ZipFile(OUTPUT) as z:
        assert len(z.namelist())==len(files)
        assert z.testzip() is None
    print('Created:',OUTPUT,'(',OUTPUT.stat().st_size,'bytes )')
    return 0

if __name__=='__main__':
    sys.exit(main())
