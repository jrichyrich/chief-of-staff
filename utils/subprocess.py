"""Shared subprocess helper with process-group cleanup on timeout."""

import os
import signal
import subprocess


def run_with_cleanup(cmd, timeout, **kwargs):
    """Run a subprocess with proper cleanup on timeout (kills process group).

    Uses ``start_new_session=True`` so that the child gets its own process
    group, enabling ``os.killpg`` to terminate the entire tree on timeout.

    Returns a ``subprocess.CompletedProcess`` on success.
    Raises ``subprocess.TimeoutExpired`` on timeout (after cleanup).
    """
    proc = subprocess.Popen(cmd, start_new_session=True, **kwargs)
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
        return subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)
    except subprocess.TimeoutExpired:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        proc.wait(timeout=5)
        raise
