@echo off
setlocal
chcp 65001 >nul
rem Check of "vc_object_convert --remove-history-and-disable fails on Windows" (second commit of the PR).
rem No input, no Internet, nothing installed. Under 1 minute. No window is opened.
rem On fresh copies of two real object stores (..\donnees, VC3D projects of scroll PHerc1447), converted to schema 22:
rem   AVANT : binary of main 2d3fb38d3  -> expected: exit code 1, "cannot replace file", history still enabled;
rem   APRES : fixed build               -> expected: exit code 0, history removed, same objects, integrity ok,
rem           --enable-history works, --in-place still works.
rem Work is done in %TEMP%\verifier-vc3d\convert-history (deleted at the end).
set "BASE=%USERPROFILE%\Dev\vesuvius"
set "OUT=%~dp0"
set "PY=%BASE%\.venv\Scripts\python.exe"
if not exist "%PY%" goto :no_python
if not exist "%OUT%verifier.py" goto :no_script
"%PY%" -I "%OUT%verifier.py"
goto :end

:no_python
echo ECART : Python not found (%PY%).
goto :end

:no_script
echo ECART : verifier.py not found in %OUT%.
goto :end

:end
pause
