"""VC3D's Windows tools and cache paths longer than 260 characters, before and after this PR.

    python longpath_check.py --zip VC3D-97fb933-2026-11-13-win64.zip --repo <villa clone>
                             --main <commit> --head <commit> --work <new folder> [--log <file>]

Unpacks the bin folder of the released Windows package (the `latest` release, built from main
97fb933) and makes a copy of it where vc_grow_seg_from_seed.exe gets this PR's manifest
(volume-cartographer/cmake/windows/utf8.manifest at --head), embedded with mt.exe:

  released   as released: its manifest is utf8.manifest of --main (checked)
  this-pr    the same program with the manifest of --head (checked); its sections are compared with
             the released program's, to show that the manifest is the only change

Each runs vc_grow_seg_from_seed on two published surface predictions, from a seed point on the
predicted surface (value 255), with a new, empty cache each time. A subst drive stands in for C:, so
that the default cache root, <USERPROFILE>\\.VC3D\\remote_cache, is as long as on a PC:

  root 33   X:\\Users\\alice\\.VC3D\\remote_cache  (as C:\\Users\\<5-letter name>\\.VC3D\\remote_cache)
  root 23   X:\\U\\.VC3D\\remote_cache             (a control: a short root)

HOME, VC3D_CONFIG_DIR and XDG_CACHE_HOME are unset, USERPROFILE points to a new, empty folder and
VC_READER_CACHE_DIR to the work folder. Expected: `released` stops with "create ...\\.zattrs.tmp...:
No such file or directory" with root 33 and works with root 23; `this-pr` works with both. The exit
code is 0 when all of that holds. The log lists the cache files of each run, and the files that only
one of the two programs wrote with root 23.

Needs Windows with LongPathsEnabled = 1 (HKLM\\SYSTEM\\CurrentControlSet\\Control\\FileSystem), mt.exe
from the Windows SDK, git, and Internet (about 3 MB from the Open Data bucket). Writes only in
--work, deletes it at the end, and removes the subst drive.
"""
import argparse
import ctypes
import ctypes.wintypes as wt
import datetime
import hashlib
import os
import pathlib
import platform
import re
import shutil
import struct
import subprocess
import sys
import time
import winreg
import zipfile
import xml.etree.ElementTree as ET

ZIP_SHA256 = "4b06ee91f60d6d29c8fc73a92fcd139103b9f6a288bb2ca7a55a5ee6e533abb4"
PACKAGE = "VC3D-97fb933-2026-11-13-win64"
PATCHED = "VC3D-97fb933-with-this-PR"
MANIFEST = "volume-cartographer/cmake/windows/utf8.manifest"
TOOL = "vc_grow_seg_from_seed.exe"
BUCKET = "https://vesuvius-challenge-open-data.s3.amazonaws.com/"
PREDICTIONS = {
    # name: (prediction, seed x y z: a voxel of value 255, on the predicted surface)
    "PHercParis4": ("PHercParis4/representations/predictions/surfaces/"
                    "20260411134726-surface-20260413141734-surface-recto-2um-ps256-L0-th0.45.zarr",
                    ("16256", "16256", "38016")),
    "PHerc0139": ("PHerc0139/representations/predictions/surfaces/"
                  "20260102150214-surface-20260203205514-surface-recto-2um-ps192-L0-th0.5.zarr",
                  ("13410", "13410", "38563")),
}
PROFILES = {33: r"Users\alice", 23: "U"}  # USERPROFILE below the drive -> default cache root length
PARAMS = '{"mode":"seed","cache_size":500000000,"generations":2,"thread_limit":2,"min_area_cm":0}'
VARIANTS = ("released", "this-pr")
NO_WINDOW = subprocess.CREATE_NO_WINDOW
BELOW_NORMAL = 0x00004000


class Report:
    """The English log: to a file, and to the console when run on its own."""

    def __init__(self, path=None, echo=True):
        self.file = open(path, "w", encoding="utf-8", newline="\n") if path else None
        self.echo = echo

    def __call__(self, text=""):
        if self.file:
            self.file.write(text + "\n")
            self.file.flush()
        if self.echo:
            print(text, flush=True)

    def close(self):
        if self.file:
            self.file.close()


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def run(command, **kwargs):
    return subprocess.run(command, capture_output=True, creationflags=NO_WINDOW, **kwargs)


def git(repo, *args):
    done = run(["git", "-C", str(repo), *args])
    if done.returncode:
        raise RuntimeError(f"git {' '.join(args)}: {done.stderr.decode(errors='replace').strip()}")
    return done.stdout


def canonical(xml_bytes):
    """The manifest as canonical XML, without comments or layout: what Windows reads from it."""
    return ET.canonicalize(xml_data=xml_bytes.decode("utf-8-sig"), with_comments=False, strip_text=True)


def long_paths_enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\FileSystem") as key:
            return winreg.QueryValueEx(key, "LongPathsEnabled")[0]
    except OSError:
        return None


def find_mt():
    kits = pathlib.Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Windows Kits" / "10" / "bin"
    found = sorted(kits.glob(r"10.*\x64\mt.exe"), key=lambda p: [int(n) for n in p.parent.parent.name.split(".")])
    return found[-1] if found else None


def mt(mt_exe, folder, *args):
    done = run([str(mt_exe), "-nologo", *args], cwd=folder)
    if done.returncode:
        raise RuntimeError(f"mt.exe {' '.join(args)}: exit code {done.returncode}: "
                           f"{(done.stdout + done.stderr).decode(errors='replace').strip()}")


def embedded_manifest(mt_exe, folder, out_name):
    mt(mt_exe, folder, f"-inputresource:{TOOL};#1", f"-out:{out_name}")
    data = (pathlib.Path(folder) / out_name).read_bytes()
    (pathlib.Path(folder) / out_name).unlink()
    return data


def sections(path):
    """[(name, raw data)] of a PE file, and the number of bytes after its last section."""
    b = pathlib.Path(path).read_bytes()
    pe = struct.unpack_from("<I", b, 0x3C)[0]
    count, = struct.unpack_from("<H", b, pe + 6)
    optional_size, = struct.unpack_from("<H", b, pe + 20)
    table = pe + 24 + optional_size
    found = []
    for i in range(count):
        name, _, _, size, offset = struct.unpack_from("<8sIIII", b, table + 40 * i)
        found.append((name.rstrip(b"\0").decode(), b[offset:offset + size]))
    end = max(struct.unpack_from("<I", b, table + 40 * i + 16)[0] + struct.unpack_from("<I", b, table + 40 * i + 20)[0]
              for i in range(count))
    return found, len(b) - end


def resources(path):
    """[(type, name, size)] of the resources of a PE file, read by Windows itself."""
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.LoadLibraryExW.restype = wt.HMODULE
    k.LoadLibraryExW.argtypes = [wt.LPCWSTR, wt.HANDLE, wt.DWORD]
    k.FindResourceW.restype = wt.HRSRC
    k.FindResourceW.argtypes = [wt.HMODULE, ctypes.c_void_p, ctypes.c_void_p]
    k.SizeofResource.argtypes = [wt.HMODULE, wt.HRSRC]
    k.FreeLibrary.argtypes = [wt.HMODULE]
    type_proc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HMODULE, ctypes.c_void_p, ctypes.c_void_p)
    name_proc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HMODULE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
    k.EnumResourceTypesW.argtypes = [wt.HMODULE, type_proc, ctypes.c_void_p]
    k.EnumResourceNamesW.argtypes = [wt.HMODULE, ctypes.c_void_p, name_proc, ctypes.c_void_p]
    label = {24: "RT_MANIFEST"}
    found = []

    def text(value):
        return label.get(value, f"#{value}") if value < 0x10000 else ctypes.wstring_at(value)

    @name_proc
    def on_name(module, kind, name, _):
        found.append((text(kind), "#" + str(name) if name < 0x10000 else ctypes.wstring_at(name),
                      k.SizeofResource(module, k.FindResourceW(module, name, kind))))
        return True

    @type_proc
    def on_type(module, kind, _):
        k.EnumResourceNamesW(module, kind, on_name, None)
        return True

    module = k.LoadLibraryExW(str(path), None, 0x00000002 | 0x00000020)  # as a data file, as an image resource
    if not module:
        raise OSError(f"LoadLibraryExW failed on {path}")
    try:
        k.EnumResourceTypesW(module, on_type, None)
    finally:
        k.FreeLibrary(module)
    return found


def unpack(zip_path, work):
    with zipfile.ZipFile(zip_path) as z:
        for item in z.infolist():
            if item.filename.startswith(PACKAGE + "/bin/") and not item.is_dir():
                z.extract(item, work)
    return work / PACKAGE / "bin"


def copy_bin(source, target, manifest, mt_exe):
    """`source` with its DLLs hard-linked and a real copy of the tool, whose manifest is replaced."""
    target.mkdir(parents=True)
    for item in source.iterdir():
        if item.name == TOOL:
            shutil.copyfile(item, target / item.name)
        elif item.is_file():
            try:
                os.link(item, target / item.name)
            except OSError:
                shutil.copyfile(item, target / item.name)
    (target / "embedded.manifest").write_bytes(manifest)
    mt(mt_exe, target, "-manifest", "embedded.manifest", f"-outputresource:{TOOL};#1")
    (target / "embedded.manifest").unlink()


def free_drive():
    for letter in "LKQJWXYZMNOPRSTUV":
        if not os.path.exists(f"{letter}:\\"):
            return letter
    raise RuntimeError("no free drive letter for subst")


def cache_files(profile):
    root = profile / ".VC3D" / "remote_cache"
    return [p for p in root.rglob("*") if p.is_file()] if root.is_dir() else []


def run_tool(exe, drive, root_length, prediction, report, label):
    """One run, with a new, empty profile folder; paths are seen through the drive, as the tool sees them."""
    url = BUCKET + PREDICTIONS[prediction][0]
    seed = PREDICTIONS[prediction][1]
    shown_profile = rf"{drive}:\{PROFILES[root_length]}"
    profile = pathlib.Path(shown_profile)
    if profile.exists():
        shutil.rmtree(profile)
    profile.mkdir(parents=True)
    root = shown_profile + r"\.VC3D\remote_cache"
    assert len(root) == root_length, (root, root_length)
    env = {k: v for k, v in os.environ.items() if k.upper() not in ("HOME", "VC3D_CONFIG_DIR", "XDG_CACHE_HOME")}
    env.update(USERPROFILE=shown_profile, VC_READER_CACHE_DIR=rf"{drive}:\vc_reader_cache", OMP_NUM_THREADS="2")
    command = [str(exe), "-v", url, "-t", rf"{drive}:\out\{label}", "-p", rf"{drive}:\params.json", "--seed", *seed]
    shown = rf"{drive}:\{exe.parent.parent.name}\bin\{TOOL}"
    report(f"--- {label}")
    report(f"USERPROFILE={shown_profile}   default cache root {root} ({len(root)} characters)")
    report("> " + subprocess.list2cmdline([shown, *command[1:]]))
    started = time.time()
    try:
        done = subprocess.run(command, cwd=f"{drive}:\\", env=env, capture_output=True, timeout=300,
                              creationflags=NO_WINDOW | BELOW_NORMAL)
        code, output = done.returncode, (done.stdout + done.stderr).decode("utf-8", errors="replace")
    except subprocess.TimeoutExpired as e:
        code, output = "timeout", ((e.stdout or b"") + (e.stderr or b"")).decode("utf-8", errors="replace")
    seconds = time.time() - started
    for line in output.splitlines():
        if line.strip():
            report("    " + line.rstrip())
    report(f"exit code {code}   {seconds:.1f} s")
    errors = [line.strip() for line in output.splitlines() if "rror" in line]
    result = dict(label=label, variant=label.split("-root")[0], root=root_length, prediction=prediction,
                  code=code, seconds=seconds, saved="saving " in output, seed_value=None, error=None,
                  temporary=None, parent_exists=None, first_error=errors[0] if errors else None)
    value = re.search(r"seed location \[[^\]]*\] value is (\S+)", output)
    if value:
        result["seed_value"] = value.group(1)
    error = re.search(r"create (\S+\.tmp\.\d+\.\d+): No such file or directory", output)
    if error:
        result["error"] = error.group(0)
        result["temporary"] = error.group(1)
        parent = pathlib.Path(error.group(1)).parent
        result["parent_exists"] = parent.is_dir()
        report(f"the temporary file's path has {len(error.group(1))} characters; its folder "
               f"({len(str(parent))} characters) {'exists' if result['parent_exists'] else 'does not exist'}")
    files = sorted((str(f), f.stat().st_size) for f in cache_files(profile))
    report(f"cache: {len(files)} files, {sum(s for _, s in files)} bytes"
           + (f", longest path {max(len(p) for p, _ in files)} characters" if files else ""))
    store = "https\\" + BUCKET.split("://")[1].rstrip("/") + "\\" + PREDICTIONS[prediction][0].replace("/", "\\")
    if any(p[len(root) + 1:].startswith(store) for p, _ in files):
        report(f"  <store> = {store}")
    result["files"] = [p[len(root) + 1:].replace(store, "<store>") for p, _ in files]
    for (path, size), name in zip(files, result["files"]):
        report(f"  {len(path):3} characters {size:9} bytes  {name}")
    result["chunks"] = sum(1 for p, _ in files if re.search(r"\\\d+\\\d+\\\d+\\\d+$", p))
    report()
    return result


def expectations(results):
    """(ok, what, result) for each run."""
    checks = []
    for r in results:
        name = f"{r['variant']}, {r['prediction']}, root {r['root']}"
        if r["variant"] == "released" and r["root"] == 33:
            ok = r["code"] not in (0, "timeout") and r["error"] is not None and r["parent_exists"]
            checks.append((ok, f"{name}: stops with 'create ...\\.zattrs.tmp...: No such file or directory'", r))
        else:
            ok = r["code"] == 0 and r["saved"] and r["seed_value"] == "255" and r["chunks"] >= 1
            checks.append((ok, f"{name}: reads the seed point (value 255), caches its chunk, saves a surface", r))
    return checks


def compare_programs(released, patched, report):
    """Problems, if the patched program differs from the released one by more than its manifest."""
    problems = []
    a, after_a = sections(released)
    b, after_b = sections(patched)
    if len(a) != len(b):
        return [f"{len(a)} sections in the released program, {len(b)} in the copy"]
    differ = [name for (name, x), (_, y) in zip(a, b) if x != y]
    report(f"sections: {len(a)}; with different contents: {', '.join(differ) or 'none'}")
    report(f"bytes after the last section: {after_a} in the released program, {after_b} in the copy "
           "(the COFF symbol table and its string table: debugging information, which Windows does not load "
           "to run the program; mt.exe does not keep them)")
    ra, rb = resources(released), resources(patched)
    report(f"resources: released {ra}, copy {rb}")
    if differ != [".rsrc"]:
        problems.append(f"sections that differ: {differ}, not only .rsrc")
    if [(t, n) for t, n, _ in ra] != [("RT_MANIFEST", "#1")] or [(t, n) for t, n, _ in rb] != [("RT_MANIFEST", "#1")]:
        problems.append("the manifest is not the only resource of both programs")
    return problems


def main(argv=None, say=lambda event: None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--zip", required=True, type=pathlib.Path)
    parser.add_argument("--repo", required=True, type=pathlib.Path)
    parser.add_argument("--main", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--work", required=True, type=pathlib.Path)
    parser.add_argument("--log", type=pathlib.Path)
    parser.add_argument("--quiet", action="store_true", help="write the log only to --log")
    args = parser.parse_args(argv)
    report = Report(args.log, echo=not args.quiet)
    work = args.work.resolve()
    drive = None
    outcome = {"ok": False, "problems": [], "results": [], "long_paths": None}
    try:
        report(f"longpath_check.py  {datetime.datetime.now():%Y-%m-%d %H:%M:%S}")
        report(f"Windows {platform.version()}, Python {platform.python_version()}")
        outcome["long_paths"] = lp = long_paths_enabled()
        report(f"LongPathsEnabled = {lp}")
        if lp != 1:
            outcome["problems"].append(("long_paths", f"LongPathsEnabled is {lp}, not 1: "
                                        "Windows ignores longPathAware, this PR cannot help on this PC"))

        say("source")
        main_sha = git(args.repo, "rev-parse", args.main + "^{commit}").decode().strip()
        head_sha = git(args.repo, "rev-parse", args.head + "^{commit}").decode().strip()
        changed = git(args.repo, "diff", "--name-only", main_sha, head_sha).decode().split()
        main_manifest = git(args.repo, "show", f"{main_sha}:{MANIFEST}")
        head_manifest = git(args.repo, "show", f"{head_sha}:{MANIFEST}")
        report(f"main    {main_sha}")
        report(f"this PR {head_sha}; files changed from main: {', '.join(changed)}")
        if changed != [MANIFEST]:
            outcome["problems"].append(("diff", f"this PR changes {changed}, not only {MANIFEST}"))
        for name, xml in (("main", main_manifest), ("this PR", head_manifest)):
            report(f"{MANIFEST} at {name}: longPathAware {'yes' if b'longPathAware' in xml else 'no'}, "
                   f"canonical XML sha256 {hashlib.sha256(canonical(xml).encode()).hexdigest()[:16]}")

        say("package")
        zip_hash = sha256(args.zip)
        report(f"{args.zip.name} sha256 {zip_hash}")
        if zip_hash != ZIP_SHA256:
            outcome["problems"].append(("zip", f"{args.zip.name} is not the released package (sha256 {zip_hash})"))
            return outcome
        mt_exe = find_mt()
        if not mt_exe:
            outcome["problems"].append(("mt", "mt.exe (Windows SDK) not found"))
            return outcome
        report(f"mt.exe of Windows SDK {mt_exe.parent.parent.name}")
        if work.exists():
            shutil.rmtree("\\\\?\\" + str(work))
        work.mkdir(parents=True)
        bins = {"released": unpack(args.zip, work)}
        bins["this-pr"] = work / PATCHED / "bin"
        copy_bin(bins["released"], bins["this-pr"], head_manifest, mt_exe)
        expected = {"released": ("main", main_manifest), "this-pr": ("this PR", head_manifest)}
        for variant in VARIANTS:
            exe = bins[variant] / TOOL
            embedded = embedded_manifest(mt_exe, bins[variant], "extracted.manifest")
            same = canonical(embedded) == canonical(expected[variant][1])
            report(f"{variant:8} {bins[variant].parent.name}\\bin\\{TOOL}: {exe.stat().st_size} bytes, "
                   f"sha256 {sha256(exe)[:16]}; embedded manifest: longPathAware "
                   f"{'yes' if b'longPathAware' in embedded else 'no'}, "
                   f"{'the same as' if same else 'NOT the same as'} {expected[variant][0]}'s (canonical XML)")
            if not same:
                outcome["problems"].append(("manifest", f"{variant}: the embedded manifest is not the expected one"))
        for problem in compare_programs(bins["released"] / TOOL, bins["this-pr"] / TOOL, report):
            outcome["problems"].append(("sections", problem))
        if outcome["problems"]:
            return outcome
        (work / "params.json").write_text(PARAMS, encoding="ascii")
        report(f"params.json {PARAMS}")

        drive = free_drive()
        if run(["subst", f"{drive}:", str(work)]).returncode:
            drive = None
            outcome["problems"].append(("subst", "subst failed"))
            return outcome
        report(f"{drive}: is a subst drive on the work folder, standing in for C:")
        report()
        for variant in VARIANTS:
            say(variant)
            for root_length in (33, 23):
                for prediction in PREDICTIONS:
                    label = f"{variant}-root{root_length}-{prediction}"
                    result = run_tool(bins[variant] / TOOL, drive, root_length, prediction, report, label)
                    outcome["results"].append(result)
                    say(result)

        report("Cache files written by only one of the two programs, with root 23:")
        for prediction in PREDICTIONS:
            written = {r["variant"]: set(r["files"]) for r in outcome["results"]
                       if r["root"] == 23 and r["prediction"] == prediction}
            report(f"  {prediction}: only this-pr: {', '.join(sorted(written['this-pr'] - written['released'])) or 'none'}; "
                   f"only released: {', '.join(sorted(written['released'] - written['this-pr'])) or 'none'}")
        report()
        report("SUMMARY")
        for ok, what, r in expectations(outcome["results"]):
            detail = r["error"] or ("saved a surface" if r["saved"] else r["first_error"] or "no surface")
            report(f"  {'ok ' if ok else 'NOT'}  {what}  [exit code {r['code']}: {detail}]")
            if not ok:
                outcome["problems"].append(("run", what, r))
        outcome["ok"] = not outcome["problems"]
        return outcome
    except Exception as e:  # reported, then cleaned up
        outcome["problems"].append(("error", f"{type(e).__name__}: {e}"))
        return outcome
    finally:
        if drive:
            for profile in PROFILES.values():  # the caches, through the drive: their paths stay short
                shutil.rmtree(rf"{drive}:\{profile}", ignore_errors=True)
            run(["subst", f"{drive}:", "/D"])
        if work.exists():
            shutil.rmtree("\\\\?\\" + str(work), ignore_errors=True)
        drive_gone = not drive or not os.path.exists(f"{drive}:\\")
        report(f"cleanup: subst drive removed: {'yes' if drive_gone else 'NO'}, "
               f"work folder removed: {'yes' if not work.exists() else 'NO'}")
        if not drive_gone or work.exists():
            outcome["problems"].append(("cleanup", "the subst drive or the work folder is still there"))
        for problem in outcome["problems"]:
            report(f"PROBLEM: {problem[1]}")
        outcome["ok"] = outcome["ok"] and not outcome["problems"]
        report("RESULT: as expected" if outcome["ok"] else "RESULT: NOT as expected")
        report("FIN")
        report.close()


if __name__ == "__main__":
    sys.exit(0 if main()["ok"] else 1)
