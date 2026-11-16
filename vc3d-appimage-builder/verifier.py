"""Replay the proof for the VC3D AppImage builder-image pin (read-only, about 1 minute).

1. Hash that ci.sh wants for main (Dockerfile + install_build_deps.sh).
2. vc-builder-deps-hash label of the image pinned on main and of the new pin (public ghcr.io, anonymous).
3. Conclusion of the Linux AppImage runs before / after (gh, read-only).
"""
import hashlib, json, subprocess, sys, urllib.request

REPO = r"%USERPROFILE%\Dev\vesuvius\villa"
IMG = "scrollprize/villa/volume-cartographer"
OLD = "sha256:1bebf104edbd6c290ddbaf8036c919635259f3722e8eddb31340b240baf1ed68"
NEW = "sha256:e1c9abfd3f89cdb24fa0c4330d907408035669630f6450643d9055f486daab9b"
RUNS = [
    # (label, repo, run id, what, expected conclusion)
    ("before", "ScrollPrize/villa", "43611898774", "main 2d3fb38d3, team runner (14/11)", "failure"),
    ("before", "Cmssmc-code/villa", "43774795375", "main + hosted runner, fork", "failure"),
    ("before", "Cmssmc-code/villa", "43774804955", "main + #2557 + hosted runner, fork", "failure"),
    ("pin   ", "Cmssmc-code/villa", "43774807996", "main + this fix + hosted runner: configure/compile OK, stops at #2557's install error", "failure"),
    ("after ", "Cmssmc-code/villa", "43774811522", "main + this fix + #2557 + hosted runner", "success"),
    ("real  ", "Cmssmc-code/villa", "43785970414", "that AppImage: vc_tifxyz2obj + vc_obj2tifxyz on PHerc0800 auto_grown_20251029010146642", "success"),
]

def blob(rev_path):
    return subprocess.run(["git", "-C", REPO, "show", rev_path], capture_output=True, check=True).stdout

def get(url, token=None, accept=None):
    req = urllib.request.Request(url)
    if token: req.add_header("Authorization", "Bearer " + token)
    if accept: req.add_header("Accept", accept)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)

want = hashlib.sha256(blob("origin/main:volume-cartographer/Dockerfile")
                      + blob("origin/main:volume-cartographer/scripts/install_build_deps.sh")).hexdigest()[:16]
print(f"[1] deps hash ci.sh wants for origin/main: {want}")

# The pins really are the ones in the files: OLD on main, NEW in the fix commit.
FIX = "26be730181056d430f4d5d99bca48e83362f5d74"
pin_main = OLD in blob("origin/main:volume-cartographer/scripts/Dockerfile.appimage").decode()
pin_fix = NEW in blob(f"{FIX}:volume-cartographer/scripts/Dockerfile.appimage").decode()
print(f"    Dockerfile.appimage pins OLD on origin/main: {pin_main} ; NEW in fix commit {FIX[:9]}: {pin_fix}")

tok = get(f"https://ghcr.io/token?scope=repository:{IMG}:pull")["token"]
accept = "application/vnd.oci.image.manifest.v1+json,application/vnd.docker.distribution.manifest.v2+json"
labels = {}
for name, dig in (("pinned on main", OLD), ("new pin       ", NEW)):
    man = get(f"https://ghcr.io/v2/{IMG}/manifests/{dig}", tok, accept)
    cfg = get(f"https://ghcr.io/v2/{IMG}/blobs/{man['config']['digest']}", tok)
    lab = (cfg.get("config") or {}).get("Labels") or {}
    labels[dig] = lab.get("vc-builder-deps-hash")
    print(f"[2] {name} {dig[:19]}...  deps-hash={labels[dig]}  created={cfg.get('created','')[:10]}"
          f"  revision={lab.get('org.opencontainers.image.revision','')[:9]}")

print("[3] Linux AppImage runs (expected / obtained):")
runs_ok = True
for tag, repo, run, what, expected in RUNS:
    out = subprocess.run(["gh", "run", "view", run, "--repo", repo, "--json", "conclusion,headSha"],
                         capture_output=True, text=True)
    info = json.loads(out.stdout) if out.returncode == 0 else {"conclusion": "?", "headSha": "?"}
    got = info["conclusion"]
    runs_ok &= (got == expected)
    print(f"    {tag} expected={expected:<8} obtained={got:<8} https://github.com/{repo}/actions/runs/{run}")
    print(f"           ({what})")

print()
print("Expected: old pin deps-hash != wanted hash; new pin deps-hash == wanted hash;")
print("          runs: before = failure (concurrentqueue missing), after = success.")
ok = pin_main and pin_fix and labels[OLD] != want and labels[NEW] == want and runs_ok
print("Obtained:", "OK, the new pin matches main" if ok else "MISMATCH")
sys.exit(0 if ok else 1)
