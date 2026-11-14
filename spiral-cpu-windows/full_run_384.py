"""Runs full_run.py on 384 slices, z 4032 to 4416, instead of 64: main 97fb933 with its default
settings, main with --kimimaro-parallel 1 and the branch with its default settings, then compares
the three track databases. Windows only.

On 64 slices most slabs are small, and main's default run spends most of its time on them
(logs/full-run); here the vertical slabs are six times taller. Same data, commits,
job-object accounting and comparisons as full_run.py; one English log per run goes to
./journaux/complete-384, plus compare.log; temporary files go to ./complete-384-tmp, removed at the
end. Last line: FIN.

Usage: python full_run_384.py
"""
import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('full_run', HERE / 'full_run.py')
full_run = importlib.util.module_from_spec(spec)
spec.loader.exec_module(full_run)
v = full_run.v  # the functions and settings of verifier.py, as full_run.py uses them

v.Z_MAX = 4416
v.TMP = HERE / 'complete-384-tmp'
v.LOGS = HERE / 'journaux' / 'complete-384'
v.ENV.update(VC_READER_CACHE_DIR=str(v.TMP / 'cache'), XDG_CACHE_HOME=str(v.TMP / 'cache'),
             TEMP=str(v.TMP / 'temp'), TMP=str(v.TMP / 'temp'))

if __name__ == '__main__':
    try:
        full_run.main()
    finally:
        v.remove_tmp()
        print('FIN', flush=True)
        sys.stdout.flush()
