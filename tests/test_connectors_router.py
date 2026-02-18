from connectors.router import ProviderRouter


class _StubProvider:
    def __init__(self, connected: bool):
        self._connected = connected

    def is_connected(self) -> bool:
        return self._connected


def test_decide_read_auto_uses_both_when_available():
    router = ProviderRouter({
        "apple": _StubProvider(True),
        "microsoft_365": _StubProvider(True),
    })
    decision = router.decide_read("auto")
    assert decision.providers == ["microsoft_365", "apple"]
    assert decision.preferred_provider == "microsoft_365"


def test_decide_read_m365_falls_back_to_apple():
    router = ProviderRouter({
        "apple": _StubProvider(True),
        "microsoft_365": _StubProvider(False),
    })
    decision = router.decide_read("microsoft_365")
    assert decision.providers == ["apple"]
    assert "fallback" in decision.reason


def test_decide_write_work_calendar_prefers_m365():
    router = ProviderRouter({
        "apple": _StubProvider(True),
        "microsoft_365": _StubProvider(True),
    })
    decision = router.decide_write(calendar_name="Work")
    assert decision.preferred_provider == "microsoft_365"
    assert decision.providers[0] == "microsoft_365"


def test_decide_write_default_prefers_apple():
    router = ProviderRouter({
        "apple": _StubProvider(True),
        "microsoft_365": _StubProvider(True),
    })
    decision = router.decide_write(calendar_name="Personal")
    assert decision.preferred_provider == "apple"
    assert decision.providers[0] == "apple"
