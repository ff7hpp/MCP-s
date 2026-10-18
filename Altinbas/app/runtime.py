"""Identify the loaded server and detect source edits requiring reconnection."""

import hashlib
import platform
from datetime import UTC, datetime

from app import __version__
from app.config import PROJECT_ROOT

STARTED_AT = datetime.now(UTC).isoformat()


def source_fingerprint():
    digest = hashlib.sha256()
    for path in sorted((PROJECT_ROOT / "app").rglob("*.py")) + [PROJECT_ROOT / "pyproject.toml"]:
        digest.update(path.relative_to(PROJECT_ROOT).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


LOADED_FINGERPRINT = source_fingerprint()


def runtime_info():
    current = source_fingerprint()
    return {
        "version": __version__,
        "started_at": STARTED_AT,
        "python": platform.python_version(),
        "platform": platform.system(),
        "loaded_source_fingerprint": LOADED_FINGERPRINT,
        "disk_source_fingerprint": current,
        "reconnect_required": current != LOADED_FINGERPRINT,
        "deployment": "Local single-user stdio host; other-device access is not configured",
    }
