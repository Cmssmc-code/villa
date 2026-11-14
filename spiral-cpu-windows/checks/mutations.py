"""Checks that the two new tests of the spiral PR fail where they should.

Each case is a copy of spiral-fitting (git archive) with the two test files of the branch head,
sometimes with extract_surface_tracks.py changed; pytest runs the two new tests in it.
Usage: python mutations.py   (prints one block per case, then FIN)
"""
import io
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time
from pathlib import Path

BASE = Path(r'C:\Users\me\Dev\vesuvius')
REPO = BASE / 'wt-spirale-cpu'
PY = BASE / 'venv-pywin' / 'Scripts' / 'python.exe'
WORK = BASE / 'outils' / 'scratch' / 'vague23' / 'spirale' / 'tmp' / 'mut'
MAIN = '97fb9336c8898be27e78eff8cd23ce5e7185ec0a'
PR2520 = 'b4e62efcaaea038a49c400243f8d61c36d89fd5a'
FIRST = '5562cd85c36c9aedf3917de6a18a7a5d8cc06faa'
HEAD = subprocess.run(['git', '-C', str(REPO), 'rev-parse', 'HEAD'], capture_output=True, text=True,
                      check=True).stdout.strip()
TESTS = ['tests/test_cc_labels.py::test_spawned_slab_workers_get_the_settings',
         'tests/test_extract_surface_tracks.py::test_cpu_options_on_every_os']
NEW_TEST_FILES = ['tests/test_cc_labels.py', 'tests/test_extract_surface_tracks.py']
CREATE_NO_WINDOW = 0x08000000
BELOW_NORMAL = 0x00004000

ENV = dict(os.environ, PYTHONPATH=str(BASE / 'donnees-spirale-cpu' / 'extra'), PYTHONIOENCODING='utf-8',
           PYTHONDONTWRITEBYTECODE='1', VC_READER_CACHE_DIR=str(WORK / 'cache'),
           XDG_CACHE_HOME=str(WORK / 'cache'), TEMP=str(WORK / 'temp'), TMP=str(WORK / 'temp'))
ENV.pop('PYTHONHOME', None)


def tree(name, sha):
    dest = WORK / name
    data = subprocess.run(['git', '-C', str(REPO), 'archive', '--format=tar', sha, 'spiral-fitting'],
                          capture_output=True, check=True).stdout
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        tar.extractall(dest, filter='data')
    for rel in NEW_TEST_FILES:  # the new tests, from the branch head
        (dest / 'spiral-fitting' / rel).write_bytes(subprocess.run(
            ['git', '-C', str(REPO), 'show', f'{HEAD}:spiral-fitting/{rel}'], capture_output=True,
            check=True).stdout)
    return dest / 'spiral-fitting'


def edit(src, change):
    path = src / 'extract_surface_tracks.py'
    text = path.read_bytes()
    new = change(text)
    assert new != text, 'the change did nothing'
    path.write_bytes(new)


def run(name, src, expect):
    t0 = time.perf_counter()
    r = subprocess.run([str(PY), '-m', 'pytest', '-q', '-p', 'no:cacheprovider', '-rf',
                        f'--basetemp={WORK / "pt" / re.sub(r"[^A-Za-z0-9]+", "-", name)}', *TESTS],
                       cwd=src, env=ENV,
                       capture_output=True, text=True, encoding='utf-8', errors='replace',
                       stdin=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW | BELOW_NORMAL)
    out = r.stdout + r.stderr
    summary = [l for l in out.splitlines() if re.search(r'\d+ (passed|failed)', l)]
    failed = sorted(set(re.findall(r'FAILED (\S+)', out)))
    print(f'=== {name}: {summary[-1].strip() if summary else "(no summary)"} '
          f'[{time.perf_counter() - t0:.0f} s]', flush=True)
    for f in failed:
        print(f'    failed: {f}', flush=True)
    for line in out.splitlines():
        if line.startswith('E ') and ('Error' in line or 'assert' in line):
            print(f'    {line.strip()[:400]}', flush=True)
            break
    print(f'    expected: {expect}', flush=True)


def drop(name):
    return lambda text: re.sub(rb"'" + name.encode() + rb"',\s*", b'', text, count=1)


def main():
    shutil.rmtree(WORK, ignore_errors=True)
    for d in ('cache', 'temp', 'pt'):
        (WORK / d).mkdir(parents=True)
    print(f'branch head {HEAD}; the new tests come from it', flush=True)
    run('branch', tree('branch', HEAD), 'both pass')
    for setting in ('downsample_factor', 'dust_threshold', 'max_area_threshold', 'path_mode'):
        src = tree(f'drop-{setting}', HEAD)
        edit(src, drop(setting))
        run(f'branch without {setting} in _WORKER_SETTINGS', src, 'the spawn test fails')
    run('main 97fb933', tree('main', MAIN), 'both fail')
    src = tree('main-2520', MAIN)
    (src / 'extract_surface_tracks.py').write_bytes(subprocess.run(
        ['git', '-C', str(REPO), 'show', f'{PR2520}:spiral-fitting/extract_surface_tracks.py'],
        capture_output=True, check=True).stdout)
    run('main with the extract_surface_tracks.py of #2520', src, 'both fail')
    run('first commit 5562cd85c only', tree('first', FIRST),
        'test_cpu_options_on_every_os fails (Windows default still 8)')


if __name__ == '__main__':
    try:
        main()
    finally:
        shutil.rmtree(WORK, ignore_errors=True)
        print('FIN', flush=True)
