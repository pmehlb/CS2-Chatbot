"""Tests for the Character.AI area: search authentication and current-bot status.

Run with:  venv\\Scripts\\python -m pytest tests/test_characterai.py
(or plain `python tests/test_characterai.py` to run them without pytest).

These avoid spinning up NiceGUI: the area's widgets are replaced with tiny
stand-ins and `_render_cards` (the only method that touches the live UI slot
stack) is stubbed, so `search()` can be exercised as pure logic.
"""
import asyncio
import os
import sys

# Make the application package layout (src/) importable when run from anywhere.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import areas.characterai as characterai
from areas.characterai import CharacterAIArea


def run(coro):
    return asyncio.run(coro)


class FakeCharacterMethods:
    """Records how search_characters was called and returns no results."""

    def __init__(self):
        self.calls = []

    async def search_characters(self, name, **kwargs):
        self.calls.append((name, kwargs))
        return []


class FakeClient:
    def __init__(self, character):
        self.character = character


class FakeWidget:
    """Stand-in for a NiceGUI input/button: just enough surface for search()."""

    def __init__(self, value=''):
        self.value = value
        self.text = ''
        self.disabled = False

    def disable(self):
        self.disabled = True

    def enable(self):
        self.disabled = False


def make_area(query='naruto', web_next_auth='WNA'):
    area = CharacterAIArea()
    area.token = 'tok'
    area.web_next_auth = web_next_auth
    area.client = FakeClient(FakeCharacterMethods())
    area.character_input = FakeWidget(value=query)
    area.search_btn = FakeWidget()
    area.rendered = []
    area._render_cards = lambda chars: area.rendered.append(list(chars))
    # _show_recents / status updates touch widgets we don't build here.
    area._show_recents = lambda: None
    # Capture notifications instead of hitting the live NiceGUI slot stack.
    area.notifications = []
    characterai.notify_and_log = lambda message, **kwargs: area.notifications.append((message, kwargs))
    return area


def test_search_passes_web_next_auth():
    # Regression: name search hits the tRPC endpoint, which only authenticates
    # via the web-next-auth cookie. Without it the request 401s and the user
    # sees nothing. search() must forward area.web_next_auth.
    area = make_area()
    run(area.search())
    assert area.client.character.calls, 'search_characters was never called'
    name, kwargs = area.client.character.calls[0]
    assert name == 'naruto'
    assert kwargs.get('web_next_auth') == 'WNA'
    # Button always re-enabled after a search.
    assert area.search_btn.disabled is False


def test_search_without_web_next_auth_warns_and_skips():
    # With no web-next-auth token there is no point hitting the endpoint; warn
    # the user instead of firing a request that will fail.
    area = make_area(web_next_auth='')
    run(area.search())
    assert area.client.character.calls == []
    assert area.notifications, 'expected a warning notification'


def test_status_reflects_selected_character():
    area = CharacterAIArea()
    area.status_label = FakeWidget()

    area._update_status()
    assert 'No character selected' in area.status_label.text

    area.current_char = type('Char', (), {'name': 'Naruto'})()
    area._update_status()
    assert 'Naruto' in area.status_label.text


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
    area = CharacterAIArea()
    area.app = _SettingsApp()
    assert area.consumes_events is False
    area._set_react_to_events(True)
    assert area.consumes_events is True
    assert area.app.load_area_settings('characterai')['react_to_events'] is True


def test_generate_event_delegates_to_generate_with_event_prompt():
    area = CharacterAIArea()
    captured = []

    async def fake_generate(message, app):
        captured.append(message)
        return 'cai taunt'

    area.generate = fake_generate
    ev = TiltEvent('ROUND_WIN')
    out = run(area.generate_event(ev, app=None))
    assert out == 'cai taunt'
    assert captured == [event_to_prompt(ev)]


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
