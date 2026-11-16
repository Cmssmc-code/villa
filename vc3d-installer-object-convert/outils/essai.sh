#!/bin/sh
# essai.sh NOM BIN : copie neuve des 2 projets dans essais/NOM, lance VC3D (BIN) sur un bureau caché,
# ouvre p1.vcproj puis "projet été.vcproj" par le pont, relève segments.list, capture, puis ferme.
# Sortie complète : runs/NOM/essai.txt
NOM=$1; BIN=$2; GARDE=$3   # GARDE=garde : pas de copie neuve (réouverture du même dossier)
ICI=%USERPROFILE%/Dev/vesuvius/nuit-1611/convert-paquet/gui
D=%USERPROFILE%/Dev/vesuvius/donnees-convert-paquet
E=$D/essais/$NOM
W=%USERPROFILE%/Dev/vesuvius/donnees-convert-paquet/essais/$NOM
mkdir -p $ICI/runs/$NOM $ICI/captures/$NOM
OUT=$ICI/runs/$NOM/essai.txt
{
echo "=== essai $NOM, $(date '+%F %T'), BIN=$BIN"
[ "$GARDE" = garde ] || sh $D/copie.sh $NOM >/dev/null
echo "--- fichiers avant (sha256)"; (cd "$E" && sha256sum * )
echo "--- user_version / application_id des magasins"
python -I -c "
import sqlite3,sys,glob
for f in sorted(glob.glob(sys.argv[1]+'/*.vcobj')):
    c=sqlite3.connect('file:'+f+'?mode=ro',uri=True); print(f.split('/')[-1], 'user_version', c.execute('PRAGMA user_version').fetchone()[0], 'application_id', hex(c.execute('PRAGMA application_id').fetchone()[0])); c.close()
" "$E"
rm -f $ICI/session.json
python $ICI/lanceur.py $NOM "$BIN" 300 &
LP=$!
for i in $(seq 1 60); do [ -f $ICI/session.json ] && python $ICI/rpc.py ping --delai 5 >/dev/null 2>&1 && break; sleep 2; done
echo "--- ping"; python $ICI/rpc.py ping --delai 10
for P in p1 "projet été"; do
  echo "--- volume.open $P.vcproj"
  python $ICI/rpc.py volume.open "{\"path\": \"$W/$P.vcproj\"}" --delai 120
  sleep 4
  T=$(echo "$P" | tr -c 'a-z0-9\n' '_')
  echo "--- screenshot.capture ($T)"
  python $ICI/rpc.py screenshot.capture "{\"filePath\": \"%USERPROFILE%/Dev/vesuvius/nuit-1611/convert-paquet/gui/captures/$NOM/$T.png\"}" --delai 30
  touch "$ICI/CAPTURE-$NOM-$T"
  echo "--- segments.list"
  python $ICI/rpc.py segments.list --delai 60
  echo "--- points.list"
  python $ICI/rpc.py points.list --delai 60
  sleep 6
done
touch $ICI/STOP
wait $LP
echo "--- lanceur.log"; tail -12 $ICI/runs/$NOM/lanceur.log
echo "--- stderr VC3D (lignes store/convert/Unavailable)"
grep -a -i -n "store\|convert\|unavailable\|upgrade" $ICI/runs/$NOM/vc3d-stderr.log | head -20
echo "--- fichiers après (sha256)"; (cd "$E" && ls -la && sha256sum *.vcproj *.vcobj)
echo "--- user_version / application_id après"
python -I -c "
import sqlite3,sys,glob
for f in sorted(glob.glob(sys.argv[1]+'/*.vcobj')):
    c=sqlite3.connect('file:'+f+'?mode=ro',uri=True); print(f.split('/')[-1], 'user_version', c.execute('PRAGMA user_version').fetchone()[0], 'application_id', hex(c.execute('PRAGMA application_id').fetchone()[0])); c.close()
" "$E"
echo "--- .vcproj : différences avec la source"
diff $D/source/p1/p1.vcproj "$E/p1.vcproj" && echo "p1.vcproj inchangé"
diff "$D/source/projet-ete/projet été.vcproj" "$E/projet été.vcproj" && echo "projet été.vcproj inchangé"
echo "=== FIN $(date '+%T')"
} > $OUT 2>&1
cut -c1-400 $OUT | head -120
