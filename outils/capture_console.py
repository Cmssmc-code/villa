"""Lance une commande dans une vraie console Windows (conhost) sur un bureau caché, puis
enregistre une capture PNG de la fenêtre de cette console. Rien n'apparaît à l'écran.

Usage : python capture_console.py <sortie.png> <attente_max_s> <script.cmd> [colonnes] [lignes]

Le script .cmd est lancé par `cmd /d /k`. La capture est prise quand le fichier
<sortie.png>.fin existe (le script doit le créer à la fin : `echo fin> "%FIN%"`), ou à
l'expiration de l'attente. La console est ensuite fermée.
"""
import ctypes
import ctypes.wintypes as wt
import os
import struct
import subprocess
import sys
import threading
import time
import zlib

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

GENERIC_ALL = 0x10000000
CREATE_NEW_CONSOLE = 0x00000010
CREATE_UNICODE_ENVIRONMENT = 0x00000400
PW_RENDERFULLCONTENT = 2


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", wt.DWORD), ("lpReserved", wt.LPWSTR), ("lpDesktop", wt.LPWSTR), ("lpTitle", wt.LPWSTR),
        ("dwX", wt.DWORD), ("dwY", wt.DWORD), ("dwXSize", wt.DWORD), ("dwYSize", wt.DWORD),
        ("dwXCountChars", wt.DWORD), ("dwYCountChars", wt.DWORD), ("dwFillAttribute", wt.DWORD),
        ("dwFlags", wt.DWORD), ("wShowWindow", wt.WORD), ("cbReserved2", wt.WORD),
        ("lpReserved2", ctypes.c_void_p), ("hStdInput", wt.HANDLE), ("hStdOutput", wt.HANDLE),
        ("hStdError", wt.HANDLE),
    ]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [("hProcess", wt.HANDLE), ("hThread", wt.HANDLE), ("dwProcessId", wt.DWORD), ("dwThreadId", wt.DWORD)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG), ("biPlanes", wt.WORD),
        ("biBitCount", wt.WORD), ("biCompression", wt.DWORD), ("biSizeImage", wt.DWORD),
        ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG), ("biClrUsed", wt.DWORD),
        ("biClrImportant", wt.DWORD),
    ]


WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

user32.CreateDesktopW.restype = wt.HANDLE
user32.CreateDesktopW.argtypes = [wt.LPCWSTR, wt.LPCWSTR, ctypes.c_void_p, wt.DWORD, wt.DWORD, ctypes.c_void_p]
user32.CloseDesktop.argtypes = [wt.HANDLE]
user32.SetThreadDesktop.argtypes = [wt.HANDLE]
user32.EnumDesktopWindows.argtypes = [wt.HANDLE, WNDENUMPROC, wt.LPARAM]
user32.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
user32.IsWindowVisible.argtypes = [wt.HWND]
user32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
user32.GetWindowDC.restype = wt.HDC
user32.GetWindowDC.argtypes = [wt.HWND]
user32.ReleaseDC.argtypes = [wt.HWND, wt.HDC]
user32.PrintWindow.argtypes = [wt.HWND, wt.HDC, wt.UINT]
gdi32.CreateCompatibleDC.restype = wt.HDC
gdi32.CreateCompatibleDC.argtypes = [wt.HDC]
gdi32.CreateDIBSection.restype = wt.HBITMAP
gdi32.CreateDIBSection.argtypes = [wt.HDC, ctypes.c_void_p, wt.UINT, ctypes.POINTER(ctypes.c_void_p), wt.HANDLE, wt.DWORD]
gdi32.SelectObject.restype = wt.HGDIOBJ
gdi32.SelectObject.argtypes = [wt.HDC, wt.HGDIOBJ]
gdi32.DeleteObject.argtypes = [wt.HGDIOBJ]
gdi32.DeleteDC.argtypes = [wt.HDC]
kernel32.CreateProcessW.argtypes = [
    wt.LPCWSTR, wt.LPWSTR, ctypes.c_void_p, ctypes.c_void_p, wt.BOOL, wt.DWORD, ctypes.c_void_p,
    wt.LPCWSTR, ctypes.POINTER(STARTUPINFOW), ctypes.POINTER(PROCESS_INFORMATION),
]
kernel32.CloseHandle.argtypes = [wt.HANDLE]


def ecrire_png(chemin, largeur, hauteur, bgra):
    lignes = bytearray()
    pas = largeur * 4
    for y in range(hauteur):
        ligne = bgra[y * pas:(y + 1) * pas]
        rgb = bytearray(largeur * 3)
        rgb[0::3] = ligne[2::4]
        rgb[1::3] = ligne[1::4]
        rgb[2::3] = ligne[0::4]
        lignes.append(0)
        lignes += rgb

    def bloc(nom, donnees):
        return struct.pack(">I", len(donnees)) + nom + donnees + struct.pack(">I", zlib.crc32(nom + donnees) & 0xFFFFFFFF)

    with open(chemin, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        f.write(bloc(b"IHDR", struct.pack(">IIBBBBB", largeur, hauteur, 8, 2, 0, 0, 0)))
        f.write(bloc(b"IDAT", zlib.compress(bytes(lignes), 9)))
        f.write(bloc(b"IEND", b""))


def capturer(bureau, sortie, resultat):
    """Doit tourner dans un fil neuf : SetThreadDesktop échoue si le fil a déjà une fenêtre."""
    try:
        if not user32.SetThreadDesktop(bureau):
            raise OSError(f"SetThreadDesktop a échoué (erreur {ctypes.get_last_error()})")
        fenetres = []

        @WNDENUMPROC
        def rappel(hwnd, _):
            classe = ctypes.create_unicode_buffer(64)
            user32.GetClassNameW(hwnd, classe, 64)
            if classe.value == "ConsoleWindowClass" and user32.IsWindowVisible(hwnd):
                fenetres.append(hwnd)
            return True

        user32.EnumDesktopWindows(bureau, rappel, 0)
        if not fenetres:
            raise OSError("aucune fenêtre de console trouvée sur le bureau caché")
        hwnd = fenetres[0]
        r = wt.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(r))
        largeur, hauteur = r.right - r.left, r.bottom - r.top
        if largeur <= 0 or hauteur <= 0:
            raise OSError(f"taille de fenêtre invalide : {largeur}x{hauteur}")
        dc_fenetre = user32.GetWindowDC(hwnd)
        dc = gdi32.CreateCompatibleDC(dc_fenetre)
        entete = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), largeur, -hauteur, 1, 32, 0, 0, 0, 0, 0, 0)
        pixels = ctypes.c_void_p()
        image = gdi32.CreateDIBSection(dc, ctypes.byref(entete), 0, ctypes.byref(pixels), None, 0)
        if not image:
            raise OSError("CreateDIBSection a échoué")
        ancien = gdi32.SelectObject(dc, image)
        donnees = b""
        for drapeau in (PW_RENDERFULLCONTENT, 0):
            user32.PrintWindow(hwnd, dc, drapeau)
            donnees = ctypes.string_at(pixels, largeur * hauteur * 4)
            if any(donnees[i] for i in range(0, len(donnees), 997)):
                break
        gdi32.SelectObject(dc, ancien)
        gdi32.DeleteObject(image)
        gdi32.DeleteDC(dc)
        user32.ReleaseDC(hwnd, dc_fenetre)
        if not any(donnees[i] for i in range(0, len(donnees), 997)):
            raise OSError("capture entièrement noire : PrintWindow ne rend rien sur ce bureau")
        ecrire_png(sortie, largeur, hauteur, donnees)
        resultat["ok"] = f"{largeur}x{hauteur}"
    except OSError as e:
        resultat["erreur"] = str(e)


def main():
    if len(sys.argv) < 4:
        sys.exit(__doc__)
    sortie = os.path.abspath(sys.argv[1])
    attente = float(sys.argv[2])
    script = os.path.abspath(sys.argv[3])
    colonnes = int(sys.argv[4]) if len(sys.argv) > 4 else 120
    lignes = int(sys.argv[5]) if len(sys.argv) > 5 else 40
    fin = sortie + ".fin"
    if os.path.exists(fin):
        os.remove(fin)
    try:
        user32.SetProcessDPIAware()
    except OSError:
        pass
    nom = f"vesuvius_capture_{os.getpid()}"
    bureau = user32.CreateDesktopW(nom, None, None, 0, GENERIC_ALL, None)
    if not bureau:
        sys.exit(f"CreateDesktopW a échoué (erreur {ctypes.get_last_error()})")
    si = STARTUPINFOW()
    si.cb = ctypes.sizeof(si)
    si.lpDesktop = "WinSta0\\" + nom
    pi = PROCESS_INFORMATION()
    env = dict(os.environ, FIN=fin, PROMPT="$P$G")
    bloc_env = ctypes.create_unicode_buffer("".join(f"{k}={v}\0" for k, v in env.items()) + "\0")
    commande = ctypes.create_unicode_buffer(
        f'"{os.environ["SystemRoot"]}\\System32\\conhost.exe" cmd.exe /d /k "mode con: cols={colonnes} lines={lignes} & call "{script}""'
    )
    if not kernel32.CreateProcessW(None, commande, None, None, False, CREATE_NEW_CONSOLE | CREATE_UNICODE_ENVIRONMENT,
                                   bloc_env, os.path.dirname(script), ctypes.byref(si), ctypes.byref(pi)):
        erreur = ctypes.get_last_error()
        user32.CloseDesktop(bureau)
        sys.exit(f"CreateProcessW a échoué (erreur {erreur})")
    limite = time.time() + attente
    while time.time() < limite and not os.path.exists(fin):
        time.sleep(0.5)
    termine = os.path.exists(fin)
    time.sleep(1.0)
    resultat = {}
    fil = threading.Thread(target=capturer, args=(bureau, sortie, resultat))
    fil.start()
    fil.join()
    subprocess.run(["taskkill", "/T", "/F", "/PID", str(pi.dwProcessId)], capture_output=True)
    kernel32.CloseHandle(pi.hThread)
    kernel32.CloseHandle(pi.hProcess)
    user32.CloseDesktop(bureau)
    if os.path.exists(fin):
        os.remove(fin)
    if "erreur" in resultat:
        sys.exit("capture ratée : " + resultat["erreur"])
    print(f"capture {resultat['ok']} -> {sortie} (commande terminée : {termine})")


if __name__ == "__main__":
    main()
