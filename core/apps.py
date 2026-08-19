"""App config for core."""

from __future__ import annotations

import atexit
import os
import subprocess
import sys

from django.apps import AppConfig
from django.conf import settings


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

        if lock_path.exists():
            try:
                existing_pid = int(lock_path.read_text().strip())
            except ValueError:
                existing_pid = None

            if existing_pid:
                try:
                    os.kill(existing_pid, 0)
                except OSError:
                    lock_path.unlink(missing_ok=True)
                else:
                    return
            else:
                lock_path.unlink(missing_ok=True)

        try:
            result = subprocess.run(
                ["pgrep", "-f", "manage.py qcluster"],
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError:
            result = None

        if result and result.returncode == 0:
            return

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
