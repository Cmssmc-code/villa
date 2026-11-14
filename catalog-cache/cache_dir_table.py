"""Prints what vc_reader.default_cache_dir() answers for each set of environment variables.

    python cache_dir_table.py PYTHON

PYTHON  a Python that has vc_reader installed

Each case runs in a new Python process, started in an empty folder (shown as <cwd>), with only the
named variables set among VC_READER_CACHE_DIR, XDG_CACHE_HOME, USERPROFILE, HOMEDRIVE, HOMEPATH and
HOME. The folders are temporary ones, shown as <tmp>.
"""
import os
import pathlib
import subprocess
import sys
import tempfile

NAMES = ("VC_READER_CACHE_DIR", "XDG_CACHE_HOME", "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "HOME")
CODE = ("import sys, vc_reader; sys.stdout.reconfigure(encoding='utf-8'); "
        "p = vc_reader.default_cache_dir(); print(p if p.is_absolute() else '<cwd>/' + p.as_posix())")


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    sys.stdout.reconfigure(encoding="utf-8")
    base = {k: v for k, v in os.environ.items() if k.upper() not in NAMES}
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp).resolve()
        for name in ("cwd", "profile", "home", "xdg", "cache", "Jérôme", "ユーザー"):
            (root / name).mkdir()
        profile, home = str(root / "profile"), str(root / "home")
        drive, tail = os.path.splitdrive(profile)
        cases = [
            ("USERPROFILE", {"USERPROFILE": profile}),
            ("USERPROFILE, HOME", {"USERPROFILE": profile, "HOME": home}),
            ("HOMEDRIVE, HOMEPATH", {"HOMEDRIVE": drive, "HOMEPATH": tail}),
            ("HOMEDRIVE, HOMEPATH, HOME", {"HOMEDRIVE": drive, "HOMEPATH": tail, "HOME": home}),
            ("HOME", {"HOME": home}),
            ("none", {}),
            ("XDG_CACHE_HOME, USERPROFILE, HOME", {"XDG_CACHE_HOME": str(root / "xdg"), "USERPROFILE": profile, "HOME": home}),
            ("VC_READER_CACHE_DIR, XDG_CACHE_HOME, USERPROFILE, HOME",
             {"VC_READER_CACHE_DIR": str(root / "cache"), "XDG_CACHE_HOME": str(root / "xdg"), "USERPROFILE": profile, "HOME": home}),
            ("USERPROFILE (a folder named Jérôme)", {"USERPROFILE": str(root / "Jérôme")}),
            ("USERPROFILE (a folder named ユーザー)", {"USERPROFILE": str(root / "ユーザー")}),
        ]
        for label, extra in cases:
            done = subprocess.run([sys.argv[1], "-c", CODE], env={**base, **extra}, cwd=root / "cwd",
                                  capture_output=True, text=True, encoding="utf-8", errors="replace")
            answer = done.stdout.strip() if done.returncode == 0 else "FAILED: " + done.stderr.strip()[-300:]
            print(f"{label:55} -> {answer.replace(str(root), '<tmp>')}")


if __name__ == "__main__":
    main()
