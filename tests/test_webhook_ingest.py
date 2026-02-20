# tests/test_webhook_ingest.py
"""Tests for the file-drop webhook inbox ingestion."""

import json

import pytest

from memory.store import MemoryStore
from webhook.ingest import ingest_events


@pytest.fixture
def memory_store(tmp_path):
    db_path = tmp_path / "test_webhook.db"
    store = MemoryStore(db_path)
    yield store
    store.close()


@pytest.fixture
def inbox_dir(tmp_path):
    d = tmp_path / "webhook-inbox"
    d.mkdir()
    return d


class TestIngestEvents:
    def test_valid_json_ingested(self, memory_store, inbox_dir):
        event_file = inbox_dir / "event1.json"
        event_file.write_text(
            json.dumps({
                "source": "github",
                "event_type": "push",
                "payload": {"ref": "main"},
            })
        )

        result = ingest_events(memory_store, inbox_dir)

        assert result["ingested"] == 1
        assert result["failed"] == 0
        assert result["skipped"] == 0

        # Verify file moved to processed/
        assert not event_file.exists()
        assert (inbox_dir / "processed" / "event1.json").exists()

        # Verify event stored in DB
        events = memory_store.list_webhook_events(limit=10)
        assert len(events) == 1
        assert events[0].source == "github"
        assert events[0].event_type == "push"
        assert json.loads(events[0].payload) == {"ref": "main"}
        assert events[0].status == "pending"

    def test_multiple_files_ingested(self, memory_store, inbox_dir):
        for i in range(3):
            (inbox_dir / f"event{i}.json").write_text(
                json.dumps({"source": f"src{i}", "event_type": "test"})
            )

        result = ingest_events(memory_store, inbox_dir)

        assert result["ingested"] == 3
        assert result["failed"] == 0
        events = memory_store.list_webhook_events(limit=10)
        assert len(events) == 3

    def test_malformed_json_moved_to_failed(self, memory_store, inbox_dir):
        bad_file = inbox_dir / "bad.json"
        bad_file.write_text("not valid json {{{")

        result = ingest_events(memory_store, inbox_dir)

        assert result["ingested"] == 0
        assert result["failed"] == 1
        assert not bad_file.exists()
        assert (inbox_dir / "failed" / "bad.json").exists()

    def test_missing_source_field_fails(self, memory_store, inbox_dir):
        (inbox_dir / "nosource.json").write_text(
            json.dumps({"event_type": "test"})
        )

        result = ingest_events(memory_store, inbox_dir)

        assert result["failed"] == 1
        assert result["ingested"] == 0
        assert (inbox_dir / "failed" / "nosource.json").exists()

    def test_missing_event_type_field_fails(self, memory_store, inbox_dir):
        (inbox_dir / "notype.json").write_text(
            json.dumps({"source": "test"})
        )

        result = ingest_events(memory_store, inbox_dir)

        assert result["failed"] == 1
        assert result["ingested"] == 0
        assert (inbox_dir / "failed" / "notype.json").exists()

    def test_non_dict_json_fails(self, memory_store, inbox_dir):
        (inbox_dir / "array.json").write_text(json.dumps([1, 2, 3]))

        result = ingest_events(memory_store, inbox_dir)

        assert result["failed"] == 1
        assert (inbox_dir / "failed" / "array.json").exists()

    def test_empty_directory_noop(self, memory_store, inbox_dir):
        result = ingest_events(memory_store, inbox_dir)

        assert result == {"ingested": 0, "failed": 0, "skipped": 0}

    def test_string_payload_stored_as_is(self, memory_store, inbox_dir):
        (inbox_dir / "strpayload.json").write_text(
            json.dumps({
                "source": "test",
                "event_type": "ping",
                "payload": "plain text",
            })
        )

        result = ingest_events(memory_store, inbox_dir)

        assert result["ingested"] == 1
        events = memory_store.list_webhook_events(limit=10)
        assert events[0].payload == "plain text"

    def test_dict_payload_serialized_to_json(self, memory_store, inbox_dir):
        (inbox_dir / "dictpayload.json").write_text(
            json.dumps({
                "source": "test",
                "event_type": "ping",
                "payload": {"key": "value"},
            })
        )

        result = ingest_events(memory_store, inbox_dir)

        assert result["ingested"] == 1
        events = memory_store.list_webhook_events(limit=10)
        assert json.loads(events[0].payload) == {"key": "value"}

    def test_missing_payload_defaults_empty(self, memory_store, inbox_dir):
        (inbox_dir / "nopayload.json").write_text(
            json.dumps({"source": "test", "event_type": "ping"})
        )

        result = ingest_events(memory_store, inbox_dir)

        assert result["ingested"] == 1
        events = memory_store.list_webhook_events(limit=10)
        assert events[0].payload == ""

    def test_duplicate_filename_handled(self, memory_store, inbox_dir):
        """If a file with the same name already exists in processed/, rename."""
        processed_dir = inbox_dir / "processed"
        processed_dir.mkdir()
        # Pre-existing file in processed/
        (processed_dir / "dup.json").write_text("old")

        (inbox_dir / "dup.json").write_text(
            json.dumps({"source": "test", "event_type": "ping"})
        )

        result = ingest_events(memory_store, inbox_dir)

        assert result["ingested"] == 1
        # Original processed file still there
        assert (processed_dir / "dup.json").exists()
        assert (processed_dir / "dup.json").read_text() == "old"
        # New file also in processed/ with a different name
        processed_files = list(processed_dir.glob("dup*.json"))
        assert len(processed_files) == 2

    def test_non_json_files_ignored(self, memory_store, inbox_dir):
        """Only *.json files are processed; others are left in place."""
        (inbox_dir / "readme.txt").write_text("ignore me")
        (inbox_dir / "event.json").write_text(
            json.dumps({"source": "test", "event_type": "ping"})
        )

        result = ingest_events(memory_store, inbox_dir)

        assert result["ingested"] == 1
        assert (inbox_dir / "readme.txt").exists()  # untouched

    def test_mixed_valid_and_invalid(self, memory_store, inbox_dir):
        (inbox_dir / "good.json").write_text(
            json.dumps({"source": "s", "event_type": "e"})
        )
        (inbox_dir / "bad.json").write_text("nope")

        result = ingest_events(memory_store, inbox_dir)

        assert result["ingested"] == 1
        assert result["failed"] == 1
        assert (inbox_dir / "processed" / "good.json").exists()
        assert (inbox_dir / "failed" / "bad.json").exists()
