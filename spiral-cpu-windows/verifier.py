"""Re-runs the before and the after of the pull request "spiral-fitting: one Kimimaro process per
slab on Windows, and --slab-workers outside Linux" on real data, and checks the results. Windows
only.

Data: the published surface_m7 surface prediction of PHerc0332, level 0, slices z 4032 to 4096,
read from a local copy of its chunks (DATA below). Nothing is downloaded or installed.

  before  villa main 97fb933 as it is, and the same with the `import sys` of #2520
  after   the branch spiral-slab-workers-windows at the commit BRANCH

Steps, all with `--backend cpu --no-packed-store` on the same 64 slices:
  1. main, the README command (`--slab-workers 4 --kimimaro-parallel 1`)   expected: NameError
  2. main with #2520, the same command                                      expected: "needs Linux"
  3. main, default settings, stopped after LIMIT seconds                    expected: not finished
  4. main, `--kimimaro-parallel 1`: the reference tracks                    expected: finished
  5. branch, default settings                                               expected: finished, same bytes as 4
  6. branch, the README command                                             expected: finished, same bytes as 4
  7. branch, `pytest tests/test_cc_labels.py tests/test_extract_surface_tracks.py`  expected: no failure

Each command runs in a Windows job object: wall time, CPU time and peak committed memory are those
of all its processes, and nothing it starts outlives it. One English log per step goes to
./journaux/verif; the two source trees, the DBMs and the caches go to ./verif-tmp, removed at the
end. The console messages are in French, for the person who starts verifier.cmd; the last line is
"TOUT EST CONFORME" (everything as expected) or "ÉCART : <cause>" (what differs).
"""
import ctypes
import ctypes.wintypes as wt
import datetime
import dbm
import io
import os
import pickle
import re
import shutil
import subprocess
import sys
import tarfile
import time
from pathlib import Path

sys.dont_write_bytecode = True

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
REPO = BASE / 'wt-spirale-cpu'  # any working tree of the villa clone: git archive reads commits
DATA = BASE / 'donnees-spirale-cpu' / 'PHerc0332-20251211183505-surface-m7-L2-th0.2.zarr' / '0'
EXTRA = BASE / 'donnees-spirale-cpu' / 'extra'  # kimimaro, cc3d, networkx, zarr, tqdm, pytest
MAIN = '97fb9336c8898be27e78eff8cd23ce5e7185ec0a'
PR2520 = 'b4e62efcaaea038a49c400243f8d61c36d89fd5a'
BRANCH = 'bc2c48d07db54fdb4049e06bd34f35091655b5f3'  # head of spiral-slab-workers-windows
FIXTURE = 'vesuvius/tests/ink_detection/fixtures/ink_roi_case.npz'  # read by test_cc_labels.py
Z_MIN, Z_MAX = 4032, 4096
# Seconds after which main's run with its default settings is stopped: it needs about 4 minutes
# (full_run.py lets it finish).
LIMIT = 120
TMP = HERE / 'verif-tmp'
LOGS = HERE / 'journaux' / 'verif'

ENV = dict(os.environ)
ENV.update(PYTHONPATH=str(EXTRA), PYTHONIOENCODING='utf-8', PYTHONUNBUFFERED='1',
           PYTHONDONTWRITEBYTECODE='1', VC_READER_CACHE_DIR=str(TMP / 'cache'),
           XDG_CACHE_HOME=str(TMP / 'cache'), TEMP=str(TMP / 'temp'), TMP=str(TMP / 'temp'))
ENV.pop('PYTHONHOME', None)

CREATE_SUSPENDED = 0x00000004
BELOW_NORMAL = 0x00004000
CREATE_NO_WINDOW = 0x08000000
KILL_ON_JOB_CLOSE = 0x00002000

k32 = ctypes.WinDLL('kernel32', use_last_error=True)
ntdll = ctypes.WinDLL('ntdll')
k32.CreateJobObjectW.restype = wt.HANDLE
k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wt.LPCWSTR]
k32.AssignProcessToJobObject.argtypes = [wt.HANDLE, wt.HANDLE]
k32.TerminateJobObject.argtypes = [wt.HANDLE, wt.UINT]
k32.QueryInformationJobObject.argtypes = [wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD,
                                          ctypes.c_void_p]
k32.SetInformationJobObject.argtypes = [wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD]
k32.CloseHandle.argtypes = [wt.HANDLE]
ntdll.NtResumeProcess.argtypes = [wt.HANDLE]


class IO_COUNTERS(ctypes.Structure):
    _fields_ = [(n, ctypes.c_ulonglong) for n in (
        'ReadOperationCount', 'WriteOperationCount', 'OtherOperationCount',
        'ReadTransferCount', 'WriteTransferCount', 'OtherTransferCount')]


class BASIC_LIMIT(ctypes.Structure):
    _fields_ = [('PerProcessUserTimeLimit', ctypes.c_longlong),
                ('PerJobUserTimeLimit', ctypes.c_longlong), ('LimitFlags', wt.DWORD),
                ('MinimumWorkingSetSize', ctypes.c_size_t), ('MaximumWorkingSetSize', ctypes.c_size_t),
                ('ActiveProcessLimit', wt.DWORD), ('Affinity', ctypes.c_size_t),
                ('PriorityClass', wt.DWORD), ('SchedulingClass', wt.DWORD)]


class EXT_LIMIT(ctypes.Structure):
    _fields_ = [('BasicLimitInformation', BASIC_LIMIT), ('IoInfo', IO_COUNTERS),
                ('ProcessMemoryLimit', ctypes.c_size_t), ('JobMemoryLimit', ctypes.c_size_t),
                ('PeakProcessMemoryUsed', ctypes.c_size_t), ('PeakJobMemoryUsed', ctypes.c_size_t)]


class BASIC_ACCOUNTING(ctypes.Structure):
    _fields_ = [('TotalUserTime', ctypes.c_longlong), ('TotalKernelTime', ctypes.c_longlong),
                ('ThisPeriodTotalUserTime', ctypes.c_longlong),
                ('ThisPeriodTotalKernelTime', ctypes.c_longlong), ('TotalPageFaultCount', wt.DWORD),
                ('TotalProcesses', wt.DWORD), ('ActiveProcesses', wt.DWORD),
                ('TotalTerminatedProcesses', wt.DWORD)]


class Difference(Exception):
    """Something that is not as expected: its message (French) ends the run as ÉCART."""


def say(text=''):
    """A line of the console, in French."""
    print(text, flush=True)


SUMMARY = []  # English lines of journaux/verif/summary.log


def note(text):
    SUMMARY.append(text)


def free_memory_gb():
    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [('dwLength', wt.DWORD), ('dwMemoryLoad', wt.DWORD)] + [
            (n, ctypes.c_ulonglong) for n in ('ullTotalPhys', 'ullAvailPhys', 'ullTotalPageFile',
                                              'ullAvailPageFile', 'ullTotalVirtual',
                                              'ullAvailVirtual', 'ullAvailExtendedVirtual')]
    status = MEMORYSTATUSEX()
    status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    k32.GlobalMemoryStatusEx(ctypes.byref(status))
    return status.ullAvailPhys / 2**30


def machine():
    """Processor, logical processors, RAM, Windows version and whether an NVIDIA GPU is visible."""
    import platform
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r'HARDWARE\DESCRIPTION\System\CentralProcessor\0') as key:
            cpu = winreg.QueryValueEx(key, 'ProcessorNameString')[0].strip()
    except OSError:
        cpu = platform.processor()

    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [('dwLength', wt.DWORD), ('dwMemoryLoad', wt.DWORD)] + [
            (n, ctypes.c_ulonglong) for n in ('ullTotalPhys', 'ullAvailPhys', 'ullTotalPageFile',
                                              'ullAvailPageFile', 'ullTotalVirtual',
                                              'ullAvailVirtual', 'ullAvailExtendedVirtual')]
    status = MEMORYSTATUSEX()
    status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    k32.GlobalMemoryStatusEx(ctypes.byref(status))
    gpu = 'an NVIDIA GPU (nvidia-smi found)' if shutil.which('nvidia-smi') else 'no NVIDIA GPU (no nvidia-smi)'
    return (f'{cpu}, {os.cpu_count()} logical processors, {status.ullTotalPhys / 2**30:.1f} GB RAM, '
            f'Windows {platform.release()} ({platform.version()}), {gpu}')


def find_git():
    git = shutil.which('git') or r'C:\Program Files\Git\cmd\git.exe'
    if not Path(git).exists():
        raise Difference('git est introuvable (il sert à extraire le code de main et de la branche)')
    return git


def git(*args):
    result = subprocess.run([GIT, '-C', str(REPO), *args], capture_output=True,
                            creationflags=CREATE_NO_WINDOW)
    if result.returncode:
        raise Difference(f'git {args[0]} a échoué : '
                         f'{result.stderr.decode("utf-8", "replace").strip()[:300]}')
    return result.stdout


def has_commit(sha):
    return subprocess.run([GIT, '-C', str(REPO), 'cat-file', '-e', f'{sha}^{{commit}}'],
                          capture_output=True, creationflags=CREATE_NO_WINDOW).returncode == 0


def extract_tree(sha, destination, *paths):
    """Writes the files of `paths` at commit `sha` under `destination` (git archive)."""
    with tarfile.open(fileobj=io.BytesIO(git('archive', '--format=tar', sha, *paths))) as tar:
        tar.extractall(destination, filter='data')


PASSES = {'horizontal ribbons': 'rubans horizontaux',
          'finding yx range': "recherche de l'étendue en y et x",
          'vertical y-stride slabs': 'tranches verticales (y)',
          'vertical x-stride slabs': 'tranches verticales (x)'}
BAR = re.compile(r'(horizontal ribbons|finding yx range|vertical [xy]-stride slabs):\s*\d+%\|'
                 r'[^|\r\n]*\|\s*(\d+)/(\d+)')


def progress(log, english=False):
    """Where an extraction is, from the last progress bar of its log."""
    if log.stem.endswith('tests'):
        return 'tests' if english else 'tests en cours'
    try:
        text = log.read_text(encoding='utf-8', errors='replace')
    except OSError:
        return ''
    bars = BAR.findall(text)
    if not bars:
        return 'starting' if english else 'démarrage (chargement des bibliothèques)'
    name, done, total = bars[-1]
    return f'{name} {done}/{total}' if english else f'{PASSES[name]} : {done} sur {total}'


def run(step, cwd, args, limit):
    """`python <args>` in `cwd`, in a job object; stopped after `limit` s. Log: LOGS/<step>.log"""
    log = LOGS / f'{step}.log'
    job = k32.CreateJobObjectW(None, None)
    limits = EXT_LIMIT()
    limits.BasicLimitInformation.LimitFlags = KILL_ON_JOB_CLOSE
    k32.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits))
    with open(log, 'w', encoding='utf-8', newline='\n') as f:
        f.write(f'$ cd {cwd}\n$ python {" ".join(args)}\n')
        f.flush()
        start = time.perf_counter()
        process = subprocess.Popen(
            [sys.executable, *args], cwd=cwd, env=ENV, stdin=subprocess.DEVNULL, stdout=f,
            stderr=subprocess.STDOUT, creationflags=CREATE_SUSPENDED | CREATE_NO_WINDOW | BELOW_NORMAL)
        # Suspended until it is in the job, so that every process it starts is in the job too.
        k32.AssignProcessToJobObject(job, int(process._handle))
        ntdll.NtResumeProcess(int(process._handle))
        finished, next_report = True, 15
        while True:
            try:
                code = process.wait(timeout=1)
                break
            except subprocess.TimeoutExpired:
                elapsed = time.perf_counter() - start
                if elapsed >= limit:
                    k32.TerminateJobObject(job, 1)
                    code, finished = process.wait(), False
                    break
                if elapsed >= next_report:
                    next_report += 15
                    say(f'      {elapsed:4.0f} s : {progress(log)}')
        seconds = time.perf_counter() - start
        accounting = BASIC_ACCOUNTING()
        k32.QueryInformationJobObject(job, 1, ctypes.byref(accounting), ctypes.sizeof(accounting),
                                      None)
        k32.QueryInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits), None)
        k32.TerminateJobObject(job, 1)  # nothing it started may outlive it
        k32.CloseHandle(job)
        result = dict(code=code, finished=finished, seconds=seconds,
                      cpu=(accounting.TotalUserTime + accounting.TotalKernelTime) / 1e7,
                      processes=accounting.TotalProcesses,
                      peak_gb=limits.PeakJobMemoryUsed / 2**30, log=log)
        ending = (f'exit code {code}' if finished else
                  f'stopped after {limit} s, not finished ({progress(log, english=True)})')
        f.write(f'\n--- {ending}; wall time {seconds:.1f} s; CPU time of all its processes '
                f'{result["cpu"]:.1f} s; processes started {result["processes"]}; peak committed '
                f'memory of all its processes {result["peak_gb"]:.2f} GB\n')
    return result


def log_text(result):
    return result['log'].read_text(encoding='utf-8', errors='replace')


def read_dbm(path):
    with dbm.open(str(path), 'r') as database:
        return {key.decode(): bytes(database[key]) for key in database.keys()}


def same_tracks(reference, other, step):
    """Compares two DBMs key by key and byte for byte; writes LOGS/<step>-compare.log."""
    a, b = read_dbm(reference), read_dbm(other)
    same_bytes = sum(a[k] == b[k] for k in a.keys() & b.keys())
    tracks = sum(len(pickle.loads(v)) for v in a.values())
    same = a.keys() == b.keys() and same_bytes == len(a)
    with open(LOGS / f'{step}-compare.log', 'w', encoding='utf-8', newline='\n') as f:
        f.write(f'{reference.name}: {len(a)} keys; {other.name}: {len(b)} keys\n'
                f'same keys: {a.keys() == b.keys()}\n'
                f'keys with identical pickled bytes: {same_bytes}/{len(a)}\n'
                f'tracks in {reference.name}: {tracks}\n'
                f'identical: {same}\n')
    return same, len(a), tracks


def extraction(out, *options):
    return ['extract_surface_tracks.py', '--backend', 'cpu', '--predictions', str(DATA),
            '--out', str(TMP / 'out' / out), '--z-min', str(Z_MIN), '--z-max', str(Z_MAX),
            '--no-packed-store', *options]


README_OPTIONS = ('--slab-workers', '4', '--kimimaro-parallel', '1')


def remove_tmp():
    for attempt in range(10):
        if not TMP.exists():
            return
        shutil.rmtree(TMP, ignore_errors=True)
        time.sleep(1)
    if TMP.exists():
        say(f'(le dossier temporaire {TMP} n\'a pas pu être effacé entièrement)')


def check_environment():
    if BRANCH.startswith('BRANCHE'):
        raise Difference("le commit de la branche à vérifier n'est pas renseigné dans verifier.py")
    probe = ('import importlib.util as u; print(" ".join(m for m in ("numpy", "kimimaro", "cc3d", '
             '"networkx", "zarr", "tqdm", "pytest", "vc_reader") if u.find_spec(m) is None))')
    missing = subprocess.run([sys.executable, '-c', probe], env=ENV, capture_output=True, text=True,
                             creationflags=CREATE_NO_WINDOW).stdout.split()
    if missing:
        raise Difference(f'il manque des bibliothèques Python : {", ".join(missing)} '
                         f'(Python utilisé : {sys.executable}, PYTHONPATH={EXTRA})')
    if not (DATA / '.zarray').exists() or not (DATA / '21').is_dir():
        raise Difference(f'la donnée réelle est introuvable : {DATA}')
    for sha, name in ((MAIN, 'main 97fb933'), (BRANCH, f'la branche {BRANCH[:9]}'),
                      (PR2520, '#2520 (b4e62ef)')):
        if not has_commit(sha):
            raise Difference(f'le commit de {name} est absent du dépôt {REPO} '
                             f'(git fetch origin, ou pour #2520 : git fetch origin refs/pull/2520/head)')


def main():
    t0 = time.perf_counter()
    when = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    say('Vérification de la PR « spirale : extraction des pistes sur processeur, sous Windows »')
    say(f'Donnée réelle : PHerc0332, prédiction de surface surface_m7, tranches z {Z_MIN} à {Z_MAX} (64 tranches).')
    say(f'AVANT = main amont {MAIN[:9]} ; APRÈS = branche spiral-slab-workers-windows, commit {BRANCH[:9]}.')
    say('Durée : 4 à 6 minutes. Rien à faire pendant ce temps.')
    free = free_memory_gb()
    say(f'Mémoire libre au départ : {free:.1f} Go.' + (' Attention : moins de 3 Go, le PC risque de ramer.' if free < 3 else ''))
    say()
    note(f'Verification run of {when}, Python {sys.version.split()[0]}.')
    note(f'Machine: {machine()}.')
    note(f'Data: PHerc0332 surface_m7 prediction, level 0, z {Z_MIN} to {Z_MAX}, local copy of the '
         f'published chunks. Before: main {MAIN}; after: branch {BRANCH}; #2520: {PR2520}. '
         f'Code extracted from these commits with git archive.')
    note(f'Free memory at the start: {free:.1f} GB.')
    differences = []

    global GIT
    GIT = find_git()
    check_environment()
    remove_tmp()
    for folder in (TMP / 'out', TMP / 'cache', TMP / 'temp', LOGS):
        folder.mkdir(parents=True, exist_ok=True)
    for old in LOGS.glob('*.log'):
        old.unlink()

    say('Préparation : extraction du code de main, de main avec #2520 et de la branche (git archive)...')
    extract_tree(MAIN, TMP / 'main', 'spiral-fitting')
    extract_tree(MAIN, TMP / 'main-2520', 'spiral-fitting')
    (TMP / 'main-2520' / 'spiral-fitting' / 'extract_surface_tracks.py').write_bytes(
        git('show', f'{PR2520}:spiral-fitting/extract_surface_tracks.py'))
    extract_tree(BRANCH, TMP / 'branch', 'spiral-fitting', FIXTURE)
    main_dir = TMP / 'main' / 'spiral-fitting'
    pr2520_dir = TMP / 'main-2520' / 'spiral-fitting'
    branch_dir = TMP / 'branch' / 'spiral-fitting'
    say()

    # ---------------------------------------------------------------- before
    say(f'=== AVANT : main amont {MAIN[:9]} ===')
    say('[1/7] La commande du README (--slab-workers 4 --kimimaro-parallel 1)...')
    r = run('1-main-readme-command', main_dir, extraction('main-readme.dbm', *README_OPTIONS), 300)
    if r['code'] != 0 and "NameError: name 'sys' is not defined" in log_text(r):
        say("      arrêt sur l'erreur « NameError: name 'sys' is not defined » : c'est le défaut attendu.")
        note("1. main, README command: stops with NameError: name 'sys' is not defined (expected).")
    else:
        differences.append("sur main, la commande du README ne s'arrête pas sur NameError")
        say(f'      PROBLÈME : code de sortie {r["code"]}, pas de NameError (voir {r["log"]}).')
        note(f'1. main, README command: exit code {r["code"]}, no NameError (NOT as expected).')

    say("[2/7] La même commande avec #2520, qui ajoute l'import manquant...")
    r = run('2-main-with-2520-readme-command', pr2520_dir, extraction('main-2520-readme.dbm', *README_OPTIONS), 300)
    if r['code'] == 2 and '--slab-workers > 1 needs Linux' in log_text(r):
        say('      refus « --slab-workers > 1 needs Linux (forked workers) » : attendu, #2520 ne suffit pas sous Windows.')
        note('2. main with #2520, README command: refused with "--slab-workers > 1 needs Linux '
             '(forked workers)" (expected).')
    else:
        differences.append('avec #2520, la commande du README n\'est pas refusée comme prévu')
        say(f'      PROBLÈME : code de sortie {r["code"]}, pas de refus « needs Linux » (voir {r["log"]}).')
        note(f'2. main with #2520, README command: exit code {r["code"]}, not refused (NOT as expected).')

    say(f'[3/7] Les réglages par défaut (8 processus Kimimaro par tranche), arrêtés au bout de {LIMIT} s...')
    r = run('3-main-default', main_dir, extraction('main-default.dbm'), LIMIT)
    if not r['finished']:
        say(f"      pas fini au bout de {LIMIT} s : arrêté. Il en était à : {progress(r['log'])} ; "
            f"{r['processes']} processus lancés.")
        note(f"3. main, default settings: not finished after {LIMIT} s, stopped at "
             f"{progress(r['log'], english=True)}; {r['processes']} processes started, "
             f"CPU time {r['cpu']:.0f} s (expected: not finished).")
    else:
        differences.append(f'sur main, les réglages par défaut ont fini en {r["seconds"]:.0f} s (lenteur non reproduite)')
        say(f'      PROBLÈME : fini en {r["seconds"]:.0f} s (code {r["code"]}) : la lenteur n\'est pas reproduite.')
        note(f'3. main, default settings: finished in {r["seconds"]:.1f} s (NOT as expected).')

    say('[4/7] Référence : main avec --kimimaro-parallel 1 (un seul processus Kimimaro)...')
    r = run('4-main-kimimaro-parallel-1', main_dir, extraction('main-k1.dbm', '--kimimaro-parallel', '1'), 300)
    reference = TMP / 'out' / 'main-k1.dbm'
    if r['finished'] and r['code'] == 0:
        keys = len(read_dbm(reference))
        say(f'      fini en {r["seconds"]:.0f} s ({keys} tranches écrites).')
        note(f'4. main, --kimimaro-parallel 1: finished in {r["seconds"]:.1f} s, {keys} keys '
             f'(the reference for 5 and 6).')
    else:
        raise Difference(f'la référence (main, --kimimaro-parallel 1) a échoué (code {r["code"]}, voir {r["log"]})')
    say()

    # ---------------------------------------------------------------- after
    say(f'=== APRÈS : branche spiral-slab-workers-windows, commit {BRANCH[:9]} ===')
    say('[5/7] Les réglages par défaut (sous Windows : 1 processus Kimimaro par tranche)...')
    r = run('5-branch-default', branch_dir, extraction('branch-default.dbm'), 300)
    if r['finished'] and r['code'] == 0:
        same, keys, tracks = same_tracks(reference, TMP / 'out' / 'branch-default.dbm', '5-branch-default')
        say(f'      fini en {r["seconds"]:.0f} s (main : pas fini en {LIMIT} s) ; '
            + ('résultat identique octet pour octet à la référence.' if same else 'RÉSULTAT DIFFÉRENT de la référence.'))
        note(f'5. branch, default settings: finished in {r["seconds"]:.1f} s; '
             + (f'same {keys} keys, byte for byte, as 4 ({tracks} tracks).' if same else 'output DIFFERENT from 4.'))
        if not same:
            differences.append('les pistes de la branche (réglages par défaut) diffèrent de la référence')
        if r['seconds'] >= LIMIT:
            differences.append(f'la branche a mis {r["seconds"]:.0f} s, pas moins que les {LIMIT} s de main')
    else:
        differences.append(f'la branche, réglages par défaut, a échoué (code {r["code"]})')
        say(f'      PROBLÈME : code {r["code"]}, fini={r["finished"]} (voir {r["log"]}).')
        note(f'5. branch, default settings: exit code {r["code"]}, finished={r["finished"]} (NOT as expected).')

    say('[6/7] La commande du README (--slab-workers 4 --kimimaro-parallel 1)...')
    r = run('6-branch-readme-command', branch_dir, extraction('branch-readme.dbm', *README_OPTIONS), 300)
    if r['finished'] and r['code'] == 0:
        same, keys, tracks = same_tracks(reference, TMP / 'out' / 'branch-readme.dbm', '6-branch-readme-command')
        say(f'      fini en {r["seconds"]:.0f} s avec 4 processus de tranches ; '
            + ('résultat identique octet pour octet à la référence.' if same else 'RÉSULTAT DIFFÉRENT de la référence.'))
        note(f'6. branch, README command: finished in {r["seconds"]:.1f} s, {r["processes"]} processes, '
             f'peak committed memory {r["peak_gb"]:.1f} GB; '
             + (f'same {keys} keys, byte for byte, as 4.' if same else 'output DIFFERENT from 4.'))
        if not same:
            differences.append('les pistes de la branche (commande du README) diffèrent de la référence')
    else:
        differences.append(f'la branche, commande du README, a échoué (code {r["code"]})')
        say(f'      PROBLÈME : code {r["code"]}, fini={r["finished"]} (voir {r["log"]}).')
        note(f'6. branch, README command: exit code {r["code"]}, finished={r["finished"]} (NOT as expected).')

    say('[7/7] Les tests du README (tests/test_cc_labels.py et tests/test_extract_surface_tracks.py)...')
    r = run('7-branch-tests', branch_dir,
            ['-m', 'pytest', '-q', '-rs', '-p', 'no:cacheprovider', f'--basetemp={TMP / "pytest"}',
             'tests/test_cc_labels.py', 'tests/test_extract_surface_tracks.py'], 600)
    lines = [l for l in log_text(r).splitlines() if re.search(r'\d+ (passed|failed)', l)]
    verdict = lines[-1].strip() if lines else '(pas de résumé pytest)'
    if r['finished'] and r['code'] == 0 and 'failed' not in verdict and 'error' not in verdict:
        say(f'      {verdict} : aucun échec.')
        note(f'7. branch, tests: {verdict}.')
    else:
        differences.append(f'des tests échouent sur la branche ({verdict})')
        say(f'      PROBLÈME : {verdict} (voir {r["log"]}).')
        note(f'7. branch, tests: {verdict} (NOT as expected).')

    total = time.perf_counter() - t0
    note(f'Total time of the verification: {total:.0f} s.')
    note('Result: ' + ('everything as expected.' if not differences else 'DIFFERENCES: ' + '; '.join(differences)))
    (LOGS / 'summary.log').write_text('\n'.join(SUMMARY) + '\n', encoding='utf-8', newline='\n')
    say()
    say(f'Durée totale : {total:.0f} s. Journaux (en anglais) : {LOGS}')
    return differences


if __name__ == '__main__':
    GIT = None
    try:
        found = main()
    except Difference as exc:
        found = [str(exc)]
    except Exception as exc:  # an unexpected failure of this script itself
        found = [f'erreur inattendue du script de vérification : {type(exc).__name__}: {exc}']
    finally:
        remove_tmp()
    if found:
        say('ÉCART : ' + ' ; '.join(found))
        sys.exit(1)
    say('TOUT EST CONFORME')
