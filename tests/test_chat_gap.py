"""Tests for the chat gap: no line goes out too soon after your own chat line.

CS2 drops a chat line from an account that spoke a moment before. In
console.log, a reply sent 0-0.1 s after the account's own line never showed,
and one sent 0.5 s after did. So after a chat line from steam_nick (you), the
app holds each keypress until MIN_CHAT_GAP has passed. Replies to other
players go out at once.

Run with:  venv\\Scripts\\python -m pytest tests/test_chat_gap.py
"""
import asyncio
import os
import sys
import time
from collections import deque

import pytest

# Make the application package layout (src/) importable when run from anywhere.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import core


class FakeApp:
    def __init__(self, tmp_path):
        self.exec_path = str(tmp_path / 'message.cfg')
        self.chat_char_limit = 221
        self.chat_delay = 0.0
        self.response_delay_ms = 0
        self.response_jitter_ms = 0
        self.auto_press = True
        self.bind_key = 'p'
        self.cfg_written = False
        self.can_exec = False
        self.exec_state_cb = None
        self.pending_sends = []
        self.last_chat_at = 0.0
        self.recent_sends = []
        self.shown_watch = []
        # For handle_tick.
        self.powered_on = True
        self.active_area = None
        self.steam_nick = 'MyNick'
        self.roster = {}
        self.roster_version = 0
        self.attribute_speakers = False
        self.gsi_events = deque(maxlen=8)
        self.chat_queue = deque(maxlen=32)
        self.cooldown_enabled = False
        self.cooldown_ms = 0
        self.last_reply_at = 0.0
        self.last_speaker = ''
        self.last_channel = 'all'
        self.rules = []


class OneLineTailer:
    def __init__(self, name, text):
        self.line = f'{core.ALL_CHAT_MARKER}{name}{core.NAME_END_MARKER}: {text}'

    def new_lines(self):
        yield self.line


class EchoArea:
    key = 'c2'

    def is_ready(self):
        return True, None

    async def generate(self, message, app):
        return 'reply'


@pytest.fixture
def events(monkeypatch):
    """Pretend CS2 is focused. Record each sleep and keypress, in order."""
    log = []

    async def fake_sleep(seconds):
        log.append(('sleep', round(seconds, 2)))

    monkeypatch.setattr(core.asyncio, 'sleep', fake_sleep)
    monkeypatch.setattr(core, 'get_foreground_window_title', lambda: 'Counter-Strike 2')
    monkeypatch.setattr(core.pydirectinput, 'write', lambda key: log.append(('key', key)))
    return log


def test_keypress_waits_out_the_gap_after_your_last_line(tmp_path, events):
    app = FakeApp(tmp_path)
    app.last_chat_at = time.monotonic()        # you just said something

    asyncio.run(core.send_to_game('Blackjack table open.', app, 'all'))

    assert events[0][0] == 'sleep' and 0.5 <= events[0][1] <= core.MIN_CHAT_GAP
    assert events[1] == ('key', 'p')


def test_no_wait_when_you_were_quiet(tmp_path, events):
    app = FakeApp(tmp_path)
    app.last_chat_at = time.monotonic() - 10

    asyncio.run(core.send_to_game('pong', app, 'all'))

    assert events[0] == ('key', 'p')


def test_a_longer_thinking_pause_needs_no_extra_wait(tmp_path, events, monkeypatch):
    app = FakeApp(tmp_path)
    app.response_delay_ms = 2000
    app.last_chat_at = time.monotonic()
    clock = [time.monotonic()]
    monkeypatch.setattr(core.time, 'monotonic', lambda: clock[0])

    async def advancing_sleep(seconds):     # the pause really passes
        events.append(('sleep', round(seconds, 2)))
        clock[0] += seconds

    monkeypatch.setattr(core.asyncio, 'sleep', advancing_sleep)
    asyncio.run(core.send_to_game('pong', app, 'all'))

    assert events[:2] == [('sleep', 2.0), ('key', 'p')]


def test_the_bots_own_send_starts_no_gap(tmp_path, events):
    app = FakeApp(tmp_path)

    asyncio.run(core.send_to_game(['one', 'two'], app, 'all'))

    assert app.last_chat_at == 0.0
    assert [e for e in events if e[0] == 'key'] == [('key', 'p'), ('key', 'p')]
    assert all(e == ('sleep', 0.0) for e in events if e[0] == 'sleep')   # chat_delay only


def test_human_control_never_waits(tmp_path, events):
    app = FakeApp(tmp_path)
    app.auto_press = False
    app.last_chat_at = time.monotonic()

    asyncio.run(core.send_to_game('pong', app, 'all'))

    assert events == []


def test_your_line_in_chat_starts_the_gap(tmp_path):
    app = FakeApp(tmp_path)
    before = time.monotonic()

    core.extract_latest_message(OneLineTailer('MyNick', 'gg'), 'MyNick', app)

    assert app.last_chat_at >= before


def test_another_players_line_starts_no_gap(tmp_path, monkeypatch):
    app = FakeApp(tmp_path)
    app.active_area = EchoArea()
    app.tailer = OneLineTailer('Bob', '!blackjack')
    seen = []

    async def fake_send(reply, app_, channel='all'):
        seen.append(app_.last_chat_at)

    monkeypatch.setattr(core, 'send_to_game', fake_send)
    asyncio.run(core.handle_tick(app))

    assert seen == [0.0]                     # Bob's reply goes out at once
