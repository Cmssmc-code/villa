"""Starts VC3D on a hidden desktop, in a chosen working folder and with no HOME variable (the way
Windows starts a program), and reports what its Open Data Catalog does.

    python vc3d_catalog.py NAME BIN CWD [PROFILE]

NAME  name of the run: its files go to runs/NAME next to this script (the folder is emptied first)
BIN   the bin folder that holds VC3D.exe
CWD   the folder VC3D starts in; "-" for a new empty folder, runs/NAME/cwd
PROFILE  the name of the profile folder, "profile" unless given (to try a name with accents)

VC3D gets a configuration folder and a user profile of its own (runs/NAME/config and
runs/NAME/PROFILE), so the catalog cache of the real profile is neither read nor written. The one
file VC3D writes in the real profile, the announcement of its agent bridge
(.vc3d/agent_bridge/<pid>.json), is removed at the end.

Prints the answer of catalog.list_samples (asked through VC3D's own agent bridge), saves a picture of
the "Open Data Catalog" window (runs/NAME/open-data-catalog.png) and lists the catalog cache files
found in the working folder and in the profile. Nothing shows on screen; VC3D is closed at the end.
Exit code: 0 when VC3D answered (whatever the answer), 2 when it did not.
"""
import contextlib
import ctypes
import json
import os
import pathlib
import shutil
import subprocess
import sys
import threading
import time

ICI = pathlib.Path(os.path.abspath(os.path.dirname(__file__)))  # abspath : garde un lecteur subst tel quel
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "outils"))  # resolve : le vrai dossier
import capture_console as cc  # noqa: E402
import capture_fenetres as cf  # noqa: E402

ATTENTE_FENETRE = 25  # secondes laissées à la fenêtre du catalogue pour finir son propre chargement
DELAI_TOTAL = 240


def appel(tube, methode, ident, delai):
    """Un appel JSON-RPC (une ligne par message) ; rend la réponse qui porte le même id."""
    tube.write((json.dumps({"jsonrpc": "2.0", "id": ident, "method": methode}) + "\n").encode("utf-8"))
    fin = time.time() + delai
    while True:
        boite = {}
        fil = threading.Thread(target=lambda: boite.update(ligne=tube.readline()), daemon=True)
        fil.start()
        fil.join(max(0.0, fin - time.time()))
        if "ligne" not in boite:
            raise TimeoutError(f"{methode}: no answer in {delai} s")
        if not boite["ligne"]:
            raise OSError(f"{methode}: VC3D closed the bridge")
        message = json.loads(boite["ligne"])
        if message.get("id") == ident:
            return message


def resume(reponse):
    if "error" in reponse:
        erreur = reponse["error"]
        detail = (erreur.get("data") or {}).get("detail", "")
        return f'error {erreur.get("code")} "{erreur.get("message")}": {detail}'
    echantillons = reponse["result"]["samples"]
    return f'{len(echantillons)} samples ({", ".join(e["id"] for e in echantillons[:4])}, ...)'


def inscriptible(dossier):
    essai = pathlib.Path(dossier) / f"vc3d-catalog-write-test-{os.getpid()}.tmp"
    try:
        essai.write_bytes(b"")
        essai.unlink()
        return True
    except OSError:
        return False


def main():
    if len(sys.argv) not in (4, 5):
        sys.exit(__doc__)
    sys.stdout.reconfigure(encoding="utf-8")
    nom, binaire, courant = sys.argv[1], sys.argv[2], sys.argv[3]
    profil = sys.argv[4] if len(sys.argv) == 5 else "profile"
    essai = ICI / "runs" / nom
    if essai.exists():
        shutil.rmtree(essai)
    for dossier in ("config", profil, "windows"):
        (essai / dossier).mkdir(parents=True)
    if courant == "-":
        (essai / "cwd").mkdir()
        courant = str(essai / "cwd")
    exe = os.path.join(binaire, "VC3D.exe")
    if not os.path.isfile(exe):
        sys.exit(f"no VC3D.exe in {binaire}")
    env = {k: v for k, v in os.environ.items() if k.upper() not in ("HOME", "VC_READER_CACHE_DIR", "XDG_CACHE_HOME")}
    env["VC3D_CONFIG_DIR"] = str(essai / "config")
    env["USERPROFILE"] = str(essai / profil)
    print(f"VC3D: {exe}")
    print(f"working folder: {courant} ({'writable' if inscriptible(courant) else 'not writable'} for this user)")
    print(f"HOME: not set ; USERPROFILE: {env['USERPROFILE']}")

    try:
        cc.user32.SetProcessDPIAware()
    except OSError:
        pass
    pont = f"vc3d-catalog-{os.getpid()}"
    annonces = pathlib.Path.home() / ".vc3d" / "agent_bridge"
    annonces_avant = annonces.is_dir()
    nom_bureau = f"vc3d_catalog_{os.getpid()}"
    bureau = cc.user32.CreateDesktopW(nom_bureau, None, None, 0, cc.GENERIC_ALL, None)
    if not bureau:
        sys.exit(f"CreateDesktopW failed (error {ctypes.get_last_error()})")
    si = cc.STARTUPINFOW()
    si.cb = ctypes.sizeof(si)
    si.lpDesktop = "WinSta0\\" + nom_bureau
    pi = cc.PROCESS_INFORMATION()
    commande = ctypes.create_unicode_buffer(subprocess.list2cmdline([exe, "--cache-size", "1", "--agent-bridge-name", pont]))
    bloc_env = ctypes.create_unicode_buffer("".join(f"{k}={v}\0" for k, v in env.items()) + "\0")
    if not cc.kernel32.CreateProcessW(None, commande, None, None, False, cc.CREATE_UNICODE_ENVIRONMENT,
                                      bloc_env, courant, ctypes.byref(si), ctypes.byref(pi)):
        erreur = ctypes.get_last_error()
        cc.user32.CloseDesktop(bureau)
        sys.exit(f"CreateProcessW failed (error {erreur})")

    def tuer():
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(pi.dwProcessId)], capture_output=True)

    annonce = annonces / f"{pi.dwProcessId}.json"
    chien = threading.Timer(DELAI_TOTAL, tuer)
    chien.daemon = True
    chien.start()
    code = 0
    try:
        tube, limite = None, time.time() + 120
        while tube is None and time.time() < limite:
            try:
                tube = open("\\\\.\\pipe\\" + pont, "r+b", buffering=0)
            except OSError:
                time.sleep(0.5)
        if tube is None:
            print("VC3D's agent bridge did not appear in 120 s")
            return 2
        version = appel(tube, "ping", 1, 30).get("result", {}).get("version", "?")
        print(f"VC3D version: {version}")
        time.sleep(ATTENTE_FENETRE)
        print("catalog.list_samples:", resume(appel(tube, "catalog.list_samples", 2, 120)))
        time.sleep(3)
        resultat = {}
        fil = threading.Thread(target=cf.capturer_tout, args=(bureau, str(essai / "windows"), resultat))
        fil.start()
        fil.join()
        image = resultat.get("images", {}).get("Open Data Catalog")
        if image:
            os.replace(image, essai / "open-data-catalog.png")
            print(f'window "Open Data Catalog": picture in runs\\{nom}\\open-data-catalog.png')
        else:
            print('window "Open Data Catalog": not found (' + "; ".join(resultat.get("lignes", [resultat.get("erreur", "")])) + ")")
    except (OSError, TimeoutError, ValueError) as e:
        print(f"FAILED: {e}")
        code = 2
    finally:
        tuer()
        chien.cancel()
        # VC3D annonce son pont dans <vrai profil>/.vc3d/agent_bridge/<pid>.json (QDir::homePath(), quel que
        # soit USERPROFILE) et ne retire ce fichier qu'à une fermeture normale : on retire le nôtre.
        with contextlib.suppress(OSError, ValueError):
            if json.loads(annonce.read_text(encoding="utf-8")).get("name") == pont:
                annonce.unlink()
            if not annonces_avant:
                annonce.parent.rmdir()  # seulement s'il est vide
        cc.kernel32.CloseHandle(pi.hThread)
        cc.kernel32.CloseHandle(pi.hProcess)
        cc.user32.CloseDesktop(bureau)
    for nom_lieu, lieu in (("working folder", pathlib.Path(courant)), ("%USERPROFILE%", essai / profil)):
        cache = lieu / ".cache" / "vc_reader"
        fichiers = sorted(f for f in cache.glob("*") if f.is_file()) if cache.is_dir() else []
        if not fichiers:
            print(f"catalog cache in the {nom_lieu}: none")
        for f in fichiers:
            print(f"catalog cache in the {nom_lieu}: .cache\\vc_reader\\{f.name} ({f.stat().st_size} bytes)")
    return code


if __name__ == "__main__":
    sys.exit(main())
