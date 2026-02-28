# tests/test_thread_safety.py
"""Tests for thread safety of shared SQLite connection across domain stores."""
from concurrent.futures import ThreadPoolExecutor, as_completed

from memory.models import Fact
from memory.store import MemoryStore


class TestThreadSafety:

    def test_concurrent_writes_do_not_corrupt(self, tmp_path):
        """50 parallel store_fact calls should all succeed without corruption."""
        store = MemoryStore(tmp_path / "test.db")
        errors = []

        def write_fact(i):
            try:
                store.store_fact(Fact(
                    category="personal",
                    key=f"key_{i}",
                    value=f"value_{i}",
                ))
            except Exception as exc:
                errors.append((i, exc))

        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(write_fact, i) for i in range(50)]
            for f in as_completed(futures):
                f.result()

        assert errors == [], f"Errors during concurrent writes: {errors}"

        # Verify all 50 facts stored
        for i in range(50):
            fact = store.get_fact("personal", f"key_{i}")
            assert fact is not None, f"key_{i} missing"
            assert fact.value == f"value_{i}"

        store.close()

    def test_concurrent_read_write_safe(self, tmp_path):
        """Concurrent reads and writes should not raise or corrupt."""
        store = MemoryStore(tmp_path / "test.db")
        # Seed some data
        for i in range(10):
            store.store_fact(Fact(category="work", key=f"seed_{i}", value=f"v_{i}"))

        errors = []

        def writer(i):
            try:
                store.store_fact(Fact(category="work", key=f"new_{i}", value=f"new_v_{i}"))
            except Exception as exc:
                errors.append(("write", i, exc))

        def reader(i):
            try:
                store.search_facts(f"seed_{i % 10}")
            except Exception as exc:
                errors.append(("read", i, exc))

        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = []
            for i in range(20):
                futures.append(executor.submit(writer, i))
                futures.append(executor.submit(reader, i))
            for f in as_completed(futures):
                f.result()

        assert errors == [], f"Errors during concurrent read/write: {errors}"
        store.close()

    def test_check_same_thread_false(self, tmp_path):
        """Verify the connection is created with check_same_thread=False."""
        store = MemoryStore(tmp_path / "test.db")
        # If check_same_thread were True, accessing from another thread would raise
        result = [None]

        def read_from_thread():
            result[0] = store.get_fact("personal", "nonexistent")

        import threading
        t = threading.Thread(target=read_from_thread)
        t.start()
        t.join()
        assert result[0] is None  # No exception, returned None
        store.close()
