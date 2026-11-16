#!/bin/bash
S=%USERPROFILE%/Dev/vesuvius/nuit-1611/sceptique-spirale-yx-range
D='%USERPROFILE%\Dev\vesuvius\donnees-sceptique-spirale-yx-range\PHerc0332-20251211183505-surface-m7-L2-th0.2.zarr\0'
export PYTHONPATH='%USERPROFILE%\Dev\vesuvius\donnees-spirale-cpu\extra'
PY=%USERPROFILE%/Dev/vesuvius/venv-pywin/Scripts/python.exe
cd $S
for c in "4032 4096" "4032 4416"; do for t in A B; do
  date +%T; timeout 400 $PY phase.py "$S/$t/spiral-fitting" "$D" $c 2>&1 | grep -v "finding yx range" | tail -3
done; done
for t in A B; do
  date +%T; rm -rf $S/out-$t.dbm*
  /usr/bin/time -f "FULL $t wall=%es user=%Us sys=%Ss" timeout 600 $PY $S/$t/spiral-fitting/extract_surface_tracks.py --backend cpu --predictions "$D" --out "$S/out-$t.dbm" --z-min 4032 --z-max 4096 --no-packed-store --kimimaro-parallel 1 > $S/full-$t.log 2>&1; echo "rc=$?"; tail -1 $S/full-$t.log
done
$PY cmp.py out-A.dbm out-B.dbm
echo "FIN rc=$?"
