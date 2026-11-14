"""Check the Windows tab of the VC3D tutorial against the real Windows downloads of VC3D.

    python vc3d_windows_tab.py before|after --commit SHA [--repo VILLA_CLONE | --doc FILE] [--build SHORT]
                               [--downloads DIR] [--work DIR] [--capture PNG] [--json FILE] [--no-start]

It reads the Windows tab of scrollprize.org/docs/06_tutorial_VC3D.md at the given commit (from a clone
with --repo, from a file with --doc, else from raw.githubusercontent.com), finds the Windows downloads
of the "latest" and "stable" releases of ScrollPrize/villa with the GitHub API (--build: the release
that holds that build, once "latest" has moved on), checks the local copies of the "latest" ones against
their published SHA-256 (it downloads them into --downloads if they are missing), then checks the
sentences of the tab that these files can confirm:

  before  the old tab: an "install file" in the .zip, the installer, the Start menu.
  after   the new tab: the two Windows downloads of every VC3D release; the installer's administrator
          rights, Start menu shortcut, default folder and PATH, read from the installer itself (nothing
          is installed); bin\\VC3D.exe and the vc_* tools in the .zip; then it
          extracts the .zip into an empty folder and starts bin\\VC3D.exe with the bin folder as working
          directory, as a double click does, on a hidden desktop: nothing shows on screen. It waits for
          the main window and the Open Data Catalog, saves a picture of the Open Data Catalog window
          (--capture; on a hidden desktop PrintWindow returns the main window blank) and closes VC3D.

VC3D runs without HOME and XDG_CACHE_HOME (Windows does not set them), with VC3D_CONFIG_DIR and
VC_READER_CACHE_DIR set to new folders in the work folder, and a VC3D.ini there that puts its remote
cache and its drafts folder in the work folder too, so your own VC3D settings and caches are not used.
The script compares %USERPROFILE%\\.VC3D, %USERPROFILE%\\.cache\\vc_reader, %APPDATA%\\Vesuvius Challenge,
%LOCALAPPDATA%\\Vesuvius Challenge and HKCU\\Software\\Vesuvius Challenge before and after, removes what
the run created there, reports any other change, and deletes the work folder.

Exit code: 0 the tab matches the downloads, 1 it does not, 2 the check could not be done.
Paths in the output are shortened to <work>, <downloads>, <repo> and %USERPROFILE%.
"""
import argparse
import collections
import ctypes
import ctypes.wintypes as wt
import fnmatch
import gzip
import hashlib
import json
import lzma
import msvcrt
import os
import platform
import re
import shutil
import struct
import subprocess
import sys
import threading
import time
import urllib.request
import winreg
import zipfile
import zlib

REPO = "ScrollPrize/villa"
DOC = "scrollprize.org/docs/06_tutorial_VC3D.md"
EXE_PATTERN, ZIP_PATTERN = "VC3D-*-win64.exe", "VC3D-*-win64.zip"
PROGRAM_EXT = (".exe", ".msi", ".bat", ".cmd", ".ps1", ".vbs", ".lnk")
INSTALL_NAME = re.compile(r"install|setup", re.IGNORECASE)
START_TIMEOUT = 240  # seconds for VC3D to show its windows and download the catalog
SETTLE = 5  # seconds left to the catalog window to fill its list before the picture
USER_AGENT = "vc3d-windows-tab-check"
NO_WINDOW = subprocess.CREATE_NO_WINDOW  # git and taskkill: no console window

HIDE = []  # (regex, replacement) applied to everything printed


def hide(path, replacement):
    parts = [re.escape(p) for p in re.split(r"[\\/]+", path.rstrip("\\/")) if p]
    if parts:
        HIDE.append((re.compile(r"[\\/]+".join(parts), re.IGNORECASE), replacement))


def clean(text):
    for pattern, replacement in HIDE:
        text = pattern.sub(replacement, text)
    return text


def say(text=""):
    print(clean(str(text)), flush=True)


def wrap(text, indent="    ", width=110):
    words, line, out = text.split(), "", []
    for w in words:
        if line and len(indent + line + " " + w) > width:
            out.append(indent + line)
            line = w
        else:
            line = f"{line} {w}" if line else w
    if line:
        out.append(indent + line)
    return "\n".join(out)


# ---------------------------------------------------------------- the tab and the releases

def read_doc(args):
    if args.doc:
        with open(args.doc, encoding="utf-8") as f:
            return f.read(), args.commit
    if args.repo:
        full = subprocess.run(["git", "-C", args.repo, "rev-parse", args.commit + "^{commit}"],
                              capture_output=True, text=True, check=True, creationflags=NO_WINDOW).stdout.strip()
        text = subprocess.run(["git", "-C", args.repo, "show", f"{full}:{DOC}"],
                              capture_output=True, check=True, creationflags=NO_WINDOW).stdout.decode("utf-8")
        return text, full
    return http_get(f"https://raw.githubusercontent.com/{REPO}/{args.commit}/{DOC}").decode("utf-8"), args.commit


def windows_tab(md):
    tab = re.search(r'<TabItem value="windows"[^>]*>(.*?)</TabItem>', md, re.S)
    launching = md[md.find("## Launching"):] if "## Launching" in md else ""
    launch = re.search(r"^- \*\*Windows:\*\*.*$", launching, re.M)
    if not tab or not launch:
        raise RuntimeError("no Windows tab or no Windows launch line in the tutorial")
    lines = [ln.strip() for ln in tab.group(1).splitlines() if ln.strip()]
    return " ".join(lines), lines, launch.group(0).strip()


def http_get(url, api=False):
    headers = {"User-Agent": USER_AGENT}
    if api:
        headers["Accept"] = "application/vnd.github+json"
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        if token:
            headers["Authorization"] = "Bearer " + token
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as r:
                return r.read()
        except OSError:
            if attempt == 2:
                raise
            time.sleep(5)


def all_releases():
    """Every release of the repository, from the GitHub API, 100 per page."""
    releases, page = [], 1
    while True:
        batch = json.loads(http_get(f"https://api.github.com/repos/{REPO}/releases?per_page=100&page={page}",
                                    api=True))
        releases += batch
        if len(batch) < 100:
            return releases
        page += 1


def release_assets(rel):
    """The .exe and the .zip Windows downloads of a release."""
    exe = [a for a in rel.get("assets", []) if fnmatch.fnmatchcase(a["name"], EXE_PATTERN)]
    zp = [a for a in rel.get("assets", []) if fnmatch.fnmatchcase(a["name"], ZIP_PATTERN)]
    return exe, zp


def windows_assets(tag, build=None):
    """The Windows assets of a release. With build (a short commit such as 97fb933), the release whose
    assets are that build: "latest" moves to each new build, and the older ones stay as archived releases."""
    rel = json.loads(http_get(f"https://api.github.com/repos/{REPO}/releases/tags/{tag}", api=True))
    if build and not any(f"-{build}-" in a["name"] for a in rel.get("assets", [])):
        rel = next((r for r in all_releases() if any(fnmatch.fnmatchcase(a["name"], f"VC3D-{build}-*-win64.zip")
                                                     for a in r.get("assets", []))), None)
        if rel is None:
            raise RuntimeError(f"no release of {REPO} has the Windows downloads of build {build}")
    return (rel,) + release_assets(rel)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def local_copy(asset, downloads):
    want = (asset.get("digest") or "").partition(":")[2].lower()
    if not want:
        raise RuntimeError(f"the release gives no SHA-256 for {asset['name']}")
    path = os.path.join(downloads, asset["name"])
    if not os.path.isfile(path):
        os.makedirs(downloads, exist_ok=True)
        say(f"  downloading {asset['name']} ({asset['size']:,} bytes)")
        part = path + ".part"
        request = urllib.request.Request(asset["browser_download_url"], headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=120) as r, open(part, "wb") as f:
            shutil.copyfileobj(r, f, 1 << 20)
        if sha256(part) != want:
            os.remove(part)
            raise RuntimeError(f"the download of {asset['name']} does not match its published SHA-256")
        os.replace(part, path)
    got = sha256(path)
    if got != want:
        raise RuntimeError(f"{asset['name']}: SHA-256 of the local copy {got[:16]}... is not the published {want[:16]}...")
    say(f"  {asset['name']}: {os.path.getsize(path):,} bytes, SHA-256 {got[:16]}... = the published digest")
    return path


# ---------------------------------------------------------------- the portable .zip

def zip_facts(path):
    with zipfile.ZipFile(path) as z:
        infos = z.infolist()
    files = [i.filename for i in infos if not i.is_dir()]
    tops = sorted({i.filename.split("/")[0] for i in infos})
    top = tops[0] if len(tops) == 1 else ""
    programs = [n for n in files if n.lower().endswith(PROGRAM_EXT)]
    installers = [n for n in programs if INSTALL_NAME.search(n.rsplit("/", 1)[-1]) or n.lower().endswith(".msi")]
    in_bin = [n.rsplit("/", 1)[-1] for n in programs if n.lower().startswith((top + "/bin/").lower())]
    return {
        "entries": len(infos), "files": len(files), "bytes": sum(i.file_size for i in infos), "top": top,
        "folders": collections.Counter(n[len(top) + 1:].split("/")[0] for n in files if top and "/" in n[len(top) + 1:]),
        "programs": programs, "installers": installers, "bin_programs": sorted(in_bin),
        "has_vc3d": f"{top}/bin/VC3D.exe" in files,
        "tools": sorted(n for n in in_bin if fnmatch.fnmatchcase(n.lower(), "vc_*.exe")),
    }


def describe_zip(z):
    say(f"  {z['files']} files ({z['bytes'] / 1e6:.1f} MB once extracted), all in one folder {z['top']}\\")
    say("  " + ", ".join(f"{k}\\ {v} files" for k, v in sorted(z["folders"].items())))
    others = [p for p in z["programs"] if p.rsplit("/", 1)[-1] not in z["bin_programs"]]
    say(f"  programs: {len(z['programs'])}, {'all ' if not others else ''}in bin\\: "
        f"{'VC3D.exe and ' if z['has_vc3d'] else ''}{len(z['tools'])} vc_*.exe tools"
        + (f"; elsewhere: {', '.join(others)}" if others else ""))
    say("  the vc_*.exe tools in bin\\:")
    say(wrap(", ".join(z["tools"]), "    "))
    say("  file named like an installer (install, setup, .msi): " + (", ".join(z["installers"]) or "none"))


# ---------------------------------------------------------------- the NSIS installer, read without running it

NS_LANG, NS_SHELL, NS_VAR, NS_SKIP = 1, 2, 3, 4  # string codes of a Unicode NSIS 3 installer
OP_CALL, OP_CREATEDIR, OP_EXTRACTFILE, OP_ASSIGNVAR, OP_STRCMP, OP_CREATESHORTCUT, OP_WRITEREG = 5, 11, 20, 25, 26, 45, 51
VAR_OUTDIR_COPY = 31  # $_OUTDIR
JUMPS = {2: (0,), 5: (0,), 12: (1, 2), 14: (0, 1), 22: (3, 5), 26: (2, 3), 28: (2, 3, 4), 34: (1, 2)}
VARS = ["$" + str(i) for i in range(10)] + ["$R" + str(i) for i in range(10)] + [
    "$CMDLINE", "$INSTDIR", "$OUTDIR", "$EXEDIR", "$LANGUAGE", "$TEMP", "$PLUGINSDIR", "$EXEPATH", "$EXEFILE",
    "$HWNDPARENT", "$_CLICK", "$_OUTDIR"]
SHELL = {(2, 23): "$SMPROGRAMS", (16, 25): "$DESKTOP", (11, 22): "$STARTMENU", (7, 24): "$SMSTARTUP",
         (5, 46): "$DOCUMENTS", (26, 35): "$APPDATA", (28, 28): "$LOCALAPPDATA"}
REG_FOLDERS = {"ProgramFilesDir": "$PROGRAMFILES", "CommonFilesDir": "$COMMONFILES"}


class Nsis:
    def __init__(self, path):
        with open(path, "rb") as f:
            data = f.read()
        pe = struct.unpack_from("<I", data, 0x3C)[0]
        if data[pe:pe + 4] != b"PE\0\0":
            raise ValueError("not a Windows program")
        opt = pe + 24
        self.pe64 = struct.unpack_from("<H", data, opt)[0] == 0x20B
        self.signed = struct.unpack_from("<II", data, opt + (112 if self.pe64 else 96) + 8 * 4)[1] > 0
        level = re.search(rb'requestedExecutionLevel\s+level="(\w+)"', data)
        self.level = level.group(1).decode() if level else "not set"
        sig = data.find(b"\xef\xbe\xad\xdeNullsoftInst")
        if sig < 4:
            raise ValueError("not an NSIS installer")
        fh = sig - 4
        header_len = struct.unpack_from("<I", data, fh + 20)[0]
        size = struct.unpack_from("<I", data, fh + 28)[0]
        block = data[fh + 32:fh + 32 + (size & 0x7FFFFFFF)]
        if size & 0x80000000:
            props = block[0]
            lc, rest = props % 9, props // 9
            lzma1 = {"id": lzma.FILTER_LZMA1, "dict_size": struct.unpack_from("<I", block, 1)[0],
                     "lc": lc, "lp": rest % 5, "pb": rest // 5}
            h = lzma.LZMADecompressor(lzma.FORMAT_RAW, filters=[lzma1]).decompress(block[5:], max_length=header_len)
        else:
            h = block
        if len(h) != header_len:
            raise ValueError("unsupported NSIS header (solid compression?)")
        for stride in (8, 12, 16):  # 32-bit or 64-bit block table
            blocks = [(struct.unpack_from("<I", h, 4 + stride * k)[0],
                       struct.unpack_from("<i", h, 4 + stride * k + (4 if stride == 8 else 8))[0]) for k in range(8)]
            if blocks[2][0] + 28 * blocks[2][1] == blocks[3][0] and blocks[0][0] < blocks[1][0] < blocks[2][0]:
                break
        else:
            raise ValueError("unknown NSIS header layout")
        (pages, n_pages), (sections, n_sections), (entries, n_entries), (strings, _), (langtables, _) = blocks[:5]
        self.units = struct.unpack_from("<%dH" % ((langtables - strings) // 2), h, strings)
        self.entries = [struct.unpack_from("<7i", h, entries + 28 * k) for k in range(n_entries)]
        fields = struct.unpack_from("<64i", h, 4 + 8 * stride)
        self.callbacks = {x for x in fields[10:20] if x >= 0}  # .onInit, .onGUIInit, ...
        page_size = (sections - pages) // max(n_pages, 1)
        for k in range(n_pages):  # page pre/show/leave functions
            self.callbacks |= {x for x in struct.unpack_from("<3i", h, pages + page_size * k + 8) if x >= 0}
        section_size = (entries - sections) // max(n_sections, 1)
        self.sections = [struct.unpack_from("<2i", h, sections + section_size * k + 12) for k in range(n_sections)]
        self.callbacks |= {code for code, _ in self.sections}
        self.entry_points = self.callbacks | {e[1] - 1 for e in self.entries if e[0] == OP_CALL and e[1] > 0}
        self.install_dir = None
        for i in range(20, 62):  # InstallDir, then the part of it a folder choice keeps: "...\VC3D", "VC3D"
            a, b = fields[i], fields[i + 1]
            if a > 0 and b > 0 and self.s(b) and self.s(a).endswith("\\" + self.s(b)):
                self.install_dir = (a, b)
                break

    def literal(self, i):
        j = i
        while 0 <= j < len(self.units) and self.units[j]:
            if self.units[j] in (NS_LANG, NS_SHELL, NS_VAR):
                return False
            j += 2 if self.units[j] == NS_SKIP else 1
        return True

    def s(self, i, resolve=False):
        if i < 0:
            return f"$(LangString{-(i + 1)})"
        out, u = [], self.units
        while i < len(u) and u[i]:
            c = u[i]
            if c in (NS_LANG, NS_SHELL, NS_VAR, NS_SKIP):
                p = u[i + 1]
                lo, hi = p & 0xFF, p >> 8
                if c == NS_SKIP:
                    out.append(chr(p))
                elif c == NS_VAR:
                    n = (lo & 0x7F) | ((hi & 0x7F) << 7)
                    out.append(VARS[n] if n < len(VARS) else f"$var{n}")
                elif c == NS_LANG:
                    out.append(f"$(LangString{(lo & 0x7F) | ((hi & 0x7F) << 7)})")
                elif lo & 0x80:  # folder read from HKLM\Software\Microsoft\Windows\CurrentVersion
                    name = self.s(lo & 0x3F)
                    out.append(self.reg_folder(name, lo & 0x40, hi) if resolve
                               else REG_FOLDERS.get(name, "$" + name) + ("64" if lo & 0x40 else ""))
                else:
                    out.append(SHELL.get((lo, hi), f"$SHELL({lo},{hi})"))
                i += 2
            else:
                out.append(chr(c))
                i += 1
        return "".join(out)

    def reg_folder(self, name, flag64, fallback):
        view = winreg.KEY_WOW64_64KEY if (flag64 or self.pe64) else winreg.KEY_WOW64_32KEY
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion",
                                0, winreg.KEY_READ | view) as key:
                return winreg.QueryValueEx(key, name)[0]
        except OSError:
            return self.s(fallback)

    def shortcuts(self):
        return [(self.s(e[1]), self.s(e[2])) for e in self.entries if e[0] == OP_CREATESHORTCUT]

    def extracted_files(self):
        out_dir, copy, files = "", "", []
        for e in self.entries:
            if e[0] == OP_ASSIGNVAR and e[1] == VAR_OUTDIR_COPY:  # File /r keeps the output folder in $_OUTDIR
                copy = self.s(e[2]).replace("$OUTDIR", out_dir)
            elif e[0] == OP_CREATEDIR and e[2]:  # SetOutPath
                out_dir = self.s(e[1]).replace("$_OUTDIR", copy)
            elif e[0] == OP_EXTRACTFILE:
                name = self.s(e[2])
                files.append(name if re.match(r"(\$|[A-Za-z]:\\)", name) else f"{out_dir}\\{name}")
        return files

    def jumped_into(self, first, last):
        if any(first <= p <= last for p in self.entry_points):
            return True
        return any(first <= e[1 + k] - 1 <= last for e in self.entries for k in JUMPS.get(e[0], ()) if e[1 + k] > 0)

    def skipped(self, call):
        """The compiled-in test right before `call` that always jumps over it, if any."""
        for k in range(call - 1, max(call - 4, -1), -1):
            e = self.entries[k]
            if e[0] == OP_STRCMP and self.literal(e[1]) and self.literal(e[2]):
                a, b = self.s(e[1]), self.s(e[2])
                jump = e[3] if (a == b if e[5] else a.lower() == b.lower()) else e[4]
                if jump > 0 and jump - 1 > call and not self.jumped_into(k + 1, call):
                    return f'StrCmp "{a}" "{b}"'
        return None

    def path_writes(self):
        """The code that writes a PATH value: {function start: ([entries that write], [(call, guard or None)])}."""
        report = {}
        for w, e in enumerate(self.entries):
            if e[0] != OP_WRITEREG or self.s(e[3]).upper() != "PATH":
                continue
            if any(code <= w < code + size for code, size in self.sections):
                report.setdefault(f"section code at {w}", ([], [("section code", None)]))[0].append(w)
                continue
            start = max(p for p in self.entry_points if p <= w)
            if start not in report:
                calls = [c for c, x in enumerate(self.entries) if x[0] == OP_CALL and x[1] - 1 == start]
                report[start] = ([], [(c, self.skipped(c)) for c in calls]
                                 + ([("as a callback", None)] if start in self.callbacks else []))
            report[start][0].append(w)
        return report


# ---------------------------------------------------------------- starting VC3D on a hidden desktop

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
GENERIC_ALL, CREATE_UNICODE_ENVIRONMENT, STARTF_USESTDHANDLES = 0x10000000, 0x400, 0x100
PW_RENDERFULLCONTENT, WM_CLOSE = 2, 0x0010


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [("cb", wt.DWORD), ("lpReserved", wt.LPWSTR), ("lpDesktop", wt.LPWSTR), ("lpTitle", wt.LPWSTR),
                ("dwX", wt.DWORD), ("dwY", wt.DWORD), ("dwXSize", wt.DWORD), ("dwYSize", wt.DWORD),
                ("dwXCountChars", wt.DWORD), ("dwYCountChars", wt.DWORD), ("dwFillAttribute", wt.DWORD),
                ("dwFlags", wt.DWORD), ("wShowWindow", wt.WORD), ("cbReserved2", wt.WORD),
                ("lpReserved2", ctypes.c_void_p), ("hStdInput", wt.HANDLE), ("hStdOutput", wt.HANDLE),
                ("hStdError", wt.HANDLE)]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [("hProcess", wt.HANDLE), ("hThread", wt.HANDLE), ("dwProcessId", wt.DWORD), ("dwThreadId", wt.DWORD)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG), ("biPlanes", wt.WORD),
                ("biBitCount", wt.WORD), ("biCompression", wt.DWORD), ("biSizeImage", wt.DWORD),
                ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG), ("biClrUsed", wt.DWORD),
                ("biClrImportant", wt.DWORD)]


WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
user32.CreateDesktopW.restype = wt.HANDLE
user32.CreateDesktopW.argtypes = [wt.LPCWSTR, wt.LPCWSTR, ctypes.c_void_p, wt.DWORD, wt.DWORD, ctypes.c_void_p]
user32.CloseDesktop.argtypes = [wt.HANDLE]
user32.SetThreadDesktop.argtypes = [wt.HANDLE]
user32.EnumDesktopWindows.argtypes = [wt.HANDLE, WNDENUMPROC, wt.LPARAM]
user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
user32.IsWindowVisible.argtypes = [wt.HWND]
user32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
user32.GetWindowDC.restype = wt.HDC
user32.GetWindowDC.argtypes = [wt.HWND]
user32.ReleaseDC.argtypes = [wt.HWND, wt.HDC]
user32.PrintWindow.argtypes = [wt.HWND, wt.HDC, wt.UINT]
user32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
gdi32.CreateCompatibleDC.restype = wt.HDC
gdi32.CreateCompatibleDC.argtypes = [wt.HDC]
gdi32.CreateDIBSection.restype = wt.HBITMAP
gdi32.CreateDIBSection.argtypes = [wt.HDC, ctypes.c_void_p, wt.UINT, ctypes.POINTER(ctypes.c_void_p), wt.HANDLE, wt.DWORD]
gdi32.SelectObject.restype = wt.HGDIOBJ
gdi32.SelectObject.argtypes = [wt.HDC, wt.HGDIOBJ]
gdi32.DeleteObject.argtypes = [wt.HGDIOBJ]
gdi32.DeleteDC.argtypes = [wt.HDC]
kernel32.CreateProcessW.argtypes = [wt.LPCWSTR, wt.LPWSTR, ctypes.c_void_p, ctypes.c_void_p, wt.BOOL, wt.DWORD,
                                    ctypes.c_void_p, wt.LPCWSTR, ctypes.POINTER(STARTUPINFOW),
                                    ctypes.POINTER(PROCESS_INFORMATION)]
kernel32.CloseHandle.argtypes = [wt.HANDLE]
kernel32.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
kernel32.WaitForSingleObject.restype = wt.DWORD
kernel32.GetExitCodeProcess.argtypes = [wt.HANDLE, ctypes.POINTER(wt.DWORD)]


def write_png(path, width, height, bgra):
    rows, stride = bytearray(), width * 4
    for y in range(height):
        line = bgra[y * stride:(y + 1) * stride]
        rgb = bytearray(width * 3)
        rgb[0::3], rgb[1::3], rgb[2::3] = line[2::4], line[1::4], line[0::4]
        rows.append(0)
        rows += rgb

    def chunk(kind, payload):
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)

    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(bytes(rows), 9)) + chunk(b"IEND", b""))


def windows_of(desk, pid):
    found = []

    @WNDENUMPROC
    def visit(hwnd, _):
        owner = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and user32.IsWindowVisible(hwnd):
            title, r = ctypes.create_unicode_buffer(256), wt.RECT()
            user32.GetWindowTextW(hwnd, title, 256)
            user32.GetWindowRect(hwnd, ctypes.byref(r))
            if r.right - r.left >= 80 and r.bottom - r.top >= 60:
                found.append((hwnd, title.value, (r.left, r.top, r.right, r.bottom)))
        return True

    user32.EnumDesktopWindows(desk, visit, 0)
    return found  # top of the z-order first


def grab(hwnd, rect):
    width, height = rect[2] - rect[0], rect[3] - rect[1]
    window_dc = user32.GetWindowDC(hwnd)
    dc = gdi32.CreateCompatibleDC(window_dc)
    header = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), width, -height, 1, 32, 0, 0, 0, 0, 0, 0)
    pixels = ctypes.c_void_p()
    bitmap = gdi32.CreateDIBSection(dc, ctypes.byref(header), 0, ctypes.byref(pixels), None, 0)
    data = b""
    if bitmap:
        old = gdi32.SelectObject(dc, bitmap)
        for flag in (PW_RENDERFULLCONTENT, 0):
            user32.PrintWindow(hwnd, dc, flag)
            data = ctypes.string_at(pixels, width * height * 4)
            if any(data[i] for i in range(0, len(data), 997)):
                break
        gdi32.SelectObject(dc, old)
        gdi32.DeleteObject(bitmap)
    gdi32.DeleteDC(dc)
    user32.ReleaseDC(hwnd, window_dc)
    return (rect, width, height, data) if data and any(data[i] for i in range(0, len(data), 997)) else None


def compose(shots, path):
    """Paste the window pictures where the windows are, bottom of the z-order first, like a screenshot."""
    left, top = min(s[0][0] for s in shots), min(s[0][1] for s in shots)
    width, height = max(s[0][2] for s in shots) - left, max(s[0][3] for s in shots) - top
    canvas = bytearray(b"\x40\x40\x40\xff" * (width * height))
    for (x0, y0, _, _), w, h, px in shots:
        for y in range(h):
            at = ((y0 - top + y) * width + (x0 - left)) * 4
            canvas[at:at + w * 4] = px[y * w * 4:(y + 1) * w * 4]
    write_png(path, width, height, canvas)
    return width, height


def read_catalog(cache_dir, sizes):
    """The catalog JSON that vc_reader saved in its cache, once its size stops changing: (name, bytes, samples)."""
    if not os.path.isdir(cache_dir):
        return None
    for name in sorted(os.listdir(cache_dir)):
        if not (name.startswith("metadata-") and name.endswith(".json")) or name.endswith(".info.json"):
            continue
        path = os.path.join(cache_dir, name)
        size = os.path.getsize(path)
        sizes.append(size)
        if size == 0 or sizes[-3:] != [size] * 3:
            return None
        try:
            with open(path, "rb") as f:
                data = f.read()
            catalog = json.loads(gzip.decompress(data) if data[:2] == b"\x1f\x8b" else data)
            return name, size, len(catalog.get("samples", {}))
        except (OSError, ValueError):
            return None
    return None


def watch(desk, pi, cache_dir, picture, out):
    """Runs in a new thread: SetThreadDesktop fails in a thread that already has a window."""
    try:
        if not user32.SetThreadDesktop(desk):
            raise OSError(f"SetThreadDesktop failed (error {ctypes.get_last_error()})")
        t0, seen, sizes, ready, wins, catalog = time.monotonic(), set(), [], None, [], None
        while True:
            elapsed = time.monotonic() - t0
            if kernel32.WaitForSingleObject(pi.hProcess, 0) == 0:
                out["exited_by_itself"] = True
                break
            wins = windows_of(desk, pi.dwProcessId)
            for _, title, rect in wins:
                if title not in seen:
                    seen.add(title)
                    say(f'  after {elapsed:3.0f} s: window "{title}" ({rect[2] - rect[0]}x{rect[3] - rect[1]})')
            if catalog is None:
                catalog = read_catalog(cache_dir, sizes)
                if catalog:
                    say(f"  after {elapsed:3.0f} s: catalog downloaded into the cache: {catalog[0]}, "
                        f"{catalog[1] / 1e6:.1f} MB, {catalog[2]} samples")
            titles = [w[1] for w in wins]
            if catalog and "Open Data Catalog" in titles and any(t.startswith("Volume Cartographer 3D") for t in titles):
                ready = ready or time.monotonic()
                if time.monotonic() - ready >= SETTLE:
                    break
            if elapsed > START_TIMEOUT:
                out["timeout"] = True
                break
            time.sleep(0.5)
        out["seconds_to_ready"] = round(time.monotonic() - t0, 1)
        out["windows"] = [{"title": t, "size": f"{r[2] - r[0]}x{r[3] - r[1]}"} for _, t, r in wins]
        out["catalog"] = catalog
        if wins and picture:
            shots = [s for s in (grab(h, r) for h, title, r in reversed(wins) if title == "Open Data Catalog") if s]
            if shots:
                out["picture"] = "%dx%d" % compose(shots, picture)
        for hwnd, _, _ in wins:
            user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
        out["closed_normally"] = kernel32.WaitForSingleObject(pi.hProcess, 20000) == 0
    except OSError as e:
        out["error"] = str(e)


# ---------------------------------------------------------------- leave the user's VC3D folders as they were

def places():
    profile = os.environ.get("USERPROFILE", os.path.expanduser("~"))
    folders = [os.path.join(profile, ".VC3D"), os.path.join(profile, ".cache", "vc_reader")]
    for var in ("APPDATA", "LOCALAPPDATA"):
        if os.environ.get(var):
            folders.append(os.path.join(os.environ[var], "Vesuvius Challenge"))
    return folders, r"Software\Vesuvius Challenge"


def snap_folder(path):
    if not os.path.isdir(path):
        return None
    out = {}
    for root, dirs, files in os.walk(path):
        for name in dirs + files:
            full = os.path.join(root, name)
            try:
                st = os.stat(full)
                out[os.path.relpath(full, path)] = (st.st_size if name in files else -1, st.st_mtime_ns)
            except OSError:
                pass
    return out


def snap_reg(path):
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, path)
    except OSError:
        return None
    out = {}
    with key:
        i = 0
        while True:
            try:
                name, value, kind = winreg.EnumValue(key, i)
            except OSError:
                break
            out["value:" + name] = (kind, value)
            i += 1
        i = 0
        while True:
            try:
                sub = winreg.EnumKey(key, i)
            except OSError:
                break
            out["key:" + sub] = snap_reg(path + "\\" + sub)
            i += 1
    return out


def delete_reg_tree(path):
    while True:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
                sub = winreg.EnumKey(key, 0)
        except OSError:
            break
        delete_reg_tree(path + "\\" + sub)
    winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)


def restore_reg(path, before, after, notes):
    if before is None:
        if after is not None:
            delete_reg_tree(path)
            notes.append(("removed", f"HKCU\\{path}, created by this run"))
        return
    for item, value in (after or {}).items():
        kind, _, name = item.partition(":")
        if kind == "key":
            restore_reg(path + "\\" + name, before.get(item), value, notes)
        elif item not in before or before[item] != value:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_SET_VALUE) as key:
                if item in before:
                    winreg.SetValueEx(key, name, 0, before[item][0], before[item][1])
                    notes.append(("restored", f"HKCU\\{path} value {name!r}"))
                else:
                    winreg.DeleteValue(key, name)
                    notes.append(("removed", f"HKCU\\{path} value {name!r}, created by this run"))


def snapshot():
    folders, reg = places()
    return {"folders": {f: snap_folder(f) for f in folders}, "reg": (reg, snap_reg(reg))}


def restore(before):
    notes = []
    for folder, old in before["folders"].items():
        new = snap_folder(folder)
        if old is None and new is not None:
            shutil.rmtree(folder, ignore_errors=True)
            notes.append(("removed", f"{folder}, created by this run"))
        elif old is not None and new != old:
            changed = sorted(k for k in set(old) | set(new or {}) if old.get(k) != (new or {}).get(k))
            notes.append(("CHANGED", f"{folder}: " + ", ".join(changed[:5]) + (" ..." if len(changed) > 5 else "")))
    reg, old = before["reg"]
    restore_reg(reg, old, snap_reg(reg), notes)
    return notes


def remove_tree(path):
    for _ in range(10):
        shutil.rmtree(path, ignore_errors=True)
        if not os.path.exists(path):
            return True
        time.sleep(1)
    return False


def start_portable(zip_path, top, work, picture):
    """Extract the .zip into an empty folder and start bin\\VC3D.exe from its bin folder on a hidden desktop."""
    result = {}
    dest = os.path.join(work, "extracted")
    t0 = time.monotonic()
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(dest)
    count = sum(len(f) for _, _, f in os.walk(dest))
    say(f"  extracted {count} files into <work>\\extracted in {time.monotonic() - t0:.1f} s")
    bin_dir = os.path.join(dest, top, "bin")
    exe = os.path.join(bin_dir, "VC3D.exe")
    config, cache = os.path.join(work, "config"), os.path.join(work, "vc_reader_cache")
    for d in (config, cache, os.path.join(work, "tmp")):
        os.makedirs(d, exist_ok=True)
    with open(os.path.join(config, "VC3D.ini"), "w", encoding="utf-8") as f:
        f.write("[viewer]\nremote_cache_dir={}\n\n[object_store]\ndraft_directory={}\n".format(
            os.path.join(work, "remote_cache").replace("\\", "/"), os.path.join(work, "drafts").replace("\\", "/")))
    env = {k: v for k, v in os.environ.items() if k.upper() not in ("HOME", "XDG_CACHE_HOME", "VC_READER_CACHE_DIR")}
    env.update(VC3D_CONFIG_DIR=config, VC_READER_CACHE_DIR=cache, TEMP=os.path.join(work, "tmp"), TMP=os.path.join(work, "tmp"))
    say("  VC3D_CONFIG_DIR=<work>\\config, VC_READER_CACHE_DIR=<work>\\vc_reader_cache, HOME not set")
    say(f"  starting {top}\\bin\\VC3D.exe, working directory {top}\\bin, on a hidden desktop")

    before = snapshot()
    try:
        user32.SetProcessDPIAware()
    except (OSError, AttributeError):
        pass
    name = f"vc3d_windows_tab_{os.getpid()}"
    desk = user32.CreateDesktopW(name, None, None, 0, GENERIC_ALL, None)
    if not desk:
        raise OSError(f"CreateDesktopW failed (error {ctypes.get_last_error()})")
    output = open(os.path.join(work, "vc3d-output.txt"), "wb")
    nul = open(os.devnull, "rb")
    for fd in (0, 1, 2):  # VC3D inherits only its own output file
        try:
            os.set_handle_inheritable(msvcrt.get_osfhandle(fd), False)
        except OSError:
            pass
    for f in (output, nul):
        os.set_handle_inheritable(msvcrt.get_osfhandle(f.fileno()), True)
    si, pi = STARTUPINFOW(), PROCESS_INFORMATION()
    si.cb, si.lpDesktop, si.dwFlags = ctypes.sizeof(si), "WinSta0\\" + name, STARTF_USESTDHANDLES
    si.hStdInput = msvcrt.get_osfhandle(nul.fileno())
    si.hStdOutput = si.hStdError = msvcrt.get_osfhandle(output.fileno())
    block = ctypes.create_unicode_buffer("".join(f"{k}={v}\0" for k, v in env.items()) + "\0")
    command = ctypes.create_unicode_buffer(subprocess.list2cmdline([exe]))
    started = kernel32.CreateProcessW(None, command, None, None, True, CREATE_UNICODE_ENVIRONMENT, block, bin_dir,
                                      ctypes.byref(si), ctypes.byref(pi))
    error = ctypes.get_last_error()
    output.close()
    nul.close()
    if not started:
        user32.CloseDesktop(desk)
        raise OSError(f"CreateProcessW failed (error {error})")
    try:
        thread = threading.Thread(target=watch, args=(desk, pi, cache, picture, result))
        thread.start()
        thread.join()
    finally:
        if kernel32.WaitForSingleObject(pi.hProcess, 0) != 0:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(pi.dwProcessId)], capture_output=True, creationflags=NO_WINDOW)
            kernel32.WaitForSingleObject(pi.hProcess, 15000)
            result["killed"] = True
        code = wt.DWORD()
        kernel32.GetExitCodeProcess(pi.hProcess, ctypes.byref(code))
        result["exit_code"] = code.value
        kernel32.CloseHandle(pi.hThread)
        kernel32.CloseHandle(pi.hProcess)
        user32.CloseDesktop(desk)
        result["places"] = restore(before)
    with open(os.path.join(work, "vc3d-output.txt"), "rb") as f:
        lines = f.read().decode("utf-8", "replace").splitlines()
    result["output"] = [ln for ln in lines if ln.strip()][:12]
    result["remote_cache_in_work"] = os.path.isdir(os.path.join(work, "remote_cache"))
    return result


# ---------------------------------------------------------------- the checks

def check(results, ident, claim, ok, evidence):
    results.append({"id": ident, "claim": claim, "ok": bool(ok), "evidence": evidence})
    say(f"  {'OK  ' if ok else 'NO  '} \"{claim}\"")
    say(wrap(evidence, "        "))


def require(text, quote):
    if quote not in text:
        raise RuntimeError(f"the tab does not say: {quote}")
    return quote


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("mode", choices=("before", "after"))
    parser.add_argument("--commit", required=True)
    parser.add_argument("--repo")
    parser.add_argument("--doc")
    here = os.path.dirname(os.path.abspath(__file__))
    parser.add_argument("--downloads", default=os.path.join(here, "downloads"))
    parser.add_argument("--work", default=os.path.join(here, "work"))
    parser.add_argument("--build", help="short commit of the 'latest' build to check, such as 97fb933 "
                        "(default: the current 'latest')")
    parser.add_argument("--capture")
    parser.add_argument("--json")
    parser.add_argument("--no-start", action="store_true", help="skip extracting the .zip and starting VC3D")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    work = os.path.abspath(args.work)
    hide(work, "<work>")
    hide(os.path.abspath(args.downloads), "<downloads>")
    if args.repo:
        hide(os.path.abspath(args.repo), "<repo>")
    hide(os.environ.get("USERPROFILE", os.path.expanduser("~")), "%USERPROFILE%")
    for var, label in (("COMPUTERNAME", "<pc>"), ("USERNAME", "<user>")):
        if len(os.environ.get(var, "")) >= 3:
            HIDE.append((re.compile(re.escape(os.environ[var]), re.IGNORECASE), label))

    t_start = time.monotonic()
    report = {"mode": args.mode, "checks": [], "vc3d": None}
    try:
        md, commit = read_doc(args)
        report["commit"] = commit
        tab, lines, launch = windows_tab(md)
        say(f"== [tab] Windows tab of {DOC} at {commit[:9]}")
        for ln in lines:
            say(wrap(ln, "  | ", 112))
        say(f"  Launching the GUI: {launch}")

        say('== [release] Windows downloads of the "latest" and "stable" releases of ' + REPO)
        rels = {}
        for tag in ("latest", "stable"):
            rel, exe, zp = windows_assets(tag, args.build if tag == "latest" else None)
            rels[tag] = (exe, zp)
            moved = f", since archived as {rel['tag_name']}" if rel.get("tag_name") != tag else ""
            say(f"  {tag} (published {rel.get('published_at', '?')[:10]}{moved}): "
                + ", ".join(a["name"] for a in exe + zp))
        exe_asset, zip_asset = rels["latest"][0][0], rels["latest"][1][0]

        say('== [sha] Local copies of the "latest" Windows downloads')
        zip_path = local_copy(zip_asset, args.downloads)
        exe_path = local_copy(exe_asset, args.downloads) if args.mode == "after" else None

        say(f"== [zip] Inside {zip_asset['name']}")
        z = zip_facts(zip_path)
        describe_zip(z)
        checks = report["checks"]

        if args.mode == "before":
            say("== [check] What the old tab says, against these files")
            check(checks, "installer_zip", require(tab, "Download the windows installer .zip file"), bool(z["installers"]),
                  f"The .zip is not an installer: it holds no install program (see above). The installer is the "
                  f"other Windows download, {exe_asset['name']}"
                  + ("; the tab never mentions an .exe." if ".exe" not in tab + launch else "."))
            check(checks, "install_file", require(tab, "Double click the install file"), bool(z["installers"]),
                  f"After extracting the .zip there is no install file to double click: its only programs are "
                  f"VC3D.exe and {len(z['tools'])} vc_*.exe tools, in bin\\.")
            check(checks, "start_menu", require(launch, "Open the application from the Start menu"),
                  bool(z["installers"]) or "VC3D.exe" in tab + launch,
                  "Extracting the .zip installs nothing, so nothing is added to the Start menu; the tab never "
                  "names bin\\VC3D.exe, the program to start.")
        else:
            say(f"== [installer] {exe_asset['name']}, read without running it")
            nsis = Nsis(exe_path)
            say(f"  NSIS installer, {'64' if nsis.pe64 else '32'}-bit, {'signed' if nsis.signed else 'not signed'}, "
                f"asks Windows for: {nsis.level}")
            default = nsis.s(nsis.install_dir[0]) if nsis.install_dir else "?"
            default_here = nsis.s(nsis.install_dir[0], resolve=True) if nsis.install_dir else "?"
            say(f"  InstallDir: {default} = {default_here} on this PC")
            files = nsis.extracted_files()
            prefix = "$INSTDIR\\bin\\"
            under_bin = [f[len(prefix):] for f in files if f.lower().startswith(prefix.lower())]
            in_bin = sorted(f for f in under_bin if "\\" not in f and f.lower().endswith(".exe"))
            elsewhere = sorted({f.rsplit("\\", 1)[0] for f in files if not f.lower().startswith(prefix.lower())})
            tools = sorted(f for f in in_bin if fnmatch.fnmatchcase(f.lower(), "vc_*.exe"))
            say(f"  files it writes under $INSTDIR\\bin: {len(under_bin)}; programs in $INSTDIR\\bin: "
                f"{'VC3D.exe and ' if 'VC3D.exe' in in_bin else ''}{len(tools)} vc_*.exe tools; "
                f"files it writes elsewhere go to: {', '.join(elsewhere) or 'nowhere'}")
            missing = sorted(set(z["tools"]) - set(tools))
            if missing:
                say(f"  vc_*.exe tools of the .zip that the installer does not have: {', '.join(missing)}")
            for link, target in nsis.shortcuts():
                say(f"  shortcut: {link} -> {target}")
            path_report = nsis.path_writes()
            calls_ok = all(calls for _, calls in path_report.values())  # no PATH code at all: nothing to skip
            guards = set()
            for start, (writes, calls) in path_report.items():
                say(f"  PATH is written by the function at entry {start} (entries {', '.join(map(str, writes))}); "
                    f"{len(calls)} call(s) to it:")
                for c, guard in calls:
                    calls_ok &= bool(guard)
                    guards.add(str(guard))
                    say(f"    call at entry {c}: " + (f"always skipped by {guard}, a test fixed when the installer "
                                                     f"was built" if guard else "can run"))

            say("== [check] What the new tab says, against these files")
            releases = all_releases()
            vc3d_rels = [r for r in releases if (r.get("name") or "").startswith("VC3D")]
            not_two = [r["tag_name"] for r in vc3d_rels if [len(x) for x in release_assets(r)] != [1, 1]]
            two = all(len(e) == 1 and len(zp) == 1 for e, zp in rels.values())
            check(checks, "downloads", require(tab, "Each VC3D release") + " ... "
                  + require(tab, "has two Windows downloads") + ": `VC3D-*-win64.exe`, `VC3D-*-win64.zip`",
                  two and vc3d_rels and not not_two and "`VC3D-*-win64.exe`" in tab and "`VC3D-*-win64.zip`" in tab,
                  f"{len(vc3d_rels)} of the {len(releases)} releases of {REPO} are VC3D releases (named "
                  + " or ".join(sorted({r['name'] for r in vc3d_rels})) + "); "
                  + (f"each publishes one {EXE_PATTERN} and one {ZIP_PATTERN}." if not not_two else
                     f"these do not publish exactly one {EXE_PATTERN} and one {ZIP_PATTERN}: {', '.join(not_two)}."))
            check(checks, "admin", require(tab, "needs administrator rights"), nsis.level == "requireAdministrator",
                  f"The installer asks Windows for {nsis.level} (see above), so Windows starts it only with "
                  f"administrator rights.")
            start_menu = [(l, t) for l, t in nsis.shortcuts()
                          if l.startswith("$SMPROGRAMS\\") and t.lower() == "$instdir\\bin\\vc3d.exe"]
            check(checks, "start_menu", require(tab, "VC3D is then in the Start menu"), start_menu,
                  f"The installer creates the shortcut {start_menu[0][0] if start_menu else '(none)'} to "
                  f"$INSTDIR\\bin\\VC3D.exe.")
            said = re.search(r"by default `([^`]+)` with the installer", tab)
            check(checks, "default_folder", require(tab, "by default `C:\\Program Files\\VC3D\\bin` with the installer"),
                  said and default_here + "\\bin" == said.group(1) and "VC3D.exe" in in_bin,
                  f"InstallDir is {default}, {default_here} here, and the programs go to $INSTDIR\\bin.")
            check(checks, "path", require(tab, "That folder is not added to `PATH`"), calls_ok,
                  (f"The only code of the installer that writes PATH is one function, and its only call is always "
                   f"skipped ({', '.join(sorted(guards))})." if len(path_report) == 1 and len(guards) == 1
                   else "No code of the installer writes PATH." if not path_report
                   else "Every call to the code that writes PATH is always skipped.") if calls_ok
                  else "A call to the code that writes PATH can run.")
            check(checks, "tools", require(tab, "Both contain VC3D together with the `vc_*` command-line tools, in the `bin` folder"),
                  z["has_vc3d"] and z["tools"] and "VC3D.exe" in in_bin and tools,
                  f"bin\\ of the .zip: VC3D.exe and {len(z['tools'])} vc_*.exe; $INSTDIR\\bin of the installer: "
                  f"VC3D.exe and {len(tools)} vc_*.exe.")
            check(checks, "nothing_to_install", require(tab, "There is nothing to install"), not z["installers"],
                  "The .zip holds no install program.")
            if args.no_start:
                say("== [start] skipped (--no-start)")
            else:
                say(f"== [start] Extract {zip_asset['name']} and double click bin\\VC3D.exe")
                say(f"  on {platform.platform()}")
                if os.path.exists(work) and not remove_tree(work):
                    raise RuntimeError("the work folder of an earlier run cannot be deleted")
                os.makedirs(work)
                vc3d = start_portable(zip_path, z["top"], work, args.capture)
                report["vc3d"] = vc3d
                short = zip_asset["name"].split("-")[1]
                titles = [w["title"] for w in vc3d.get("windows", [])]
                for ln in vc3d["output"]:
                    say("  VC3D output | " + ln)
                say(f"  VC3D closed {'by itself after WM_CLOSE' if vc3d.get('closed_normally') else 'by taskkill'}"
                    f" (exit code {vc3d.get('exit_code')}); remote cache in <work>: {vc3d['remote_cache_in_work']}")
                for what, text in vc3d["places"]:
                    say(f"  {what}: {text}")
                if not vc3d["places"]:
                    say("  %USERPROFILE%\\.VC3D, %USERPROFILE%\\.cache\\vc_reader, %APPDATA% and %LOCALAPPDATA%\\Vesuvius "
                        "Challenge, HKCU\\Software\\Vesuvius Challenge: unchanged")
                if args.capture and vc3d.get("picture"):
                    say(f"  picture of the Open Data Catalog window: {os.path.basename(args.capture)} ({vc3d['picture']})")
                catalog = vc3d.get("catalog")
                main_title = next((t for t in titles if t.startswith("Volume Cartographer 3D")), "")
                check(checks, "double_click", require(tab, "double click `VC3D.exe` in the `bin` folder"),
                      z["has_vc3d"] and short in main_title and "Open Data Catalog" in titles and catalog
                      and not vc3d.get("error"),
                      f'VC3D opened "{main_title}" and "Open Data Catalog"; the catalog lists '
                      f"{catalog[2] if catalog else 0} samples.")
                check(checks, "launch", require(launch, "With the portable .zip, double click `VC3D.exe` in the `bin` folder instead"),
                      checks[-1]["ok"], "Same start as above.")
                if any(what == "CHANGED" for what, _ in vc3d["places"]):
                    raise RuntimeError("VC3D changed files of the user's own VC3D folders (see above)")
    except Exception as e:  # report every failure the same way
        report["error"] = f"{type(e).__name__}: {e}"
        say(f"== [error] {report['error']}")
    finally:
        if os.path.isdir(work) and not args.no_start:
            report["work_removed"] = remove_tree(work)
            say(f"== [clean] work folder deleted: {report['work_removed']}")

    bad = [c for c in report["checks"] if not c["ok"]]
    report["seconds"] = round(time.monotonic() - t_start, 1)
    if "error" in report or report.get("work_removed") is False:
        report["result"], code = "error", 2
        say(f"RESULT: the check could not be done ({report.get('error', 'work folder left')})")
    elif bad:
        report["result"], code = "does not match", 1
        say(f"RESULT: the Windows tab at {report['commit'][:9]} does not match the downloads: "
            f"{len(bad)} of {len(report['checks'])} sentences are wrong ({report['seconds']:.0f} s)")
    else:
        report["result"], code = "matches", 0
        say(f"RESULT: the Windows tab at {report['commit'][:9]} matches the downloads: "
            f"{len(report['checks'])} of {len(report['checks'])} sentences checked ({report['seconds']:.0f} s)")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            f.write(clean(json.dumps(report, indent=1, ensure_ascii=False, default=str)))
    return code


if __name__ == "__main__":
    sys.exit(main())
