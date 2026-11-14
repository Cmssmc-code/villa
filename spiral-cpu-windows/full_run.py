"""Lets main 97fb933 run to the end with its default settings, on the same 64 slices as
verifier.py, between a run of main with --kimimaro-parallel 1 and a run of the branch with its
default settings, and compares the three track databases. Windows only.

verifier.py stops main's default run after 120 s to stay short; this script measures how long it
really takes. It uses the functions of verifier.py (same data, same commits, same job-object
accounting) and writes one English log per run to ./journaux/complete, plus compare.log; its
temporary files go to ./complete-tmp, removed at the end. Last line: FIN.

Usage: python full_run.py
"""
import importlib.util
import pickle
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('verifier', HERE / 'verifier.py')
v = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v)

v.TMP = HERE / 'complete-tmp'
v.LOGS = HERE / 'journaux' / 'complete'
v.ENV.update(VC_READER_CACHE_DIR=str(v.TMP / 'cache'), XDG_CACHE_HOME=str(v.TMP / 'cache'),
             TEMP=str(v.TMP / 'temp'), TMP=str(v.TMP / 'temp'))


def track_sets(path):
    """Tracks per key as a sorted list (Kimimaro's own processes may return them in another order)."""
    return {k: sorted(t.tolist() for t in pickle.loads(b)) for k, b in v.read_dbm(path).items()}


def compare(reference, other, f):
    a, b = v.read_dbm(reference), v.read_dbm(other)
    same_bytes = sum(a[k] == b[k] for k in a.keys() & b.keys())
    sa, sb = track_sets(reference), track_sets(other)
    same_sets = sum(sa[k] == sb[k] for k in sa.keys() & sb.keys())
    f.write(f'{other.name} against {reference.name}: {len(b)} and {len(a)} keys; same keys: '
            f'{a.keys() == b.keys()}; identical pickled bytes: {same_bytes}/{len(a)}; identical track '
            f'sets: {same_sets}/{len(a)}; tracks: {sum(len(x) for x in sb.values())}\n')


def main():
    v.GIT = v.find_git()
    v.check_environment()
    v.remove_tmp()
    for folder in (v.TMP / 'out', v.TMP / 'cache', v.TMP / 'temp', v.LOGS):
        folder.mkdir(parents=True, exist_ok=True)
    for old in v.LOGS.glob('*.log'):
        old.unlink()
    v.extract_tree(v.MAIN, v.TMP / 'main', 'spiral-fitting')
    v.extract_tree(v.BRANCH, v.TMP / 'branch', 'spiral-fitting')
    main_dir, branch_dir = v.TMP / 'main' / 'spiral-fitting', v.TMP / 'branch' / 'spiral-fitting'
    lines = [f'Machine: {v.machine()}; free memory at the start {v.free_memory_gb():.1f} GB.',
             f'main {v.MAIN}; branch {v.BRANCH}; PHerc0332 surface_m7, level 0, z {v.Z_MIN} to {v.Z_MAX}.']
    runs = (('a-main-default', main_dir, 'main-default.dbm', (), 1800),
            ('b-main-kimimaro-parallel-1', main_dir, 'main-k1.dbm', ('--kimimaro-parallel', '1'), 600),
            ('c-branch-default', branch_dir, 'branch-default.dbm', (), 600))
    for step, cwd, out, options, limit in runs:
        print(time.strftime('%H:%M:%S'), step, flush=True)
        r = v.run(step, cwd, v.extraction(out, *options), limit)
        lines.append(f'{step}: ' + (f'exit code {r["code"]}' if r['finished'] else f'stopped after {limit} s')
                     + f', wall time {r["seconds"]:.1f} s, CPU time {r["cpu"]:.1f} s, '
                     f'{r["processes"]} processes started, peak committed memory {r["peak_gb"]:.2f} GB')
        print('   ', lines[-1], flush=True)
    with open(v.LOGS / 'compare.log', 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(lines) + '\n')
        reference = v.TMP / 'out' / 'main-k1.dbm'
        for other in ('main-default.dbm', 'branch-default.dbm'):
            if (v.TMP / 'out' / other).exists():
                compare(reference, v.TMP / 'out' / other, f)
    print((v.LOGS / 'compare.log').read_text(encoding='utf-8'), flush=True)


if __name__ == '__main__':
    try:
        main()
    finally:
        v.remove_tmp()
        print('FIN', flush=True)
        sys.stdout.flush()
