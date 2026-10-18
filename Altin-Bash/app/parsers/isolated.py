"""Bound document parsing to a disposable process, time and memory budget."""

import json
import os
import subprocess
import sys
from pathlib import Path

from app.config import PROJECT_ROOT
from app.errors import ActionableError

TIMEOUT_SECONDS = 15


def extract_isolated(path: Path, max_chars: int) -> str:
    environment = {
        key: value
        for key, value in os.environ.items()
        if key.upper() in {"SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATH"}
    }
    environment.update(PYTHONPATH=str(PROJECT_ROOT), PYTHONIOENCODING="utf-8")
    try:
        result = subprocess.run(
            [sys.executable, "-B", "-m", "app.parsers.worker"],
            input=json.dumps({"path": str(path), "max_chars": max_chars}).encode(),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=TIMEOUT_SECONDS,
            cwd=PROJECT_ROOT,
            env=environment,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except subprocess.TimeoutExpired:
        raise ActionableError(
            "DOCUMENT_TIMEOUT: parser stopped; server remains available"
        ) from None
    if result.returncode or len(result.stdout) > 3_000_000:
        raise ActionableError("DOCUMENT_WORKER_FAILED: parser exited or exceeded resource budget")
    try:
        payload = json.loads(result.stdout)
    except ValueError:
        raise ActionableError("DOCUMENT_WORKER_FAILED: invalid bounded parser response") from None
    if not isinstance(payload, dict):
        raise ActionableError("DOCUMENT_WORKER_FAILED: invalid response shape")
    if payload.get("error"):
        code = payload["error"]
        if code not in {
            "DOCUMENT_ENCRYPTED",
            "DOCUMENT_RESOURCE_LIMIT_UNAVAILABLE",
            "DOCUMENT_RESOURCE_LIMIT",
            "DOCUMENT_PARSE_FAILED",
        }:
            code = "DOCUMENT_PARSE_FAILED"
        raise ActionableError(code + ": cannot extract this document")
    text = payload.get("text")
    if not isinstance(text, str) or len(text) > max_chars:
        raise ActionableError("DOCUMENT_WORKER_FAILED: invalid text limit")
    return text
