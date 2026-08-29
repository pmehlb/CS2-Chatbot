"""Tests for Human Control (the "Auto-press execute key" switch turned off).

Human Control means the app never presses the bind key. It writes the whole
reply into message.cfg in one go and the exec light says "ready to fire":
green once the reply is in the file, red again once the message shows up in
chat. The cfg is emptied when a new reply starts, so an early keypress cannot
fire a stale command.

Run with:  venv\\Scripts\\python -m pytest tests/test_human_control.py
"""
import asyncio
import os
import sys

# Make the application package layout (src/) importable when run from anywhere.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import core


class FakeApp:
    def __init__(self, tmp_path, auto_press=False):
        self.exec_path = str(tmp_path / 'message.cfg')
        self.chat_char_limit = 221
        self.chat_delay = 0.0
        self.response_delay_ms = 0
        self.response_jitter_ms = 0
        self.auto_press = auto_press
        self.bind_key = 'p'
        self.cfg_written = False
        self.can_exec = False
        self.exec_state_cb = None
        self.pending_sends = []
        self.steam_nick = 'MyNick'
        self.roster = {}
        self.roster_version = 0
        self.lights = []

    def record_light(self, ready):
        self.lights.append(ready)


class FakeTailer:
    def __init__(self, lines):
        self._lines = lines

    def new_lines(self):
        yield from self._lines


M = core.ALL_CHAT_MARKER
LRM = '‎'


def _in_cs2(monkeypatch, keys):
    """Pretend CS2 is focused and record every simulated keypress."""
    monkeypatch.setattr(core, 'get_foreground_window_title', lambda: 'Counter-Strike 2')
    monkeypatch.setattr(core.pydirectinput, 'write', lambda key: keys.append(key))


def _no_real_waiting(monkeypatch):
    """Record every requested sleep and return at once. Returns the record."""
    slept = []
    real_sleep = asyncio.sleep

    async def fake_sleep(seconds):
        slept.append(seconds)
        await real_sleep(0)

    monkeypatch.setattr(core.asyncio, 'sleep', fake_sleep)
    return slept


def _read_cfg(app):
    with open(app.exec_path, encoding='utf-8') as f:
        return f.read()


# --- chat_message_chunks: the exact text CS2 will show ------------------------

def test_chat_message_chunks_cleans_and_chunks():
    chunks = core.chat_message_chunks('ab"c\nd', char_limit=4)
    assert chunks == ["ab''", 'c d']


def test_chat_message_chunks_skips_empty_lines():
    assert core.chat_message_chunks(['', 'hi'], char_limit=221) == ['hi']


# --- send_to_game: one write, no keypress ------------------------------------

def test_human_control_writes_whole_reply_at_once(tmp_path, monkeypatch):
    app = FakeApp(tmp_path, auto_press=False)
    app.exec_state_cb = app.record_light
    keys = []
    _in_cs2(monkeypatch, keys)

    asyncio.run(core.send_to_game(['first', 'second'], app, 'all'))

    assert _read_cfg(app) == 'say "first"\nsay "second"\n'
    assert keys == []                       # the human presses the key
    assert app.pending_sends == ['first', 'second']
    assert app.can_exec is True             # green: ready to fire
    assert app.lights == [True]


def test_auto_press_still_types_each_line(tmp_path, monkeypatch):
    app = FakeApp(tmp_path, auto_press=True)
    keys = []
    _in_cs2(monkeypatch, keys)

    asyncio.run(core.send_to_game(['first', 'second'], app, 'all'))

    assert keys == ['p', 'p']               # one keypress per line, as before
    assert _read_cfg(app) == 'say "second"' # last line only
    assert app.pending_sends == []          # nothing waits on a chat confirmation
    assert app.can_exec is True


def test_human_control_skips_the_thinking_pause(tmp_path, monkeypatch):
    # The pause exists so a reply does not appear in chat instantly. The human
    # sets that timing here, so a finished reply must not be held back.
    app = FakeApp(tmp_path, auto_press=False)
    app.response_delay_ms = 5000
    app.response_jitter_ms = 5000
    _in_cs2(monkeypatch, [])
    slept = _no_real_waiting(monkeypatch)

    asyncio.run(core.send_to_game('hello', app, 'all'))

    assert slept == []
    assert app.can_exec is True


def test_auto_press_still_waits_the_thinking_pause(tmp_path, monkeypatch):
    app = FakeApp(tmp_path, auto_press=True)
    app.response_delay_ms = 200
    _in_cs2(monkeypatch, [])
    slept = _no_real_waiting(monkeypatch)

    asyncio.run(core.send_to_game('hello', app, 'all'))

    assert slept[0] == 0.2


def test_human_control_uses_say_team_for_team_chat(tmp_path, monkeypatch):
    app = FakeApp(tmp_path, auto_press=False)
    _in_cs2(monkeypatch, [])

    asyncio.run(core.send_to_game('rotate B', app, 'team'))

    assert _read_cfg(app) == 'say_team "rotate B"\n'


# --- begin_reply: red, and an empty cfg while we think -----------------------

def test_begin_reply_empties_cfg_in_human_control(tmp_path):
    app = FakeApp(tmp_path, auto_press=False)
    app.exec_state_cb = app.record_light
    with open(app.exec_path, 'w', encoding='utf-8') as f:
        f.write('say "stale"\n')
    app.can_exec = True
    app.pending_sends = ['stale']

    core.begin_reply(app)

    assert _read_cfg(app) == ''
    assert app.pending_sends == []
    assert app.can_exec is False
    assert app.lights == [False]


def test_begin_reply_keeps_cfg_when_auto_press(tmp_path):
    app = FakeApp(tmp_path, auto_press=True)
    with open(app.exec_path, 'w', encoding='utf-8') as f:
        f.write('say "old"\n')

    core.begin_reply(app)

    assert _read_cfg(app) == 'say "old"\n'   # the app fires it itself
    assert app.can_exec is False


def test_begin_reply_survives_a_missing_cfg_directory(tmp_path):
    app = FakeApp(tmp_path, auto_press=False)
    app.exec_path = str(tmp_path / 'no-such-dir' / 'message.cfg')

    core.begin_reply(app)                    # must not raise

    assert app.can_exec is False


# --- confirmation: our own line in chat turns the light red ------------------

def test_own_chat_line_confirms_the_send(tmp_path):
    app = FakeApp(tmp_path, auto_press=False)
    app.exec_state_cb = app.record_light
    app.can_exec = True
    app.pending_sends = ['hello there']
    tailer = FakeTailer([f'06/25 06:31:32{M}MyNick{LRM} [DEAD]: hello there'])

    core.extract_latest_message(tailer, 'MyNick', app)

    assert app.pending_sends == []
    assert app.can_exec is False
    assert app.lights == [False]
    assert app.roster == {}                  # we never roster ourselves


def test_light_stays_green_until_every_chunk_lands(tmp_path):
    app = FakeApp(tmp_path, auto_press=False)
    app.can_exec = True
    app.pending_sends = ['part one', 'part two']
    tailer = FakeTailer([f'06/25 06:31:32{M}MyNick{LRM}: part one'])

    core.extract_latest_message(tailer, 'MyNick', app)

    assert app.pending_sends == ['part two']
    assert app.can_exec is True              # still ready to fire the rest


def test_unrelated_own_line_does_not_confirm(tmp_path):
    # Typing in chat yourself must not clear a reply that is still waiting.
    app = FakeApp(tmp_path, auto_press=False)
    app.can_exec = True
    app.pending_sends = ['hello there']
    tailer = FakeTailer([f'06/25 06:31:32{M}MyNick{LRM}: nice shot'])

    core.extract_latest_message(tailer, 'MyNick', app)

    assert app.pending_sends == ['hello there']
    assert app.can_exec is True


def test_confirmation_ignores_trailing_space_from_cs2(tmp_path):
    app = FakeApp(tmp_path, auto_press=False)
    app.can_exec = True
    app.pending_sends = ['gg']
    tailer = FakeTailer([f'06/25 06:31:32{M}MyNick{LRM} [DEAD]: gg '])

    core.extract_latest_message(tailer, 'MyNick', app)

    assert app.pending_sends == []
    assert app.can_exec is False


def test_other_players_never_confirm_a_send(tmp_path):
    app = FakeApp(tmp_path, auto_press=False)
    app.can_exec = True
    app.pending_sends = ['gg']
    tailer = FakeTailer([f'06/25 06:31:32{M}Babs{LRM}: gg'])

    core.extract_latest_message(tailer, 'MyNick', app)

    assert app.pending_sends == ['gg']       # Babs said it, not us
    assert app.can_exec is True


if __name__ == '__main__':
    # These tests use the tmp_path / monkeypatch fixtures, so pytest runs them.
    raise SystemExit(__import__('pytest').main([__file__]))
