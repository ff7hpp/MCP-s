"""Private parser worker protocol; no portal sessions, credentials or network clients."""

import contextlib
import importlib
import json
import os
import sys
from pathlib import Path

MEMORY_BYTES = 512 * 1024 * 1024
_JOB = None


def _limit_resources():
    if os.name != "nt":
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (MEMORY_BYTES, MEMORY_BYTES))
        resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
        return
    import ctypes
    from ctypes import wintypes

    class BasicLimits(ctypes.Structure):
        _fields_ = [
            ("ProcessTime", ctypes.c_longlong),
            ("JobTime", ctypes.c_longlong),
            ("Flags", wintypes.DWORD),
            ("Minimum", ctypes.c_size_t),
            ("Maximum", ctypes.c_size_t),
            ("ActiveProcesses", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("Priority", wintypes.DWORD),
            ("Scheduling", wintypes.DWORD),
        ]

    class Counters(ctypes.Structure):
        _fields_ = [
            (key, ctypes.c_ulonglong)
            for key in ("ReadOps", "WriteOps", "OtherOps", "ReadBytes", "WriteBytes", "OtherBytes")
        ]

    class ExtendedLimits(ctypes.Structure):
        _fields_ = [
            ("Basic", BasicLimits),
            ("IO", Counters),
            ("ProcessMemory", ctypes.c_size_t),
            ("JobMemory", ctypes.c_size_t),
            ("PeakProcessMemory", ctypes.c_size_t),
            ("PeakJobMemory", ctypes.c_size_t),
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    kernel.SetInformationJobObject.restype = wintypes.BOOL
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.AssignProcessToJobObject.restype = wintypes.BOOL
    global _JOB
    _JOB = kernel.CreateJobObjectW(None, None)
    limits = ExtendedLimits()
    limits.Basic.Flags = 0x100 | 0x2000 | 0x2  # Per-process memory/CPU; kill worker on job close.
    limits.Basic.ProcessTime = 10 * 10_000_000
    limits.ProcessMemory = MEMORY_BYTES
    if (
        not _JOB
        or not kernel.SetInformationJobObject(_JOB, 9, ctypes.byref(limits), ctypes.sizeof(limits))
        or not kernel.AssignProcessToJobObject(_JOB, kernel.GetCurrentProcess())
    ):
        raise OSError("DOCUMENT_RESOURCE_LIMIT_UNAVAILABLE")


def main():
    response = {}
    try:
        _limit_resources()
        payload = json.loads(sys.stdin.buffer.read(4096))
        path, limit = Path(payload["path"]), payload["max_chars"]
        if (
            type(limit) is not int
            or not 1 <= limit <= 250_001
            or not path.is_file()
            or not 0 < path.stat().st_size <= 25 * 1024 * 1024
        ):
            raise ValueError("DOCUMENT_PARSE_FAILED")
        name = {".pdf": "pdf", ".docx": "docx", ".pptx": "pptx", ".txt": "text", ".md": "text"}[
            path.suffix.casefold()
        ]
        with open(os.devnull, "w") as discard, contextlib.redirect_stdout(discard):
            reader = importlib.import_module("app.parsers." + name)
            text = reader.extract(path, limit)
        response = {"text": text[:limit]}
    except MemoryError:
        response = {"error": "DOCUMENT_RESOURCE_LIMIT"}
    except Exception as exc:  # noqa: BLE001 - never pass untrusted parser details to the parent
        message = str(exc)
        response = {
            "error": "DOCUMENT_ENCRYPTED"
            if message.startswith("DOCUMENT_ENCRYPTED")
            else "DOCUMENT_RESOURCE_LIMIT_UNAVAILABLE"
            if message.startswith("DOCUMENT_RESOURCE_LIMIT_UNAVAILABLE")
            else "DOCUMENT_PARSE_FAILED"
        }
    print(json.dumps(response, ensure_ascii=False))


if __name__ == "__main__":
    main()
