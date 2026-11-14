@echo off
rem "Before" screenshot of the pull request "spiral-fitting: one Kimimaro process per slab on
rem Windows, and --slab-workers outside Linux": villa main, unchanged. Started in a console on a
rem hidden desktop by capturer.py, which sets PY, CHRONO, REPO, MAIN, PRED (the prediction) and
rem WORK (the code of main, extracted by git archive, and an output folder), the last two on drive
rem letters so that no user folder shows.
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
set "PYTHONDONTWRITEBYTECODE=1"
cd /d "%WORK%\main\spiral-fitting"
cls
git -C "%REPO%" log -1 --format="code: villa main %%h (%%cs) %%s" %MAIN%
"%PY%" -c "import platform, sys; print('Windows', platform.release(), platform.version(), '- Python', sys.version.split()[0], '- no NVIDIA GPU')"
echo data: PHerc0332 surface_m7 surface prediction, level 0, z 4032 to 4096 (64 slices)
echo.
echo ^> python extract_surface_tracks.py --backend cpu --predictions %PRED% --out %WORK%\out\readme.dbm --z-min 4032 --z-max 4096 --no-packed-store --slab-workers 4 --kimimaro-parallel 1
"%PY%" "%CHRONO%" 300 "%PY%" extract_surface_tracks.py --backend cpu --predictions %PRED% --out %WORK%\out\readme.dbm --z-min 4032 --z-max 4096 --no-packed-store --slab-workers 4 --kimimaro-parallel 1
echo.
echo ^> python extract_surface_tracks.py --backend cpu --predictions %PRED% --out %WORK%\out\default.dbm --z-min 4032 --z-max 4096 --no-packed-store
"%PY%" "%CHRONO%" 420 "%PY%" extract_surface_tracks.py --backend cpu --predictions %PRED% --out %WORK%\out\default.dbm --z-min 4032 --z-max 4096 --no-packed-store
cd /d "%SystemRoot%"
echo fin> "%FIN%"
