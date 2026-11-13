#!/usr/bin/env python3
"""Print the path of the generated HTML. Reuse an installed or private Python environment."""
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parent
REQUIREMENTS = ROOT / 'requirements.txt'
sys.path.insert(0, str(ROOT / 'scripts'))
from viewer_dependencies import OPTIONAL

# The launcher uses stdlib only until the conversion environment is ready.
# Keep lower bounds aligned with requirements.txt, including hosts with old packages.
bounds = dict(line.split('>=') for line in REQUIREMENTS.read_text().splitlines() if line)
IMPORT_CHECK = f"""
import re
from importlib.metadata import version
import numpy, PIL, scipy, trimesh, networkx, lxml.etree, collada

def release(value):
    numbers = re.match(r'[0-9]+(?:\\.[0-9]+)*', value).group().split('.')
    return tuple(map(int, numbers)) + (0,) * (6 - len(numbers))

assert all(release(version(name)) >= release(floor) for name, floor in {bounds!r}.items())
""".strip()



def ready(python, check):
    return Path(python).is_file() and subprocess.run(
        [str(python), '-c', check], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    ).returncode == 0


def private_python(requirements=(), check=IMPORT_CHECK):
    cache = Path(os.environ.get('XDG_CACHE_HOME') or os.environ.get('LOCALAPPDATA') or Path.home()/'.cache')
    fingerprint = hashlib.sha256(REQUIREMENTS.read_bytes() + sys.executable.encode()).hexdigest()[:12]
    prefix = cache / '3D-Inspector' / f'py{sys.version_info.major}{sys.version_info.minor}-{fingerprint}'
    python = prefix / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    lock = prefix.with_suffix('.lock')
    lock.parent.mkdir(parents=True, exist_ok=True)
    if ready(python, check):
        return python
    with lock.open('a+b') as handle:
        # A process lock releases automatically if a first-time install is interrupted.
        if os.name == 'nt':
            import msvcrt
            import time
            if handle.seek(0, os.SEEK_END) == 0:
                handle.write(b'0')
                handle.flush()
            handle.seek(0)
            while True:
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError as exc:
                    if exc.errno not in (13, 36): raise
                    time.sleep(.2)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX)
        if not ready(python, check):
            if not python.is_file():
                venv.EnvBuilder(with_pip=True).create(prefix)
            subprocess.run([str(python), '-m', 'pip', 'install', '--disable-pip-version-check', '-r', str(REQUIREMENTS), *requirements],
                           check=True, stdout=sys.stderr)
        return python


def main():
    if len(sys.argv) == 1 or sys.argv[1:] in (['--help'], ['-h']):
        print('Usage: python view.py MODEL [-o preview.html] [--runtime-source embedded|cdn]\n'
              'Prints the output HTML path. Additional build_viewer.py options are accepted.')
        return 0 if len(sys.argv) > 1 else 2
    python = sys.executable if ready(sys.executable, IMPORT_CHECK) else private_python()
    args = [str(ROOT/'scripts/build_viewer.py'), '--path-only', *sys.argv[1:]]
    requirements, checks = [], [IMPORT_CHECK]
    while True:
        status = subprocess.call([str(python), *args])
        missing = next((info for info in OPTIONAL.values() if info[0] == status), None)
        if missing is None or missing[1] in requirements:
            return status
        requirements.append(missing[1])
        checks.append(missing[2])
        python = private_python(requirements, '\n'.join(checks))


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f'Unable to prepare the viewer environment: {exc}. Install {REQUIREMENTS} and retry.', file=sys.stderr)
        raise SystemExit(1)
