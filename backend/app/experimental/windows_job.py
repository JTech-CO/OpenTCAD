"""Contain the Windows MVP service and descendants in a kill-on-close job.

Call only in the dedicated CLI process, before launching any solver. The handle
is non-inheritable and intentionally lives until OS process teardown. Do not
close it early: that would also terminate the service itself.
"""
import ctypes
from ctypes import wintypes
import sys
import os
import threading

_job = None


def _create_job():
    if sys.platform != "win32":
        raise RuntimeError("windows-mvp-requires-windows")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)

    class Basic(ctypes.Structure):
        _fields_ = [("processTime", ctypes.c_int64), ("jobTime", ctypes.c_int64),
                    ("flags", wintypes.DWORD), ("minWorkingSet", ctypes.c_size_t),
                    ("maxWorkingSet", ctypes.c_size_t), ("activeProcesses", wintypes.DWORD),
                    ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD), ("scheduling", wintypes.DWORD)]

    class IO(ctypes.Structure):
        _fields_ = [(name, ctypes.c_uint64) for name in ("readOps", "writeOps", "otherOps", "readBytes", "writeBytes", "otherBytes")]

    class Extended(ctypes.Structure):
        _fields_ = [("basic", Basic), ("io", IO), ("processMemory", ctypes.c_size_t),
                    ("jobMemory", ctypes.c_size_t), ("peakProcess", ctypes.c_size_t), ("peakJob", ctypes.c_size_t)]

    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.SetInformationJobObject.restype = wintypes.BOOL
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateJobObjectW(None, None)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    limits = Extended()
    limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE; no breakaway.
    if not kernel.SetInformationJobObject(handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
        error = ctypes.get_last_error(); kernel.CloseHandle(handle)
        raise ctypes.WinError(error)
    return kernel, handle


def contain_current_process(parent_pid=None):
    global _job
    if _job is not None:
        return
    kernel, handle = _create_job()
    if not kernel.AssignProcessToJobObject(handle, kernel.GetCurrentProcess()):
        error = ctypes.get_last_error(); kernel.CloseHandle(handle)
        raise ctypes.WinError(error)
    _job = handle
    # Windows venv launchers and npm can otherwise outlive each other. Watch
    # the explicitly supplied launcher handle, not a repeatedly queried PID.
    parent_pid = os.getppid() if parent_pid is None else parent_pid
    if type(parent_pid) is not int or parent_pid <= 0 or parent_pid == os.getpid():
        raise ValueError("launcher-process-invalid")
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    parent = kernel.OpenProcess(0x100000, False, parent_pid)
    if not parent:
        raise ctypes.WinError(ctypes.get_last_error())

    def watch_launcher():
        kernel.WaitForSingleObject(parent, 0xFFFFFFFF)
        os._exit(1)  # Closing this process's job handle kills its descendants.

    threading.Thread(target=watch_launcher, daemon=True, name="mvp-launcher-liveness").start()


class ChildJob:
    def __init__(self, pid):
        if type(pid) is not int or pid <= 0 or pid == os.getpid():
            raise ValueError("solver-process-invalid")
        kernel, handle = _create_job()
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        process = kernel.OpenProcess(0x100101, False, pid)  # sync, quota, terminate
        if not process or not kernel.AssignProcessToJobObject(handle, process):
            error = ctypes.get_last_error()
            if process: kernel.CloseHandle(process)
            kernel.CloseHandle(handle)
            raise ctypes.WinError(error)
        self.kernel, self.handle, self.process = kernel, handle, process

    def close(self):
        if self.handle is None:
            return
        self.kernel.CloseHandle(self.handle)
        self.handle = None
        result = self.kernel.WaitForSingleObject(self.process, 10000)
        self.kernel.CloseHandle(self.process)
        if result != 0:
            raise RuntimeError("solver-process-exit-unconfirmed")
