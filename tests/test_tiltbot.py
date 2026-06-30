import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import asyncio

from areas.tiltbot import TiltBotArea, EVENT_LABELS, CANNED, CLAPBACKS
from areas.event_prompts import event_to_prompt
from system.gsi import TiltEvent


class FakeBrain:
    """Stands in for an AI area Tilt Bot borrows (Claude/ChatGPT/C.AI)."""

    def __init__(self, key='claude', ready=True, reply='get rekt', raises=False):
        self.key = key
        self._ready = ready
        self._reply = reply
        self._raises = raises
        self.received = []          # messages passed to generate()

    def is_ready(self):
        return (True, None) if self._ready else (False, 'Please set an API key!')

    async def generate(self, message, app):
        self.received.append(message)
        if self._raises:
            raise RuntimeError('boom')
        return self._reply


class FakeApp:
    def __init__(self, saved=None, brains=None):
        self._saved = saved or {}
        self._brains = {b.key: b for b in (brains or [])}
        self.areas = list(self._brains.values())

    def load_area_settings(self, key):
        return dict(self._saved)

    def save_area_settings(self, key, data):
        self._saved = dict(data)

    def area_by_key(self, key):
        return self._brains.get(key)


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


# --- AI-source delegation (clapback) -----------------------------------------

def test_clapback_ai_source_delegates_to_brain():
    brain = FakeBrain(key='claude', reply='cope harder')
    area = TiltBotArea()
    area.clapback_source = 'claude'
    out = asyncio.run(area.generate('ez noobs', FakeApp(brains=[brain])))
    assert out == 'cope harder'
    assert brain.received == ['ez noobs']


def test_clapback_ai_falls_back_to_canned_when_not_ready():
    brain = FakeBrain(key='claude', ready=False)
    area = TiltBotArea()
    area.clapback_source = 'claude'
    out = asyncio.run(area.generate('ez', FakeApp(brains=[brain])))
    assert out in CLAPBACKS
    assert brain.received == []  # not called when unready


def test_clapback_ai_falls_back_when_brain_returns_none():
    brain = FakeBrain(key='claude', reply=None)
    area = TiltBotArea()
    area.clapback_source = 'claude'
    out = asyncio.run(area.generate('ez', FakeApp(brains=[brain])))
    assert out in CLAPBACKS


def test_clapback_ai_falls_back_on_exception():
    brain = FakeBrain(key='claude', raises=True)
    area = TiltBotArea()
    area.clapback_source = 'claude'
    out = asyncio.run(area.generate('ez', FakeApp(brains=[brain])))
    assert out in CLAPBACKS


# --- AI-source delegation (events) -------------------------------------------

def test_event_ai_source_delegates_with_event_prompt():
    brain = FakeBrain(key='chatgpt', reply='4k diff')
    area = TiltBotArea()
    area.event_source = 'chatgpt'
    ev = TiltEvent('MULTI_KILL', {'kills': 4})
    out = asyncio.run(area.generate_event(ev, FakeApp(brains=[brain])))
    assert out == '4k diff'
    assert brain.received == [event_to_prompt(ev)]


def test_event_ai_falls_back_to_canned_line():
    brain = FakeBrain(key='chatgpt', ready=False)
    area = TiltBotArea()
    area.event_source = 'chatgpt'
    out = asyncio.run(area.generate_event(TiltEvent('MULTI_KILL', {'kills': 5}),
                                          FakeApp(brains=[brain])))
    assert isinstance(out, str) and '5' in out  # a formatted canned MULTI_KILL line


# --- readiness reflects selected AI sources ----------------------------------

def test_is_ready_blocks_when_selected_ai_source_unready():
    brain = FakeBrain(key='claude', ready=False)
    area = TiltBotArea()
    area.app = FakeApp(brains=[brain])
    area.clapback = True
    area.clapback_source = 'claude'
    ok, reason = area.is_ready()
    assert ok is False
    assert 'API key' in reason


def test_is_ready_ok_when_selected_ai_source_ready():
    brain = FakeBrain(key='claude', ready=True)
    area = TiltBotArea()
    area.app = FakeApp(brains=[brain])
    area.event_source = 'claude'
    assert area.is_ready() == (True, None)


def test_is_ready_ignores_ai_source_for_disabled_section():
    # Clapback OFF -> its claude source must not gate power-on.
    brain = FakeBrain(key='claude', ready=False)
    area = TiltBotArea()
    area.app = FakeApp(brains=[brain])
    area.clapback = False
    area.clapback_source = 'claude'
    assert area.is_ready() == (True, None)


# --- editable + fallback canned pools ----------------------------------------

def test_edited_event_lines_are_used():
    area = TiltBotArea()
    area.event_lines['MVP'] = ['custom mvp brag']
    out = asyncio.run(area.generate_event(TiltEvent('MVP'), FakeApp()))
    assert out == 'custom mvp brag'


def test_safe_format_survives_bad_token():
    area = TiltBotArea()
    area.event_lines['MULTI_KILL'] = ['{bogus} go brrr']
    out = asyncio.run(area.generate_event(TiltEvent('MULTI_KILL', {'kills': 3}),
                                          FakeApp()))
    assert out == '{bogus} go brrr'  # literal, no KeyError


def test_empty_event_pool_falls_back_to_default():
    area = TiltBotArea()
    area.event_lines['MVP'] = []
    out = asyncio.run(area.generate_event(TiltEvent('MVP'), FakeApp()))
    assert out in CANNED['MVP']


def test_empty_clapback_pool_falls_back_to_default():
    area = TiltBotArea()
    area.clapback_lines = []
    out = asyncio.run(area.generate('hi', FakeApp()))
    assert out in CLAPBACKS


# --- pure pool parse/restore helpers -----------------------------------------

def test_parse_lines_strips_blanks_and_whitespace():
    out = TiltBotArea._parse_lines('  a \n\n  b\n   \nc')
    assert out == ['a', 'b', 'c']


def test_restore_pool_uses_default_when_unset():
    assert TiltBotArea._restore_pool(None, ['x', 'y']) == ['x', 'y']


def test_restore_pool_uses_saved_when_present():
    assert TiltBotArea._restore_pool(['  a', 'b  '], ['x']) == ['a', 'b']


def test_restore_pool_empty_saved_reverts_to_default():
    assert TiltBotArea._restore_pool([], ['x', 'y']) == ['x', 'y']
