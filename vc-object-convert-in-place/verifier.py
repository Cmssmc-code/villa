"""Proof for "vc_object_convert --in-place fails on Windows".

Usage : python -I verifier.py avant|apres|verifier

Data : the two real object stores (schema 21) of the VC3D projects made on 2026-11-15 with the official Windows
package VC3D-97fb933-2026-11-13-win64 on scroll PHerc1447 (copies in donnees\\). They are never modified: every run
works on a fresh copy in a temporary folder.

avant    : runs `vc_object_convert --in-place <store>` with the binary of main 2d3fb38d3 (binaire\\main).
apres    : same command, same stores, with the binary built from the fix (binaire\\corrige), then compares the
           result with a normal two-path conversion of the same store, and runs the command a second time.
verifier : both, short output (expected / obtained).
"""
import hashlib
import json
import os
import pathlib
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time

ICI = pathlib.Path(__file__).resolve().parent
BASE = ICI.parent
DLL = [BASE / "outils-vc3d" / "bin-main-2d3fb38d3", BASE / "outils-vc3d" / "msys64" / "ucrt64" / "bin"]
EXE = {"main": ICI / "binaire" / "main" / "vc_object_convert.exe",
       "corrige": ICI / "binaire" / "corrige" / "vc_object_convert.exe"}
VERSION = {"main": "main 2d3fb38d3 (unchanged)", "corrige": "main 2d3fb38d3 + commit e8b3d3dd9 (ConvertStore.cpp only)"}
MAGASINS = [("p1", "p1.vcobj"), ("projet-ete", "projet été.vcobj")]
TRAVAIL = pathlib.Path(tempfile.gettempdir()) / "verifier-vc3d" / "convert-in-place"
JOURNAUX = ICI / "journaux"


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def inspecte(p):
    """user_version, row count of every table and integrity_check, read on a private copy of the file."""
    copie = p.parent / "inspect.tmp"
    shutil.copyfile(p, copie)
    try:
        c = sqlite3.connect(str(copie))
        version = c.execute("PRAGMA user_version").fetchone()[0]
        comptes = {}
        for (nom,) in c.execute("SELECT name FROM sqlite_schema WHERE type='table' ORDER BY 1").fetchall():
            try:
                comptes[nom] = c.execute(f'SELECT count(*) FROM "{nom}"').fetchone()[0]
            except sqlite3.Error as e:
                comptes[nom] = "unreadable: " + str(e)[:60]
        integrite = c.execute("PRAGMA integrity_check").fetchone()[0]
        c.close()
    finally:
        for s in ("", "-wal", "-shm", "-journal"):
            try:
                os.remove(str(copie) + s)
            except OSError:
                pass
    return version, comptes, integrite


def lance(exe, args, cwd):
    env = dict(os.environ)
    env["PATH"] = os.pathsep.join(str(d) for d in DLL) + os.pathsep + env.get("PATH", "")
    t0 = time.time()
    try:
        r = subprocess.run([str(exe)] + args, cwd=str(cwd), env=env, stdin=subprocess.DEVNULL,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=180)
        rc, brut = r.returncode, r.stdout
    except subprocess.TimeoutExpired as e:
        rc, brut = "TIMEOUT 180 s", e.stdout or b""
    try:
        texte = brut.decode("utf-8")
    except UnicodeDecodeError:
        texte = brut.decode("cp1252", errors="replace")
    return rc, texte.replace("\r\n", "\n"), time.time() - t0


def fichiers(d):
    return sorted(f"{p.stat().st_size:>9}  {p.name}" for p in d.iterdir() if p.is_file())


def extrait(texte, n=6):
    lignes = texte.rstrip("\n").split("\n")
    if len(lignes) <= 2 * n + 2:
        return lignes
    return lignes[:n] + [f"[... {len(lignes) - 2 * n} more lines, full output in journaux\\ ...]"] + lignes[-n:]


def essai(quoi, dossier, nom, sortie, complet):
    """One run of --in-place on a fresh copy. Returns a dict of facts."""
    w = TRAVAIL / quoi / dossier
    shutil.rmtree(w, ignore_errors=True)
    w.mkdir(parents=True)
    for f in (ICI / "donnees" / dossier).iterdir():
        if ".vcobj" in f.name:
            shutil.copyfile(f, w / f.name)
    store = w / nom
    v0, c0, _ = inspecte(store)
    s0 = sha(store)
    rc, texte, duree = lance(EXE[quoi], ["--in-place", nom], w)
    JOURNAUX.mkdir(exist_ok=True)
    (JOURNAUX / f"{quoi}-{dossier}-in-place.txt").write_text(texte, encoding="utf-8")
    v1, c1, integ = inspecte(store)
    restes = [p.name for p in w.iterdir() if ".convert-" in p.name or ".members-" in p.name]
    faits = dict(rc=rc, avant=v0, apres=v1, integrite=integ, restes=restes, comptes=c1, texte=texte,
                 inchange=(sha(store) == s0), dossier=w, store=store)
    if complet:
        sortie(f"--- store: {nom}  (copy of donnees\\{dossier}\\, sha256 {s0[:16]}..., schema {v0})")
        sortie(f"$ cd {w}")
        sortie(f"$ vc_object_convert.exe --in-place \"{nom}\"")
        for ligne in extrait(texte):
            sortie("  " + ligne)
        sortie(f"exit code: {rc}   ({duree:.1f} s)")
        sortie(f"schema (PRAGMA user_version) of {nom} after the command: {v1}   integrity_check: {integ}")
        sortie("files in the folder after the command:")
        for ligne in fichiers(w):
            sortie("  " + ligne)
        sortie("")
    return faits


def reference(dossier, nom, sortie, complet):
    """Normal two-path conversion of the same store with the binary of main (works on Windows)."""
    w = TRAVAIL / "reference" / dossier
    shutil.rmtree(w, ignore_errors=True)
    w.mkdir(parents=True)
    for f in (ICI / "donnees" / dossier).iterdir():
        if ".vcobj" in f.name:
            shutil.copyfile(f, w / f.name)
    rc, texte, _ = lance(EXE["main"], [nom, "reference.vcobj"], w)
    (JOURNAUX / f"reference-{dossier}.txt").write_text(texte, encoding="utf-8")
    if rc != 0:
        sortie(f"reference conversion failed (exit code {rc})")
        return None
    v, c, integ = inspecte(w / "reference.vcobj")
    if complet:
        sortie(f"reference: `vc_object_convert \"{nom}\" reference.vcobj` with main -> exit code {rc}, schema {v}, "
               f"{len(c)} tables, {sum(x for x in c.values() if isinstance(x, int))} rows, integrity_check {integ}")
    return c


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "verifier"
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sortie = print
    complet = mode in ("avant", "apres")
    quois = {"avant": ["main"], "apres": ["corrige"], "verifier": ["main", "corrige"]}[mode]
    ok = True
    for q in list(quois):
        if not EXE[q].exists():
            print(f"ECART : binary missing: {EXE[q]}" + (" (only the other part is replayed)" if len(quois) > 1 else ""))
            quois.remove(q)
            ok = False
    if not quois:
        return 2
    for q in quois:
        if complet:
            sortie(f"=== {time.strftime('%Y-%m-%d %H:%M:%S')}  vc_object_convert --in-place, {VERSION[q]}")
            sortie(f"binary: {EXE[q]}  sha256 {sha(EXE[q])[:16]}...")
            sortie("Windows 11, MSYS2 UCRT64 build. Data: object stores of two real VC3D projects (PHerc1447, made "
                   "2026-11-15 with the official package VC3D-97fb933-2026-11-13-win64, store schema 21).")
            sortie("")
        for dossier, nom in MAGASINS:
            f = essai(q, dossier, nom, sortie, complet)
            if q == "main":
                vu = (f["rc"] == 1 and "cannot replace file" in f["texte"] and f["apres"] == 21)
                if not complet:
                    print(f"[main 2d3fb38d3] {nom}")
                    print("  expected : exit code 1, \"cannot replace file\", store still schema 21 (the defect)")
                    print(f"  obtained : exit code {f['rc']}, schema {f['avant']} -> {f['apres']}, "
                          f"message: {f['texte'].strip().splitlines()[0][:110] if f['texte'].strip() else '(none)'}")
                    print("  => " + ("defect reproduced" if vu else "ECART : defect NOT reproduced"))
                ok = ok and vu
            else:
                ref = reference(dossier, nom, sortie, complet)
                memes = ref is not None and ref == f["comptes"]
                rc2, texte2, _ = lance(EXE[q], ["--in-place", nom], f["dossier"])
                (JOURNAUX / f"{q}-{dossier}-in-place-second-run.txt").write_text(texte2, encoding="utf-8")
                v2, c2, integ2 = inspecte(f["store"])
                bon = (f["rc"] == 0 and f["avant"] == 21 and f["apres"] == 22 and f["integrite"] == "ok"
                       and not f["restes"] and memes and rc2 == 1 and "output already exists" in texte2
                       and v2 == 22 and integ2 == "ok" and c2 == f["comptes"])
                if complet:
                    sortie(f"same row count in every table as the reference conversion: {'yes' if memes else 'NO'}")
                    sortie(f"leftover .convert-/.members- files: {f['restes'] or 'none'}")
                    sortie(f"second run of the same command on the converted store (the docs say existing mapping/report "
                           f"files are not overwritten): exit code {rc2}, message: {texte2.strip()[:90]}")
                    sortie(f"  store after the second run: schema {v2}, integrity_check {integ2}, "
                           f"row counts unchanged: {'yes' if c2 == f['comptes'] else 'NO'}")
                    sortie("")
                else:
                    print(f"[fix e8b3d3dd9] {nom}")
                    print("  expected : exit code 0, store schema 21 -> 22, integrity ok, same rows as a normal conversion")
                    print(f"  obtained : exit code {f['rc']}, schema {f['avant']} -> {f['apres']}, integrity {f['integrite']}, "
                          f"same rows as a normal conversion: {'yes' if memes else 'NO'}")
                    print("  => " + ("fixed" if bon else "ECART : not as expected"))
                ok = ok and bon
    shutil.rmtree(TRAVAIL, ignore_errors=True)
    if not complet:
        print()
        print("RESULT: " + ("as expected (defect on main, fixed with the change)" if ok else "ECART, see above"))
    else:
        sortie("VERDICT: " + ("as expected" if ok else "NOT as expected"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
