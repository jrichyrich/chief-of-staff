"""End-to-end integration tests for async iMessage command channel."""

import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.mark.asyncio
async def test_full_imessage_command_flow(tmp_path):
    """Full flow: new message -> ingest -> execute -> reply."""
    from chief.imessage_daemon import DaemonConfig, IMessageDaemon

    cfg = DaemonConfig(
        project_dir=tmp_path,
        data_dir=tmp_path,
        state_db_path=tmp_path / "worker.db",
    )

    # Mock MessageStore with a new message
    mock_msg_store = MagicMock()
    mock_msg_store.get_messages.return_value = [
        {
            "guid": "e2e-001",
            "text": "Jarvis, what meetings do I have tomorrow?",
            "date_local": "2026-03-03 14:00:00",
            "is_from_me": True,
            "sender": "+15551234567",
            "chat_identifier": "+15551234567",
        }
    ]

    # Mock executor
    mock_executor = AsyncMock()
    mock_executor.execute = AsyncMock(
        return_value="Tomorrow you have: 9am Standup, 2pm 1:1 with Sarah, 4pm Sprint Review."
    )

    # Capture replies
    replies_sent = []

    def capture_reply(body: str) -> dict:
        replies_sent.append(body)
        return {"status": "sent"}

    daemon = IMessageDaemon(
        cfg,
        message_store=mock_msg_store,
        executor=mock_executor,
        reply_fn=capture_reply,
    )

    # Run full cycle
    result = await daemon.run_once()

    assert result["ingested"] == 1
    assert result["dispatched"] == 1
    assert len(replies_sent) == 1
    assert "Standup" in replies_sent[0]
    assert "Sprint Review" in replies_sent[0]

    # Verify idempotency — second run should not re-process
    result2 = await daemon.run_once()
    assert result2["ingested"] == 0  # same GUID, already ingested
    assert result2["dispatched"] == 0  # no new queued jobs

    daemon.close()


@pytest.mark.asyncio
async def test_imessage_command_handles_executor_failure(tmp_path):
    """Failed execution should mark job as failed, not crash daemon."""
    from chief.imessage_daemon import DaemonConfig, IMessageDaemon

    cfg = DaemonConfig(
        project_dir=tmp_path,
        data_dir=tmp_path,
        state_db_path=tmp_path / "worker.db",
    )

    mock_msg_store = MagicMock()
    mock_msg_store.get_messages.return_value = [
        {
            "guid": "fail-001",
            "text": "Do something impossible",
            "date_local": "2026-03-03 14:00:00",
            "is_from_me": True,
            "sender": "+15551234567",
            "chat_identifier": "+15551234567",
        }
    ]

    mock_executor = AsyncMock()
    mock_executor.execute = AsyncMock(side_effect=RuntimeError("API error"))

    daemon = IMessageDaemon(
        cfg,
        message_store=mock_msg_store,
        executor=mock_executor,
    )

    result = await daemon.run_once()

    assert result["ingested"] == 1
    assert result["dispatched"] == 0  # failed, not dispatched
    assert daemon.store.count_jobs_by_status("failed") == 1

    daemon.close()


@pytest.mark.asyncio
async def test_multiple_messages_processed_in_order(tmp_path):
    """Multiple messages should be ingested and dispatched in timestamp order."""
    from chief.imessage_daemon import DaemonConfig, IMessageDaemon

    cfg = DaemonConfig(
        project_dir=tmp_path,
        data_dir=tmp_path,
        state_db_path=tmp_path / "worker.db",
    )

    mock_msg_store = MagicMock()
    mock_msg_store.get_messages.return_value = [
        {
            "guid": "multi-001",
            "text": "First message",
            "date_local": "2026-03-03 10:00:00",
            "is_from_me": True,
            "sender": "+15551234567",
            "chat_identifier": "+15551234567",
        },
        {
            "guid": "multi-002",
            "text": "Second message",
            "date_local": "2026-03-03 10:01:00",
            "is_from_me": True,
            "sender": "+15551234567",
            "chat_identifier": "+15551234567",
        },
        {
            "guid": "multi-003",
            "text": "Third message",
            "date_local": "2026-03-03 10:02:00",
            "is_from_me": True,
            "sender": "+15551234567",
            "chat_identifier": "+15551234567",
        },
    ]

    execution_order = []

    async def tracking_execute(text):
        execution_order.append(text)
        return f"Reply to: {text}"

    mock_executor = AsyncMock()
    mock_executor.execute = AsyncMock(side_effect=tracking_execute)

    replies = []
    daemon = IMessageDaemon(
        cfg,
        message_store=mock_msg_store,
        executor=mock_executor,
        reply_fn=lambda body: replies.append(body),
    )

    result = await daemon.run_once()

    assert result["ingested"] == 3
    assert result["dispatched"] == 3
    assert len(replies) == 3
    assert execution_order == ["First message", "Second message", "Third message"]

    daemon.close()


@pytest.mark.asyncio
async def test_empty_text_messages_skipped(tmp_path):
    """Messages with empty text should be marked failed, not dispatched."""
    from chief.imessage_daemon import DaemonConfig, IMessageDaemon

    cfg = DaemonConfig(
        project_dir=tmp_path,
        data_dir=tmp_path,
        state_db_path=tmp_path / "worker.db",
    )

    mock_msg_store = MagicMock()
    mock_msg_store.get_messages.return_value = [
        {
            "guid": "empty-001",
            "text": "",
            "date_local": "2026-03-03 10:00:00",
            "is_from_me": True,
            "sender": "+15551234567",
            "chat_identifier": "+15551234567",
        },
        {
            "guid": "valid-001",
            "text": "Check calendar",
            "date_local": "2026-03-03 10:01:00",
            "is_from_me": True,
            "sender": "+15551234567",
            "chat_identifier": "+15551234567",
        },
    ]

    mock_executor = AsyncMock()
    mock_executor.execute = AsyncMock(return_value="Calendar checked.")

    daemon = IMessageDaemon(
        cfg,
        message_store=mock_msg_store,
        executor=mock_executor,
    )

    result = await daemon.run_once()

    assert result["ingested"] == 2
    assert result["dispatched"] == 1
    # Empty message marked as failed
    assert daemon.store.count_jobs_by_status("failed") == 1
    assert daemon.store.count_jobs_by_status("succeeded") == 1

    daemon.close()


@pytest.mark.asyncio
async def test_no_reply_fn_still_dispatches(tmp_path):
    """Without reply_fn, dispatch should succeed but no reply is sent."""
    from chief.imessage_daemon import DaemonConfig, IMessageDaemon

    cfg = DaemonConfig(
        project_dir=tmp_path,
        data_dir=tmp_path,
        state_db_path=tmp_path / "worker.db",
    )

    mock_msg_store = MagicMock()
    mock_msg_store.get_messages.return_value = [
        {
            "guid": "noreply-001",
            "text": "Do something silently",
            "date_local": "2026-03-03 10:00:00",
            "is_from_me": True,
            "sender": "+15551234567",
            "chat_identifier": "+15551234567",
        }
    ]

    mock_executor = AsyncMock()
    mock_executor.execute = AsyncMock(return_value="Done silently.")

    daemon = IMessageDaemon(
        cfg,
        message_store=mock_msg_store,
        executor=mock_executor,
        reply_fn=None,  # no reply function
    )

    result = await daemon.run_once()

    assert result["ingested"] == 1
    assert result["dispatched"] == 1
    assert daemon.store.count_jobs_by_status("succeeded") == 1

    daemon.close()
