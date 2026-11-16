"""historique-windows: replay vc_object_convert history maintenance on fresh copies of real stores.

usage: python essai.py <label> <bin-name> [<bin-name> ...]
For each real store: convert it to schema 22 with main (two-path conversion), then on a fresh
copy of that schema-22 store run --remove-history-and-disable, then --enable-history, then
--remove-history-and-disable again, with each binary. Also replays --in-place on schema-21 copies.
"""
import hashlib, pathlib, shutil, sqlite3, subprocess, sys, time

R = pathlib.Path(r"%USERPROFILE%\Dev\vesuvius")
M = R / "nuit-1611" / "historique-windows"
D = R / "donnees-historique-windows"
SRC = D / "source"
STORES = {"p1": "p1.vcobj", "projet-ete": "projet été.vcobj", "open-data-1447": "PHerc1447.vcobj"}
label = sys.argv[1]
BINS = sys.argv[2:]
ESS = D / ("essais-" + label)
out = open(M / "journaux" / f"essai-{label}.txt", "w", encoding="utf-8")


def p(*a):
    t = " ".join(str(x) for x in a)
    print(t, flush=True); out.write(t + "\n"); out.flush()


def sha(f):
    return hashlib.sha256(pathlib.Path(f).read_bytes()).hexdigest()


HIST = ("journal", "object_revisions", "geometry_revisions", "history_generations", "store_commits",
        "object_versions", "relationship_versions", "geometry_revision_chunks")


def etat(db):
    c = sqlite3.connect(f"file:{pathlib.Path(db).as_posix()}?mode=ro", uri=True)
    try:
        v = c.execute("PRAGMA user_version").fetchone()[0]
        ic = c.execute("PRAGMA integrity_check").fetchone()[0]
        counts = {}
        for (n,) in c.execute("SELECT name FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY 1"):
            counts[n] = c.execute(f'SELECT count(*) FROM "{n}"').fetchone()[0]
        try:
            he = "%s commit_sequence=%s" % c.execute("SELECT history_enabled,commit_sequence FROM store_manifest").fetchone()
        except Exception as e:  # schema 21 has no such column
            he = f"n/a ({e})"
        return v, ic, counts, he
    finally:
        c.close()


def lance(exe, args, cwd, timeout=180):
    t = time.time()
    try:
        r = subprocess.run([str(exe)] + args, cwd=cwd, capture_output=True, timeout=timeout)
        txt = (r.stdout + r.stderr).decode("utf-8", "replace").strip()
        return r.returncode, txt, time.time() - t
    except subprocess.TimeoutExpired:
        return "TIMEOUT", "", time.time() - t


def resume(tag, db):
    v, ic, counts, he = etat(db)
    hist = {k: counts[k] for k in HIST if k in counts}
    p(f"  {tag}: user_version={v} integrity={ic} history_enabled={he} tables={len(counts)} rows={sum(counts.values())}")
    p(f"  {tag}: history tables present: {hist if hist else 'none'}")
    return counts


def fichiers(d):
    return sorted(x.name for x in d.iterdir())


main_exe = M / "bin" / "main" / "vc_object_convert.exe"
p(f"label {label}; date {time.strftime('%Y-%m-%d %H:%M:%S')}")
for b in BINS:
    p(f"binary {b}: {M / 'bin' / b / 'vc_object_convert.exe'}")
    p(f"  sha256 exe {sha(M / 'bin' / b / 'vc_object_convert.exe')}")
    p(f"  sha256 libvc_objects.dll {sha(M / 'bin' / b / 'libvc_objects.dll')}")
if ESS.exists():
    shutil.rmtree(ESS)
for key, nom in STORES.items():
    p("")
    p(f"=== store {key}: {nom} (source {SRC / key}) ===")
    base = ESS / key / "base"
    shutil.copytree(SRC / key, base)
    rc, txt, dt = lance(main_exe, [nom, "s22.vcobj"], base)
    p(f"[prepare, main] $ vc_object_convert.exe \"{nom}\" s22.vcobj -> rc={rc} ({dt:.1f}s)")
    if rc != 0:
        p("  " + txt[-600:]); continue
    ref = resume("s22.vcobj", base / "s22.vcobj")
    for b in BINS:
        exe = M / "bin" / b / "vc_object_convert.exe"
        d = ESS / key / b
        d.mkdir(parents=True)
        shutil.copy2(base / "s22.vcobj", d / "store.vcobj")
        for i, mode in enumerate(["--remove-history-and-disable", "--enable-history", "--remove-history-and-disable"]):
            before = sha(d / "store.vcobj")
            rc, txt, dt = lance(exe, [mode, "store.vcobj"], d)
            p(f"[{b}] run {i + 1} $ vc_object_convert.exe {mode} store.vcobj -> rc={rc} ({dt:.1f}s)")
            if txt:
                for line in txt.splitlines()[-4:]:
                    p("  output: " + line)
            p(f"  store file changed: {before != sha(d / 'store.vcobj')}")
            p(f"  files left: {fichiers(d)}")
            counts = resume("store.vcobj", d / "store.vcobj")
            keep = {k: v for k, v in counts.items() if k in ("objects", "edges", "geometry_chunks")}
            p(f"  objects/edges/geometry_chunks: {keep} (s22 reference: {{'objects': {ref.get('objects')}, 'edges': {ref.get('edges')}, 'geometry_chunks': {ref.get('geometry_chunks')}}})")
        # in-place non-regression on a schema-21 copy
        d2 = ESS / key / (b + "-inplace")
        shutil.copytree(SRC / key, d2)
        rc, txt, dt = lance(exe, ["--in-place", nom], d2)
        p(f"[{b}] $ vc_object_convert.exe --in-place \"{nom}\" -> rc={rc} ({dt:.1f}s)")
        if rc != 0:
            p("  output: " + txt.splitlines()[-1] if txt else "  (no output)")
        resume(nom, d2 / nom)
p("")
p("FIN")
