"""Before/after check for the villa pull request
"dinovol: read metadata.json when the bucket serves it gzip-compressed".

It runs dinovol's own command, `python -m dinovol_2.cache_metadata_meshes`, on the public
Open Data bucket (read anonymously), with the code of two villa commits exported by
`git archive`: the base commit ("before") and the commit of the pull request ("after").

    python dinovol_gzip.py --repo VILLA_CLONE --before COMMIT --after COMMIT \
        --python PYTHON --work NEW_FOLDER --logs LOG_FOLDER [--sample PHerc0172] [--keep]

PYTHON runs dinovol: it must import numpy, scipy and vc_reader (torch is not needed for
this command). NEW_FOLDER must not exist; it is deleted at the end unless --keep is given.
Each step writes its full output to a log in LOG_FOLDER:

  1-bucket.log           GET metadata.json with urllib: request, answer headers, first bytes
  2-export.log           the two commits and the files the pull request changes
  3-before-docs.log      before: the command of the module docstring, unchanged
  4-before.log           before: the documented config reduced to one sample, new cache folder
  5-after.log            after: the same command, new cache folder
  6-after-old-cache.log  after: a cache folder holding only the gzip metadata.json of step 4
  7-readback.log         meshes of steps 5 and 6 read back with load_mesh_segments_cache
  8-tests.log            tests/test_metadata_gzip.py at both commits (copied into "before")
  summary.log            one line per check, then "RESULT: OK" or "RESULT: MISMATCH: ..."

NEW_FOLDER is written as <work> in the logs, and other paths under the home folder as
C:\\Users\\me (~ on other systems).
"""

from __future__ import annotations

import argparse
import ast
import contextlib
import gzip
import hashlib
import io
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request
from pathlib import Path

URL = "https://vesuvius-challenge-open-data.s3.amazonaws.com/metadata.json"
MODULE = "dinovol_2.cache_metadata_meshes"
DOC_CONFIG = "dinovol_2/configs/pretrain_8_9um.json"
TEST_FILE = "tests/test_metadata_gzip.py"
GZIP_MAGIC = b"\x1f\x8b"
DECODE_ERROR = "UnicodeDecodeError: 'utf-8' codec can't decode byte 0x8b in position 1: invalid start byte"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _home_patterns() -> list[tuple[re.Pattern, str]]:
    home = Path.home()
    shown = "C:\\Users\\me" if os.name == "nt" else "~"
    pairs = [(str(home).replace("\\", "\\\\"), shown.replace("\\", "\\\\")),
             (str(home), shown),
             (home.as_posix(), shown.replace("\\", "/"))]
    return [(re.compile(re.escape(real), re.IGNORECASE), new) for real, new in pairs]


HOME_PATTERNS = _home_patterns()


def hide_home(text: str) -> str:
    for pattern, new in HOME_PATTERNS:
        text = pattern.sub(lambda _m, new=new: new, text)
    return text


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def say_english(event: str, **info) -> None:
    if event == "step":
        print(f"== {info['text']}", flush=True)
    elif event == "check":
        print(f"   {'ok' if info['ok'] else 'MISMATCH'}: {info['text']}", flush=True)


class Proof:
    def __init__(self, args: argparse.Namespace, say=say_english) -> None:
        self.args = args
        self.say = say
        self.repo = Path(args.repo)
        self.python = args.python
        self.work = Path(args.work).resolve()
        self.logs = Path(args.logs).resolve()
        self.sample = args.sample
        self.checks: list[tuple[str, bool, str]] = []
        self.served: bytes | None = None
        self.n_after: int | None = None
        self.started = time.time()
        self.work_patterns = [re.compile(re.escape(p), re.IGNORECASE) for p in
                              (str(self.work).replace("\\", "\\\\"), str(self.work), self.work.as_posix())]
        self.env = {k: v for k, v in os.environ.items() if not k.upper().startswith("PYTHON")}
        self.env.update(
            PYTHONIOENCODING="utf-8",
            PYTHONUNBUFFERED="1",
            PYTHONDONTWRITEBYTECODE="1",
            PYTHONNOUSERSITE="1",
            OMP_NUM_THREADS="2",
            VC_READER_CACHE_DIR=str(self.work / "vc_reader_cache"),
            XDG_CACHE_HOME=str(self.work / "xdg_cache"),
            TEMP=str(self.work / "tmp"),
            TMP=str(self.work / "tmp"),
        )

    # -- helpers -------------------------------------------------------------------------
    def step(self, key: str, text: str) -> None:
        self.say("step", key=key, text=text)

    def check(self, key: str, ok: bool, text: str, **info) -> bool:
        self.checks.append((key, ok, text))
        self.say("check", key=key, ok=ok, text=text, **info)
        return ok

    def log(self, name: str, text: str) -> None:
        for pattern in self.work_patterns:
            text = pattern.sub("<work>", text)
        with (self.logs / name).open("a", encoding="utf-8", newline="\n") as f:
            f.write(hide_home(text))

    def git(self, *args: str) -> str:
        p = subprocess.run(["git", "-C", str(self.repo), *args], capture_output=True,
                           creationflags=NO_WINDOW)
        if p.returncode:
            raise RuntimeError(f"git {' '.join(args)}: {p.stderr.decode('utf-8', 'replace').strip()}")
        return p.stdout.decode("utf-8", "replace").rstrip()

    def run(self, log: str, args: list[str], cwd: Path, timeout: float,
            shown: str | None = None) -> tuple[int | None, str]:
        t0 = time.time()
        try:
            p = subprocess.run([self.python, *args], cwd=cwd, env=self.env, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout,
                               creationflags=NO_WINDOW)
            rc, raw = p.returncode, p.stdout
        except subprocess.TimeoutExpired as e:
            rc, raw = None, (e.stdout or b"") + f"\n[stopped after {timeout:.0f} s]\n".encode()
        out = raw.decode("utf-8", "replace").replace("\r\n", "\n")
        rel = cwd.relative_to(self.work).as_posix()
        self.log(log, f"$ cd <work>/{rel}\n$ python {shown or ' '.join(args)}\n{out.rstrip()}\n"
                      f"[exit code {rc}, {time.time() - t0:.1f} s]\n\n")
        return rc, out

    def describe_cache(self, log: str, cache: Path) -> list[Path]:
        lines = [f"files in <work>/{cache.relative_to(self.work).as_posix()}:"]
        files = sorted(p for p in cache.iterdir() if p.is_file()) if cache.is_dir() else []
        for p in files:
            head = p.read_bytes()[:2]
            kind = "gzip" if head == GZIP_MAGIC else ("plain JSON text" if head[:1] == b"{" else "binary")
            if p.suffix == ".npz":
                kind = "mesh cache"
            lines.append(f"  {p.name}  {p.stat().st_size:,} bytes  ({kind})")
        if not files:
            lines.append("  (none)")
        self.log(log, "\n".join(lines) + "\n\n")
        return files

    # -- steps ---------------------------------------------------------------------------
    def bucket(self) -> None:
        self.step("bucket", f"1. GET {URL} with urllib")
        buf = io.StringIO()
        opener = urllib.request.build_opener(urllib.request.HTTPSHandler(debuglevel=1))
        try:
            with contextlib.redirect_stdout(buf):
                with opener.open(URL, timeout=120) as answer:
                    status, reason, headers = answer.status, answer.reason, list(answer.headers.items())
                    body = answer.read()
        except OSError as e:
            self.log("1-bucket.log", f"GET {URL} failed: {e!r}\n")
            self.check("bucket", False, f"cannot download {URL}: {e}")
            return
        sent = []
        for line in buf.getvalue().splitlines():
            if line.startswith("send: b"):
                sent += ast.literal_eval(line[len("send: "):]).decode("latin-1").splitlines()
        lines = [f"$ python: urllib.request.urlopen({URL!r})  (Python {platform.python_version()})",
                 "request sent by urllib:", *[f"  {s}" for s in sent if s],
                 f"answer: {status} {reason}",
                 *[f"  {k}: {v}" for k, v in headers if k.lower() not in ("x-amz-id-2", "x-amz-request-id")]]
        encoding = dict((k.lower(), v) for k, v in headers).get("content-encoding", "")
        lines.append(f"body: {len(body):,} bytes, first bytes {body[:4].hex(' ')}")
        if body[:2] == GZIP_MAGIC:
            plain = gzip.decompress(body)
            samples = json.loads(plain).get("samples", {})
            lines.append(f"gunzip: {len(plain):,} bytes of JSON, {len(samples)} samples, sha256 "
                         f"{hashlib.sha256(plain).hexdigest()}")
            self.served = body
        self.log("1-bucket.log", "\n".join(lines) + "\n")
        asked_identity = any(s.lower() == "accept-encoding: identity" for s in sent)
        self.check("bucket-gzip", encoding.lower() == "gzip" and body[:2] == GZIP_MAGIC and asked_identity,
                   f"urllib asked for 'Accept-Encoding: identity'={asked_identity}; the bucket answered "
                   f"'Content-Encoding: {encoding}' with {len(body):,} bytes starting with {body[:2].hex(' ')}",
                   size=len(body))

    def export(self) -> bool:
        self.step("export", "2. git archive of dinovol/ at both commits")
        try:
            self.before_sha = self.git("rev-parse", "--verify", f"{self.args.before}^{{commit}}")
            self.after_sha = self.git("rev-parse", "--verify", f"{self.args.after}^{{commit}}")
            lines = [f"before: {self.git('log', '-1', '--format=%H %s', self.before_sha)}",
                     f"after:  {self.git('log', '-1', '--format=%H %s', self.after_sha)}",
                     f"parent of after: {self.git('rev-parse', self.after_sha + '^')}",
                     "files changed by after (git diff --stat before after):",
                     self.git("diff", "--stat", self.before_sha, self.after_sha)]
            for name, sha in (("before", self.before_sha), ("after", self.after_sha)):
                data = subprocess.run(["git", "-C", str(self.repo), "archive", "--format=tar", sha, "dinovol"],
                                      capture_output=True, check=True, creationflags=NO_WINDOW).stdout
                dest = self.work / name
                dest.mkdir(parents=True)
                with tarfile.open(fileobj=io.BytesIO(data)) as tar:
                    tar.extractall(dest, filter="data")
                lines.append(f"git archive {sha[:9]} dinovol -> <work>/{name}/dinovol ({len(data):,} bytes)")
        except (RuntimeError, subprocess.CalledProcessError, OSError) as e:
            self.log("2-export.log", f"export failed: {e}\n")
            return self.check("export", False, f"cannot export the two commits: {e}")
        self.log("2-export.log", "\n".join(lines) + "\n")
        return self.check("export", True, f"before {self.before_sha[:9]}, after {self.after_sha[:9]}")

    def make_config(self) -> str:
        config = json.loads((self.work / "before" / "dinovol" / DOC_CONFIG).read_text(encoding="utf-8"))
        entries = config["dataset"]["datasets"]
        config["dataset"]["datasets"] = [e for e in entries if e.get("sample_id") == self.sample]
        if len(config["dataset"]["datasets"]) != 1:
            raise RuntimeError(f"{self.sample} is not exactly once in {DOC_CONFIG}")
        name = f"cfg-{self.sample}.json"
        (self.work / name).write_text(json.dumps(config, indent=1), encoding="utf-8")
        self.config_note = (f"<work>/{name} is {DOC_CONFIG} with dataset.datasets reduced to its "
                            f"{self.sample} entry ({len(entries)} entries in the file):\n"
                            f"  {json.dumps(config['dataset']['datasets'][0])}\n"
                            f"dataset.s3_storage_options (unchanged): "
                            f"{json.dumps(config['dataset'].get('s3_storage_options'))}\n\n")
        return name

    def before_docs(self) -> None:
        self.step("before-docs", "3. before: the command of the module docstring, unchanged")
        cwd = self.work / "before" / "dinovol"
        rc, out = self.run("3-before-docs.log", ["-m", MODULE, "--config", DOC_CONFIG], cwd, 600)
        files = self.describe_cache("3-before-docs.log", self.work / "before" / "mesh_cache_8_9um")
        meta = [p for p in files if p.name == "metadata.json"]
        gz = bool(meta) and meta[0].read_bytes()[:2] == GZIP_MAGIC
        self.check("before-docs", rc not in (0, None) and DECODE_ERROR in out and gz
                   and not any(p.suffix == ".npz" for p in files),
                   f"exit code {rc}; UnicodeDecodeError (byte 0x8b): {DECODE_ERROR in out}; "
                   f"metadata.json saved gzip-compressed: {gz}; no mesh cached")

    def before(self, config: str) -> None:
        self.step("before", f"4. before: config reduced to {self.sample}, new cache folder")
        self.log("4-before.log", self.config_note)
        rc, out = self.run("4-before.log", ["-m", MODULE, "--config", f"../../{config}", "--cache-dir", "../cache"],
                           self.work / "before" / "dinovol", 600)
        files = self.describe_cache("4-before.log", self.work / "before" / "cache")
        meta = self.work / "before" / "cache" / "metadata.json"
        gz = meta.is_file() and meta.read_bytes()[:2] == GZIP_MAGIC
        same = gz and self.served is not None and meta.read_bytes() == self.served
        self.log("4-before.log", f"metadata.json is byte for byte the gzip body served by the bucket: {same}\n")
        self.check("before", rc not in (0, None) and DECODE_ERROR in out and gz
                   and not any(p.suffix == ".npz" for p in files),
                   f"exit code {rc}; UnicodeDecodeError (byte 0x8b): {DECODE_ERROR in out}; "
                   f"metadata.json saved gzip-compressed: {gz}; no mesh cached")

    def after(self, config: str) -> None:
        self.step("after", f"5. after: config reduced to {self.sample}, new cache folder")
        self.log("5-after.log", self.config_note)
        rc, out = self.run("5-after.log", ["-m", MODULE, "--config", f"../../{config}", "--cache-dir", "../cache"],
                           self.work / "after" / "dinovol", 1800)
        files = self.describe_cache("5-after.log", self.work / "after" / "cache")
        meta = self.work / "after" / "cache" / "metadata.json"
        plain = meta.is_file() and meta.read_bytes()[:1] == b"{"
        parsed = False
        if plain:
            try:
                parsed = isinstance(json.loads(meta.read_text(encoding="utf-8")).get("samples"), dict)
            except ValueError:
                parsed = False
        same = parsed and self.served is not None and meta.read_bytes() == gzip.decompress(self.served)
        self.log("5-after.log", f"metadata.json is plain JSON: {parsed}; it is the gunzipped body served "
                                f"by the bucket, byte for byte: {same}\n")
        m = re.search(r"^Done: cached (\d+) meshes", out, re.MULTILINE)
        self.n_after = int(m.group(1)) if m else None
        npz = [p for p in files if p.suffix == ".npz"]
        self.check("after", rc == 0 and bool(self.n_after) and len(npz) == 1 and parsed and same,
                   f"exit code {rc}; 'Done: cached {self.n_after} meshes'; {len(npz)} mesh cache file; "
                   f"metadata.json is plain JSON: {parsed}", n=self.n_after or 0)

    def after_old_cache(self, config: str) -> None:
        self.step("after-old-cache", "6. after: cache folder holding only the gzip metadata.json of step 4")
        old = self.work / "before" / "cache" / "metadata.json"
        cache = self.work / "after" / "cache-old"
        if not (old.is_file() and old.read_bytes()[:2] == GZIP_MAGIC):
            self.check("after-old-cache", False, "no gzip metadata.json from step 4 to start from")
            return
        cache.mkdir()
        shutil.copy2(old, cache / "metadata.json")
        digest = sha256(cache / "metadata.json")
        self.log("6-after-old-cache.log", f"<work>/after/cache-old/metadata.json: copy of the gzip file that "
                                          f"step 4 saved in <work>/before/cache, sha256 {digest}\n\n")
        rc, out = self.run("6-after-old-cache.log", ["-m", MODULE, "--config", f"../../{config}",
                                                     "--cache-dir", "../cache-old"],
                           self.work / "after" / "dinovol", 1800)
        self.describe_cache("6-after-old-cache.log", cache)
        unchanged = sha256(cache / "metadata.json") == digest
        downloaded = "Downloading" in out
        m = re.search(r"^Done: cached (\d+) meshes", out, re.MULTILINE)
        n = int(m.group(1)) if m else None
        self.log("6-after-old-cache.log", f"metadata.json left as it was (gzip, same sha256): {unchanged}; "
                                          f"catalog downloaded again: {downloaded}\n")
        self.check("after-old-cache", rc == 0 and n is not None and n == self.n_after and unchanged
                   and not downloaded,
                   f"exit code {rc}; 'Done: cached {n} meshes'; no new download: {not downloaded}",
                   n=n or 0)

    def readback(self) -> None:
        self.step("readback", "7. read the cached meshes back with load_mesh_segments_cache")
        caches = [self.work / "after" / "cache", self.work / "after" / "cache-old"]
        paths = [os.path.relpath(p, self.work / "after" / "dinovol")
                 for c in caches if c.is_dir() for p in sorted(c.glob("*.npz"))]
        if len(paths) != 2:
            self.check("readback", False, f"expected one mesh cache file in each of 2 folders, found {len(paths)}")
            return
        code = ("import hashlib, json, sys\n"
                "from dinovol_2.dataset.object_labels import load_mesh_segments_cache\n"
                "result = {}\n"
                "for path in sys.argv[1:]:\n"
                "    segments = load_mesh_segments_cache(path)\n"
                "    result[path] = [[s.segment_id, list(s.zyx.shape), int(s.valid.sum()),\n"
                "                     hashlib.sha256(s.zyx.tobytes() + s.valid.tobytes()).hexdigest()[:16]]\n"
                "                    for s in segments]\n"
                "    del segments\n"
                "print('JSON ' + json.dumps(result))\n")
        rc, out = self.run("7-readback.log", ["-c", code, *paths], self.work / "after" / "dinovol", 900,
                           shown="-c <load_mesh_segments_cache on each file, see dinovol_gzip.py> "
                                 + " ".join(paths))
        line = next((l for l in out.splitlines() if l.startswith("JSON ")), None)
        if rc != 0 or line is None:
            self.check("readback", False, f"load_mesh_segments_cache failed (exit code {rc})")
            return
        result = json.loads(line[5:])
        a, b = (result[p] for p in paths)
        lines = []
        for p in paths:
            segs = result[p]
            lines.append(f"{p}: {len(segs)} segments, {sum(s[2] for s in segs):,} valid points")
            lines += [f"  {s[0]}  grid {s[1][0]}x{s[1][1]}  valid {s[2]:,}  sha256 {s[3]}" for s in segs]
        lines.append(f"same segments and same arrays in both caches: {a == b}")
        self.log("7-readback.log", "\n".join(lines) + "\n")
        self.check("readback", len(a) == self.n_after and a == b,
                   f"{len(a)} and {len(b)} segments read back, identical: {a == b}", n=len(a))

    def tests(self) -> None:
        self.step("tests", f"8. {TEST_FILE} at both commits")
        src = self.work / "after" / "dinovol" / TEST_FILE
        dst = self.work / "before" / "dinovol" / TEST_FILE
        shutil.copy2(src, dst)
        self.log("8-tests.log", f"{TEST_FILE} of the after commit copied into <work>/before/dinovol\n\n")
        (self.work / "tmp").mkdir(exist_ok=True)
        rc_b, out_b = self.run("8-tests.log", ["-m", "unittest", "-v", "tests.test_metadata_gzip"],
                               self.work / "before" / "dinovol", 300)
        rc_a, out_a = self.run("8-tests.log", ["-m", "unittest", "-v", "tests.test_metadata_gzip"],
                               self.work / "after" / "dinovol", 300)
        before_ok = rc_b not in (0, None) and "FAILED (errors=2)" in out_b and out_b.count(DECODE_ERROR) >= 2
        after_ok = rc_a == 0 and "Ran 2 tests" in out_a and re.search(r"^OK$", out_a, re.MULTILINE) is not None
        self.check("tests", before_ok and after_ok,
                   f"before: {'2 errors, UnicodeDecodeError' if before_ok else 'unexpected, see log'}; "
                   f"after: {'2 tests OK' if after_ok else 'FAILED, see log'}")

    def environment(self) -> str:
        code = ("import importlib.metadata as m, platform, sys\n"
                "print(platform.platform(), '| Python', platform.python_version(), '|',\n"
                "      ', '.join(f'{n} {m.version(n)}' for n in ('numpy', 'scipy', 'vc_reader')))\n")
        p = subprocess.run([self.python, "-c", code], capture_output=True, env=self.env, creationflags=NO_WINDOW)
        return p.stdout.decode("utf-8", "replace").strip() or p.stderr.decode("utf-8", "replace").strip()

    # -- all -----------------------------------------------------------------------------
    def run_all(self) -> bool:
        if self.work.exists():
            raise SystemExit(f"{self.work} already exists: give a new folder")
        self.logs.mkdir(parents=True, exist_ok=True)
        for old in self.logs.glob("*.log"):
            old.unlink()
        (self.work / "tmp").mkdir(parents=True)
        try:
            self.bucket()
            if self.export():
                config = self.make_config()
                self.before_docs()
                self.before(config)
                self.after(config)
                self.after_old_cache(config)
                self.readback()
                self.tests()
        except Exception as e:  # reported as a failed check, then the summary is written
            self.check("error", False, f"{type(e).__name__}: {e}")
        finally:
            env_line = self.environment()
            if not self.args.keep:
                shutil.rmtree(self.work, ignore_errors=True)
        failed = [text for key, ok, text in self.checks if not ok]
        result = "RESULT: OK" if self.checks and not failed else f"RESULT: MISMATCH: {failed[0] if failed else 'no check ran'}"
        lines = [f"dinovol_gzip.py, {time.strftime('%Y-%m-%d %H:%M %z')}, {time.time() - self.started:.0f} s",
                 f"environment: {env_line}",
                 f"sample: {self.sample}",
                 *[f"{'ok      ' if ok else 'MISMATCH'} {key}: {text}" for key, ok, text in self.checks],
                 f"work folder deleted: {not self.work.exists()}",
                 result]
        self.log("summary.log", "\n".join(lines) + "\n")
        self.result = hide_home(result)
        return not failed and bool(self.checks)


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", required=True, help="a clone of ScrollPrize/villa that has both commits")
    parser.add_argument("--before", required=True, help="base commit (main)")
    parser.add_argument("--after", required=True, help="commit of the pull request")
    parser.add_argument("--python", required=True, help="python that imports numpy, scipy and vc_reader")
    parser.add_argument("--work", required=True, help="new folder for the exports and caches")
    parser.add_argument("--logs", required=True, help="folder for the logs")
    parser.add_argument("--sample", default="PHerc0172", help="sample of the documented config to keep")
    parser.add_argument("--keep", action="store_true", help="keep the work folder")
    return parser.parse_args(argv)


if __name__ == "__main__":
    proof = Proof(parse_args())
    ok = proof.run_all()
    print(proof.result, flush=True)
    sys.exit(0 if ok else 1)
