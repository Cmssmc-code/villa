# Earlier runs

Runs made before `verifier.py`, on the same PC (Windows 11, Intel Core i5-12450H, 12 logical processors, 15.7 GB RAM, no NVIDIA GPU) and the same local copy of the PHerc0332 `surface_m7` prediction, level 0, all with `--backend cpu --no-packed-store`. Each run was timed by [`mesure.py`](mesure.py) in a Windows job object: its `MESURE` line gives the wall time, the CPU time, the processes started and the peak committed memory of the run. [`compare_dbm.py`](compare_dbm.py) compares two DBMs key by key.

- `tree=main`: the code run is the `spiral-fitting` folder of villa main 97fb933, exported before the runs. The commit printed under `=== commit:` is the head of the branch at the time, 5562cd85c, for every run: it is not the code that ran.
- `tree=branch`: the branch at its first commit, 5562cd85c. The second commit only changes the default of `--kimimaro-parallel` on Windows; these runs set it to 1.
- `fin-main-k1-a`, `fin-main-k1-b`: main, `--kimimaro-parallel 1`, z 4032 to 4416 (384 slices): 76.9 s and 89.5 s, 3 processes, a peak committed memory of 1348 and 1350 MB.
- `fin-br-sw4-a`, `fin-br-sw4-b`: branch, `--slab-workers 4 --kimimaro-parallel 1`, same slices: 65.4 s and 54.6 s, 15 processes, 5222 and 4909 MB. `fin-br-sw2-a`, `--slab-workers 2`: 65.5 s, 9 processes, 2630 MB.
- `compare-fin-384.txt`: the DBMs of these five runs have the same 120 keys, with the same pickled bytes.
- `fin-main-k8-64`: main, default settings, z 4032 to 4096 (64 slices), stopped by its 360 s limit (`FIN rc=1`).
- `fin-main-k1-64`: main, `--kimimaro-parallel 1`, the same 64 slices: 29.9 s, 3 processes, 1344 MB.
- `tests-main.txt`: `python -m pytest -q tests/test_cc_labels.py tests/test_extract_surface_tracks.py` on main: 2 failed with `ValueError: cannot find context for 'fork'`, 29 passed, 9 skipped, in 638.93 s.

Other jobs ran on the PC during these runs, so their times can be longer than on a quiet PC. For example, on the same 64 slices, main's default run was stopped here after 360 s, with 516 processes started, while in [`../full-run`](../full-run/compare.log) it finished in 246.3 s, with 787 processes; `--kimimaro-parallel 1` took 29.9 s here and 22.2 s there. The message of the commit that changes the default on Windows ("not finished after 6 minutes (516 processes started), against 30 s") quotes `fin-main-k8-64` and `fin-main-k1-64`.
