import sys, time, numpy as np
sys.path.insert(0, r'%USERPROFILE%\Dev\vesuvius\wt-accel-py\spiral-fitting')
import extract_surface_tracks as m
a = m.open_predictions(r'%USERPROFILE%\Dev\vesuvius\donnees-spirale-cpu\PHerc0332-20251211183505-surface-m7-L2-th0.2.zarr\0')
print(type(a), a.shape, a.chunks, a.dtype, flush=True)
z0, step, n = 4032, 3, 16
zs = np.arange(z0, z0 + step * n, step)
zs = zs[zs // a.chunks[0] == zs[0] // a.chunks[0]]
print('zs', zs.tolist(), flush=True)
for k in range(2):
    t = time.perf_counter(); c = time.process_time(); x = a[slice(int(zs[0]), int(zs[-1]) + 1, step)]; print('slice step', time.perf_counter() - t, time.process_time() - c, x.shape, flush=True)
    t = time.perf_counter(); c = time.process_time(); y = a[zs]; print('index arr', time.perf_counter() - t, time.process_time() - c, y.shape, flush=True)
    print('equal', np.array_equal(x, y), flush=True)
