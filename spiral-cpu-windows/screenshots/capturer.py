"""Takes the two screenshots of the pull request "spiral-fitting: one Kimimaro process per slab on
Windows, and --slab-workers outside Linux": before.png (villa main) and after.png (the branch at a
given commit), in this folder. Windows only.

It needs capture_console.py, a local tool that is not published with these files: it runs a
script in a console on a hidden desktop and saves a picture of that console window. Without it,
before.cmd and after.cmd can be run by hand in a console, with the environment variables that
capturer.py sets below.

The code of main and of the branch is extracted by git archive into ../capture-tmp, with copies of
before.cmd, after.cmd and chrono.py. That folder and the data folder get free drive letters (subst),
so that no user folder shows in the pictures. before.cmd and after.cmd run in a console on a hidden
desktop (capture_console.py, in the folder outils of this work area): nothing appears on screen.
The drive letters and ../capture-tmp are removed at the end. Progress goes to stdout, ending with FIN.

Usage: python capturer.py <full commit of the branch>
"""
import ctypes
import io
import os
import shutil
import subprocess
import sys
import tarfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parent.parent
REPO = BASE / 'wt-spirale-cpu'
DATA = BASE / 'donnees-spirale-cpu'
CAPTURE = BASE / 'outils' / 'capture_console.py'
MAIN = '97fb9336c8898be27e78eff8cd23ce5e7185ec0a'
PREDICTION = r'PHerc0332-20251211183505-surface-m7-L2-th0.2.zarr\0'
WORK = HERE.parent / 'capture-tmp'
CREATE_NO_WINDOW = 0x08000000


def log(text):
    print(time.strftime('%H:%M:%S'), text, flush=True)


def git(*args):
    return subprocess.run(['git', '-C', str(REPO), *args], capture_output=True, check=True,
                          creationflags=CREATE_NO_WINDOW).stdout


def extract(sha, destination):
    with tarfile.open(fileobj=io.BytesIO(git('archive', '--format=tar', sha, 'spiral-fitting'))) as tar:
        tar.extractall(destination, filter='data')


def free_letters(count):
    used = ctypes.windll.kernel32.GetLogicalDrives()
    letters = [c for c in 'WVUTSRQP' if not used & (1 << (ord(c) - ord('A')))]
    if len(letters) < count:
        raise SystemExit('not enough free drive letters')
    return [f'{c}:' for c in letters[:count]]


def subst(*args):
    subprocess.run(['subst', *args], capture_output=True, creationflags=CREATE_NO_WINDOW)


def remove_work():
    for _ in range(10):
        if not WORK.exists():
            return
        shutil.rmtree(WORK, ignore_errors=True)
        time.sleep(1)
    log(f'could not remove {WORK.name} entirely')


def main():
    branch = sys.argv[1]
    if len(branch) != 40:
        raise SystemExit('give the full commit of the branch')
    remove_work()
    for folder in ('out', 'cache', 'temp'):
        (WORK / folder).mkdir(parents=True)
    extract(MAIN, WORK / 'main')
    extract(branch, WORK / 'branch')
    for name in ('before.cmd', 'after.cmd', 'chrono.py'):
        shutil.copy2(HERE / name, WORK / name)
    work, data = free_letters(2)
    log(f'code extracted; drive letters {work} (work) and {data} (data)')
    subst(work, str(WORK))
    subst(data, str(DATA))
    try:
        env = dict(os.environ, PY=sys.executable, CHRONO=f'{work}\\chrono.py', REPO=str(REPO),
                   MAIN=MAIN, BRANCH=branch, WORK=work, PRED=f'{data}\\{PREDICTION}',
                   PYTHONPATH=f'{data}\\extra', VC_READER_CACHE_DIR=f'{work}\\cache',
                   XDG_CACHE_HOME=f'{work}\\cache', TEMP=f'{work}\\temp', TMP=f'{work}\\temp')
        env.pop('PYTHONHOME', None)
        for name, wait in (('before', 480), ('after', 330)):
            # Both scripts write the same DBM names, and the extraction skips the slabs already in
            # a DBM: each one starts with an empty output folder.
            shutil.rmtree(WORK / 'out')
            (WORK / 'out').mkdir()
            log(f'{name}: running {name}.cmd on a hidden desktop')
            result = subprocess.run([sys.executable, str(CAPTURE), str(HERE / f'{name}.png'), str(wait),
                                     f'{work}\\{name}.cmd', '150', '45'], env=env, capture_output=True,
                                    text=True, encoding='utf-8', errors='replace',
                                    creationflags=CREATE_NO_WINDOW)
            log(f'{name}: exit code {result.returncode} {(result.stdout + result.stderr).strip()}')
    finally:
        subst(work, '/d')
        subst(data, '/d')
        remove_work()
        log('drive letters removed, capture-tmp removed')


if __name__ == '__main__':
    try:
        main()
    finally:
        print('FIN', flush=True)
