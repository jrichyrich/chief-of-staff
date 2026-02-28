"""Tests for advisory file locking in OKRStore and SessionBrain."""

import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from okr.models import Initiative, KeyResult, OKRSnapshot, Objective
from okr.store import OKRStore
from session.brain import SessionBrain


def _make_snapshot(label: str = "test") -> OKRSnapshot:
    return OKRSnapshot(
        timestamp="2026-01-01T00:00:00",
        source_file=f"{label}.xlsx",
        objectives=[Objective(
            okr_id="O-1", name=f"Obj-{label}", statement="Test objective",
            owner="tester", team="eng", year="2026", status="On Track", pct_complete=50,
        )],
        key_results=[KeyResult(
            kr_id="KR-1", okr_id="O-1", name=f"KR-{label}", status="On Track",
            team="eng",
        )],
        initiatives=[Initiative(
            initiative_id="I-1", kr_ids="KR-1", okr_id="O-1",
            name=f"Init-{label}", description="Test",
            team="eng", status="On Track", investment_dollars=100, blocker="",
        )],
    )


class TestOKRStoreLocking:
    def test_concurrent_saves_do_not_corrupt(self, tmp_path):
        """Multiple concurrent saves should not produce corrupted JSON."""
        store = OKRStore(tmp_path / "okr")
        errors = []

        def save_snapshot(i):
            try:
                store.save(_make_snapshot(f"writer-{i}"))
            except Exception as e:
                errors.append(e)

        with ThreadPoolExecutor(max_workers=10) as pool:
            list(pool.map(save_snapshot, range(20)))

        assert not errors, f"Save errors: {errors}"
        # Final state should be a valid snapshot
        result = store.load_latest()
        assert result is not None
        assert result.objectives[0].name.startswith("Obj-writer-")

    def test_read_during_write_returns_valid_data(self, tmp_path):
        """Reading during concurrent writes should always return valid JSON."""
        store = OKRStore(tmp_path / "okr")
        store.save(_make_snapshot("initial"))

        errors = []
        stop = threading.Event()

        def writer():
            i = 0
            while not stop.is_set():
                try:
                    store.save(_make_snapshot(f"w-{i}"))
                    i += 1
                except Exception as e:
                    errors.append(("write", e))

        def reader():
            while not stop.is_set():
                try:
                    result = store.load_latest()
                    assert result is not None
                    assert len(result.objectives) > 0
                except Exception as e:
                    errors.append(("read", e))

        threads = [threading.Thread(target=writer)]
        threads += [threading.Thread(target=reader) for _ in range(3)]
        for t in threads:
            t.start()

        # Let them race for a bit
        stop.wait(timeout=1.0)
        stop.set()
        for t in threads:
            t.join(timeout=5)

        assert not errors, f"Errors during concurrent read/write: {errors}"


class TestSessionBrainLocking:
    def test_concurrent_saves_do_not_corrupt(self, tmp_path):
        """Multiple concurrent saves should not produce corrupted markdown."""
        brain_path = tmp_path / "brain.md"
        errors = []

        def save_brain(i):
            try:
                brain = SessionBrain(brain_path)
                brain.add_workstream(f"ws-{i}", "active", f"context-{i}")
                brain.add_handoff_note(f"note-{i}")
                brain.save()
            except Exception as e:
                errors.append(e)

        with ThreadPoolExecutor(max_workers=10) as pool:
            list(pool.map(save_brain, range(20)))

        assert not errors, f"Save errors: {errors}"
        # Final state should be valid markdown
        brain = SessionBrain(brain_path)
        brain.load()
        assert len(brain.workstreams) >= 1 or len(brain.handoff_notes) >= 1

    def test_read_during_write_returns_valid_data(self, tmp_path):
        """Reading during concurrent writes should always return valid markdown."""
        brain_path = tmp_path / "brain.md"
        initial = SessionBrain(brain_path)
        initial.add_workstream("initial", "active", "setup")
        initial.save()

        errors = []
        stop = threading.Event()

        def writer():
            i = 0
            while not stop.is_set():
                try:
                    brain = SessionBrain(brain_path)
                    brain.add_workstream(f"ws-{i}", "active", f"context-{i}")
                    brain.save()
                    i += 1
                except Exception as e:
                    errors.append(("write", e))

        def reader():
            while not stop.is_set():
                try:
                    brain = SessionBrain(brain_path)
                    brain.load()
                    # Should always be parseable (no partial writes)
                    rendered = brain.render()
                    assert "## Active Workstreams" in rendered
                except Exception as e:
                    errors.append(("read", e))

        threads = [threading.Thread(target=writer)]
        threads += [threading.Thread(target=reader) for _ in range(3)]
        for t in threads:
            t.start()

        stop.wait(timeout=1.0)
        stop.set()
        for t in threads:
            t.join(timeout=5)

        assert not errors, f"Errors during concurrent read/write: {errors}"
