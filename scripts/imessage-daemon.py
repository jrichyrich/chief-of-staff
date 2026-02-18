#!/usr/bin/env python3
"""Run the local Jarvis iMessage daemon."""

from __future__ import annotations

import argparse
import fcntl
import logging
import os
import signal
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from chief.imessage_daemon import DaemonConfig, IMessageDaemon


def env_int(name: str, default: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        val = int(raw)
    except ValueError:
        return default
    return val if val > 0 else default


class FileLock:
    def __init__(self, path: Path):
        self.path = path
        self._fh = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self.path.open("a+", encoding="utf-8")
        try:
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._fh.seek(0)
            self._fh.truncate(0)
            self._fh.write(str(os.getpid()))
            self._fh.flush()
            return True
        except OSError:
            return False

    def release(self) -> None:
        if self._fh is None:
            return
        try:
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        finally:
            self._fh.close()
            self._fh = None


def configure_logging(log_path: Path, verbose: bool) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def parse_args() -> argparse.Namespace:
    cwd = Path.cwd()
    parser = argparse.ArgumentParser(description="Run Jarvis iMessage daemon.")
    parser.add_argument("--project-dir", default=os.getenv("JARVIS_PROJECT_DIR", str(cwd)))
    parser.add_argument("--data-dir", default=os.getenv("JARVIS_DATA_DIR", ""))
    parser.add_argument("--poll-interval-seconds", type=int, default=env_int("IMESSAGE_DAEMON_POLL_INTERVAL_SECONDS", 5))
    parser.add_argument("--bootstrap-lookback-minutes", type=int, default=env_int("IMESSAGE_DAEMON_BOOTSTRAP_LOOKBACK_MINUTES", 30))
    parser.add_argument("--max-lookback-minutes", type=int, default=env_int("IMESSAGE_DAEMON_MAX_LOOKBACK_MINUTES", 1440))
    parser.add_argument("--dispatch-batch-size", type=int, default=env_int("IMESSAGE_DAEMON_DISPATCH_BATCH_SIZE", 25))
    parser.add_argument("--once", action="store_true", help="Run one ingest+dispatch cycle and exit.")
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


def build_config(args: argparse.Namespace) -> DaemonConfig:
    project_dir = Path(args.project_dir).expanduser().resolve()
    data_dir = Path(args.data_dir).expanduser().resolve() if args.data_dir else project_dir / "data"
    reader_path = Path(os.getenv("IMESSAGE_READER_PATH", str(project_dir / "scripts" / "imessage-reader"))).expanduser().resolve()
    monitor_path = Path(os.getenv("INBOX_MONITOR_PATH", str(project_dir / "scripts" / "inbox-monitor.sh"))).expanduser().resolve()
    state_db = Path(os.getenv("IMESSAGE_DAEMON_STATE_DB", str(data_dir / "imessage-worker.db"))).expanduser().resolve()
    processed_file = Path(os.getenv("INBOX_MONITOR_PROCESSED_FILE", str(data_dir / "inbox-processed.json"))).expanduser().resolve()
    return DaemonConfig(
        project_dir=project_dir,
        data_dir=data_dir,
        reader_path=reader_path,
        inbox_monitor_path=monitor_path,
        state_db_path=state_db,
        processed_file=processed_file,
        poll_interval_seconds=max(1, args.poll_interval_seconds),
        bootstrap_lookback_minutes=max(1, args.bootstrap_lookback_minutes),
        max_lookback_minutes=max(5, args.max_lookback_minutes),
        dispatch_batch_size=max(1, args.dispatch_batch_size),
    )


def main() -> int:
    args = parse_args()
    cfg = build_config(args)
    log_path = Path(os.getenv("IMESSAGE_DAEMON_LOG_FILE", str(cfg.data_dir / "imessage-daemon.log"))).expanduser().resolve()
    configure_logging(log_path, verbose=args.verbose)

    if not cfg.reader_path.exists():
        logging.getLogger("imessage-daemon").error("Missing iMessage reader binary: %s", cfg.reader_path)
        return 1
    if not cfg.inbox_monitor_path.exists():
        logging.getLogger("imessage-daemon").error("Missing inbox monitor script: %s", cfg.inbox_monitor_path)
        return 1

    lock = FileLock(Path(os.getenv("IMESSAGE_DAEMON_LOCK_FILE", str(cfg.data_dir / "imessage-daemon.lock"))).expanduser().resolve())
    if not lock.acquire():
        logging.getLogger("imessage-daemon").error("Another daemon instance is already running.")
        return 1

    daemon = IMessageDaemon(cfg)
    should_stop = False

    def _handle_signal(_signum: int, _frame: object) -> None:
        nonlocal should_stop
        should_stop = True

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    try:
        if args.once:
            result = daemon.run_once()
            logging.getLogger("imessage-daemon").info("Run once: %s", result)
            return 0

        while not should_stop:
            try:
                result = daemon.run_once()
                if result["ingested"] > 0 or result["dispatched"] > 0:
                    logging.getLogger("imessage-daemon").info("Cycle result: %s", result)
            except Exception:
                logging.getLogger("imessage-daemon").exception("Daemon cycle crashed")
            time.sleep(cfg.poll_interval_seconds)
        logging.getLogger("imessage-daemon").info("Shutdown requested.")
        return 0
    finally:
        daemon.close()
        lock.release()


if __name__ == "__main__":
    raise SystemExit(main())
