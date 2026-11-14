"""Does each open PR that touches the files of the spiral PR still apply on top of it?

For every diff in diffs/ (gh pr diff N), the spiral-fitting part is applied with `git apply --cached`
to a temporary index of main 97fb933 (baseline) and of the branch head; nothing in the working tree
changes. For #2520 and #2539, whose base commits are in the clone, git merge-tree is run too; the
spiral-fitting folder of the merge with #2520 is exported, and pytest runs there the test of #2520
and the CPU options test of this PR.
Usage: python conflicts.py <branch head>
"""
import io
import os
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

BASE = r'C:\Users\me\Dev\vesuvius'
REPO = BASE + r'\wt-spirale-cpu'
PY = BASE + r'\venv-pywin\Scripts\python.exe'
EXTRA = BASE + r'\donnees-spirale-cpu\extra'  # kimimaro, cc3d, zarr, pytest...
HERE = Path(__file__).resolve().parent
MAIN = '97fb9336c8898be27e78eff8cd23ce5e7185ec0a'
HEADS = {2520: 'b4e62efcaaea038a49c400243f8d61c36d89fd5a', 2539: '0a9dde96be6d4ce902631744d711a5ebd1e3fd27'}


def git(*args, env=None):
    return subprocess.run(['git', '-C', REPO, *args], capture_output=True, text=True, env=env)


def merged_tests(tree, head):
    """Runs the test of #2520 and the CPU options test of this PR in the merged tree."""
    path = 'spiral-fitting/extract_surface_tracks.py'
    same = git('rev-parse', f'{tree}:{path}').stdout == git('rev-parse', f'{head}:{path}').stdout
    print(f'        merged extract_surface_tracks.py identical to the branch head: {same}')
    with tempfile.TemporaryDirectory() as d:
        data = subprocess.run(['git', '-C', REPO, 'archive', '--format=tar', tree, 'spiral-fitting'],
                              capture_output=True, check=True).stdout
        with tarfile.open(fileobj=io.BytesIO(data)) as tar:
            tar.extractall(d, filter='data')
        env = dict(os.environ, PYTHONPATH=EXTRA, PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8')
        env.pop('PYTHONHOME', None)
        r = subprocess.run([PY, '-m', 'pytest', '-q', '-rf', '-p', 'no:cacheprovider', f'--basetemp={d}/pt',
                            'tests/test_extract_surface_tracks.py', '-k',
                            'test_slab_workers_need_linux or test_cpu_options_on_every_os'],
                           cwd=os.path.join(d, 'spiral-fitting'), env=env, capture_output=True, text=True,
                           encoding='utf-8', errors='replace', stdin=subprocess.DEVNULL,
                           creationflags=0x08000000)  # CREATE_NO_WINDOW
    for line in (r.stdout + r.stderr).splitlines():
        if line.startswith(('FAILED', 'E   ')) or ' passed' in line or ' failed' in line:
            print(f'        {line.strip()}')


def applies(diff, treeish):
    with tempfile.TemporaryDirectory() as d:
        env = dict(os.environ, GIT_INDEX_FILE=str(Path(d) / 'index'))
        git('read-tree', treeish, env=env)
        r = git('apply', '--cached', '--check', '--include=spiral-fitting/*', str(diff), env=env)
        return 'applies cleanly' if r.returncode == 0 else 'DOES NOT APPLY: ' + ' | '.join(
            l for l in r.stderr.splitlines() if l.startswith('error'))[:300]


def main():
    head = sys.argv[1]
    print(f'branch head {head}; main {MAIN}')
    for diff in sorted((HERE / 'diffs').glob('pr*.diff')):
        n = int(diff.stem[2:])
        files = sorted({l.split(' b/')[-1] for l in diff.read_text(encoding='utf-8').splitlines()
                        if l.startswith('diff --git') and ' b/spiral-fitting/' in l})
        print(f'#{n} ({", ".join(f.replace("spiral-fitting/", "") for f in files)})')
        print(f'    on main:   {applies(diff, MAIN)}')
        print(f'    on branch: {applies(diff, head)}')
        if n in HEADS:
            r = git('merge-tree', '--write-tree', '--name-only', head, HEADS[n])
            print(f'    git merge-tree {head[:9]} {HEADS[n][:9]}: exit {r.returncode}, '
                  + ('no conflict' if r.returncode == 0 else 'CONFLICT ' + r.stdout.replace(chr(10), ' ')[:300]))
            if n == 2520 and r.returncode == 0:
                merged_tests(r.stdout.split()[0], head)
    print('FIN')


if __name__ == '__main__':
    main()
