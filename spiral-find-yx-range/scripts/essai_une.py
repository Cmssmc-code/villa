import sys, time, numpy as np
sys.path.insert(0, r'%USERPROFILE%\Dev\vesuvius\wt-accel-py\spiral-fitting')
import extract_surface_tracks as m
a = m.open_predictions(r'%USERPROFILE%\Dev\vesuvius\donnees-spirale-cpu\PHerc0332-20251211183505-surface-m7-L2-th0.2.zarr\0')
for z in (4032, 4035):
    t = time.perf_counter(); c = time.process_time(); x = a[z]; print('a[z]', z, round(time.perf_counter() - t, 2), round(time.process_time() - c, 2), flush=True)
    t = time.perf_counter(); c = time.process_time(); yx = np.stack(np.where(x > 0), axis=-1); print(' where', len(yx), round(time.perf_counter() - t, 2), round(time.process_time() - c, 2), flush=True)
