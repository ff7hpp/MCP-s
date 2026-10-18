"""Owned daily child process with a hard 15-minute cancellation boundary."""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    child = subprocess.Popen(
        [sys.executable, "-m", "app.cli", "daily-update", "--quiet"],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    try:
        return child.wait(timeout=900)
    except (subprocess.TimeoutExpired, KeyboardInterrupt):
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(child.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=20,
            )
        else:
            child.kill()
        child.wait(timeout=30)
        sys.path.insert(0, str(ROOT))
        from app.services.daily import STATE_PATH, _now
        from app.storage.state import load_state, operation_lock, save_state

        with operation_lock(wait_seconds=15):
            state = load_state(STATE_PATH)
            state.setdefault("run", {}).update(
                status="CANCELLED", last_error="DAILY_TIMEOUT_OR_CANCELLED", last_completed=_now()
            )
            save_state(STATE_PATH, state)
        return 124


if __name__ == "__main__":
    raise SystemExit(main())
