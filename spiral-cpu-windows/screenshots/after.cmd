@echo off
rem "After" screenshot of the pull request "spiral-fitting: one Kimimaro process per slab on
rem Windows, and --slab-workers outside Linux": the branch, at the commit BRANCH. Started in a
rem console on a hidden desktop by capturer.py, which sets PY, CHRONO, REPO, BRANCH, PRED (the
rem prediction) and WORK (the code of the branch, extracted by git archive, and an output folder),
rem the last two on drive letters so that no user folder shows.
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
set "PYTHONDONTWRITEBYTECODE=1"
cd /d "%WORK%\branch\spiral-fitting"
cls
git -C "%REPO%" log -1 --format="code: branch spiral-slab-workers-windows %%h (%%cs) %%s" %BRANCH%
"%PY%" -c "import platform, sys; print('Windows', platform.release(), platform.version(), '- Python', sys.version.split()[0], '- no NVIDIA GPU')"
echo data: PHerc0332 surface_m7 surface prediction, level 0, z 4032 to 4096 (64 slices)
echo.
echo ^> python extract_surface_tracks.py --backend cpu --predictions %PRED% --out %WORK%\out\default.dbm --z-min 4032 --z-max 4096 --no-packed-store
"%PY%" "%CHRONO%" 300 "%PY%" extract_surface_tracks.py --backend cpu --predictions %PRED% --out %WORK%\out\default.dbm --z-min 4032 --z-max 4096 --no-packed-store
echo.
echo ^> python extract_surface_tracks.py --backend cpu --predictions %PRED% --out %WORK%\out\readme.dbm --z-min 4032 --z-max 4096 --no-packed-store --slab-workers 4 --kimimaro-parallel 1
"%PY%" "%CHRONO%" 300 "%PY%" extract_surface_tracks.py --backend cpu --predictions %PRED% --out %WORK%\out\readme.dbm --z-min 4032 --z-max 4096 --no-packed-store --slab-workers 4 --kimimaro-parallel 1
cd /d "%SystemRoot%"
echo fin> "%FIN%"
