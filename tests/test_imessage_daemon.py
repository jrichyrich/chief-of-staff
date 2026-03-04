import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

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
        state_db_path=data_dir / "imessage-worker.db",
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


def test_ingest_cycle_uses_message_store_directly(tmp_path):
    """Ingest cycle should read from MessageStore, not subprocess."""
    cfg = _config(tmp_path)
    mock_store = MagicMock()
    mock_store.get_messages.return_value = [
        {
            "guid": "msg-001",
            "text": "Jarvis, check my calendar",
            "date_local": "2026-03-03 10:00:00",
            "is_from_me": True,
            "sender": "+15551234567",
            "chat_identifier": "+15551234567",
        }
    ]
    daemon = IMessageDaemon(cfg, message_store=mock_store)
    count = daemon._ingest_cycle()
    mock_store.get_messages.assert_called_once()
    assert count == 1
    daemon.close()


def test_ingest_cycle_skips_messages_without_guid(tmp_path):
    """Messages without guid or date_local should be skipped."""
    cfg = _config(tmp_path)
    mock_store = MagicMock()
    mock_store.get_messages.return_value = [
        {"guid": "", "text": "no guid", "date_local": "2026-03-03 10:00:00"},
        {"guid": "has-guid", "text": "has guid", "date_local": ""},
        {"guid": "ok", "text": "ok", "date_local": "2026-03-03 10:00:00"},
    ]
    daemon = IMessageDaemon(cfg, message_store=mock_store)
    count = daemon._ingest_cycle()
    assert count == 1
    daemon.close()


@pytest.mark.asyncio
async def test_dispatch_cycle_executes_and_replies(tmp_path):
    """Dispatch cycle should execute queued messages and send iMessage reply."""
    cfg = _config(tmp_path)
    daemon = IMessageDaemon(cfg, message_store=MagicMock())

    # Seed a queued job
    daemon.store.ingest_messages([
        IngestedMessage(
            guid="msg-dispatch-001",
            text="Check my calendar",
            date_local="2026-03-03 10:00:00",
            timestamp_epoch=1741000000,
            raw_json="{}",
        )
    ])

    mock_executor = AsyncMock()
    mock_executor.execute = AsyncMock(return_value="You have 3 meetings today.")
    daemon.executor = mock_executor

    replies = []
    daemon.reply_fn = lambda body: replies.append(body)

    dispatched = await daemon._dispatch_cycle()

    assert dispatched == 1
    mock_executor.execute.assert_called_once_with("Check my calendar")
    assert len(replies) == 1
    assert "3 meetings" in replies[0]
    daemon.close()


@pytest.mark.asyncio
async def test_dispatch_cycle_handles_no_executor(tmp_path):
    """Dispatch without executor should mark jobs as failed."""
    cfg = _config(tmp_path)
    daemon = IMessageDaemon(cfg, message_store=MagicMock())

    daemon.store.ingest_messages([
        IngestedMessage(
            guid="msg-no-exec",
            text="Do something",
            date_local="2026-03-03 10:00:00",
            timestamp_epoch=1741000000,
            raw_json="{}",
        )
    ])

    dispatched = await daemon._dispatch_cycle()
    assert dispatched == 0
    assert daemon.store.count_jobs_by_status("failed") == 1
    daemon.close()


@pytest.mark.asyncio
async def test_dispatch_cycle_handles_executor_failure(tmp_path):
    """Executor errors should mark job failed, not crash the daemon."""
    cfg = _config(tmp_path)
    daemon = IMessageDaemon(cfg, message_store=MagicMock())

    daemon.store.ingest_messages([
        IngestedMessage(
            guid="msg-fail",
            text="Break things",
            date_local="2026-03-03 10:00:00",
            timestamp_epoch=1741000000,
            raw_json="{}",
        )
    ])

    mock_executor = AsyncMock()
    mock_executor.execute = AsyncMock(side_effect=RuntimeError("API error"))
    daemon.executor = mock_executor

    dispatched = await daemon._dispatch_cycle()
    assert dispatched == 0
    assert daemon.store.count_jobs_by_status("failed") == 1
    daemon.close()


@pytest.mark.asyncio
async def test_run_once_ingest_and_dispatch(tmp_path):
    """run_once should ingest then dispatch."""
    cfg = _config(tmp_path)
    mock_store = MagicMock()
    mock_store.get_messages.return_value = [
        {
            "guid": "run-once-001",
            "text": "Check my meetings",
            "date_local": "2026-03-03 10:00:00",
            "is_from_me": True,
            "sender": "+15551234567",
            "chat_identifier": "+15551234567",
        }
    ]

    mock_executor = AsyncMock()
    mock_executor.execute = AsyncMock(return_value="You have 2 meetings.")

    daemon = IMessageDaemon(
        cfg,
        message_store=mock_store,
        executor=mock_executor,
        reply_fn=lambda body: None,
    )

    result = await daemon.run_once()
    assert result["ingested"] == 1
    assert result["dispatched"] == 1
    daemon.close()
