#!/bin/bash
# Module tests on origin/main (git archive) then on the branch, same venv.
export PYTHONPATH='%USERPROFILE%/Dev/vesuvius/donnees-spirale-cpu/extra'
R=%USERPROFILE%/Dev/vesuvius
J=$R/nuit-1611/acceleration-python/journaux
PY=$R/venv-pywin/Scripts/python.exe
for side in main branche; do
  if [ $side = main ]; then dir=$R/nuit-1611/acceleration-python/main-arbre/spiral-fitting; else dir=$R/wt-accel-py/spiral-fitting; fi
  cd $dir
  echo "=== $(date +%H:%M:%S) $side in $dir"
  timeout 900 $PY -m pytest -q -p no:cacheprovider tests/test_cc_labels.py tests/test_extract_surface_tracks.py > $J/tests-$side.txt 2>&1
  echo "rc=$? $(tail -1 $J/tests-$side.txt)"
done
echo "FIN rc=0"
