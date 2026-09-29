"""App config for core."""

from __future__ import annotations

import atexit
import os
import subprocess
import sys
from typing import TYPE_CHECKING

from django.apps import AppConfig
from django.conf import settings

if TYPE_CHECKING:
    from pathlib import Path


def _lock_holder_is_alive(lock_path: Path) -> bool:
    """Return whether the PID recorded in the autostart lock file is still running."""
    try:
        existing_pid = int(lock_path.read_text().strip())
    except ValueError:
        existing_pid = None

    if not existing_pid:
        lock_path.unlink(missing_ok=True)
        return False

    try:
        os.kill(existing_pid, 0)
    except OSError:
        lock_path.unlink(missing_ok=True)
        return False

    return True


def _qcluster_process_running() -> bool:
    """Return whether a qcluster management command is already running."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", "manage.py qcluster"],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return False

    return result.returncode == 0


def _start_qcluster_worker(lock_path: Path) -> None:
    """Spawn the qcluster worker process and register its shutdown handler."""
    os.environ["QCLUSTER_AUTOSTART"] = "1"
    cmd = [sys.executable, "manage.py", "qcluster"]
    process = subprocess.Popen(cmd, cwd=str(settings.BASE_DIR))
    lock_path.write_text(str(process.pid))

    def _stop_worker() -> None:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()

        lock_path.unlink(missing_ok=True)

    atexit.register(_stop_worker)


class CoreConfig(AppConfig):
    """Core app config."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "core"

    def ready(self) -> None:
        """Auto-start render queue worker unless one is already running."""
        if "runserver" not in sys.argv:
            return
        if os.environ.get("RUN_MAIN") != "true":
            return
        if os.environ.get("SKIP_QCLUSTER_AUTOSTART") == "1":
            return
        if os.environ.get("QCLUSTER_AUTOSTART") == "1":
            return

        lock_path = settings.BASE_DIR / ".qcluster-autostart.pid"

        if lock_path.exists() and _lock_holder_is_alive(lock_path):
            return

        if _qcluster_process_running():
            return

        _start_qcluster_worker(lock_path)
