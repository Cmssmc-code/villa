"""Branch find_yx_range on chunked zarr arrays == main find_yx_range on numpy arrays (several shapes/ranges)."""
import importlib.util
import os
import sys
import tempfile

import numpy as np
import zarr

S = os.path.dirname(os.path.abspath(__file__))


def load(t):
    d = os.path.join(S, t, 'spiral-fitting')
    spec = importlib.util.spec_from_file_location('est_' + t, os.path.join(d, 'extract_surface_tracks.py'))
    m = importlib.util.module_from_spec(spec)
    sys.path.insert(0, d)
    spec.loader.exec_module(m)
    sys.path.remove(d)
    return m


A, B = load('A'), load('B')
rng = np.random.default_rng(1)
tmp = tempfile.mkdtemp()
bad = 0
n = 0
for shape, chunks in [((100, 40, 50), (7, 16, 16)), ((300, 33, 21), (32, 32, 32)), ((50, 20, 20), (64, 8, 8))]:
    vol = np.zeros(shape, np.uint8)
    for _ in range(30):
        z, y, x = (rng.integers(0, s) for s in shape)
        vol[z, y, x] = 1
    arr = zarr.open_array(os.path.join(tmp, f'{n}.zarr'), mode='w', shape=shape, chunks=chunks, dtype='u1')
    arr[:] = vol
    for z0, z1 in [(0, shape[0]), (3, 17), (5, shape[0] - 1), (10, 10_000), (0, 5)]:
        n += 1
        A.z_min, A.z_max, B.z_min, B.z_max = z0, z1, z0, z1
        want = [v.tolist() for v in A.find_yx_range(vol)]
        for got_arr in (arr, vol):
            got = [v.tolist() for v in B.find_yx_range(got_arr)]
            if got != want:
                bad += 1
                print('MISMATCH', shape, chunks, z0, z1, want, got)
print(f'{n} cases, {bad} mismatches')
