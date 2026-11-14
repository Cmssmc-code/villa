"""Runs a command in this console, then prints its exit code, its wall time and the number of
processes it started. Stops it after a time limit. Windows only.

Usage: python chrono.py <limit in seconds> <program> [arguments...]

The command runs in a Windows job object: the count includes every process it started, and the
limit stops all of them.
"""
import ctypes
import ctypes.wintypes as wt
import subprocess
import sys
import time

CREATE_SUSPENDED = 0x00000004
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


class BASIC_LIMIT(ctypes.Structure):
    _fields_ = [('PerProcessUserTimeLimit', ctypes.c_longlong),
                ('PerJobUserTimeLimit', ctypes.c_longlong), ('LimitFlags', wt.DWORD),
                ('MinimumWorkingSetSize', ctypes.c_size_t), ('MaximumWorkingSetSize', ctypes.c_size_t),
                ('ActiveProcessLimit', wt.DWORD), ('Affinity', ctypes.c_size_t),
                ('PriorityClass', wt.DWORD), ('SchedulingClass', wt.DWORD)]


class EXT_LIMIT(ctypes.Structure):
    _fields_ = [('BasicLimitInformation', BASIC_LIMIT), ('IoInfo', ctypes.c_ulonglong * 6),
                ('ProcessMemoryLimit', ctypes.c_size_t), ('JobMemoryLimit', ctypes.c_size_t),
                ('PeakProcessMemoryUsed', ctypes.c_size_t), ('PeakJobMemoryUsed', ctypes.c_size_t)]


class BASIC_ACCOUNTING(ctypes.Structure):
    _fields_ = [('TotalUserTime', ctypes.c_longlong), ('TotalKernelTime', ctypes.c_longlong),
                ('ThisPeriodTotalUserTime', ctypes.c_longlong),
                ('ThisPeriodTotalKernelTime', ctypes.c_longlong), ('TotalPageFaultCount', wt.DWORD),
                ('TotalProcesses', wt.DWORD), ('ActiveProcesses', wt.DWORD),
                ('TotalTerminatedProcesses', wt.DWORD)]


def main():
    limit = float(sys.argv[1])
    job = k32.CreateJobObjectW(None, None)
    limits = EXT_LIMIT()
    limits.BasicLimitInformation.LimitFlags = KILL_ON_JOB_CLOSE
    k32.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits))
    start = time.perf_counter()
    process = subprocess.Popen(sys.argv[2:], creationflags=CREATE_SUSPENDED)
    # Suspended until it is in the job, so that every process it starts is in the job too.
    k32.AssignProcessToJobObject(job, int(process._handle))
    ntdll.NtResumeProcess(int(process._handle))
    try:
        code, finished = process.wait(timeout=limit), True
    except subprocess.TimeoutExpired:
        k32.TerminateJobObject(job, 1)
        code, finished = process.wait(), False
    seconds = time.perf_counter() - start
    accounting = BASIC_ACCOUNTING()
    k32.QueryInformationJobObject(job, 1, ctypes.byref(accounting), ctypes.sizeof(accounting), None)
    k32.TerminateJobObject(job, 1)
    k32.CloseHandle(job)
    sys.stderr.flush()
    if finished:
        print(f'-> exit code {code}, wall time {seconds:.1f} s, '
              f'{accounting.TotalProcesses} processes started', flush=True)
    else:
        print(f'\n-> stopped after {limit:.0f} s, not finished; '
              f'{accounting.TotalProcesses} processes started', flush=True)
    sys.exit(code if finished else 1)


if __name__ == '__main__':
    main()
