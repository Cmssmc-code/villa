#!/usr/bin/env bash
# cli-essai.sh : the user path the error message asks for ("convert upstream stores with vc_object_convert"),
# with only the files of an installer, before (installer without the commit) and after (installer with it).
# Data: fresh copies of the two real projects of 2026-11-15 (stores at schema 21, written by the official VC3D 97fb933;
# their volume is PHerc1447 20250521151220 on the public bucket).
D=%USERPROFILE%/Dev/vesuvius/nuit-1611/convert-paquet
S=%USERPROFILE%/Dev/vesuvius/donnees-convert-paquet
TO=/usr/bin/timeout
uv() { PYTHONIOENCODING=utf-8 python -I -c "
import sqlite3,sys
for f in sys.argv[1:]:
    c=sqlite3.connect('file:'+f+'?mode=ro',uri=True); print(f.split('/')[-1], 'user_version', c.execute('PRAGMA user_version').fetchone()[0]); c.close()
" "$@"; }
for etape in avant apres; do
  B=$D/inst-$etape/bin
  E=$S/essais/cli-$etape
  rm -rf "$E"; mkdir -p "$E/old" "$E/new"
  cp -p $S/source/p1/p1.vcproj $S/source/p1/p1.vcobj "$S/source/projet-ete/projet été.vcproj" "$S/source/projet-ete/projet été.vcobj" "$E/old/"
  echo "=== $(date '+%F %T') $etape : installer tree $B"
  echo "--- programs in bin: $(ls $B/*.exe | wc -l) ; vc_object_convert.exe present: $([ -f $B/vc_object_convert.exe ] && echo yes || echo NO)"
  echo "--- stores before conversion"; uv "$E/old/p1.vcobj" "$E/old/projet été.vcobj"
  for P in p1 "projet été"; do
    echo "\$ cd <installer>\\bin && vc_object_convert \"old\\$P.vcobj\" \"new\\$P.vcobj\""
    if [ -f $B/vc_object_convert.exe ]; then
      (cd $B && PATH="$B:/c/Windows/System32:/c/Windows" $TO 300 ./vc_object_convert.exe "$(cygpath -w "$E/old/$P.vcobj")" "$(cygpath -w "$E/new/$P.vcobj")" 2>&1 | head -20; echo "rc=${PIPESTATUS[0]}")
      cp -p "$E/old/$P.vcproj" "$E/new/"
    else
      (cd $B && cmd //c "vc_object_convert.exe --help" 2>&1 | head -3; echo "rc=${PIPESTATUS[0]}")
    fi
  done
  echo "--- stores after conversion"; ls "$E/new"/*.vcobj >/dev/null 2>&1 && uv "$E/new"/*.vcobj || echo "(no converted store)"
  echo "--- originals unchanged:"; (cd "$E/old" && sha256sum p1.vcobj "projet été.vcobj"); (cd $S/source && sha256sum p1/p1.vcobj "projet-ete/projet été.vcobj")
done
echo "FIN rc=0 $(date '+%F %T')"
