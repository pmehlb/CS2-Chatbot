"""Tests for the C2 / Command Bot area: dispatch and command output.

Run with:  venv\\Scripts\\python -m pytest tests/test_commands.py
(or plain `python tests/test_commands.py` to run them without pytest).
"""
import asyncio
import os
import random
import sys

# Make the application package layout (src/) importable when run from anywhere.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import areas.commands as commands
from areas.commands import CommandBotArea


class FakeApp:
    """In-memory stand-in for AppState's area-settings persistence."""

    def __init__(self):
        self._store = {}

    def load_area_settings(self, key):
        value = self._store.get(key, {})
        return dict(value) if isinstance(value, dict) else {}

    def save_area_settings(self, key, data):
        self._store[key] = data


def run(coro):
    return asyncio.run(coro)


def make_area():
    area = CommandBotArea()
    area.app = FakeApp()
    return area


def test_non_command_returns_none():
    area = make_area()
    assert run(area.generate('hello world', area.app)) is None


def test_bang_only_returns_none():
    area = make_area()
    assert run(area.generate('!', area.app)) is None


def test_unknown_command_returns_none():
    area = make_area()
    assert run(area.generate('!nope', area.app)) is None


def test_disabled_command_returns_none():
    area = make_area()
    area.enabled = {'ping': False}
    assert run(area.generate('!ping', area.app)) is None


def test_ping():
    area = make_area()
    assert run(area.generate('!ping', area.app)) == 'pong'


def test_command_is_case_insensitive():
    area = make_area()
    assert run(area.generate('!PING', area.app)) == 'pong'


def test_flip_seeded():
    area = make_area()
    random.seed(1)
    assert run(area.generate('!flip', area.app)) in ('flip: Heads', 'flip: Tails')


def test_roll_default_and_arg():
    area = make_area()
    random.seed(0)
    assert run(area.generate('!roll', area.app)).endswith('(d6)')
    assert run(area.generate('!roll 20', area.app)).endswith('(d20)')


def test_roll_clamps_out_of_range():
    area = make_area()
    assert run(area.generate('!roll 99999', area.app)).endswith('(d1000)')
    assert run(area.generate('!roll 1', area.app)).endswith('(d2)')


def test_roll_bad_arg_defaults_d6():
    area = make_area()
    assert run(area.generate('!roll abc', area.app)).endswith('(d6)')


def test_slots_jackpot_format():
    area = make_area()
    original = commands.random.choice
    commands.random.choice = lambda seq: 'seven'
    try:
        out = run(area.generate('!slots', area.app))
    finally:
        commands.random.choice = original
    assert out == 'slots: seven | seven | seven - JACKPOT!'


def test_8ball_prefix_and_known_answer():
    area = make_area()
    out = run(area.generate('!8ball will I win', area.app))
    assert out.startswith('8ball: ')
    assert out[len('8ball: '):] in commands.EIGHTBALL_ANSWERS


def test_help_is_three_lines_of_enabled_only():
    area = make_area()
    area.enabled = {'fact': False, 'dadjoke': False}
    out = run(area.generate('!help', area.app))
    assert isinstance(out, list) and len(out) == 3
    assert out[0] == out[2] and set(out[0]) == {'=', '-'}
    assert '!ping' in out[1]
    assert '!fact' not in out[1] and '!dadjoke' not in out[1]


def test_help_button_source_matches_help_command():
    # The "Send help to chat" button writes _help_lines(); it must match !help.
    area = make_area()
    assert area._help_lines() == run(area.generate('!help', area.app))


def test_send_help_writes_all_say_lines_at_once():
    # Regression: the button must write EVERY help line to message.cfg in one
    # file so a single in-game exec sends the whole block. The bug left only the
    # last line (the closing '-----' divider) because each line overwrote the
    # previous one via core.send_to_game's per-line, exec-as-you-go writes.
    import tempfile

    area = make_area()
    area.enabled = {'fact': False, 'dadjoke': False}
    with tempfile.TemporaryDirectory() as d:
        cfg = os.path.join(d, 'message.cfg')
        area.app.exec_path = cfg
        area.app.chat_char_limit = 221
        area.app.cfg_written = False
        area.app.can_exec = False
        area.app.exec_state_cb = None
        area._send_help()
        with open(cfg, encoding='utf-8') as f:
            content = f.read()

    say_lines = [ln for ln in content.splitlines() if ln.startswith('say "')]
    assert len(say_lines) == 3
    assert 'Commands:' in content and '!ping' in content


def test_is_ready_requires_one_enabled():
    area = make_area()
    area.enabled = {name: False for name in area.registry}
    ok, reason = area.is_ready()
    assert ok is False and reason
    area.enabled['ping'] = True
    assert area.is_ready() == (True, None)


def test_dadjoke_success():
    area = make_area()

    async def fake_text(url, headers=None):
        return '  Why did the chicken cross the road?  '

    original = commands._http_get_text
    commands._http_get_text = fake_text
    try:
        out = run(area.generate('!dadjoke', area.app))
    finally:
        commands._http_get_text = original
    assert out == 'Why did the chicken cross the road?'


def test_dadjoke_failure_returns_error():
    area = make_area()

    async def boom(url, headers=None):
        raise RuntimeError('network down')

    original = commands._http_get_text
    commands._http_get_text = boom
    try:
        out = run(area.generate('!dadjoke', area.app))
    finally:
        commands._http_get_text = original
    assert out == "dadjoke: couldn't fetch a joke right now"


def test_fact_success():
    area = make_area()

    async def fake_json(url, headers=None):
        return {'text': 'Honey never spoils.'}

    original = commands._http_get_json
    commands._http_get_json = fake_json
    try:
        out = run(area.generate('!fact', area.app))
    finally:
        commands._http_get_json = original
    assert out == 'fact: Honey never spoils.'


def test_fact_failure_returns_error():
    area = make_area()

    async def boom(url, headers=None):
        raise RuntimeError('network down')

    original = commands._http_get_json
    commands._http_get_json = boom
    try:
        out = run(area.generate('!fact', area.app))
    finally:
        commands._http_get_json = original
    assert out == "fact: couldn't fetch a fact right now"


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
