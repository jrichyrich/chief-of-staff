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
        alarms=None,
        attendees=None,
        recurrence=None,
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
        if alarms is not None:
            event["alarms"] = alarms
        self.created.append(event)
        return event

    def update_event(self, event_uid: str, calendar_name=None, attendees=None, recurrence=None, **kwargs) -> dict:
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
        "showAs": "busy",
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
    # Cross-provider duplicate deduped: M365 version kept (richer metadata)
    assert len(events) == 2
    standups = [e for e in events if e["title"] == "Team Standup"]
    assert len(standups) == 1
    assert standups[0]["provider"] == "microsoft_365"


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


def test_create_event_passes_alarms_to_provider(tmp_path: Path):
    """Alarms parameter is threaded through to the provider's create_event."""
    apple = _FakeProvider("apple")
    m365 = _FakeProvider("microsoft_365")
    service = _service(tmp_path, apple=apple, m365=m365)
    result = service.create_event(
        title="Alert Meeting",
        start_dt=datetime(2026, 3, 1, 10, 0),
        end_dt=datetime(2026, 3, 1, 11, 0),
        calendar_name="Work",
        alarms=[15, 30],
    )
    assert "error" not in result
    assert result["title"] == "Alert Meeting"
    # Work calendar routes to m365 first
    assert len(m365.created) == 1
    assert m365.created[0].get("alarms") == [15, 30]


def test_create_event_no_alarms_by_default(tmp_path: Path):
    """When alarms not passed, provider doesn't get alarms key."""
    apple = _FakeProvider("apple")
    m365 = _FakeProvider("microsoft_365")
    service = _service(tmp_path, apple=apple, m365=m365)
    result = service.create_event(
        title="No Alarm",
        start_dt=datetime(2026, 3, 1, 10, 0),
        end_dt=datetime(2026, 3, 1, 11, 0),
        calendar_name="Work",
    )
    assert "error" not in result
    # Work calendar routes to m365 first
    assert len(m365.created) == 1
    assert "alarms" not in m365.created[0]


# ---------------------------------------------------------------------------
# require_all_success parameter tests
# ---------------------------------------------------------------------------


def test_get_events_require_all_success_false(tmp_path: Path):
    """With one provider failing, require_all_success=False returns the successful provider's events."""
    apple = _FakeProvider("apple")
    m365 = _FakeProvider("microsoft_365")
    m365.read_should_fail = True
    apple.events = [
        {
            "uid": "apple-1",
            "title": "Personal",
            "start": "2026-02-16T10:00:00",
            "end": "2026-02-16T11:00:00",
            "calendar": "Personal",
        },
    ]
    service = _service(tmp_path, apple=apple, m365=m365)
    rows = service.get_events(
        datetime(2026, 2, 16), datetime(2026, 2, 17),
        require_all_success=False,
    )
    # Should get Apple's event, not an error dict
    assert len(rows) >= 1
    assert rows[0].get("title") == "Personal"
    assert "error" not in rows[0]


def test_get_events_require_all_success_true(tmp_path: Path):
    """With one provider failing, require_all_success=True returns error dict."""
    apple = _FakeProvider("apple")
    m365 = _FakeProvider("microsoft_365")
    m365.read_should_fail = True
    apple.events = [
        {
            "uid": "apple-1",
            "title": "Personal",
            "start": "2026-02-16T10:00:00",
            "end": "2026-02-16T11:00:00",
            "calendar": "Personal",
        },
    ]
    service = _service(tmp_path, apple=apple, m365=m365)
    rows = service.get_events(
        datetime(2026, 2, 16), datetime(2026, 2, 17),
        require_all_success=True,
    )
    assert len(rows) == 1
    assert "error" in rows[0]
    assert rows[0]["providers_required"] == ["microsoft_365", "apple"]


def test_get_events_require_all_success_default_none(tmp_path: Path):
    """require_all_success=None uses the instance default (True)."""
    apple = _FakeProvider("apple")
    m365 = _FakeProvider("microsoft_365")
    m365.read_should_fail = True
    apple.events = [
        {
            "uid": "apple-1",
            "title": "Personal",
            "start": "2026-02-16T10:00:00",
            "end": "2026-02-16T11:00:00",
            "calendar": "Personal",
        },
    ]
    # Instance default is require_all_read_providers_success=True
    service = _service(tmp_path, apple=apple, m365=m365)
    rows = service.get_events(
        datetime(2026, 2, 16), datetime(2026, 2, 17),
        require_all_success=None,
    )
    # Should behave like require_all_success=True (instance default)
    assert len(rows) == 1
    assert "error" in rows[0]


# ---------------------------------------------------------------------------
# _event_dedupe_key provider-aware fallback tests
# ---------------------------------------------------------------------------


def test_dedupe_cross_provider_same_title_prefers_m365(tmp_path: Path):
    """Two events with same title/start/end from different providers ARE deduped; M365 wins."""
    apple = _FakeProvider("apple")
    m365 = _FakeProvider("microsoft_365")
    shared = {
        "title": "1:1",
        "start": "2026-03-10T10:00:00",
        "end": "2026-03-10T10:30:00",
        "calendar": "Work",
    }
    m365.events = [{"uid": "m365-1", "showAs": "busy", **shared}]
    apple.events = [{"uid": "apple-1", **shared}]
    service = _service(tmp_path, apple=apple, m365=m365)
    events = service.get_events(datetime(2026, 3, 10), datetime(2026, 3, 11))
    assert len(events) == 1
    assert events[0]["provider"] == "microsoft_365"


def test_dedupe_same_provider_same_title_deduped(tmp_path: Path):
    """Two events with same title/start/end AND same provider ARE deduped."""
    apple = _FakeProvider("apple")
    m365 = _FakeProvider("microsoft_365")
    m365.events = [
        {
            "uid": "m365-dup-1",
            "title": "1:1",
            "start": "2026-03-10T10:00:00",
            "end": "2026-03-10T10:30:00",
            "calendar": "Work",
        },
        {
            "uid": "m365-dup-2",
            "title": "1:1",
            "start": "2026-03-10T10:00:00",
            "end": "2026-03-10T10:30:00",
            "calendar": "Work",
        },
    ]
    apple.events = []
    service = _service(tmp_path, apple=apple, m365=m365)
    events = service.get_events(datetime(2026, 3, 10), datetime(2026, 3, 11))
    assert len(events) == 1
    assert events[0]["provider"] == "microsoft_365"


def test_dedupe_ical_uid_ignores_provider(tmp_path: Path):
    """Events with ical_uid dedup correctly regardless of provider."""
    apple = _FakeProvider("apple")
    m365 = _FakeProvider("microsoft_365")
    m365.events = [{
        "uid": "m365-1",
        "ical_uid": "SHARED-ICAL-UID-123",
        "title": "Sync Meeting",
        "start": "2026-03-10T14:00:00",
        "end": "2026-03-10T15:00:00",
        "calendar": "Work",
    }]
    apple.events = [{
        "uid": "apple-1",
        "ical_uid": "shared-ical-uid-123",
        "title": "Sync Meeting",
        "start": "2026-03-10T14:00:00",
        "end": "2026-03-10T15:00:00",
        "calendar": "Work",
    }]
    service = _service(tmp_path, apple=apple, m365=m365)
    events = service.get_events(datetime(2026, 3, 10), datetime(2026, 3, 11))
    # ical_uid match (case-insensitive) → deduped to 1, M365 preferred
    assert len(events) == 1
    assert events[0]["provider"] == "microsoft_365"


# ---------------------------------------------------------------------------
# M365-preferred dedup tests
# ---------------------------------------------------------------------------


def test_dedupe_ical_uid_prefers_m365_over_apple(tmp_path: Path):
    """When ical_uid matches, the M365 version is kept (richer metadata)."""
    apple = _FakeProvider("apple")
    m365 = _FakeProvider("microsoft_365")
    # Apple event is seen first (providers iterate m365 first, but let's test
    # the case where Apple is first by feeding only via the dedup method).
    service = _service(tmp_path, apple=apple, m365=m365)
    rows = [
        {
            "uid": "apple-1",
            "ical_uid": "SHARED-UID",
            "title": "Review",
            "start": "2026-03-10T10:00:00",
            "end": "2026-03-10T11:00:00",
            "provider": "apple",
        },
        {
            "uid": "m365-1",
            "ical_uid": "shared-uid",
            "title": "Review",
            "start": "2026-03-10T10:00:00",
            "end": "2026-03-10T11:00:00",
            "provider": "microsoft_365",
            "showAs": "busy",
            "isCancelled": False,
        },
    ]
    deduped = service._dedupe_events(rows)
    assert len(deduped) == 1
    assert deduped[0]["provider"] == "microsoft_365"
    assert deduped[0].get("showAs") == "busy"


def test_dedupe_fallback_prefers_m365_over_apple(tmp_path: Path):
    """Fallback key (title+start+end) cross-provider dedup prefers M365."""
    apple = _FakeProvider("apple")
    m365 = _FakeProvider("microsoft_365")
    service = _service(tmp_path, apple=apple, m365=m365)
    rows = [
        {
            "uid": "apple-1",
            "title": "Standup",
            "start": "2026-03-10T09:00:00",
            "end": "2026-03-10T09:30:00",
            "provider": "apple",
        },
        {
            "uid": "m365-1",
            "title": "Standup",
            "start": "2026-03-10T09:00:00",
            "end": "2026-03-10T09:30:00",
            "provider": "microsoft_365",
            "showAs": "tentative",
            "responseStatus": "tentativelyAccepted",
        },
    ]
    deduped = service._dedupe_events(rows)
    assert len(deduped) == 1
    assert deduped[0]["provider"] == "microsoft_365"
    assert deduped[0].get("responseStatus") == "tentativelyAccepted"


def test_dedupe_unique_events_both_preserved(tmp_path: Path):
    """Events unique to each provider are both kept."""
    apple = _FakeProvider("apple")
    m365 = _FakeProvider("microsoft_365")
    service = _service(tmp_path, apple=apple, m365=m365)
    rows = [
        {
            "uid": "m365-1",
            "title": "Board Meeting",
            "start": "2026-03-10T10:00:00",
            "end": "2026-03-10T11:00:00",
            "provider": "microsoft_365",
        },
        {
            "uid": "apple-1",
            "title": "Dentist",
            "start": "2026-03-10T14:00:00",
            "end": "2026-03-10T15:00:00",
            "provider": "apple",
        },
    ]
    deduped = service._dedupe_events(rows)
    assert len(deduped) == 2
    titles = {e["title"] for e in deduped}
    assert titles == {"Board Meeting", "Dentist"}


def test_dedupe_m365_first_still_kept(tmp_path: Path):
    """When M365 is seen first (normal provider order), it is still kept."""
    apple = _FakeProvider("apple")
    m365 = _FakeProvider("microsoft_365")
    service = _service(tmp_path, apple=apple, m365=m365)
    rows = [
        {
            "uid": "m365-1",
            "title": "Sprint Planning",
            "start": "2026-03-10T10:00:00",
            "end": "2026-03-10T11:00:00",
            "provider": "microsoft_365",
            "showAs": "busy",
        },
        {
            "uid": "apple-1",
            "title": "Sprint Planning",
            "start": "2026-03-10T10:00:00",
            "end": "2026-03-10T11:00:00",
            "provider": "apple",
        },
    ]
    deduped = service._dedupe_events(rows)
    assert len(deduped) == 1
    assert deduped[0]["provider"] == "microsoft_365"


def test_dedupe_single_provider_unchanged(tmp_path: Path):
    """Single-provider queries still work — no regression."""
    apple = _FakeProvider("apple")
    m365 = _FakeProvider("microsoft_365")
    service = _service(tmp_path, apple=apple, m365=m365)
    rows = [
        {
            "uid": "apple-1",
            "title": "Lunch",
            "start": "2026-03-10T12:00:00",
            "end": "2026-03-10T13:00:00",
            "provider": "apple",
        },
        {
            "uid": "apple-2",
            "title": "Gym",
            "start": "2026-03-10T17:00:00",
            "end": "2026-03-10T18:00:00",
            "provider": "apple",
        },
    ]
    deduped = service._dedupe_events(rows)
    assert len(deduped) == 2


# ---------------------------------------------------------------------------
# get_events_with_routing tests
# ---------------------------------------------------------------------------


def test_get_events_with_routing_returns_metadata(tmp_path: Path):
    """get_events_with_routing returns events and routing metadata."""
    apple = _FakeProvider("apple")
    m365 = _FakeProvider("microsoft_365")
    m365.events = [{
        "uid": "m365-1",
        "title": "Work Meeting",
        "start": "2026-03-10T10:00:00",
        "end": "2026-03-10T11:00:00",
        "calendar": "Work",
    }]
    apple.events = [{
        "uid": "apple-1",
        "title": "Personal",
        "start": "2026-03-10T12:00:00",
        "end": "2026-03-10T13:00:00",
        "calendar": "Personal",
    }]
    service = _service(tmp_path, apple=apple, m365=m365)
    events, routing = service.get_events_with_routing(
        datetime(2026, 3, 10), datetime(2026, 3, 11),
        provider_preference="both",
    )
    assert len(events) == 2
    assert "microsoft_365" in routing["providers_requested"]
    assert "apple" in routing["providers_requested"]
    assert "microsoft_365" in routing["providers_succeeded"]
    assert "apple" in routing["providers_succeeded"]
    assert routing["is_fallback"] is False
    assert routing["provider_preference"] == "both"


def test_get_events_with_routing_detects_fallback(tmp_path: Path):
    """When M365 is disconnected, routing metadata shows fallback."""
    apple = _FakeProvider("apple")
    m365 = _FakeProvider("microsoft_365", connected=False)
    apple.events = [{
        "uid": "apple-1",
        "title": "Personal",
        "start": "2026-03-10T12:00:00",
        "end": "2026-03-10T13:00:00",
        "calendar": "Personal",
    }]
    service = _service(tmp_path, apple=apple, m365=m365)
    events, routing = service.get_events_with_routing(
        datetime(2026, 3, 10), datetime(2026, 3, 11),
        provider_preference="microsoft_365",
    )
    assert len(events) == 1
    assert events[0]["provider"] == "apple"
    assert routing["is_fallback"] is True
    assert "fallback" in routing["routing_reason"]
    assert routing["providers_requested"] == ["apple"]
    assert routing["providers_succeeded"] == ["apple"]
    assert routing["provider_preference"] == "microsoft_365"


def test_get_events_with_routing_m365_only(tmp_path: Path):
    """When M365 is connected and requested, no fallback."""
    apple = _FakeProvider("apple")
    m365 = _FakeProvider("microsoft_365")
    m365.events = [{
        "uid": "m365-1",
        "title": "Work Meeting",
        "start": "2026-03-10T10:00:00",
        "end": "2026-03-10T11:00:00",
        "calendar": "Work",
    }]
    service = _service(tmp_path, apple=apple, m365=m365)
    events, routing = service.get_events_with_routing(
        datetime(2026, 3, 10), datetime(2026, 3, 11),
        provider_preference="microsoft_365",
    )
    assert len(events) >= 1
    assert routing["is_fallback"] is False
    assert "microsoft_365" in routing["providers_requested"]
    assert "microsoft_365" in routing["providers_succeeded"]


def test_get_events_with_routing_both_m365_disconnected(tmp_path: Path):
    """When both requested but M365 disconnected, only Apple data returned with fallback flag."""
    apple = _FakeProvider("apple")
    m365 = _FakeProvider("microsoft_365", connected=False)
    apple.events = [{
        "uid": "apple-1",
        "title": "Personal",
        "start": "2026-03-10T12:00:00",
        "end": "2026-03-10T13:00:00",
        "calendar": "Personal",
    }]
    service = _service(tmp_path, apple=apple, m365=m365)
    events, routing = service.get_events_with_routing(
        datetime(2026, 3, 10), datetime(2026, 3, 11),
        provider_preference="both",
    )
    assert len(events) == 1
    assert events[0]["provider"] == "apple"
    assert routing["providers_succeeded"] == ["apple"]
    assert "microsoft_365" not in routing["providers_succeeded"]
