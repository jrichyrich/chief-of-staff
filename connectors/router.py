from __future__ import annotations

from dataclasses import dataclass

from connectors.provider_base import CalendarProvider


_PROVIDER_ALIASES = {
    "apple": "apple",
    "local": "apple",
    "local_jarvis": "apple",
    "microsoft_365": "microsoft_365",
    "microsoft365": "microsoft_365",
    "m365": "microsoft_365",
    "office365": "microsoft_365",
    "outlook": "microsoft_365",
}


def normalize_provider_name(value: str) -> str:
    return _PROVIDER_ALIASES.get((value or "").strip().lower(), "")


@dataclass
class RouteDecision:
    providers: list[str]
    preferred_provider: str
    fallback_provider: str
    reason: str


class ProviderRouter:
    """Policy router for read/write provider selection."""

    def __init__(self, providers: dict[str, CalendarProvider]):
        self.providers = providers

    def get_provider(self, provider_name: str) -> CalendarProvider | None:
        normalized = normalize_provider_name(provider_name)
        return self.providers.get(normalized)

    def is_connected(self, provider_name: str) -> bool:
        provider = self.get_provider(provider_name)
        return bool(provider and provider.is_connected())

    def connected_providers(self) -> list[str]:
        return [name for name, provider in self.providers.items() if provider.is_connected()]

    def decide_read(self, provider_preference: str = "auto") -> RouteDecision:
        pref = normalize_provider_name(provider_preference) or (provider_preference or "").strip().lower()
        has_apple = self.is_connected("apple")
        has_m365 = self.is_connected("microsoft_365")

        if pref == "both":
            if has_m365 and has_apple:
                return RouteDecision(["microsoft_365", "apple"], "microsoft_365", "apple", "explicit_both")
            if has_m365:
                return RouteDecision(["microsoft_365"], "microsoft_365", "", "both_requested_m365_only")
            if has_apple:
                return RouteDecision(["apple"], "apple", "", "both_requested_apple_only")
            return RouteDecision([], "", "", "no_provider_connected")

        if pref == "microsoft_365":
            if has_m365:
                fallback = "apple" if has_apple else ""
                providers = ["microsoft_365"] + (["apple"] if fallback else [])
                return RouteDecision(providers, "microsoft_365", fallback, "explicit_m365")
            if has_apple:
                return RouteDecision(["apple"], "apple", "", "m365_unavailable_fallback_apple")
            return RouteDecision([], "", "", "no_provider_connected")

        if pref == "apple":
            if has_apple:
                fallback = "microsoft_365" if has_m365 else ""
                providers = ["apple"] + (["microsoft_365"] if fallback else [])
                return RouteDecision(providers, "apple", fallback, "explicit_apple")
            if has_m365:
                return RouteDecision(["microsoft_365"], "microsoft_365", "", "apple_unavailable_fallback_m365")
            return RouteDecision([], "", "", "no_provider_connected")

        # Auto: include both when possible for full-picture reads.
        if has_m365 and has_apple:
            return RouteDecision(["microsoft_365", "apple"], "microsoft_365", "apple", "auto_both_connected")
        if has_apple:
            return RouteDecision(["apple"], "apple", "", "auto_apple_only")
        if has_m365:
            return RouteDecision(["microsoft_365"], "microsoft_365", "", "auto_m365_only")
        return RouteDecision([], "", "", "no_provider_connected")

    def decide_write(
        self,
        target_provider: str = "",
        calendar_name: str = "",
        provider_preference: str = "auto",
    ) -> RouteDecision:
        target = normalize_provider_name(target_provider)
        pref = normalize_provider_name(provider_preference)
        has_apple = self.is_connected("apple")
        has_m365 = self.is_connected("microsoft_365")

        if target:
            if self.is_connected(target):
                fallback = "apple" if target == "microsoft_365" and has_apple else ""
                if target == "apple" and has_m365:
                    fallback = "microsoft_365"
                providers = [target] + ([fallback] if fallback else [])
                return RouteDecision(providers, target, fallback, "explicit_target")
            fallback = "apple" if has_apple else ("microsoft_365" if has_m365 else "")
            providers = [fallback] if fallback else []
            reason = f"target_unavailable_fallback_{fallback}" if fallback else "no_provider_connected"
            return RouteDecision(providers, fallback, "", reason)

        if pref in {"apple", "microsoft_365"}:
            return self.decide_write(target_provider=pref, calendar_name=calendar_name, provider_preference=pref)

        if self._looks_work_calendar(calendar_name):
            if has_m365:
                providers = ["microsoft_365"] + (["apple"] if has_apple else [])
                fallback = "apple" if has_apple else ""
                return RouteDecision(providers, "microsoft_365", fallback, "work_calendar_routed_to_m365")
            if has_apple:
                return RouteDecision(["apple"], "apple", "", "work_calendar_m365_unavailable")
            return RouteDecision([], "", "", "no_provider_connected")

        # Default create/update/delete route: personal-first safety.
        if has_apple:
            providers = ["apple"] + (["microsoft_365"] if has_m365 else [])
            fallback = "microsoft_365" if has_m365 else ""
            return RouteDecision(providers, "apple", fallback, "default_personal_first")
        if has_m365:
            return RouteDecision(["microsoft_365"], "microsoft_365", "", "apple_unavailable_using_m365")
        return RouteDecision([], "", "", "no_provider_connected")

    @staticmethod
    def _looks_work_calendar(calendar_name: str) -> bool:
        name = (calendar_name or "").lower()
        if not name:
            return False
        keywords = ("work", "office", "outlook", "exchange", "corp", "company", "team")
        return any(kw in name for kw in keywords)
