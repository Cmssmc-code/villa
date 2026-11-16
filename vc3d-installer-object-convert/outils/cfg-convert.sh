#!/usr/bin/env bash
# convert-paquet: configuration-only check (no compilation) in the tree wt-paquet-cfg.
# Before (main 2d3fb38d3) then after (branch vc3d-installer-object-convert): which install rules does CMake
# generate for vc_object_convert, and in which component? The Windows installer (CPACK_COMPONENTS_ALL
# vc_runtime), the macOS app, the AppImage and the Docker image only take the vc_runtime component.
# Usage: bash cfg-convert.sh OUTDIR   (OUTDIR gets the logs; last line FIN rc=)
W=%USERPROFILE%/Dev/vesuvius/wt-paquet-cfg
OUT=${1:-%USERPROFILE%/Dev/vesuvius/nuit-1611/convert-paquet/cfg}
mkdir -p "$OUT"
cd "$W/volume-cartographer" || { echo "FIN rc=9"; exit 9; }
if [ -n "$(git -C "$W" status --short)" ]; then echo "wt-paquet-cfg not clean, stop"; echo "FIN rc=8"; exit 8; fi
rc=0
B=build/ci-windows-mingw
for etape in avant apres; do
  if [ "$etape" = avant ]; then ref=2d3fb38d3; else ref=vc3d-installer-object-convert; fi
  git -C "$W" checkout -q --detach "$ref"
  echo "=== $(date '+%F %T') $etape : HEAD $(git -C "$W" rev-parse --short=9 HEAD) ; git status : [$(git -C "$W" status --short)]"
  rm -f $B/build.ninja
  echo "\$ cmake --preset ci-windows-mingw"
  cmake --preset ci-windows-mingw > "$OUT/cfg-$etape-cmake.log" 2>&1
  r=$?; echo "cmake rc=$r"; [ $r -ne 0 ] && rc=$r && tail -20 "$OUT/cfg-$etape-cmake.log"
  grep -i "CPACK_COMPONENTS_ALL" -r --include=CPackConfig.cmake $B | head -2 | sed 's#.*CPackConfig.cmake:#CPackConfig.cmake: #'
  echo "\$ install rules for vc_object_convert.exe in $B/**/cmake_install.cmake (component of each rule):"
  n_all=0; n_rt=0
  while IFS= read -r f; do
    awk -v F="$f" '/^if\(CMAKE_INSTALL_COMPONENT/ {comp=$0} /file\(INSTALL .*vc_object_convert\.exe"\)/ {print F ":" NR ": " comp}' "$f"
  done < <(grep -rl --include=cmake_install.cmake 'vc_object_convert\.exe")' $B) > "$OUT/cfg-$etape-regles.txt"
  sed 's#%USERPROFILE%/Dev/vesuvius/wt-paquet-cfg/volume-cartographer/##' "$OUT/cfg-$etape-regles.txt"
  n_all=$(wc -l < "$OUT/cfg-$etape-regles.txt")
  n_rt=$(grep -c 'STREQUAL "vc_runtime"' "$OUT/cfg-$etape-regles.txt")
  echo "RESULT $etape : vc_object_convert.exe install rules = $n_all ; in component vc_runtime (installer) = $n_rt"
done
git -C "$W" checkout -q --detach 2d3fb38d3
echo "wt-paquet-cfg back on $(git -C "$W" rev-parse --short=9 HEAD), git status : [$(git -C "$W" status --short)]"
echo "FIN rc=$rc $(date '+%F %T')"
