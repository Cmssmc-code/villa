#!/bin/bash
S=%USERPROFILE%/Dev/vesuvius/nuit-1611/sceptique-spirale-yx-range
W=%USERPROFILE%/Dev/vesuvius/nuit-1611/sceptique-spirale-yx-range
D=%USERPROFILE%/Dev/vesuvius/donnees-sceptique-spirale-yx-range/PHerc0332-20251211183505-surface-m7-L2-th0.2.zarr/0
export PYTHONPATH='%USERPROFILE%\Dev\vesuvius\donnees-spirale-cpu\extra'
PY=%USERPROFILE%/Dev/vesuvius/venv-pywin/Scripts/python.exe
cd $S
for t in A B; do
  date +%T; rm -rf $S/out-$t.dbm*
  $PY mesure.py FULL-$t $W/mesures.txt 600 -- $PY $W/$t/spiral-fitting/extract_surface_tracks.py --backend cpu --predictions $D --out $W/out-$t.dbm --z-min 4032 --z-max 4096 --no-packed-store --kimimaro-parallel 1 > $S/full-$t.log 2>&1
  tail -1 $S/full-$t.log
done
$PY cmp.py out-A.dbm out-B.dbm
echo "FIN rc=$?"
