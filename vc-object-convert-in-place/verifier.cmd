@echo off
setlocal
chcp 65001 >nul
rem Check of "vc_object_convert --in-place fails on Windows".
rem No input, no Internet, nothing installed. Under 1 minute. No window is opened.
rem Runs `vc_object_convert --in-place <store>` on fresh copies of two real object stores (VC3D projects made on
rem 2026-11-15 with the official package VC3D-97fb933-2026-11-13-win64, scroll PHerc1447, store schema 21):
rem   1. with the binary of main 2d3fb38d3 (binaire\main)      -> expected: exit code 1, "cannot replace file",
rem      store still schema 21 ;
rem   2. with the binary built from the fix (binaire\corrige)  -> expected: exit code 0, store now schema 22,
rem      integrity ok, same rows as a normal two-path conversion.
rem Work is done in %TEMP%\verifier-vc3d\convert-in-place (deleted at the end). The stores in donnees\ are not modified.
set "BASE=%USERPROFILE%\Dev\vesuvius"
set "OUT=%~dp0"
set "PY=%BASE%\.venv\Scripts\python.exe"
if not exist "%PY%" goto :no_python
if not exist "%OUT%verifier.py" goto :no_script
"%PY%" -I "%OUT%verifier.py" verifier
goto :end

:no_python
echo ECART : Python not found (%PY%).
goto :end

:no_script
echo ECART : verifier.py not found in %OUT%.
goto :end

:end
pause
