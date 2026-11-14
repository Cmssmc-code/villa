"""Checks the inputs of the vc_extend_edge test (essai-extend-edge.ps1): the two programs and the segment.

    python check_inputs.py --zip VC3D-97fb933-2026-11-13-win64.zip --copy <vc_extend_edge.exe of the "after" run>
                           --repo <villa clone> --main 97fb933 --head <this PR> --segment <tifxyz_original folder>
                           --before before-extend-edge.txt --after after-extend-edge.txt
                           --work <new folder> [--log check_inputs.log]

essai-extend-edge.ps1 printed the sha256 of the program it ran on the first line of its output
(before-extend-edge.txt: the released program; after-extend-edge.txt: the copy). This script checks that:
  - vc_extend_edge.exe of the release asset has the "before" sha256, and its embedded manifest is
    utf8.manifest of --main (canonical XML);
  - --copy has the "after" sha256, its embedded manifest is utf8.manifest of --head (canonical XML), and
    its sections have the same contents as the released program's apart from .rsrc, which holds the manifest;
  - the files of --segment are those of the published segment (size, and MD5 = ETag on the Open Data bucket).
Needs mt.exe from the Windows SDK, git, Internet (four HEAD requests) and longpath_check.py in the folder
above this one. Writes only in --work (deleted at the end) and --log.
"""
import argparse
import datetime
import hashlib
import pathlib
import re
import shutil
import sys
import urllib.request
import zipfile

sys.dont_write_bytecode = True
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import longpath_check as lc  # noqa: E402

TOOL = "vc_extend_edge.exe"
SEGMENT = "PHerc0800/segments/20251029010146-auto_grown_20251029010146642/mesh/intermediate/tifxyz_original/"
SEGMENT_FILES = ("meta.json", "x.tif", "y.tif", "z.tif")


def printed_sha256(path):
    """The first line of the script's output, and the sha256 it gives."""
    first = pathlib.Path(path).read_text(encoding="utf-8-sig").splitlines()[0]
    found = re.search(r"sha256=([0-9A-Fa-f]{64})", first)
    return first, found.group(1).lower() if found else None


def embedded_manifest(mt_exe, folder):
    lc.mt(mt_exe, folder, f"-inputresource:{TOOL};#1", "-out:extracted.manifest")
    data = (folder / "extracted.manifest").read_bytes()
    (folder / "extracted.manifest").unlink()
    return data


def on_bucket(name):
    request = urllib.request.Request(lc.BUCKET + SEGMENT + name, method="HEAD")
    with urllib.request.urlopen(request, timeout=30) as response:
        return int(response.headers["Content-Length"]), response.headers["ETag"].strip('"')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    for name in ("--zip", "--copy", "--repo", "--segment", "--before", "--after", "--work"):
        parser.add_argument(name, required=True, type=pathlib.Path)
    parser.add_argument("--main", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--log", type=pathlib.Path)
    args = parser.parse_args(argv)
    report = lc.Report(args.log)
    work = args.work.resolve()
    problems = []
    try:
        report(f"check_inputs.py  {datetime.datetime.now():%Y-%m-%d %H:%M:%S}")
        main_sha = lc.git(args.repo, "rev-parse", args.main + "^{commit}").decode().strip()
        head_sha = lc.git(args.repo, "rev-parse", args.head + "^{commit}").decode().strip()
        expected = {"main": lc.git(args.repo, "show", f"{main_sha}:{lc.MANIFEST}"),
                    "this PR": lc.git(args.repo, "show", f"{head_sha}:{lc.MANIFEST}")}
        report(f"main    {main_sha}")
        report(f"this PR {head_sha}")

        printed = {}
        for run, path in (("before", args.before), ("after", args.after)):
            line, printed[run] = printed_sha256(path)
            report(f"{path.name}, first line: {line}")

        zip_hash = lc.sha256(args.zip)
        report(f"{args.zip.name} sha256 {zip_hash}")
        if zip_hash != lc.ZIP_SHA256:
            problems.append(f"{args.zip.name} is not the released package")
        mt_exe = lc.find_mt()
        if not mt_exe:
            problems.append("mt.exe (Windows SDK) not found")
            return 1
        report(f"mt.exe of Windows SDK {mt_exe.parent.parent.name}")
        if work.exists():
            shutil.rmtree(work)
        folders = {"released": work / "released", "copy": work / "copy"}
        for folder in folders.values():
            folder.mkdir(parents=True)
        with zipfile.ZipFile(args.zip) as z:
            (folders["released"] / TOOL).write_bytes(z.read(f"{lc.PACKAGE}/bin/{TOOL}"))
        shutil.copyfile(args.copy, folders["copy"] / TOOL)

        for variant, label, run, source in (("released", f"{lc.PACKAGE}\\bin\\{TOOL}", "before", "main"),
                                            ("copy", args.copy.name, "after", "this PR")):
            exe = folders[variant] / TOOL
            digest = lc.sha256(exe)
            manifest = embedded_manifest(mt_exe, folders[variant])
            same = lc.canonical(manifest) == lc.canonical(expected[source])
            report(f"{variant:8} {label}: {exe.stat().st_size} bytes, sha256 {digest}")
            report(f"         {'the same as' if digest == printed[run] else 'NOT the same as'} the sha256 printed "
                   f"for the {run!r} run; embedded manifest: longPathAware "
                   f"{'yes' if b'longPathAware' in manifest else 'no'}, "
                   f"{'the same as' if same else 'NOT the same as'} utf8.manifest of {source} (canonical XML)")
            if digest != printed[run]:
                problems.append(f"{variant}: not the program of the {run!r} run")
            if not same:
                problems.append(f"{variant}: the embedded manifest is not utf8.manifest of {source}")
        problems += lc.compare_programs(folders["released"] / TOOL, folders["copy"] / TOOL, report)

        report(f"segment {lc.BUCKET}{SEGMENT}")
        for name in SEGMENT_FILES:
            local = (args.segment / name).read_bytes()
            md5 = hashlib.md5(local).hexdigest()
            size, etag = on_bucket(name)
            same = size == len(local) and etag == md5
            report(f"  {name:9} here: {len(local):6} bytes, MD5 {md5}; bucket: {size:6} bytes, ETag {etag}"
                   f"{'' if same else '  DIFFERENT'}")
            if not same:
                problems.append(f"segment file {name} is not the bucket's")
    except Exception as error:  # noqa: BLE001 - reported in the log
        problems.append(f"error: {error!r}")
    finally:
        if work.exists():
            shutil.rmtree(work, ignore_errors=True)
        report(f"work folder removed: {'yes' if not work.exists() else 'no'}")
        for problem in problems:
            report(f"PROBLEM: {problem}")
        report("RESULT: " + ("as expected" if not problems else "NOT as expected"))
        report("FIN")
        report.close()
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
