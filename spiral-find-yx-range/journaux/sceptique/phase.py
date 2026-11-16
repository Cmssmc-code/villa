"""One fresh process: time find_yx_range of one spiral-fitting tree, count blosc chunk decodes.

usage: python phase.py <spiral-fitting dir> <zarr level dir> <z_min> <z_max>
"""
import importlib.util
import os
import sys
import time

tree, data, z0, z1 = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])

import numcodecs

decodes = [0]
_orig = numcodecs.Blosc.decode


def counting_decode(self, *a, **k):
    decodes[0] += 1
    return _orig(self, *a, **k)


numcodecs.Blosc.decode = counting_decode

sys.path.insert(0, tree)
spec = importlib.util.spec_from_file_location('est', os.path.join(tree, 'extract_surface_tracks.py'))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
m.z_min, m.z_max = z0, z1
arr = m.open_predictions(data)
c0, w0 = time.process_time(), time.perf_counter()
lo, hi = m.find_yx_range(arr)
print(f'PHASE tree={os.path.basename(os.path.dirname(tree))} z={z0}..{z1} wall={time.perf_counter() - w0:.1f}s '
      f'cpu={time.process_time() - c0:.1f}s blosc_decodes={decodes[0]} range={lo.tolist()}..{hi.tolist()}', flush=True)
