"""A volume served from a URL with a port, rendered by a VC3D for Windows.

    python vc3d_port.py NAME BIN [DLLS]

NAME  a label for the run: its VC3D settings, remote cache and renders go to ./runs/NAME.
BIN   the `bin` folder of a VC3D for Windows: the released package, or a build.
DLLS  for a build that is not packaged, the folder of the DLLs it needs (MSYS2's ucrt64\\bin).

Runs BIN's vc_render_tifxyz three times, on level 2 of the PHerc0800 volume
20250521135224-8.640um-1.2m-116keV-masked.zarr and its published segment
20251029010146-auto_grown_20251029010146642 (a 210x210 image of the papyrus surface):

  local  the volume read from the disk                                             control
  port   the same files served by `python -m http.server` on 127.0.0.1 and a free port
  root   the volume's folder served at the root of such a server: http://127.0.0.1:<port>

and prints what each run wrote, its exit code, the image it rendered (size, range of values and the
SHA-256 of its pixels) and the folders it created in the remote cache. The exit code is 0 when both
served volumes were rendered and their images are the local one, pixel for pixel.

Data: from the public bucket vesuvius-challenge-open-data, downloaded once into ./mirror (15 MB):
the documents of the volume, the .zarray of its six levels, the seven level-2 chunks this render
reads, and the segment's tifxyz. Nothing is written outside this script's folder. Needs Pillow, to read
the images.
"""
import contextlib
import hashlib
import os
import pathlib
import shutil
import socket
import subprocess
import sys
import urllib.request

from PIL import Image

BUCKET = "https://vesuvius-challenge-open-data.s3.amazonaws.com/"
VOLUME = "PHerc0800/volumes/20250521135224-8.640um-1.2m-116keV-masked.zarr"
SEGMENT = "PHerc0800/segments/20251029010146-auto_grown_20251029010146642/mesh/intermediate/tifxyz_original"
CHUNKS = ["22/11/6", "22/12/6", "23/11/6", "23/12/6", "23/12/7", "24/11/6", "24/12/6"]  # all that this render reads
VOLUME_OBJECTS = [".zgroup", ".zattrs", "metadata.json", *(f"{level}/.zarray" for level in range(6)),
                  *(f"2/{chunk}" for chunk in CHUNKS)]
SEGMENT_OBJECTS = ["meta.json", "x.tif", "y.tif", "z.tif"]

HERE = pathlib.Path(__file__).resolve().parent
MIRROR = HERE / "mirror"


def without_user_name(text):
    return text.replace(str(pathlib.Path.home()), r"C:\Users\me").replace(pathlib.Path.home().as_posix(), "C:/Users/me")


def download():
    for prefix, names in ((VOLUME, VOLUME_OBJECTS), (SEGMENT, SEGMENT_OBJECTS)):
        for name in names:
            target = MIRROR / prefix / name
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                with urllib.request.urlopen(BUCKET + prefix + "/" + name, timeout=120) as response:
                    target.write_bytes(response.read())


def run(tool, arguments, environment):
    """One command: prints it, what it wrote and its exit code. Returns the exit code."""
    print(without_user_name("$ " + subprocess.list2cmdline([tool.name, *arguments])))
    done = subprocess.run([str(tool), *arguments], env=environment, capture_output=True, timeout=600)
    text = (done.stdout + done.stderr).decode("utf-8", "replace").replace("\r", "")
    for line in text.splitlines():
        if line.strip() and "tiles/s" not in line:  # not the progress line
            print(without_user_name("    " + line.strip()))
    print(f"    exit code {done.returncode}\n")
    return done.returncode


@contextlib.contextmanager
def served(directory):
    """`python -m http.server` on a free port of 127.0.0.1; gives the port."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = subprocess.Popen([sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1", "--directory", str(directory)],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            with socket.socket() as probe:
                probe.settimeout(0.2)
                if probe.connect_ex(("127.0.0.1", port)) == 0:
                    break
        yield port
    finally:
        server.terminate()
        server.wait()


def image(folder):
    """The one image a render wrote: its size, its range of values and the SHA-256 of its pixels, or None.

    Not the SHA-256 of the file: its four tiles are stored in the order they were rendered, which
    changes from run to run.
    """
    files = sorted(folder.glob("*.tif")) if folder.is_dir() else []
    if len(files) != 1:
        return None
    with Image.open(files[0]) as picture:
        low, high = picture.getextrema()
        return f"{picture.width}x{picture.height}, values {low} to {high}, pixels {hashlib.sha256(picture.tobytes()).hexdigest()}"


def main():
    if len(sys.argv) not in (3, 4):
        sys.exit(__doc__)
    sys.stdout.reconfigure(encoding="utf-8")  # a log file reads the same on every PC
    name, tools = sys.argv[1], pathlib.Path(sys.argv[2])
    render = tools / "vc_render_tifxyz.exe"
    if not render.is_file():
        sys.exit(f"FAILED: no vc_render_tifxyz.exe in {tools}")
    download()
    work = HERE / "runs" / name
    shutil.rmtree(work, ignore_errors=True)
    for folder in ("config", "cache", "output"):
        (work / folder).mkdir(parents=True)
    environment = dict(os.environ, VC3D_CONFIG_DIR=str(work / "config"))
    if len(sys.argv) == 4:
        environment["PATH"] = sys.argv[3] + os.pathsep + environment["PATH"]
    run(tools / "vc_cache_root.exe", ["--set", str(work / "cache")], environment)

    def render_level2(case, location):
        return run(render, ["-v", location, "-s", str(MIRROR / SEGMENT), "-g", "2", "--scale", "1",
                            "--tif-output", str(work / "output" / case), "--cache-gb", "1"], environment)

    codes = {"local": render_level2("local", str(MIRROR / VOLUME))}
    with served(MIRROR) as port:
        codes["port"] = render_level2("port", f"http://127.0.0.1:{port}/{VOLUME}")
    with served(MIRROR / VOLUME) as port:
        codes["root"] = render_level2("root", f"http://127.0.0.1:{port}")

    images = {case: image(work / "output" / case) for case in codes}
    for case, code in codes.items():
        print(f"{case:6} exit code {code}   image: {images[case] or 'none'}")
    cached = sorted(path.relative_to(work / "cache") for path in (work / "cache").glob("*/*"))
    print("remote cache:", ", ".join(str(path) for path in cached) or "nothing")
    if any(codes[case] != 0 or images[case] is None for case in ("port", "root")):
        print("RESULT: FAILED: the volume served on a port was not rendered")
    elif codes["local"] != 0 or any(images[case] != images["local"] for case in ("port", "root")):
        print("RESULT: FAILED: the image rendered from the port is not the local one")
    else:
        print("RESULT: the volume served on a port was rendered, and its image is the local one")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
