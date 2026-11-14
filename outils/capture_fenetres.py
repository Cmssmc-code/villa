"""Lance un programme à fenêtres sur un bureau caché, attend, puis enregistre une capture PNG de
chacune de ses fenêtres visibles. Rien n'apparaît à l'écran.

Usage : python capture_fenetres.py <dossier_sortie> <attente_s> <dossier_courant> [-VAR ...] [VAR=valeur ...] -- <exe> [arguments...]

  -VAR         retire la variable d'environnement VAR pour le programme lancé
  VAR=valeur   la fixe

Si <dossier_sortie>/STOP apparaît avant la fin de l'attente, la capture est prise tout de suite.
Écrit <dossier_sortie>/fenetre-<n>.png et affiche pour chaque fenêtre : classe, titre, taille.
Le programme (et ses enfants) est tué à la fin.
"""
import ctypes
import ctypes.wintypes as wt
import os
import subprocess
import sys
import threading
import time

import capture_console as cc

user32, kernel32, gdi32 = cc.user32, cc.kernel32, cc.gdi32
user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]


def capturer_tout(bureau, dossier, resultat):
    """Doit tourner dans un fil neuf : SetThreadDesktop échoue si le fil a déjà une fenêtre."""
    try:
        if not user32.SetThreadDesktop(bureau):
            raise OSError(f"SetThreadDesktop a échoué (erreur {ctypes.get_last_error()})")
        fenetres = []

        @cc.WNDENUMPROC
        def rappel(hwnd, _):
            if user32.IsWindowVisible(hwnd):
                fenetres.append(hwnd)
            return True

        user32.EnumDesktopWindows(bureau, rappel, 0)
        lignes, images = [], {}
        for n, hwnd in enumerate(fenetres, 1):
            classe = ctypes.create_unicode_buffer(128)
            titre = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, classe, 128)
            user32.GetWindowTextW(hwnd, titre, 256)
            r = wt.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(r))
            largeur, hauteur = r.right - r.left, r.bottom - r.top
            if largeur < 80 or hauteur < 60:
                lignes.append(f"fenetre-{n} ignorée ({largeur}x{hauteur}) classe={classe.value!r} titre={titre.value!r}")
                continue
            dc_fenetre = user32.GetWindowDC(hwnd)
            dc = gdi32.CreateCompatibleDC(dc_fenetre)
            entete = cc.BITMAPINFOHEADER(ctypes.sizeof(cc.BITMAPINFOHEADER), largeur, -hauteur, 1, 32, 0, 0, 0, 0, 0, 0)
            pixels = ctypes.c_void_p()
            image = gdi32.CreateDIBSection(dc, ctypes.byref(entete), 0, ctypes.byref(pixels), None, 0)
            if not image:
                lignes.append(f"fenetre-{n} : CreateDIBSection a échoué")
                continue
            ancien = gdi32.SelectObject(dc, image)
            donnees, rendu = b"", "noire"
            for drapeau in (cc.PW_RENDERFULLCONTENT, 0):
                user32.PrintWindow(hwnd, dc, drapeau)
                donnees = ctypes.string_at(pixels, largeur * hauteur * 4)
                if any(donnees[i] for i in range(0, len(donnees), 997)):
                    rendu = f"PrintWindow({drapeau})"
                    break
            gdi32.SelectObject(dc, ancien)
            gdi32.DeleteObject(image)
            gdi32.DeleteDC(dc)
            user32.ReleaseDC(hwnd, dc_fenetre)
            if rendu != "noire":
                cc.ecrire_png(os.path.join(dossier, f"fenetre-{n}.png"), largeur, hauteur, donnees)
                images[titre.value] = os.path.join(dossier, f"fenetre-{n}.png")
            lignes.append(f"fenetre-{n} {largeur}x{hauteur} {rendu} classe={classe.value!r} titre={titre.value!r}")
        resultat["lignes"] = lignes
        resultat["images"] = images  # titre de la fenêtre -> fichier PNG
    except OSError as e:
        resultat["erreur"] = str(e)


def main():
    if "--" not in sys.argv or sys.argv.index("--") < 4 or sys.argv.index("--") == len(sys.argv) - 1:
        sys.exit(__doc__)
    coupe = sys.argv.index("--")
    dossier = os.path.abspath(sys.argv[1])
    attente = float(sys.argv[2])
    courant = os.path.abspath(sys.argv[3])
    env = dict(os.environ)
    for reglage in sys.argv[4:coupe]:
        if reglage.startswith("-"):
            for nom in [n for n in env if n.upper() == reglage[1:].upper()]:
                del env[nom]
        else:
            nom, _, valeur = reglage.partition("=")
            env[nom] = valeur
    exe, arguments = os.path.abspath(sys.argv[coupe + 1]), sys.argv[coupe + 2:]
    os.makedirs(dossier, exist_ok=True)
    stop = os.path.join(dossier, "STOP")
    if os.path.exists(stop):
        os.remove(stop)
    try:
        user32.SetProcessDPIAware()
    except OSError:
        pass
    nom = f"vesuvius_fenetres_{os.getpid()}"
    bureau = user32.CreateDesktopW(nom, None, None, 0, cc.GENERIC_ALL, None)
    if not bureau:
        sys.exit(f"CreateDesktopW a échoué (erreur {ctypes.get_last_error()})")
    si = cc.STARTUPINFOW()
    si.cb = ctypes.sizeof(si)
    si.lpDesktop = "WinSta0\\" + nom
    pi = cc.PROCESS_INFORMATION()
    bloc_env = ctypes.create_unicode_buffer("".join(f"{k}={v}\0" for k, v in env.items()) + "\0")
    commande = ctypes.create_unicode_buffer(subprocess.list2cmdline([exe, *arguments]))
    if not kernel32.CreateProcessW(None, commande, None, None, False, cc.CREATE_UNICODE_ENVIRONMENT,
                                   bloc_env, courant, ctypes.byref(si), ctypes.byref(pi)):
        erreur = ctypes.get_last_error()
        user32.CloseDesktop(bureau)
        sys.exit(f"CreateProcessW a échoué (erreur {erreur})")
    limite = time.time() + attente
    while time.time() < limite and not os.path.exists(stop):
        time.sleep(0.5)
    resultat = {}
    fil = threading.Thread(target=capturer_tout, args=(bureau, dossier, resultat))
    fil.start()
    fil.join()
    subprocess.run(["taskkill", "/T", "/F", "/PID", str(pi.dwProcessId)], capture_output=True)
    kernel32.CloseHandle(pi.hThread)
    kernel32.CloseHandle(pi.hProcess)
    user32.CloseDesktop(bureau)
    if "erreur" in resultat:
        sys.exit("capture ratée : " + resultat["erreur"])
    for ligne in resultat.get("lignes", []):
        print(ligne)
    print(f"{len(resultat.get('lignes', []))} fenêtre(s) visible(s) ; captures dans {dossier}")


if __name__ == "__main__":
    main()
