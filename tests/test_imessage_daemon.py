import json
import subprocess
from pathlib import Path

from chief.imessage_daemon import (
    DaemonConfig,
    IMessageDaemon,
    IngestedMessage,
    StateStore,
    compute_lookback_minutes,
    parse_local_date_to_epoch,
)


def _config(tmp_path: Path) -> DaemonConfig:
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return DaemonConfig(
        project_dir=tmp_path,
        data_dir=data_dir,
        reader_path=tmp_path / "scripts" / "imessage-reader",
        inbox_monitor_path=tmp_path / "scripts" / "inbox-monitor.sh",
        state_db_path=data_dir / "imessage-worker.db",
        processed_file=data_dir / "inbox-processed.json",
    )


def test_parse_local_date_to_epoch():
    epoch = parse_local_date_to_epoch("2026-02-16 10:30:00")
    assert isinstance(epoch, int)
    assert epoch > 0


def test_compute_lookback_minutes_bootstrap():
    assert compute_lookback_minutes(0, now_epoch=1000, bootstrap_minutes=30, max_minutes=120) == 30


def test_state_store_ingest_dedup(tmp_path: Path):
    store = StateStore(tmp_path / "state.db")
    msg = IngestedMessage(
        guid="guid-1",
        text="jarvis: test",
        date_local="2026-02-16 10:00:00",
        timestamp_epoch=1700000000,
        raw_json='{"guid":"guid-1"}',
    )
    inserted, max_epoch = store.ingest_messages([msg, msg])
    assert inserted == 1
    assert max_epoch == 1700000000
    assert store.count_jobs_by_status("queued") == 1
    store.close()


def test_daemon_ingest_and_dispatch_reconcile(tmp_path: Path, monkeypatch):
    cfg = _config(tmp_path)
    cfg.reader_path.parent.mkdir(parents=True, exist_ok=True)
    cfg.inbox_monitor_path.parent.mkdir(parents=True, exist_ok=True)
    cfg.reader_path.write_text("", encoding="utf-8")
    cfg.inbox_monitor_path.write_text("", encoding="utf-8")
    cfg.processed_file.write_text('{"processed_ids":["g1"]}', encoding="utf-8")

    daemon = IMessageDaemon(cfg)

    def fake_run(cmd, capture_output, text, check):
        if "imessage-reader" in str(cmd[0]):
            payload = [
                {"guid": "g1", "text": "jarvis: one", "date_local": "2026-02-16 10:00:00"},
                {"guid": "g2", "text": "jarvis: two", "date_local": "2026-02-16 10:01:00"},
            ]
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(payload), stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("chief.imessage_daemon.subprocess.run", fake_run)

    ingested = daemon._ingest_cycle()
    assert ingested == 2
    assert daemon.store.count_jobs_by_status("queued") == 2

    dispatched = daemon._dispatch_cycle()
    assert dispatched == 1
    assert daemon.store.count_jobs_by_status("succeeded") == 1
    assert daemon.store.count_jobs_by_status("failed") == 1

    daemon.close()
