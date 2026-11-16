@echo off
setlocal
chcp 65001 >nul
rem Vérifie la correction "VC3D packaging: ship vc_object_convert with VC3D" (branche locale vc3d-installer-object-convert).
rem
rem 0. Empreintes des deux installateurs téléchargés depuis la CI officielle lancée sur le fork
rem    (attendu : les sha256 notés dans before.txt et after.txt).
rem 1. (quelques secondes) Liste les deux installateurs :
rem    AVANT = main + #2557 (fabrication 43774798604), APRÈS = main + #2557 + ce commit (fabrication 43774438503).
rem    Attendu : AVANT = aucune ligne vc_object_convert.exe ; APRÈS = une ligne bin\vc_object_convert.exe.
rem 2. (quelques secondes) Convertit une copie d'un vrai ancien magasin (p1.vcobj, schéma 21, fait le 15/11 avec le VC3D
rem    officiel 97fb933 sur PHerc1447) avec le vc_object_convert.exe sorti de l'installateur APRÈS.
rem    Attendu : rc=0, "source_schema": 21, "target_schema": 22, "validation": "ok".
rem Aucune fenêtre ne s'ouvre. Moins d'une minute.
set "BASE=%USERPROFILE%\Dev\vesuvius"
set "OUT=%BASE%\preuves-vc3d-installateur-convert"
set "Z=%BASE%\outils\scratch\7z\bin\7z.exe"
set "AV=%BASE%\donnees-convert-paquet\ci-avant\VC3D-1a02553-2026-11-16-win64.exe"
set "AP=%BASE%\donnees-convert-paquet\ci-apres\VC3D-f546487-2026-11-16-win64.exe"
set "CONV=%BASE%\nuit-1611\convert-paquet\inst-apres\bin\vc_object_convert.exe"
set "SRC=%BASE%\donnees-convert-paquet\source\p1\p1.vcobj"
if not exist "%OUT%\journaux" mkdir "%OUT%\journaux"

echo === 0. Empreintes des installateurs de la CI ===
echo Attendu AVANT : f33601e9c96b2179ec61a7d5b392cee37315f3fb89f1ff7a3234ffc0181da870
echo Obtenu  AVANT :
certutil -hashfile "%AV%" SHA256 | findstr /r "^[0-9a-f][0-9a-f]*$"
echo Attendu APRÈS : 10c622f218a088b0a8ce70190d6818310857897a2443aa0818d9c8cc67ab77f8
echo Obtenu  APRÈS :
certutil -hashfile "%AP%" SHA256 | findstr /r "^[0-9a-f][0-9a-f]*$"

echo.
echo === 1. vc_object_convert.exe dans les installateurs de la CI ===
echo Attendu : AVANT = aucune ligne ; APRÈS = bin\vc_object_convert.exe
echo --- AVANT (main + #2557) :
"%Z%" l -ba "%AV%" | findstr /i /c:"vc_object_convert.exe" || echo     (aucune ligne)
echo --- APRÈS (main + #2557 + ce commit) :
"%Z%" l -ba "%AP%" | findstr /i /c:"vc_object_convert.exe" || echo     (aucune ligne)

echo.
echo === 2. Conversion d'un vrai ancien magasin avec l'outil de l'installateur APRÈS ===
echo Attendu : rc=0, source_schema 21, target_schema 22, validation ok
set "T=%OUT%\journaux\verif-conversion"
if exist "%T%" rmdir /s /q "%T%"
mkdir "%T%"
copy /y "%SRC%" "%T%\p1-ancien.vcobj" >nul
"%CONV%" "%T%\p1-ancien.vcobj" "%T%\p1-converti.vcobj" > "%T%\sortie.json" 2>&1
echo Obtenu : rc=%errorlevel%
findstr /c:"source_schema" /c:"target_schema" /c:"\"validation\"" "%T%\sortie.json"

echo.
echo Journaux : %OUT%\journaux
pause
