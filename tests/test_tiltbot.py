import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import asyncio

from areas.tiltbot import TiltBotArea, EVENT_LABELS
from system.gsi import TiltEvent


class FakeApp:
    def __init__(self, saved=None):
        self._saved = saved or {}

    def load_area_settings(self, key):
        return dict(self._saved)

    def save_area_settings(self, key, data):
        self._saved = dict(data)


def test_any_event_enabled_reflects_toggles():
    area = TiltBotArea()
    assert area._any_event_enabled() is True          # all on by default
    area.enabled = {k: False for k in EVENT_LABELS}
    assert area._any_event_enabled() is False
    area.enabled['MVP'] = True
    assert area._any_event_enabled() is True


def test_consumes_events_flag():
    assert TiltBotArea.consumes_events is True


def test_generate_event_returns_line_for_enabled_kind():
    area = TiltBotArea()
    line = asyncio.run(area.generate_event(TiltEvent('MULTI_KILL', {'kills': 5}), FakeApp()))
    assert isinstance(line, str) and line
    assert '5' in line  # the kill count is formatted in


def test_generate_event_silent_for_disabled_kind():
    area = TiltBotArea()
    area.enabled = {'MVP': False}
    line = asyncio.run(area.generate_event(TiltEvent('MVP'), FakeApp()))
    assert line is None


def test_generate_event_unknown_kind_is_silent():
    area = TiltBotArea()
    assert asyncio.run(area.generate_event(TiltEvent('NOPE'), FakeApp())) is None


def test_clapback_toggle_controls_chat_reply():
    area = TiltBotArea()
    area.clapback = True
    assert asyncio.run(area.generate('ez noobs', FakeApp()))
    area.clapback = False
    assert asyncio.run(area.generate('ez noobs', FakeApp())) is None


def test_is_ready_needs_no_api_key():
    ok, _ = TiltBotArea().is_ready()
    assert ok is True
