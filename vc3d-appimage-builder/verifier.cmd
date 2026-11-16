@echo off
setlocal
chcp 65001 >nul
rem Vérifie la correction "VC3D AppImage: build on the builder image that has concurrentqueue".
rem Lecture seule, environ 10 secondes, rien à installer (Python + gh déjà sur le PC, accès Internet).
rem  [1] calcule l'étiquette d'image que main attend (Dockerfile + install_build_deps.sh, comme ci.sh) ;
rem  [2] lit sur ghcr.io (sans compte) l'étiquette de l'ancienne image épinglée et de la nouvelle ;
rem  [3] affiche le résultat des fabrications Linux avant / après (gh, lecture seule).
rem Attendu : ancienne = 675836fc3d478d17 (différente), nouvelle = 6309e96d71462b0a (identique à main),
rem           fabrications "before" = failure, "after" = success, puis "Obtained: OK, the new pin matches main".
set "OUT=%USERPROFILE%\Dev\vesuvius\preuves-vc3d-appimage-concurrentqueue"
echo === Attendu ===
echo   [1] 6309e96d71462b0a
echo   [2] pinned on main deps-hash=675836fc3d478d17 ; new pin deps-hash=6309e96d71462b0a
echo   [3] before x3 = failure ; pin = failure (erreur suivante, corrigee par #2557) ; after = success ; real = success
echo   Obtained: OK, the new pin matches main
echo.
echo === Obtenu ===
python -I "%OUT%\verifier.py"
echo.
echo Code de retour : %ERRORLEVEL% (0 = preuve OK)
echo Essai sur un vrai segment avec l'AppImage : voir "%OUT%\appimage-reel.txt"
pause
