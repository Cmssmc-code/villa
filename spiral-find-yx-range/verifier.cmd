@echo off
rem Replays the proof of spirale-yx-range in a few minutes, installs nothing.
rem A = origin/main 2d3fb38d3 (git archive), B = branch spiral-find-yx-range-read-rows (27a2feefe).
rem Data: local mirror of PHerc0332 surface predictions m7-L2-th0.2 (zarr v2, chunk rows z 21 and 22).
setlocal
set R=%USERPROFILE%\Dev\vesuvius
set PYTHONPATH=%R%\donnees-spirale-cpu\extra
set PY=%R%\venv-pywin\Scripts\python.exe
set A=%R%\nuit-1611\acceleration-python\main-arbre\spiral-fitting
set B=%R%\wt-accel-py\spiral-fitting
set D=%R%\donnees-acceleration-python

echo === 1. Branch content
git -C "%B%" log --oneline -1
echo.
echo === 2. find_yx_range only, z 4032..4096, A then B (one round)
echo EXPECTED: (A reads 22 slices one by one, B reads 2 batches) both print
echo           range [768, 384] .. [3455, 3839]; B takes less wall and cpu time.
echo OBTAINED:
"%PY%" "%~dp0scripts\phase_yx.py" "%A%" "%B%" 4032 4096 1 2>nul
echo.
echo === 3. Full extract_surface_tracks runs recorded tonight (same command, same data)
echo EXPECTED: RESULT IDENTICAL, fingerprint 0795c83cd244afe5 for every store
echo OBTAINED:
"%PY%" "%~dp0scripts\compare.py" "%D%\A1-64p2.dbm" "%D%\B1-64p2.dbm" "%D%\A2-64p2.dbm" "%D%\B2-64p2.dbm" "%D%\A3-64p2.dbm" "%D%\B3-64p2.dbm"
echo.
echo === 4. Timings recorded tonight (mesure.py: wall and cpu of the whole process tree)
echo EXPECTED: B lines have about half the cpu of A lines
echo OBTAINED:
findstr /c:"64p2" "%~dp0journaux\mesures.txt"
echo.
pause
