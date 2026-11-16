"""Compare find_yx_range of two spiral-fitting trees on the real PHerc0332 mirror (alternated A/B).

usage: python phase_yx.py <tree A spiral-fitting> <tree B spiral-fitting> <z_min> <z_max> <rounds>
"""
import importlib.util
import os
import sys
import time

a_dir, b_dir, z0, z1, rounds = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5])
DATA = r'%USERPROFILE%\Dev\vesuvius\donnees-spirale-cpu\PHerc0332-20251211183505-surface-m7-L2-th0.2.zarr\0'


def load(d, name):
    sys.path.insert(0, d)
    spec = importlib.util.spec_from_file_location(name, os.path.join(d, 'extract_surface_tracks.py'))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    sys.path.remove(d)
    m.z_min, m.z_max = z0, z1
    return m


mods = {'A': load(a_dir, 'est_a'), 'B': load(b_dir, 'est_b')}
for r in range(rounds):
    for k in ('A', 'B'):
        m = mods[k]
        arr = m.open_predictions(DATA)
        c0, w0 = time.process_time(), time.perf_counter()
        lo, hi = m.find_yx_range(arr)
        print(f'{k} round {r}: wall {time.perf_counter() - w0:.2f} s cpu {time.process_time() - c0:.2f} s '
              f'range {lo.tolist()} .. {hi.tolist()}', flush=True)
