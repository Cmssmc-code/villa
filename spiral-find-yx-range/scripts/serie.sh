#!/bin/bash
# A/B alternated, 3 rounds: A = origin/main 2d3fb38d3 (git archive), B = branch perf-python-1611.
# usage: bash serie.sh <z_min> <z_max> <tag>
export PYTHONPATH='%USERPROFILE%/Dev/vesuvius/donnees-spirale-cpu/extra'
R=%USERPROFILE%/Dev/vesuvius
J=$R/nuit-1611/acceleration-python/journaux
PY=$R/venv-pywin/Scripts/python.exe
MES='%USERPROFILE%/Dev/vesuvius/nuit-1611/acceleration-python/mesure.py'
LOG='%USERPROFILE%/Dev/vesuvius/nuit-1611/acceleration-python/journaux/mesures.txt'
DATA='%USERPROFILE%/Dev/vesuvius/donnees-spirale-cpu/PHerc0332-20251211183505-surface-m7-L2-th0.2.zarr/0'
OUT='%USERPROFILE%/Dev/vesuvius/donnees-acceleration-python'
for r in 1 2 3; do
  for side in A B; do
    if [ $side = A ]; then dir=$R/nuit-1611/acceleration-python/main-arbre/spiral-fitting; else dir=$R/wt-accel-py/spiral-fitting; fi
    name=$side$r-$3
    rm -f $R/donnees-acceleration-python/$name.dbm*
    cd $dir
    echo "=== $(date +%H:%M:%S) $name in $dir"
    $PY $MES $name "$LOG" 600 -- $PY extract_surface_tracks.py --backend cpu --predictions "$DATA" --out "$OUT/$name.dbm" --z-min $1 --z-max $2 --no-packed-store --kimimaro-parallel 1 > $J/run-$name.txt 2>&1
    echo "rc=$? $(tail -1 $J/run-$name.txt)"
  done
done
echo "FIN rc=0"
