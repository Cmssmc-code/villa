"""Local check of the dinovol report "gen-19 mesh cached at 1/4 of its position".

Started by verifier.cmd, no input. It reproduces the report with the real dinovol code on the real public data:

  1. downloads the public catalog (metadata.json, served gzip-compressed) and checks the facts of the report;
  2. exports the code of dinovol with `git archive` (main 97fb9336c + the gzip fix of PR #2544, commit 6ef70e322,
     which is only there so that main can read the compressed catalog), twice: as it is, and with
     correctif.diff applied;
  3. runs the real `python -m dinovol_2.cache_metadata_meshes` (its main()) on the PHercParis4 entry of
     pretrain_8_9um.json, restricted to the segment 20260926044226 (spiral-output-generation-19), in a Windows
     job object limited to 3.5 GB of memory, for each export. The only replaced piece is that
     build_mesh_segment_from_arrays is called on slices of rows (see worker.py), because the whole-array call
     does not fit in 3.5 GB; a run without the slices shows it;
  4. measures where the points of the cached mesh fall, compared with the chunks that exist at level 4 of the
     masked volume.

The last line is "TOUT EST CONFORME" or "ECART : <cause>" (with the accent). Nothing is opened or installed.
Work folder (deleted at the end): %USERPROFILE%\\Dev\\vesuvius\\donnees-dinovol\\gen19\\travail.
Logs: logs\\ next to this file.
"""
import ctypes
import ctypes.wintypes as wt
import gzip
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
HOME = Path(os.environ["USERPROFILE"])
BASE = HOME / "Dev" / "vesuvius"
REPO = BASE / "wt-dinovol"  # only read (git archive); nothing is checked out or written there
COMMIT = "6ef70e3227f119c55dcf79e5babc8674e2bc01cc"
MAIN = "97fb9336c"
PYTHON = BASE / "venv-pywin" / "Scripts" / "python.exe"
DATA = BASE / "donnees-dinovol" / "gen19"
WORK = DATA / "travail"
LOGS = HERE / "logs"
BUCKET = "https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com"
SAMPLE, VOLUME, SEG = "PHercParis4", "20260411134726", "20260926044226"
LIMIT = 3.5e9  # bytes of committed memory for the whole job
MIN_FREE = 4.5 * 2**30
NO_WINDOW = 0x08000000

problems: list[str] = []
CATALOG = {}  # facts read from the catalog, for the comparison


def say(text=""):
    print(text, flush=True)


def hide_home(text):
    text = str(text)
    for form in (str(HOME), str(HOME).replace("\\", "/"), str(HOME).replace("\\", "\\\\")):
        text = text.replace(form, "%USERPROFILE%")
    return text


def check(ok, good, bad):
    if ok:
        say("   OK: " + good)
    else:
        problems.append(bad)
        say("   PROBLEM: " + bad)
    return ok


def free_memory():
    class MS(ctypes.Structure):
        _fields_ = [("l", wt.DWORD), ("load", wt.DWORD)] + [(n, ctypes.c_ulonglong) for n in (
            "tp", "ap", "tpf", "apf", "tv", "av", "ae")]
    ms = MS()
    ms.l = ctypes.sizeof(ms)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms))
    return ms.ap


# --- job object with a memory limit -------------------------------------------------------------------
k32 = ctypes.WinDLL("kernel32", use_last_error=True)
ntdll = ctypes.WinDLL("ntdll")
k32.CreateJobObjectW.restype = wt.HANDLE
k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wt.LPCWSTR]
k32.AssignProcessToJobObject.argtypes = [wt.HANDLE, wt.HANDLE]
k32.TerminateJobObject.argtypes = [wt.HANDLE, wt.UINT]
k32.QueryInformationJobObject.argtypes = [wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD, ctypes.c_void_p]
k32.SetInformationJobObject.argtypes = [wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD]
k32.CloseHandle.argtypes = [wt.HANDLE]
ntdll.NtResumeProcess.argtypes = [wt.HANDLE]


class IO_COUNTERS(ctypes.Structure):
    _fields_ = [(n, ctypes.c_ulonglong) for n in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


class BASIC_LIMIT(ctypes.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wt.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wt.DWORD),
                ("Affinity", ctypes.c_size_t), ("PriorityClass", wt.DWORD), ("SchedulingClass", wt.DWORD)]


class EXT_LIMIT(ctypes.Structure):
    _fields_ = [("BasicLimitInformation", BASIC_LIMIT), ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]


KILL_ON_JOB_CLOSE, JOB_MEMORY = 0x2000, 0x200
ENV = {k: v for k, v in os.environ.items() if not k.upper().startswith("PYTHON")}


def run_limited(step, args, limit_seconds=1500):
    """python -I <args> in a job object limited to LIMIT bytes. Log: logs/<step>.log. Returns a dict."""
    log = LOGS / f"{step}.log"
    job = k32.CreateJobObjectW(None, None)
    limits = EXT_LIMIT()
    limits.BasicLimitInformation.LimitFlags = KILL_ON_JOB_CLOSE | JOB_MEMORY
    limits.JobMemoryLimit = int(LIMIT)
    k32.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits))
    env = dict(ENV, PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1",
               VC_READER_CACHE_DIR=str(WORK / "reader-cache"), XDG_CACHE_HOME=str(WORK / "reader-cache"),
               TEMP=str(WORK / "temp"), TMP=str(WORK / "temp"))
    with open(log, "w", encoding="utf-8", newline="\n") as f:
        f.write("$ python -I " + hide_home(" ".join(map(str, args))) + "\n")
        f.flush()
        start = time.perf_counter()
        p = subprocess.Popen([str(PYTHON), "-I", *map(str, args)], cwd=str(WORK), env=env,
                             stdin=subprocess.DEVNULL, stdout=f, stderr=subprocess.STDOUT,
                             creationflags=0x4 | NO_WINDOW | 0x4000)  # suspended, no window, below normal
        k32.AssignProcessToJobObject(job, int(p._handle))
        ntdll.NtResumeProcess(int(p._handle))
        finished, nxt = True, 30
        while True:
            try:
                code = p.wait(timeout=1)
                break
            except subprocess.TimeoutExpired:
                el = time.perf_counter() - start
                if el >= limit_seconds:
                    k32.TerminateJobObject(job, 1)
                    code, finished = p.wait(), False
                    break
                if el >= nxt:
                    nxt += 30
                    say(f"      {el:4.0f} s ...")
        seconds = time.perf_counter() - start
        k32.QueryInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits), None)
        k32.TerminateJobObject(job, 1)
        k32.CloseHandle(job)
        peak = limits.PeakJobMemoryUsed
        f.write(f"\n--- exit code {code}{'' if finished else ' (stopped: time limit)'}; wall time {seconds:.0f} s; "
                f"peak committed memory {peak / 1e9:.2f} GB ({peak / 2**30:.2f} GiB), limit {LIMIT / 1e9:.1f} GB\n")
    return dict(code=code, finished=finished, seconds=seconds, peak=peak, log=log)


# --- steps ---------------------------------------------------------------------------------------------
def get(url):
    req = urllib.request.Request(url, headers={"Accept-Encoding": "identity"})
    with urllib.request.urlopen(req, timeout=120) as r:
        data, last = r.read(), r.headers.get("Last-Modified")
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    return data, last


def git(*args, binary=False):
    p = subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, creationflags=NO_WINDOW, timeout=120)
    return p.returncode, (p.stdout if binary else p.stdout.decode("utf-8", "replace").strip()), p.stderr.decode(
        "utf-8", "replace")


def step_catalogue():
    say("\nStep 1/6: public catalog (metadata.json) and the facts of the report.")
    raw, last = get(f"{BUCKET}/metadata.json")
    cat = json.loads(raw)
    say(f"   catalog: {len(raw):,} bytes after gunzip, Last-Modified {last}")
    samp = cat["samples"][SAMPLE]
    seg = samp["segments"][SEG]
    reps = seg.get("data") or seg.get("representations") or []
    types = [r.get("type") for r in reps]
    transformed = [r for r in reps if r.get("type") == "tifxyz-transformed"
                   and (r.get("parameters") or {}).get("target_volume") == VOLUME]
    ds = (seg.get("properties") or {}).get("original_volume_downscale")
    check(seg.get("original_volume_id") == VOLUME and ds == 4 and "tifxyz-normalized" in types and not transformed,
          f"segment {seg['long_id']}: original volume {VOLUME}, original_volume_downscale {ds}, "
          f"tifxyz-normalized present, no tifxyz-transformed onto {VOLUME} (representations: {', '.join(types)})",
          "the catalog no longer has the situation of the report for this segment (it may have been fixed upstream)")
    others = [s["id"] for s in samp["segments"].values() if s["id"] != SEG
              and (s.get("properties") or {}).get("original_volume_downscale") == 4
              and s.get("original_volume_id") == VOLUME
              and not any(r.get("type") == "tifxyz-transformed"
                          and (r.get("parameters") or {}).get("target_volume") == VOLUME
                          for r in (s.get("data") or s.get("representations") or []))]
    say(f"   other {SAMPLE} segments of this volume with downscale 4 and no transformed copy onto it: {len(others)}")
    CATALOG["bbox_xyz"] = seg["creation"]["metadata"]["bbox"]
    samp = dict(samp)
    samp["segments"] = {SEG: seg}  # same entry, only the other segments are left out
    small = dict(cat, samples={SAMPLE: samp})
    (WORK / "catalogue.json").write_text(json.dumps(small), encoding="utf-8")
    return cat


def step_volume():
    say("\nStep 2/6: shape and existing chunks of the masked volume (level 2 and level 4).")
    base = f"{BUCKET}/{SAMPLE}/volumes/20260411134726-2.400um-0.2m-78keV-masked.zarr"
    za = {lv: json.loads(get(f"{base}/{lv}/.zarray")[0]) for lv in (2, 4)}
    present, token = [], None
    while True:
        url = f"{BUCKET}/?list-type=2&prefix={SAMPLE}/volumes/20260411134726-2.400um-0.2m-78keV-masked.zarr/4/"
        if token:
            url += "&continuation-token=" + urllib.request.quote(token, safe="")
        text = get(url)[0].decode()
        present += [tuple(map(int, m)) for m in re.findall(r"zarr/4/(\d+)/(\d+)/(\d+)</Key>", text)]
        m = re.search(r"<NextContinuationToken>([^<]*)</NextContinuationToken>", text)
        if not m:
            break
        token = m.group(1)
    grid = [-(-s // c) for s, c in zip(za[4]["shape"], za[4]["chunks"])]
    say(f"   level 2 shape {za[2]['shape']}, level 4 shape {za[4]['shape']}, chunks {za[4]['chunks']}: "
        f"{len(present)} chunks exist out of {grid[0] * grid[1] * grid[2]}")
    vol = dict(volume_id=VOLUME, volume_scale=2, selected_shape=za[2]["shape"], level4_shape=za[4]["shape"],
               chunks=za[4]["chunks"], present_level4=present)
    (WORK / "volume.json").write_text(json.dumps(vol), encoding="utf-8")
    return vol


def step_export():
    say(f"\nStep 3/6: code of dinovol, exported with git archive (commit {COMMIT[:9]} = main {MAIN} + the gzip fix).")
    rc, out, err = git("cat-file", "-e", COMMIT + "^{commit}")
    if rc:
        say("   PROBLEM: " + hide_home(err))
        problems.append(f"commit {COMMIT[:9]} not found in the dinovol work tree")
        return False
    patch = HERE / "correctif.diff"
    for name in ("before", "after"):
        d = WORK / name
        d.mkdir(parents=True)
        rc, tar, err = git("archive", "--format=tar", COMMIT, "dinovol", binary=True)
        if rc:
            problems.append("git archive failed: " + hide_home(err))
            return False
        subprocess.run(["tar", "-xf", "-", "-C", str(d)], input=tar, check=True, creationflags=NO_WINDOW)
    p = subprocess.run(["git", "apply", "--whitespace=nowarn", str(patch)], cwd=str(WORK / "after"),
                       capture_output=True, creationflags=NO_WINDOW, text=True)
    if p.returncode:
        problems.append("correctif.diff does not apply to the export: " + hide_home(p.stderr.strip()))
        say("   PROBLEM: " + problems[-1])
        return False
    pb = WORK / "before" / "dinovol" / "dinovol_2" / "dataset" / "object_labels.py"
    pa = WORK / "after" / "dinovol" / "dinovol_2" / "dataset" / "object_labels.py"
    ta, tb = pa.read_text(encoding="utf-8").replace("\r\n", "\n"), pb.read_text(encoding="utf-8").replace("\r\n", "\n")
    n = len(ta.splitlines()) - len(tb.splitlines())
    check(n == 1, "the export with correctif.diff has exactly one more line in object_labels.py",
          f"correctif.diff changes {n} lines, expected 1")
    for name in ("before", "after"):  # the config is the real one of the export, restricted to PHercParis4
        d = WORK / name / "dinovol" / "dinovol_2" / "configs" / "pretrain_8_9um.json"
        cfg = json.loads(d.read_text(encoding="utf-8"))
        cfg["dataset"]["datasets"] = [e for e in cfg["dataset"]["datasets"] if e.get("sample_id") == SAMPLE]
        (WORK / f"config-{name}.json").write_text(json.dumps(cfg), encoding="utf-8")
        e = cfg["dataset"]["datasets"]
        say(f"   {name}: config pretrain_8_9um.json restricted to {SAMPLE} "
            f"({len(e)} entry, volume_scale {e[0].get('volume_scale')})")
    return True


def worker(step, *args):
    return run_limited(step, [HERE / "worker.py", *args])


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8")) if Path(path).is_file() else None


def build_and_measure(name):
    code = WORK / name / "dinovol"
    cache = WORK / f"cache-{name}"
    cache.mkdir()
    r = worker(f"build-{name}", "build", code, WORK / "catalogue.json", WORK / f"config-{name}.json", cache,
               WORK / f"build-{name}.json", "banded")
    say(f"   build: exit code {r['code']}, {r['seconds']:.0f} s, peak {r['peak'] / 1e9:.2f} GB")
    info = read_json(WORK / f"build-{name}.json")
    if not check(r["code"] == 0 and info and info.get("n_meshes") == 1 and r["peak"] < LIMIT,
                 f"{name}: the real cache_metadata_meshes cached the mesh, under {LIMIT / 1e9:.1f} GB",
                 f"{name}: the real cache_metadata_meshes did not finish under {LIMIT / 1e9:.1f} GB "
                 f"(see logs/build-{name}.log)"):
        return None
    m = worker(f"measure-{name}", "measure", code, cache, WORK / "volume.json", WORK / f"measure-{name}.json",
               WORK / f"sample-{name}.npz")
    res = read_json(WORK / f"measure-{name}.json")
    if not check(m["code"] == 0 and res and m["peak"] < LIMIT, f"{name}: the cached mesh is read back and measured",
                 f"{name}: measuring the cached mesh failed (see logs/measure-{name}.log)"):
        return None
    return info, res


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    t0 = time.time()
    LOGS.mkdir(exist_ok=True)
    say("Check of the dinovol report: PHercParis4 gen-19 mesh cached at 1/4 of its position.")
    say("Real dinovol code and real public data, in a job object limited to 3.5 GB. Needs Internet; a few minutes.")
    say("Nothing is opened or installed. Work folder: " + hide_home(WORK))
    if not PYTHON.is_file():
        return fin(t0, "the Python of dinovol (venv-pywin) is not found")
    if (HERE / "correctif.diff").is_file() is False:
        return fin(t0, "correctif.diff is not next to verifier.py")
    free = free_memory()
    say(f"Free memory: {free / 2**30:.2f} GiB (at least {MIN_FREE / 2**30:.1f} GiB needed before the heavy steps).")
    if free < MIN_FREE:
        return fin(t0, f"only {free / 2**30:.2f} GiB of memory are free, {MIN_FREE / 2**30:.1f} GiB needed: not tried")
    shutil.rmtree(WORK, ignore_errors=True)
    for sub in ("temp", "reader-cache"):
        (WORK / sub).mkdir(parents=True)
    for old in LOGS.glob("*.log"):
        if old.name != "verifier.log":
            old.unlink()
    try:
        step_catalogue()
        if problems:
            return fin(t0, problems[0])
        vol = step_volume()
        if not step_export():
            return fin(t0, problems[0])
        before = after = None
        if free_memory() < MIN_FREE:
            return fin(t0, "free memory fell under 4.5 GiB before the build: not tried")
        say("\nStep 4/6: BEFORE (code as it is): real cache_metadata_meshes on gen-19, in 3.5 GB.")
        # the whole-array call, to show that it does not fit (informational, expected to be stopped)
        say("   first the whole-array call, without slices of rows (expected not to fit in 3.5 GB)...")
        (WORK / "cache-whole").mkdir()
        w = worker("build-before-whole", "build", WORK / "before" / "dinovol", WORK / "catalogue.json",
                   WORK / "config-before.json", WORK / "cache-whole", WORK / "build-whole.json", "unbanded")
        fits = w["code"] == 0 and (WORK / "build-whole.json").is_file()
        err = next((l.strip() for l in w["log"].read_text(encoding="utf-8").splitlines() if "MemoryError" in l), "")
        say(f"   whole-array call: {'finished' if fits else 'did not finish'} (exit code {w['code']}"
            f"{'; ' + err if err else ''})")
        shutil.rmtree(WORK / "cache-whole", ignore_errors=True)
        before = build_and_measure("before")
        if before is None:
            return fin(t0, problems[0])
        if free_memory() < MIN_FREE:
            return fin(t0, "free memory fell under 4.5 GiB before the second build: not tried")
        say("\nStep 5/6: AFTER (same export with correctif.diff applied).")
        after = build_and_measure("after")
        if after is None:
            return fin(t0, problems[0])
        say("\nStep 6/6: comparison.")
        compare(vol, before, after, fits)
    except Exception as exc:  # network down, bucket error, ...
        problems.append(f"unexpected error: {type(exc).__name__}: {hide_home(exc)}")
        say("   PROBLEM: " + problems[-1])
    finally:
        shutil.rmtree(WORK, ignore_errors=True)
    if WORK.exists():
        problems.append("the work folder could not be deleted")
    return fin(t0, problems[0] if problems else None)


def compare(vol, before, after, whole_fits):
    import numpy as np
    (ib, mb), (ia, ma) = before, after
    for name, info in (("before", ib), ("after", ia)):
        say(f"   {name}: banded call equals whole-array call on 24 rows: {info.get('banded_equals_whole_on_24_rows')}; "
            f"selected shape {info['selected_shapes']}; tiff files read: "
            f"{sorted({u.rsplit('/', 1)[0].rsplit('/', 1)[-1] for u in info['tiff_urls']})}")
    check(ib["selected_shapes"] == ia["selected_shapes"] == [vol["selected_shape"]],
          f"selected shape given to dinovol = level 2 of the volume {vol['selected_shape']}",
          "the shape used by dinovol is not level 2 of the volume")
    check(ib.get("banded_equals_whole_on_24_rows") and ia.get("banded_equals_whole_on_24_rows"),
          "slicing the rows gives exactly the whole-array result (checked with the real function on 24 rows)",
          "slicing the rows changes the result of build_mesh_segment_from_arrays")
    sb, sa = ib["builds"][0]["coordinate_scale"], ia["builds"][0]["coordinate_scale"]
    check(sb == 1.0 and sa == 4.0,
          f"coordinate_scale given to the mesh builder: {sb} before, {sa} after (original_volume_downscale is 4)",
          f"coordinate_scale is {sb} before and {sa} after; expected 1.0 and 4.0")
    check(any("tifxyz_normalized" in u for u in ib["tiff_urls"]) and ib["tiff_urls"] == ia["tiff_urls"],
          "same files read (tifxyz_normalized/x.tif, y.tif, z.tif): only the scale differs",
          "the two runs did not read the same tifxyz files")
    for name, m in (("before", mb), ("after", ma)):
        say(f"   {name}: {m['valid_points']:,} points, {m['points_in_existing_level4_chunk']:,} in an existing level-4 chunk "
            f"({100 * m['points_in_existing_level4_chunk'] / max(1, m['valid_points']):.4f} %), "
            f"bbox z {m['bbox_lo_zyx'][0]:.0f}-{m['bbox_hi_zyx'][0]:.0f}, y {m['bbox_lo_zyx'][1]:.0f}-"
            f"{m['bbox_hi_zyx'][1]:.0f}, x {m['bbox_lo_zyx'][2]:.0f}-{m['bbox_hi_zyx'][2]:.0f}")
    fb = mb["points_in_existing_level4_chunk"] / max(1, mb["valid_points"])
    fa = ma["points_in_existing_level4_chunk"] / max(1, ma["valid_points"])
    check(mb["valid_points"] == ma["valid_points"] and mb["valid_points"] > 10_000_000,
          f"same number of cached points before and after ({mb['valid_points']:,}): nothing is dropped, only moved",
          "the number of cached points differs between the two runs")
    check(fb < 0.01, f"BEFORE: {100 * fb:.4f} % of the cached points fall in an existing chunk (almost all in empty space)",
          f"BEFORE: {100 * fb:.2f} % of the points are in an existing chunk, the defect is not reproduced")
    check(fa > 0.95, f"AFTER: {100 * fa:.2f} % of the cached points fall in an existing chunk",
          f"AFTER: only {100 * fa:.2f} % of the points are in an existing chunk")
    (x0, y0, z0), (x1, y1, z1) = CATALOG["bbox_xyz"]  # bbox of the segment, in level-2 voxels, from the catalog
    gap = max(abs(ma["bbox_lo_zyx"][0] - z0), abs(ma["bbox_lo_zyx"][1] - y0), abs(ma["bbox_lo_zyx"][2] - x0),
              abs(ma["bbox_hi_zyx"][0] - z1), abs(ma["bbox_hi_zyx"][1] - y1), abs(ma["bbox_hi_zyx"][2] - x1))
    check(gap < 1.5, f"AFTER: the bounding box of the cached mesh equals the one the catalog gives for the segment "
          f"(creation bbox z {z0:.0f}-{z1:.0f}, y {y0:.0f}-{y1:.0f}, x {x0:.0f}-{x1:.0f}; largest gap {gap:.2f} voxel)",
          f"AFTER: the bounding box of the cached mesh differs from the catalog's by {gap:.1f} voxels")
    sb_, sa_ = np.load(WORK / "sample-before.npz"), np.load(WORK / "sample-after.npz")
    same_rc = np.array_equal(sb_["rc"], sa_["rc"])
    # raw value r (level-2 voxels): before = (r + .5) / 4 - .5, after = r - .375
    err = float(np.abs((sb_["zyx"].astype(np.float64) + 0.5) * 4 - 0.875 - sa_["zyx"]).max()) if same_rc else 1e9
    check(same_rc and err < 0.05,
          f"{len(sb_['rc']):,} sampled points: position after = 4 x position before (max deviation {err:.4f} voxel)",
          "the positions of the two caches are not related by a factor of 4")
    say("   whole-array call in 3.5 GB: " + ("it fitted (the slices were not needed)" if whole_fits
        else "it did not fit (MemoryError)"))


def clean_logs():
    """Logs are published: write the user folder as %USERPROFILE%."""
    for f in LOGS.glob("*.log"):
        if f.name == "verifier.log":
            continue
        f.write_text(hide_home(f.read_text(encoding="utf-8", errors="replace")), encoding="utf-8", newline="\n")


def fin(t0, cause):
    clean_logs()
    say(f"\nDuration: {time.time() - t0:.0f} s")
    if cause:
        say("ÉCART : " + cause)
        return 1
    say("TOUT EST CONFORME")
    return 0


if __name__ == "__main__":
    sys.exit(main())
