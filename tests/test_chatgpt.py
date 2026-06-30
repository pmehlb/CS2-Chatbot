"""Tests for the ChatGPT area: message assembly, history rolling and readiness.

Run with:  venv\\Scripts\\python -m pytest tests/test_chatgpt.py
(or plain `python tests/test_chatgpt.py` to run them without pytest).

No live API calls: a fake AsyncOpenAI client whose
``chat.completions.create`` returns a canned response is injected, so
``generate()`` is exercised as pure logic.
"""
import asyncio
import os
import sys

# Make the application package layout (src/) importable when run from anywhere.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import areas.chatgpt as chatgpt
from areas.chatgpt import ChatGPTArea, MAX_HISTORY_MESSAGES


def run(coro):
    return asyncio.run(coro)


class FakeCompletions:
    """Records the create() kwargs and returns a canned (paddable) reply."""

    def __init__(self, reply='  hello there  '):
        self.reply = reply
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        message = type('Msg', (), {'content': self.reply})()
        choice = type('Choice', (), {'message': message})()
        return type('Response', (), {'choices': [choice]})()


class FakeClient:
    def __init__(self, completions):
        self.chat = type('Chat', (), {'completions': completions})()


def make_area(reply='  hello there  '):
    area = ChatGPTArea()
    area.api_key = 'sk-test'
    area.completions = FakeCompletions(reply)
    area.client = FakeClient(area.completions)
    # Capture notifications instead of hitting the live NiceGUI slot stack.
    area.notifications = []
    chatgpt.notify_and_log = lambda message, **kwargs: area.notifications.append((message, kwargs))
    return area


def test_generate_builds_system_history_user_in_order():
    area = make_area()
    area.system_prompt = 'be a bot'
    area.history = [{'role': 'user', 'content': 'earlier'},
                    {'role': 'assistant', 'content': 'reply'}]

    run(area.generate('hi', app=None))

    messages = area.completions.calls[0]['messages']
    assert messages[0] == {'role': 'system', 'content': 'be a bot'}
    # System, then the two prior history messages, then the new user message.
    assert messages[1] == {'role': 'user', 'content': 'earlier'}
    assert messages[2] == {'role': 'assistant', 'content': 'reply'}
    assert messages[-1] == {'role': 'user', 'content': 'hi'}


def test_generate_returns_stripped_reply():
    area = make_area(reply='  pong  ')
    assert run(area.generate('ping', app=None)) == 'pong'


def test_history_grows_and_trims_to_max():
    area = make_area(reply='ok')
    # Each call adds 2 messages (user + assistant). Run enough to overflow.
    calls = MAX_HISTORY_MESSAGES  # 2 * MAX guarantees we exceed the window
    for i in range(calls):
        run(area.generate(f'msg {i}', app=None))

    assert len(area.history) == MAX_HISTORY_MESSAGES
    # The window keeps the most recent messages, ending on the last assistant reply.
    assert area.history[-1] == {'role': 'assistant', 'content': 'ok'}
    assert area.history[-2]['content'] == f'msg {calls - 1}'


def test_is_ready_requires_api_key():
    area = ChatGPTArea()
    ok, reason = area.is_ready()
    assert ok is False and 'API key' in reason

    area.api_key = 'sk-test'
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
    area = ChatGPTArea()
    run(area.set_api_key('sk-test'))
    assert area.api_key == 'sk-test'
    assert area.client is not None

    run(area.set_api_key(''))
    assert area.api_key == ''
    assert area.client is None


# --- opt-in GSI event reactions ----------------------------------------------

from areas.event_prompts import event_to_prompt  # noqa: E402
from system.gsi import TiltEvent  # noqa: E402


class _SettingsApp:
    def __init__(self):
        self._data = {}

    def load_area_settings(self, key):
        return dict(self._data)

    def save_area_settings(self, key, data):
        self._data = dict(data)


def test_react_to_events_toggle_flips_consumes_and_persists():
    area = ChatGPTArea()
    area.app = _SettingsApp()
    assert area.consumes_events is False
    area._set_react_to_events(True)
    assert area.consumes_events is True
    assert area.app.load_area_settings('chatgpt')['react_to_events'] is True
    area._set_react_to_events(False)
    assert area.consumes_events is False


def test_generate_event_delegates_to_generate_with_event_prompt():
    area = make_area(reply='ggez')
    ev = TiltEvent('MVP')
    out = run(area.generate_event(ev, app=None))
    assert out == 'ggez'
    assert area.completions.calls[0]['messages'][-1] == {
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
