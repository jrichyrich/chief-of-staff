from __future__ import annotations

from datetime import datetime
from pathlib import Path

from connectors.calendar_unified import UnifiedCalendarService
from connectors.router import ProviderRouter


class _FakeProvider:
    def __init__(self, name: str, connected: bool = True):
        self.provider_name = name
        self._connected = connected
        self.events: list[dict] = []
        self.created: list[dict] = []
        self.updated: list[tuple[str, dict]] = []
        self.deleted: list[str] = []
        self.create_should_fail = False
        self.read_should_fail = False

    def is_connected(self) -> bool:
        return self._connected

    def list_calendars(self) -> list[dict]:
        return [{
            "name": "Work" if self.provider_name == "microsoft_365" else "Personal",
            "source_account": "Microsoft 365" if self.provider_name == "microsoft_365" else "iCloud",
            "provider": self.provider_name,
        }]

    def get_events(self, start_dt: datetime, end_dt: datetime, calendar_names=None) -> list[dict]:
        if self.read_should_fail:
            return [{"error": f"{self.provider_name} read failed"}]
        return list(self.events)

    def create_event(
        self,
        title: str,
        start_dt: datetime,
        end_dt: datetime,
        calendar_name=None,
        location=None,
        notes=None,
        is_all_day=False,
    ) -> dict:
        if self.create_should_fail:
            return {"error": f"{self.provider_name} unavailable"}
        event = {
            "uid": f"{self.provider_name}-new",
            "title": title,
            "start": start_dt.isoformat(),
            "end": end_dt.isoformat(),
            "calendar": calendar_name or "Default",
            "provider": self.provider_name,
            "native_id": f"{self.provider_name}-new",
            "unified_uid": f"{self.provider_name}:{self.provider_name}-new",
        }
        self.created.append(event)
        return event

    def update_event(self, event_uid: str, calendar_name=None, **kwargs) -> dict:
        self.updated.append((event_uid, kwargs))
        return {
            "uid": event_uid,
            "title": kwargs.get("title", "Updated"),
            "start": kwargs.get("start_dt", datetime(2026, 1, 1)).isoformat(),
            "end": kwargs.get("end_dt", datetime(2026, 1, 1, 1, 0)).isoformat(),
            "calendar": calendar_name or "Default",
            "provider": self.provider_name,
            "native_id": event_uid,
            "unified_uid": f"{self.provider_name}:{event_uid}",
        }

    def delete_event(self, event_uid: str, calendar_name=None) -> dict:
        self.deleted.append(event_uid)
        return {"status": "deleted", "event_uid": event_uid}

    def search_events(self, query: str, start_dt: datetime, end_dt: datetime) -> list[dict]:
        if self.read_should_fail:
            return [{"error": f"{self.provider_name} read failed"}]
        return [e for e in self.events if query.lower() in str(e.get("title", "")).lower()]


def _service(tmp_path: Path, apple: _FakeProvider, m365: _FakeProvider) -> UnifiedCalendarService:
    router = ProviderRouter({
        "apple": apple,
        "microsoft_365": m365,
    })
    return UnifiedCalendarService(router=router, ownership_db_path=tmp_path / "calendar-routing.db")


def test_get_events_auto_merges_and_dedupes(tmp_path: Path):
    apple = _FakeProvider("apple")
    m365 = _FakeProvider("microsoft_365")
    m365.events = [{
        "uid": "shared-1",
        "title": "Team Standup",
        "start": "2026-02-16T09:00:00",
        "end": "2026-02-16T09:30:00",
        "calendar": "Work",
    }]
    apple.events = [
        {
            "uid": "apple-shared-1",
            "title": "Team Standup",
            "start": "2026-02-16T09:00:00",
            "end": "2026-02-16T09:30:00",
            "calendar": "Work",
        },
        {
            "uid": "apple-private-1",
            "title": "Family Dinner",
            "start": "2026-02-16T18:00:00",
            "end": "2026-02-16T19:00:00",
            "calendar": "Personal",
            "source_account": "iCloud",
        },
    ]
    service = _service(tmp_path, apple=apple, m365=m365)
    events = service.get_events(datetime(2026, 2, 16), datetime(2026, 2, 17))
    assert len(events) == 2
    standup = next(e for e in events if e["title"] == "Team Standup")
    assert standup["provider"] == "microsoft_365"


def test_create_event_work_fallbacks_to_apple(tmp_path: Path):
    apple = _FakeProvider("apple")
    m365 = _FakeProvider("microsoft_365")
    m365.create_should_fail = True
    service = _service(tmp_path, apple=apple, m365=m365)
    result = service.create_event(
        title="Launch Review",
        start_dt=datetime(2026, 2, 20, 10, 0),
        end_dt=datetime(2026, 2, 20, 11, 0),
        calendar_name="Work",
    )
    assert result["provider_used"] == "apple"
    assert result["fallback_used"] is True


def test_update_event_uses_prefixed_owner(tmp_path: Path):
    apple = _FakeProvider("apple")
    m365 = _FakeProvider("microsoft_365")
    service = _service(tmp_path, apple=apple, m365=m365)
    result = service.update_event(
        event_uid="apple:evt-1",
        calendar_name="Personal",
        title="Moved",
    )
    assert result["provider_used"] == "apple"
    assert apple.updated[0][0] == "evt-1"


def test_dual_read_policy_errors_when_one_provider_fails(tmp_path: Path):
    apple = _FakeProvider("apple")
    m365 = _FakeProvider("microsoft_365")
    m365.read_should_fail = True
    apple.events = [{
        "uid": "apple-1",
        "title": "Personal",
        "start": "2026-02-16T10:00:00",
        "end": "2026-02-16T11:00:00",
        "calendar": "Personal",
    }]
    service = _service(tmp_path, apple=apple, m365=m365)
    rows = service.get_events(datetime(2026, 2, 16), datetime(2026, 2, 17))
    assert len(rows) == 1
    assert "error" in rows[0]
    assert rows[0]["providers_required"] == ["microsoft_365", "apple"]
    assert "apple" in rows[0]["providers_succeeded"]
