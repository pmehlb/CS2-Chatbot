"""Tests for the Claude area: message assembly, history rolling, readiness and
the per-model temperature/effort tuning matrix.

Run with:  venv\\Scripts\\python -m pytest tests/test_claude.py
(or plain `python tests/test_claude.py` to run them without pytest).

No live API calls: a fake AsyncAnthropic client whose ``messages.create``
returns a canned response is injected, so ``generate()`` is exercised as pure
logic.
"""
import asyncio
import os
import sys

# Make the application package layout (src/) importable when run from anywhere.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import areas.claude as claude
from areas.claude import ClaudeArea, MAX_HISTORY_MESSAGES


def run(coro):
    return asyncio.run(coro)


class _TextBlock:
    def __init__(self, text):
        self.type = 'text'
        self.text = text


class FakeMessages:
    """Records the create() kwargs and returns a canned (paddable) reply."""

    def __init__(self, reply='  hello there  '):
        self.reply = reply
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return type('Response', (), {'content': [_TextBlock(self.reply)]})()


class FakeClient:
    def __init__(self, messages):
        self.messages = messages


def make_area(reply='  hello there  '):
    area = ClaudeArea()
    area.api_key = 'sk-ant-test'
    area.messages = FakeMessages(reply)
    area.client = FakeClient(area.messages)
    # Capture notifications instead of hitting the live NiceGUI slot stack.
    area.notifications = []
    claude.notify_and_log = lambda message, **kwargs: area.notifications.append((message, kwargs))
    return area


def test_generate_builds_system_history_user():
    area = make_area()
    area.system_prompt = 'be a bot'
    area.history = [{'role': 'user', 'content': 'earlier'},
                    {'role': 'assistant', 'content': 'reply'}]

    run(area.generate('hi', app=None))

    call = area.messages.calls[0]
    # Anthropic takes the system prompt as a top-level param, not a message.
    assert call['system'] == 'be a bot'
    assert call['messages'][0] == {'role': 'user', 'content': 'earlier'}
    assert call['messages'][1] == {'role': 'assistant', 'content': 'reply'}
    assert call['messages'][-1] == {'role': 'user', 'content': 'hi'}


def test_generate_returns_stripped_reply():
    area = make_area(reply='  pong  ')
    assert run(area.generate('ping', app=None)) == 'pong'


def test_history_grows_and_trims_to_max():
    area = make_area(reply='ok')
    for i in range(MAX_HISTORY_MESSAGES):  # each call adds 2 messages -> overflow
        run(area.generate(f'msg {i}', app=None))

    assert len(area.history) == MAX_HISTORY_MESSAGES
    assert area.history[-1] == {'role': 'assistant', 'content': 'ok'}
    assert area.history[-2]['content'] == f'msg {MAX_HISTORY_MESSAGES - 1}'


def test_is_ready_requires_api_key():
    area = ClaudeArea()
    ok, reason = area.is_ready()
    assert ok is False and 'API key' in reason

    area.api_key = 'sk-ant-test'
    assert area.is_ready() == (True, None)


def test_generate_without_client_notifies_and_returns_none():
    area = make_area()
    area.client = None
    assert run(area.generate('hi', app=None)) is None
    assert area.notifications, 'expected a notification when client is missing'


def test_clear_history_empties_history():
    area = make_area()
    area.history = [{'role': 'user', 'content': 'x'}]
    area._clear_history()
    assert area.history == []


def test_set_api_key_builds_and_drops_client():
    area = ClaudeArea()
    run(area.set_api_key('sk-ant-test'))
    assert area.api_key == 'sk-ant-test'
    assert area.client is not None

    run(area.set_api_key(''))
    assert area.api_key == ''
    assert area.client is None


# --- tuning matrix: only send params the chosen model accepts -----------------

def test_opus_sends_effort_not_temperature():
    area = ClaudeArea()
    area.model = 'claude-opus-4-8'
    area.temperature = 0.5
    area.effort = 'xhigh'
    kwargs = area._tuning_kwargs()
    assert kwargs == {'output_config': {'effort': 'xhigh'}}  # temperature would 400


def test_haiku_sends_temperature_not_effort():
    area = ClaudeArea()
    area.model = 'claude-haiku-4-5'
    area.temperature = 0.3
    area.effort = 'low'
    kwargs = area._tuning_kwargs()
    assert kwargs == {'temperature': 0.3}  # effort errors on Haiku


def test_sonnet_sends_both():
    area = ClaudeArea()
    area.model = 'claude-sonnet-4-6'
    area.temperature = 0.7
    area.effort = 'high'
    kwargs = area._tuning_kwargs()
    assert kwargs == {'temperature': 0.7, 'output_config': {'effort': 'high'}}


def test_effort_dropped_when_unsupported_level_for_model():
    # xhigh is Opus-only; on Sonnet it must not be sent.
    area = ClaudeArea()
    area.model = 'claude-sonnet-4-6'
    area.effort = 'xhigh'
    area.temperature = 0.7
    kwargs = area._tuning_kwargs()
    assert 'output_config' not in kwargs
    assert kwargs == {'temperature': 0.7}


def test_temperature_zero_is_sent():
    # 0.0 is falsy but a valid temperature — must still be sent.
    area = ClaudeArea()
    area.model = 'claude-haiku-4-5'
    area.temperature = 0.0
    kwargs = area._tuning_kwargs()
    assert kwargs == {'temperature': 0.0}


def test_sanitize_effort_snaps_invalid_level_to_default():
    area = ClaudeArea()
    area.app = _FakeApp()
    area.model = 'claude-sonnet-4-6'   # no xhigh
    area.effort = 'xhigh'              # carried over from an Opus model
    area._sanitize_effort()
    assert area.effort in claude.MODEL_CAPS['claude-sonnet-4-6']['efforts']
    assert area.effort == claude.DEFAULT_EFFORT


def test_sanitize_effort_leaves_valid_level_untouched():
    area = ClaudeArea()
    area.app = _FakeApp()
    area.model = 'claude-opus-4-8'
    area.effort = 'xhigh'
    area._sanitize_effort()
    assert area.effort == 'xhigh'


class _FakeApp:
    """Minimal stand-in for AppState's per-area settings store (in-memory)."""

    def __init__(self):
        self._data = {}

    def load_area_settings(self, key):
        return dict(self._data)

    def save_area_settings(self, key, data):
        self._data = dict(data)


def test_set_field_persists_temperature_and_effort():
    area = ClaudeArea()
    area.app = _FakeApp()
    area._set_field('temperature', 0.25)
    area._set_field('effort', 'medium')
    assert area.app.load_area_settings('claude') == {'temperature': 0.25, 'effort': 'medium'}


# --- opt-in GSI event reactions ----------------------------------------------

from areas.event_prompts import event_to_prompt  # noqa: E402
from system.gsi import TiltEvent  # noqa: E402


def test_react_to_events_toggle_flips_consumes_and_persists():
    area = ClaudeArea()
    area.app = _FakeApp()
    assert area.consumes_events is False
    area._set_react_to_events(True)
    assert area.consumes_events is True
    assert area.app.load_area_settings('claude')['react_to_events'] is True
    area._set_react_to_events(False)
    assert area.consumes_events is False


def test_generate_event_delegates_to_generate_with_event_prompt():
    area = make_area(reply='ggez')
    ev = TiltEvent('MULTI_KILL', {'kills': 4})
    out = run(area.generate_event(ev, app=None))
    assert out == 'ggez'
    assert area.messages.calls[0]['messages'][-1] == {
        'role': 'user', 'content': event_to_prompt(ev)}


if __name__ == '__main__':
    import traceback

    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            try:
                fn()
                print(f'PASS {name}')
            except Exception:
                failures += 1
                print(f'FAIL {name}')
                traceback.print_exc()
    raise SystemExit(1 if failures else 0)
