"""Tests for setup_jarvis.py — step framework."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import pytest
from setup_jarvis import Status, SetupStep, StepRunner


class TestStatus:
    def test_status_values(self):
        assert Status.OK.value == "ok"
        assert Status.MISSING.value == "missing"
        assert Status.ERROR.value == "error"

    def test_status_label(self):
        assert Status.OK.label == "[ok]"
        assert Status.MISSING.label == "[--]"
        assert Status.ERROR.label == "[!!]"


class TestSetupStep:
    def test_abstract_methods_exist(self):
        with pytest.raises(TypeError):
            SetupStep(name="test", key="test", profiles={"minimal"})

    def test_applies_to_profile(self):
        class DummyStep(SetupStep):
            def check(self): return Status.OK
        step = DummyStep(name="test", key="test", profiles={"minimal", "personal"})
        assert step.applies_to("minimal")
        assert step.applies_to("personal")
        assert not step.applies_to("full")

    def test_is_auto_default_false(self):
        class DummyStep(SetupStep):
            def check(self): return Status.OK
        step = DummyStep(name="test", key="test", profiles={"minimal"})
        assert step.is_auto is False

    def test_is_manual_default_false(self):
        class DummyStep(SetupStep):
            def check(self): return Status.OK
        step = DummyStep(name="test", key="test", profiles={"minimal"})
        assert step.is_manual is False


class TestStepRunner:
    def test_scan_filters_by_profile(self):
        class OkStep(SetupStep):
            def check(self): return Status.OK
        class MissingStep(SetupStep):
            def check(self): return Status.MISSING
        steps = [
            OkStep(name="A", key="a", profiles={"minimal", "full"}),
            MissingStep(name="B", key="b", profiles={"full"}),
        ]
        runner = StepRunner(steps=steps, profile="minimal", interactive=False)
        results = runner.scan()
        assert len(results) == 1
        assert results[0][0].key == "a"
        assert results[0][1] == Status.OK

    def test_scan_returns_all_for_full_profile(self):
        class OkStep(SetupStep):
            def check(self): return Status.OK
        steps = [
            OkStep(name="A", key="a", profiles={"minimal", "full"}),
            OkStep(name="B", key="b", profiles={"full"}),
        ]
        runner = StepRunner(steps=steps, profile="full", interactive=False)
        results = runner.scan()
        assert len(results) == 2
