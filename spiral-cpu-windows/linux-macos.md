# `--slab-workers` on Linux and macOS (GitHub Actions)

Run: https://github.com/Cmssmc-code/villa-pr-checks/actions/runs/43586881689 - both jobs passed every check
([Ubuntu job](https://github.com/Cmssmc-code/villa-pr-checks/actions/runs/43586881689/job/132423197399),
[macOS job](https://github.com/Cmssmc-code/villa-pr-checks/actions/runs/43586881689/job/132423197190);
workflow and scripts at [abec804](https://github.com/Cmssmc-code/villa-pr-checks/tree/abec80483575b007eef7b43eecc30c0eca2b02b0)).

- Tested: Cmssmc-code/villa `spiral-slab-workers-windows` at `bc2c48d07db54fdb4049e06bd34f35091655b5f3` (the head of this PR: both commits and the tests), against ScrollPrize/villa `main` at `97fb9336c8898be27e78eff8cd23ce5e7185ec0a`, both fetched by partial clone in each job.
- Runners: `ubuntu-latest` (Ubuntu 26.04.1 LTS x86_64, 4 CPUs) and `macos-latest` (macOS 26.7.2 arm64, 3 CPUs). Python 3.14.10 (lower bound of `requires-python`), numpy 2.5.4, zarr 3.4.2, kimimaro 5.9.0; vc-reader built from `main`'s `vc_reader/` (same git tree on the branch).
- Data: chunk row 21 of the public PHerc0332 `surface_m7` prediction, level 0 (`https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0332/representations/predictions/surfaces/20251211183505-surface-20260413222639-surface-m7-L2-th0.2.zarr/0`): 195 chunk files, 45.2 MB, SHA-256 of `.zarray` and chunks `0bed6251aefa6eb4...`; z 4032 to 4096, the range of the Windows default-settings runs.
- Command, in each tree's `spiral-fitting/`: `python extract_surface_tracks.py --backend cpu --predictions <crop>/0 --out <run>.dbm --z-min 4032 --z-max 4096 --no-packed-store [options]`. Tests: `python -m pytest -q tests/test_cc_labels.py tests/test_extract_surface_tracks.py`.

| | Ubuntu 26.04 x86_64 | macOS 26.7.2 arm64 |
|---|---|---|
| tests, `main` | 31 passed, 9 skipped, 18 fork warnings | 31 passed, 9 skipped, 18 fork warnings |
| tests, branch (2 more tests) | 33 passed, 9 skipped, 18 fork warnings | 33 passed, 9 skipped, no warning |
| `main`, defaults | exit 0, 179.0 s | exit 0, 223.0 s |
| branch, defaults | exit 0, 186.2 s | exit 0, 212.1 s |
| `main`, `--kimimaro-parallel 1` | exit 0, 14.5 s | exit 0, 18.1 s |
| branch, `--kimimaro-parallel 1` | exit 0, 14.5 s | exit 0, 20.1 s |
| branch, `--slab-workers 2 --kimimaro-parallel 1` | exit 0, 13.0 s; 6 forked workers seen, at most 2 at once | exit 0, 23.3 s; 6 spawned workers seen, at most 2 at once |
| `main`, `--slab-workers 2 --kimimaro-parallel 1` | exit 1 after 0.1 s: `NameError: name 'sys' is not defined` | exit 1 after 0.3 s: same `NameError` |
| every finished run | 100 keys, 1988 tracks, 127737 vertices | 100 keys, 1981 tracks, 127546 vertices |
| branch `--slab-workers 2` vs `main` `--kimimaro-parallel 1` | same keys, same pickled bytes for 100/100 keys | same keys, same bytes 100/100 |
| branch vs `main`, `--kimimaro-parallel 1` | same keys, same bytes 100/100 | same keys, same bytes 100/100 |
| branch vs `main`, defaults | same keys, same set of tracks 100/100, same bytes 79/100 | same keys, same set of tracks 100/100, same bytes 74/100 |
| `main` defaults vs `main` `--kimimaro-parallel 1` | same keys, same set of tracks 100/100, same bytes 84/100 | same keys, same set of tracks 100/100, same bytes 67/100 |

- On `main`, `parse_args` reads `sys.platform` without importing `sys`, so `--slab-workers 2` stops on Linux as well as on macOS; the branch imports it. The branch's workers are forked on Linux (same command line as the run) and spawned on macOS (`spawn_main`), as listed by `ps` every second.
- With the default eight Kimimaro processes per slab, some keys get the same set of tracks with other pickled bytes, between two runs of `main` as well. The spiral-fitting tests compare track sets for this reason ("Kimimaro's own parallelism can return skeletons in another order").
- The eight Kimimaro processes per slab are about 12 times slower than one process on these runners too (Ubuntu 179.0 s against 14.5 s, macOS 223.0 s against 18.1 s, on `main`). The branch leaves that default alone outside Windows.
- The fork warnings are all in `tests/test_cc_labels.py`, which holds the slab-worker tests (`DeprecationWarning: This process ... is multi-threaded, use of fork() may lead to deadlocks in the child`). On macOS they appear with `main` only: the branch spawns its workers there.
- The 9 skipped tests are the same in both trees: 5 need numba, 1 needs brook (GPU backend), 3 need a fixture of the `vesuvius/` package, outside the partial clone.
- Timings: one run each on shared GitHub runners, not a benchmark.
- Earlier runs of the same workflow on the previous head (`6589e78ab`, before the two tests were added) gave the same results: https://github.com/Cmssmc-code/villa-pr-checks/actions/runs/43582180569 passed; https://github.com/Cmssmc-code/villa-pr-checks/actions/runs/43580445342 failed at its summary step only, because its checks expected `main`'s `--slab-workers 2` to work on Linux.
- Logs: [logs/ci-linux.log](logs/ci-linux.log) and [logs/ci-macos.log](logs/ci-macos.log), the job logs of the run (colour codes removed). The run keeps the per-run logs, `compare-*.txt` files and summaries as artifacts.
