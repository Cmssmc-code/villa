"""Check of "vc_object_convert --remove-history-and-disable fails on Windows" (second commit of the PR).

On fresh copies of two real object stores (donnees\\ of the parent folder, schema 21), first converted to
schema 22 with the normal two-path conversion of main:
  AVANT : vc_object_convert of main 2d3fb38d3 --remove-history-and-disable store.vcobj
          expected: exit code 1, "cannot replace file", history still enabled.
  APRES : same command with the fixed build (exe of commit e8b3d3dd9 + libvc_objects.dll of commit d530dfb85)
          expected: exit code 0, history disabled, history tables gone, same objects, integrity ok;
          then --enable-history: exit code 0, history enabled again;
          and --in-place on a schema-21 copy still works (exit code 0, schema 22).
Work folder: %TEMP%\\verifier-vc3d\\convert-history (deleted at the end). Nothing else is modified.
"""
import os
import pathlib
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time

ICI = pathlib.Path(__file__).resolve().parent
PARENT = ICI.parent
BASE = PARENT.parent
DLL = [BASE / "outils-vc3d" / "bin-main-2d3fb38d3", BASE / "outils-vc3d" / "msys64" / "ucrt64" / "bin"]
MAIN = PARENT / "binaire" / "main" / "vc_object_convert.exe"
EXE_FIX = PARENT / "binaire" / "corrige" / "vc_object_convert.exe"
DLL_FIX = ICI / "binaire" / "libvc_objects.dll"
MAGASINS = [("p1", "p1.vcobj"), ("projet-ete", "projet été.vcobj")]
TRAVAIL = pathlib.Path(tempfile.gettempdir()) / "verifier-vc3d" / "convert-history"
HIST = ("journal", "object_revisions", "geometry_revisions", "store_commits", "object_versions")
ecarts = []


def etat(db):
    c = sqlite3.connect(f"file:{pathlib.Path(db).as_posix()}?mode=ro", uri=True)
    try:
        v = c.execute("PRAGMA user_version").fetchone()[0]
        ic = c.execute("PRAGMA integrity_check").fetchone()[0]
        tables = {n for (n,) in c.execute("SELECT name FROM sqlite_schema WHERE type='table'")}
        objets = c.execute("SELECT count(*) FROM objects").fetchone()[0]
        he = c.execute("SELECT history_enabled FROM store_manifest").fetchone()[0] if v == 22 else None
        return v, ic, he, objets, sorted(t for t in HIST if t in tables)
    finally:
        c.close()


def lance(exe, args, cwd):
    env = dict(os.environ)
    env["PATH"] = os.pathsep.join(str(d) for d in DLL) + os.pathsep + env.get("PATH", "")
    try:
        r = subprocess.run([str(exe)] + args, cwd=str(cwd), env=env, stdin=subprocess.DEVNULL,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60)
        rc, brut = r.returncode, r.stdout
    except subprocess.TimeoutExpired as e:
        rc, brut = "TIMEOUT 60 s", e.stdout or b""
    try:
        texte = brut.decode("utf-8")
    except UnicodeDecodeError:
        texte = brut.decode("cp1252", errors="replace")
    return rc, texte.strip().splitlines()[-1] if texte.strip() else "(no output)"


def compare(nom, attendu, obtenu):
    ok = attendu == obtenu
    print(f"    {nom:<34} expected: {attendu!s:<22} got: {obtenu!s:<22} {'OK' if ok else 'MISMATCH'}")
    if not ok:
        ecarts.append(nom)


def main():
    for f in (MAIN, EXE_FIX, DLL_FIX):
        if not f.exists():
            print(f"ECART : missing file {f}")
            return 1
    t0 = time.time()
    if TRAVAIL.exists():
        shutil.rmtree(TRAVAIL)
    fix = TRAVAIL / "bin-fix"
    fix.mkdir(parents=True)
    shutil.copy2(EXE_FIX, fix)
    shutil.copy2(DLL_FIX, fix)  # next to the exe, so Windows loads it before the one of main in PATH
    try:
        for cle, nom in MAGASINS:
            print(f"\n=== real store {cle} ({nom}) ===")
            base = TRAVAIL / cle / "base"
            shutil.copytree(PARENT / "donnees" / cle, base)
            rc, msg = lance(MAIN, [nom, "s22.vcobj"], base)
            v, ic, he, objets0, hist = etat(base / "s22.vcobj")
            print(f"  schema-22 copy made by main (two-path conversion): rc={rc}, schema {v}, history_enabled={he}, objects={objets0}")
            for qui, exe in (("AVANT (main)", MAIN), ("APRES (fix)", fix / "vc_object_convert.exe")):
                d = TRAVAIL / cle / qui.split()[0]
                d.mkdir()
                shutil.copy2(base / "s22.vcobj", d / "store.vcobj")
                rc, msg = lance(exe, ["--remove-history-and-disable", "store.vcobj"], d)
                v, ic, he, objets, hist = etat(d / "store.vcobj")
                print(f"  {qui}: --remove-history-and-disable store.vcobj")
                print(f"    message: {msg[:150]}")
                if qui.startswith("AVANT"):
                    compare("exit code", 1, rc)
                    compare("'cannot replace file' shown", True, "cannot replace file" in msg)
                    compare("history_enabled", 1, he)
                else:
                    compare("exit code", 0, rc)
                    compare("history_enabled", 0, he)
                    compare("history tables left", [], hist)
                    compare("objects (same as before)", objets0, objets)
                    compare("integrity_check", "ok", ic)
                    rc, msg = lance(exe, ["--enable-history", "store.vcobj"], d)
                    v, ic, he, objets, hist = etat(d / "store.vcobj")
                    print(f"  {qui}: --enable-history store.vcobj")
                    compare("exit code", 0, rc)
                    compare("history_enabled", 1, he)
                    compare("integrity_check", "ok", ic)
                    d2 = TRAVAIL / cle / "inplace"
                    shutil.copytree(PARENT / "donnees" / cle, d2)
                    rc, msg = lance(exe, ["--in-place", nom], d2)
                    v, ic, he, objets, hist = etat(d2 / nom)
                    print(f"  {qui}: --in-place {nom} (first commit of the PR, still works)")
                    compare("exit code", 0, rc)
                    compare("schema after", 22, v)
                    compare("objects", objets0, objets)
    finally:
        shutil.rmtree(TRAVAIL, ignore_errors=True)
    print(f"\nDuration: {time.time() - t0:.1f} s")
    if ecarts:
        print("ECART : " + ", ".join(ecarts))
        return 1
    print("TOUT EST CONFORME : main fails, the fix works and --in-place still works.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
