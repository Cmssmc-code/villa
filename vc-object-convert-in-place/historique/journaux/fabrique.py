"""Builds libvc_objects.dll with StoreConversion.cpp taken from a given commit, OUTSIDE the shared tree.

Same approach as nuit-1611/fibres-22/fabrique.py (helpers copied in hors_arbre_base.py, normal priority):
1. StoreConversion.cpp is taken from git (git show <commit>:<path>) and compiled with ninja's command line;
2. libvc_objects.dll is relinked with the same objects and libraries, only this object replaced.
Nothing is written in wt-vc3d.

Usage: fabrique.py <name> <commit>
"""
import pathlib
import subprocess
import sys
import time

sys.dont_write_bytecode = True
import hors_arbre_base as h

CPP = "vc_object_store/src/StoreConversion.cpp"
OBJET = "object_store/src/CMakeFiles/vc_objects.dir/StoreConversion.cpp.obj"
CIBLE = "bin/libvc_objects.dll"


def u(p):
    return str(p).replace("\\", "/")


def main():
    nom, commit = sys.argv[1:3]
    sortie = h.R / "nuit-1611" / "historique-windows" / "bin-corrige" / nom
    prive = sortie / "travail"
    prive.mkdir(parents=True, exist_ok=True)
    journal = sortie / "compilation.log"
    journal.write_text(f"=== {time.strftime('%Y-%m-%d %H:%M:%S')} fabrique.py {nom} {commit}\n", encoding="utf-8")
    lignes = h.lire_ninja()
    regle_c, entrees_c, var_c = h.lire_instruction(lignes, OBJET)
    regle_l, entrees_l, var_l = h.lire_instruction(lignes, CIBLE)
    source_origine = pathlib.Path(entrees_c[0])
    assert source_origine.resolve() == (h.SRC_ROOT / CPP).resolve(), source_origine
    assert OBJET in entrees_l, "objet absent du lien"
    tete = subprocess.run(["git", "-C", str(h.SRC_ROOT), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()

    contenu = subprocess.run(["git", "-C", str(h.VILLA), "show", f"{commit}:{CPP}"], capture_output=True, check=True).stdout
    cpp = prive / "StoreConversion.cpp"
    cpp.write_bytes(contenu)
    diff = subprocess.run(["git", "-C", str(h.VILLA), "diff", "--stat", tete, commit, "--", CPP], capture_output=True, text=True).stdout

    obj = prive / "StoreConversion.cpp.obj"
    args = [h.GXX] + var_c.get("DEFINES", "").split() + ["-iquote", u(source_origine.parent)] \
        + var_c.get("INCLUDES", "").split() + var_c.get("FLAGS", "").split() \
        + ["-MD", "-MT", u(obj), "-MF", u(obj) + ".d", "-o", u(obj), "-c", u(cpp)]
    rc = h.lance(args, journal, h.B)
    if rc != 0 or not obj.exists():
        raise SystemExit(f"compilation failed (rc={rc}), see {journal}")

    produit = sortie / "libvc_objects.dll"
    entrees = [u(obj) if e == OBJET else e for e in entrees_l]
    rsp = prive / "lien.rsp"
    rsp.write_text(" ".join(entrees) + " " + var_l.get("LINK_PATH", "") + " " + var_l["LINK_LIBRARIES"] + "\n", encoding="utf-8")
    drapeaux = (var_l.get("LANGUAGE_COMPILE_FLAGS", "") + " " + var_l.get("ARCH_FLAGS", "") + " " + var_l.get("LINK_FLAGS", "")).split()
    args = [h.GXX] + drapeaux + ["-o", u(produit), "-Wl,--out-implib," + u(prive / "libvc_objects.dll.a"),
                                 "-Wl,--major-image-version,0,--minor-image-version,0", "@" + u(rsp)]
    rc = h.lance(args, journal, h.B)
    if rc != 0 or not produit.exists():
        raise SystemExit(f"link failed (rc={rc}), see {journal}")

    origine = h.B / "bin" / "libvc_objects.dll"
    recette = [
        f"Product: {produit}",
        f"Built on {time.strftime('%Y-%m-%d at %H:%M:%S')} by nuit-1611/historique-windows/fabrique.py, outside the shared tree.",
        f"Base: built tree {h.SRC_ROOT} at commit {tete} (main).",
        f"Only file different from main: {CPP}, taken at commit {commit}.",
        "git diff --stat of this file between main and this commit:",
        diff.strip() or "(no difference: control build)",
        f"Ninja rules reused: compile {regle_c}, link {regle_l} (same flags, same objects,",
        f"  same libraries; only {OBJET} is replaced).",
        f"Size: {produit.stat().st_size} bytes (main libvc_objects.dll: {origine.stat().st_size} bytes).",
        f"SHA-256: {h.sha(produit)}",
        f"SHA-256 of the compiled .cpp: {h.sha(cpp)}",
        f"Full command log: {journal}",
    ]
    (sortie / "RECETTE.txt").write_text("\n".join(recette) + "\n", encoding="utf-8")
    print("\n".join(recette))
    print("FIN rc=0")


if __name__ == "__main__":
    main()
