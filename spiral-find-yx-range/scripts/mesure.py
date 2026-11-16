"""Run one command inside a Windows job object and report wall time, total CPU time and
peak memory of the whole process tree (children inherit the job).

usage: python mesure.py <label> <log file> <timeout s> -- <command...>
Appends one result line to the log and prints it. Below-normal priority.
"""
import ctypes
import ctypes.wintypes as wt
import datetime
import subprocess
import sys
import time

k32 = ctypes.WinDLL('kernel32', use_last_error=True)


class IO_COUNTERS(ctypes.Structure):
    _fields_ = [(n, ctypes.c_ulonglong) for n in (
        'ReadOperationCount', 'WriteOperationCount', 'OtherOperationCount',
        'ReadTransferCount', 'WriteTransferCount', 'OtherTransferCount')]


class BASIC_LIMIT(ctypes.Structure):
    _fields_ = [('PerProcessUserTimeLimit', ctypes.c_longlong), ('PerJobUserTimeLimit', ctypes.c_longlong),
                ('LimitFlags', wt.DWORD), ('MinimumWorkingSetSize', ctypes.c_size_t),
                ('MaximumWorkingSetSize', ctypes.c_size_t), ('ActiveProcessLimit', wt.DWORD),
                ('Affinity', ctypes.c_size_t), ('PriorityClass', wt.DWORD), ('SchedulingClass', wt.DWORD)]


class EXT_LIMIT(ctypes.Structure):
    _fields_ = [('BasicLimitInformation', BASIC_LIMIT), ('IoInfo', IO_COUNTERS),
                ('ProcessMemoryLimit', ctypes.c_size_t), ('JobMemoryLimit', ctypes.c_size_t),
                ('PeakProcessMemoryUsed', ctypes.c_size_t), ('PeakJobMemoryUsed', ctypes.c_size_t)]


class BASIC_ACCOUNTING(ctypes.Structure):
    _fields_ = [('TotalUserTime', ctypes.c_longlong), ('TotalKernelTime', ctypes.c_longlong),
                ('ThisPeriodTotalUserTime', ctypes.c_longlong), ('ThisPeriodTotalKernelTime', ctypes.c_longlong),
                ('TotalPageFaultCount', wt.DWORD), ('TotalProcesses', wt.DWORD),
                ('ActiveProcesses', wt.DWORD), ('TotalTerminatedProcesses', wt.DWORD)]


def free_mb():
    class MS(ctypes.Structure):
        _fields_ = [('dwLength', wt.DWORD), ('dwMemoryLoad', wt.DWORD)] + [
            (n, ctypes.c_ulonglong) for n in ('ullTotalPhys', 'ullAvailPhys', 'ullTotalPageFile',
                                              'ullAvailPageFile', 'ullTotalVirtual', 'ullAvailVirtual',
                                              'ullAvailExtendedVirtual')]
    m = MS()
    m.dwLength = ctypes.sizeof(MS)
    k32.GlobalMemoryStatusEx(ctypes.byref(m))
    return m.ullAvailPhys // 2**20


def main():
    label, log, timeout = sys.argv[1], sys.argv[2], float(sys.argv[3])
    cmd = sys.argv[sys.argv.index('--') + 1:]
    k32.CreateJobObjectW.restype = wt.HANDLE
    job = k32.CreateJobObjectW(None, None)
    free0 = free_mb()
    t0 = time.perf_counter()
    start = datetime.datetime.now().strftime('%H:%M:%S')
    BELOW_NORMAL = 0x00004000
    sys.stdout.flush()
    # Explicit std handles: with CREATE_NO_WINDOW the child would otherwise get none.
    proc = subprocess.Popen(cmd, stdout=sys.stdout, stderr=sys.stderr,
                            creationflags=0x08000000)  # CREATE_NO_WINDOW; normal priority (below-normal starved on this busy PC)
    k32.AssignProcessToJobObject(wt.HANDLE(job), wt.HANDLE(int(proc._handle)))
    status = 'ok'
    try:
        rc = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        k32.TerminateJobObject(wt.HANDLE(job), 1)
        rc, status = proc.wait(), 'TIMEOUT-killed'
    wall = time.perf_counter() - t0
    acc = BASIC_ACCOUNTING()
    k32.QueryInformationJobObject(wt.HANDLE(job), 1, ctypes.byref(acc), ctypes.sizeof(acc), None)
    ext = EXT_LIMIT()
    k32.QueryInformationJobObject(wt.HANDLE(job), 9, ctypes.byref(ext), ctypes.sizeof(ext), None)
    cpu = (acc.TotalUserTime + acc.TotalKernelTime) / 1e7
    line = (f'MESURE {label}: start {start} rc={rc} {status} wall={wall:.1f}s cpu={cpu:.1f}s '
            f'cpu/wall={cpu / wall:.2f} processes={acc.TotalProcesses} '
            f'peak_job_mem={ext.PeakJobMemoryUsed / 2**20:.0f}MB peak_proc_mem={ext.PeakProcessMemoryUsed / 2**20:.0f}MB '
            f'free_mem_start={free0}MB free_mem_end={free_mb()}MB')
    print(line, flush=True)
    with open(log, 'a', encoding='utf-8') as f:
        f.write(line + '\n')
    sys.exit(rc)


if __name__ == '__main__':
    main()
