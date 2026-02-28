from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Optional

from connectors.router import ProviderRouter, normalize_provider_name


class UnifiedCalendarService:
    """Unified calendar facade across multiple providers."""

    def __init__(
        self,
        router: ProviderRouter,
        ownership_db_path: Path,
        require_all_read_providers_success: bool = True,
    ):
        self.router = router
        self.ownership_db_path = Path(ownership_db_path)
        self.require_all_read_providers_success = bool(require_all_read_providers_success)
        self.ownership_db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_ownership_db()

    def _open_ownership_db(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.ownership_db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    @staticmethod
    def _utc_now_iso() -> str:
        return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    def _init_ownership_db(self) -> None:
        with self._open_ownership_db() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS event_ownership (
                    unified_uid TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    native_id TEXT NOT NULL,
                    calendar_name TEXT,
                    updated_at_utc TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_event_ownership_native
                    ON event_ownership(native_id, updated_at_utc DESC);
                """
            )
            conn.commit()

    def _upsert_ownership(self, event: dict) -> None:
        unified_uid = str(event.get("unified_uid", "")).strip()
        provider = normalize_provider_name(str(event.get("provider", "")))
        native_id = str(event.get("native_id", "")).strip()
        calendar_name = str(event.get("calendar", "") or event.get("calendar_id", "")).strip()
        if not unified_uid or not provider or not native_id:
            return
        with self._open_ownership_db() as conn:
            conn.execute(
                """
                INSERT INTO event_ownership(unified_uid, provider, native_id, calendar_name, updated_at_utc)
                VALUES(?, ?, ?, ?, ?)
                ON CONFLICT(unified_uid) DO UPDATE SET
                    provider=excluded.provider,
                    native_id=excluded.native_id,
                    calendar_name=excluded.calendar_name,
                    updated_at_utc=excluded.updated_at_utc
                """,
                (unified_uid, provider, native_id, calendar_name, self._utc_now_iso()),
            )
            conn.commit()

    def _delete_ownership(self, unified_uid: str) -> None:
        if not unified_uid:
            return
        with self._open_ownership_db() as conn:
            conn.execute("DELETE FROM event_ownership WHERE unified_uid = ?", (unified_uid,))
            conn.commit()

    def _lookup_ownership(self, event_uid: str) -> tuple[str, str] | None:
        event_uid = (event_uid or "").strip()
        if not event_uid:
            return None
        with self._open_ownership_db() as conn:
            row = conn.execute(
                "SELECT provider, native_id FROM event_ownership WHERE unified_uid = ?",
                (event_uid,),
            ).fetchone()
            if row:
                return str(row["provider"]), str(row["native_id"])

            row = conn.execute(
                """
                SELECT provider, native_id
                FROM event_ownership
                WHERE native_id = ?
                ORDER BY updated_at_utc DESC
                LIMIT 1
                """,
                (event_uid,),
            ).fetchone()
            if row:
                return str(row["provider"]), str(row["native_id"])
        return None

    def _tag_event(self, event: dict, provider_name: str) -> dict:
        tagged = dict(event)
        provider = normalize_provider_name(provider_name) or provider_name
        native_id = str(tagged.get("native_id", "") or tagged.get("uid", "")).strip()
        if native_id:
            tagged["native_id"] = native_id
        tagged["provider"] = provider
        if not tagged.get("calendar_id"):
            tagged["calendar_id"] = str(tagged.get("calendar", "") or "")
        if not tagged.get("source_account"):
            tagged["source_account"] = str(tagged.get("source", "") or "")
        if not tagged.get("unified_uid"):
            tagged["unified_uid"] = f"{provider}:{native_id}" if native_id else ""
        return tagged

    @staticmethod
    def _is_error_payload(payload: object) -> bool:
        if isinstance(payload, dict):
            return bool(payload.get("error"))
        if isinstance(payload, list) and payload and isinstance(payload[0], dict):
            return bool(payload[0].get("error"))
        return False

    @staticmethod
    def _build_dual_read_error(required: list[str], succeeded: list[str], rows: list[dict], errors: list[dict]) -> dict:
        failed = [p for p in required if p not in succeeded]
        return {
            "error": "Dual-read policy requires all connected providers to succeed",
            "providers_required": required,
            "providers_succeeded": succeeded,
            "providers_failed": failed,
            "partial_results": rows,
            "provider_errors": errors,
        }

    def _filter_source(self, rows: list[dict], source_filter: str) -> list[dict]:
        needle = (source_filter or "").strip().lower()
        if not needle:
            return rows
        filtered: list[dict] = []
        for row in rows:
            haystack = " ".join(
                [
                    str(row.get("provider", "") or ""),
                    str(row.get("source_account", "") or ""),
                    str(row.get("calendar", "") or ""),
                    str(row.get("calendar_id", "") or ""),
                ]
            ).lower()
            if needle in haystack:
                filtered.append(row)
        return filtered

    @staticmethod
    def _event_dedupe_key(event: dict) -> tuple:
        ical_uid = str(event.get("ical_uid", "")).strip()
        if ical_uid:
            return ("ical_uid", ical_uid.lower())
        title = str(event.get("title", "")).strip().lower()
        start = str(event.get("start", "")).strip()
        end = str(event.get("end", "")).strip()
        return ("fallback", title, start, end)

    def _dedupe_events(self, rows: list[dict]) -> list[dict]:
        seen: dict[tuple, dict] = {}
        for row in rows:
            key = self._event_dedupe_key(row)
            if key in seen:
                continue
            seen[key] = row
        deduped = list(seen.values())
        deduped.sort(key=lambda r: str(r.get("start", "")))
        return deduped

    @staticmethod
    def _provider_from_prefixed_uid(event_uid: str) -> tuple[str, str] | None:
        uid = (event_uid or "").strip()
        if ":" not in uid:
            return None
        provider_token, native_id = uid.split(":", 1)
        provider = normalize_provider_name(provider_token)
        if not provider or not native_id:
            return None
        return provider, native_id

    def list_calendars(
        self,
        provider_preference: str = "auto",
        source_filter: str = "",
    ) -> list[dict]:
        decision = self.router.decide_read(provider_preference=provider_preference)
        if not decision.providers:
            return [{"error": "No connected calendar providers available"}]

        rows: list[dict] = []
        errors: list[dict] = []
        succeeded: set[str] = set()
        for provider_name in decision.providers:
            provider = self.router.get_provider(provider_name)
            if provider is None:
                continue
            payload = provider.list_calendars()
            if self._is_error_payload(payload):
                errors.extend(payload if isinstance(payload, list) else [payload])
                continue
            succeeded.add(provider_name)
            rows.extend(payload if isinstance(payload, list) else [payload])

        rows = self._filter_source(rows, source_filter=source_filter)
        if (
            self.require_all_read_providers_success
            and len(decision.providers) > 1
            and len(succeeded) < len(decision.providers)
        ):
            return [self._build_dual_read_error(decision.providers, sorted(succeeded), rows, errors)]
        if rows:
            return rows
        if errors:
            return errors
        return []

    def get_events(
        self,
        start_dt: datetime,
        end_dt: datetime,
        calendar_names: Optional[list[str]] = None,
        provider_preference: str = "auto",
        source_filter: str = "",
    ) -> list[dict]:
        decision = self.router.decide_read(provider_preference=provider_preference)
        if not decision.providers:
            return [{"error": "No connected calendar providers available"}]

        rows: list[dict] = []
        errors: list[dict] = []
        succeeded: set[str] = set()
        for provider_name in decision.providers:
            provider = self.router.get_provider(provider_name)
            if provider is None:
                continue
            payload = provider.get_events(start_dt, end_dt, calendar_names=calendar_names)
            if self._is_error_payload(payload):
                errors.extend(payload if isinstance(payload, list) else [payload])
                continue
            succeeded.add(provider_name)
            provider_rows = payload if isinstance(payload, list) else [payload]
            for row in provider_rows:
                tagged = self._tag_event(row, provider_name)
                rows.append(tagged)

        rows = self._dedupe_events(rows)
        rows = self._filter_source(rows, source_filter=source_filter)
        if (
            self.require_all_read_providers_success
            and len(decision.providers) > 1
            and len(succeeded) < len(decision.providers)
        ):
            return [self._build_dual_read_error(decision.providers, sorted(succeeded), rows, errors)]
        for row in rows:
            self._upsert_ownership(row)
        if rows:
            return rows
        if errors:
            return errors
        return []

    def search_events(
        self,
        query: str,
        start_dt: datetime,
        end_dt: datetime,
        provider_preference: str = "auto",
        source_filter: str = "",
    ) -> list[dict]:
        decision = self.router.decide_read(provider_preference=provider_preference)
        if not decision.providers:
            return [{"error": "No connected calendar providers available"}]

        rows: list[dict] = []
        errors: list[dict] = []
        succeeded: set[str] = set()
        for provider_name in decision.providers:
            provider = self.router.get_provider(provider_name)
            if provider is None:
                continue
            payload = provider.search_events(query, start_dt, end_dt)
            if self._is_error_payload(payload):
                errors.extend(payload if isinstance(payload, list) else [payload])
                continue
            succeeded.add(provider_name)
            provider_rows = payload if isinstance(payload, list) else [payload]
            for row in provider_rows:
                tagged = self._tag_event(row, provider_name)
                rows.append(tagged)

        rows = self._dedupe_events(rows)
        rows = self._filter_source(rows, source_filter=source_filter)
        if (
            self.require_all_read_providers_success
            and len(decision.providers) > 1
            and len(succeeded) < len(decision.providers)
        ):
            return [self._build_dual_read_error(decision.providers, sorted(succeeded), rows, errors)]
        for row in rows:
            self._upsert_ownership(row)
        if rows:
            return rows
        if errors:
            return errors
        return []

    def _resolve_write_provider(
        self,
        event_uid: str = "",
        target_provider: str = "",
        calendar_name: str = "",
        provider_preference: str = "auto",
    ) -> tuple[list[str], str, str, str]:
        if target_provider:
            decision = self.router.decide_write(
                target_provider=target_provider,
                calendar_name=calendar_name,
                provider_preference=provider_preference,
            )
            native_id = event_uid
            parsed = self._provider_from_prefixed_uid(event_uid)
            if parsed:
                _, native_id = parsed
            return decision.providers, decision.preferred_provider, decision.fallback_provider, native_id

        parsed = self._provider_from_prefixed_uid(event_uid)
        if parsed:
            provider, native_id = parsed
            decision = self.router.decide_write(
                target_provider=provider,
                calendar_name=calendar_name,
                provider_preference=provider_preference,
            )
            return decision.providers, decision.preferred_provider, decision.fallback_provider, native_id

        ownership = self._lookup_ownership(event_uid)
        if ownership:
            provider, native_id = ownership
            decision = self.router.decide_write(
                target_provider=provider,
                calendar_name=calendar_name,
                provider_preference=provider_preference,
            )
            return decision.providers, decision.preferred_provider, decision.fallback_provider, native_id

        decision = self.router.decide_write(
            target_provider="",
            calendar_name=calendar_name,
            provider_preference=provider_preference,
        )
        return decision.providers, decision.preferred_provider, decision.fallback_provider, event_uid

    def create_event(
        self,
        title: str,
        start_dt: datetime,
        end_dt: datetime,
        calendar_name: Optional[str] = None,
        location: Optional[str] = None,
        notes: Optional[str] = None,
        is_all_day: bool = False,
        target_provider: str = "",
        provider_preference: str = "auto",
    ) -> dict:
        providers, preferred, _, _ = self._resolve_write_provider(
            target_provider=target_provider,
            calendar_name=calendar_name or "",
            provider_preference=provider_preference,
        )
        if not providers:
            return {"error": "No connected calendar providers available for write"}

        errors: list[str] = []
        for provider_name in providers:
            provider = self.router.get_provider(provider_name)
            if provider is None:
                continue
            result = provider.create_event(
                title=title,
                start_dt=start_dt,
                end_dt=end_dt,
                calendar_name=calendar_name,
                location=location,
                notes=notes,
                is_all_day=is_all_day,
            )
            if result.get("error"):
                errors.append(f"{provider_name}: {result['error']}")
                continue
            tagged = self._tag_event(result, provider_name)
            self._upsert_ownership(tagged)
            tagged["provider_used"] = provider_name
            tagged["fallback_used"] = provider_name != preferred
            return tagged
        return {"error": "; ".join(errors) if errors else "Failed to create event"}

    def update_event(
        self,
        event_uid: str,
        calendar_name: Optional[str] = None,
        target_provider: str = "",
        provider_preference: str = "auto",
        **kwargs,
    ) -> dict:
        providers, preferred, _, native_id = self._resolve_write_provider(
            event_uid=event_uid,
            target_provider=target_provider,
            calendar_name=calendar_name or "",
            provider_preference=provider_preference,
        )
        if not providers:
            return {"error": "No connected calendar providers available for write"}
        native_id = native_id or event_uid

        errors: list[str] = []
        for provider_name in providers:
            provider = self.router.get_provider(provider_name)
            if provider is None:
                continue
            result = provider.update_event(native_id, calendar_name=calendar_name, **kwargs)
            if result.get("error"):
                errors.append(f"{provider_name}: {result['error']}")
                continue
            tagged = self._tag_event(result, provider_name)
            self._upsert_ownership(tagged)
            tagged["provider_used"] = provider_name
            tagged["fallback_used"] = provider_name != preferred
            return tagged
        return {"error": "; ".join(errors) if errors else "Failed to update event"}

    def delete_event(
        self,
        event_uid: str,
        calendar_name: Optional[str] = None,
        target_provider: str = "",
        provider_preference: str = "auto",
    ) -> dict:
        providers, preferred, _, native_id = self._resolve_write_provider(
            event_uid=event_uid,
            target_provider=target_provider,
            calendar_name=calendar_name or "",
            provider_preference=provider_preference,
        )
        if not providers:
            return {"error": "No connected calendar providers available for write"}
        native_id = native_id or event_uid

        errors: list[str] = []
        for provider_name in providers:
            provider = self.router.get_provider(provider_name)
            if provider is None:
                continue
            result = provider.delete_event(native_id, calendar_name=calendar_name)
            if result.get("error"):
                errors.append(f"{provider_name}: {result['error']}")
                continue
            tagged = dict(result)
            tagged["provider_used"] = provider_name
            tagged["fallback_used"] = provider_name != preferred
            tagged["provider"] = provider_name
            tagged["native_id"] = native_id
            tagged["unified_uid"] = f"{provider_name}:{native_id}"
            self._delete_ownership(tagged["unified_uid"])
            return tagged
        return {"error": "; ".join(errors) if errors else "Failed to delete event"}
