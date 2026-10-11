# tests/test_core_events.py
import asyncio
import os
import sys
from collections import deque

# Make the application package layout (src/) importable when run from anywhere.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import core
from system.gsi import TiltEvent


class FakeArea:
    key = 'fake'
    consumes_events = True

    def __init__(self, reply='taunt!'):
        self.reply = reply
        self.events_seen = []

    def is_ready(self):
        return True, None

    async def generate_event(self, event, app):
        self.events_seen.append(event)
        return self.reply


class FakeTailer:
    def new_lines(self):
        return iter(())  # no chat


class FakeApp:
    def __init__(self, area):
        self.powered_on = True
        self.active_area = area
        self.areas = [area]
        self.tailer = FakeTailer()
        self.steam_nick = 'me'
        self.roster = {}
        self.roster_version = 0
        self.gsi_events = deque(maxlen=8)
        self.chat_queue = deque(maxlen=32)
        self.pending_sends = []
        self.cooldown_enabled = False
        self.cooldown_ms = 0
        self.last_reply_at = 0.0
        self.last_chat_at = 0.0
        self.recent_sends = []
        self.shown_watch = []
        self.auto_press = True   # the app fires the reply itself (not Human Control)
        self.can_exec = False
        self.exec_state_cb = None
        self.rules = []
        self.sent = []


def test_next_event_pops_newest_and_clears_stale():
    app = FakeApp(FakeArea())
    app.gsi_events.extend([TiltEvent('OLD'), TiltEvent('NEW')])
    ev = core._next_event(app)
    assert ev.kind == 'NEW'
    assert len(app.gsi_events) == 0


def test_handle_tick_reacts_to_event(monkeypatch):
    area = FakeArea(reply='ez')
    app = FakeApp(area)
    app.gsi_events.append(TiltEvent('MULTI_KILL', {'kills': 5}))

    async def fake_send(reply, app_, channel='all'):
        app_.sent.append((reply, channel))

    monkeypatch.setattr(core, 'send_to_game', fake_send)
    asyncio.run(core.handle_tick(app))

    assert app.sent == [('ez', 'all')]
    assert area.events_seen[0].kind == 'MULTI_KILL'


def test_handle_tick_ignores_events_when_area_opts_out(monkeypatch):
    area = FakeArea()
    area.consumes_events = False
    app = FakeApp(area)
    app.gsi_events.append(TiltEvent('MVP'))

    async def fake_send(reply, app_, channel='all'):
        app_.sent.append((reply, channel))

    monkeypatch.setattr(core, 'send_to_game', fake_send)
    asyncio.run(core.handle_tick(app))

    assert app.sent == []
    assert app.gsi_events  # untouched


class TimedArea(FakeArea):
    """An area whose timer has a line due (like the blackjack deal)."""
    consumes_events = False

    def __init__(self, due):
        super().__init__()
        self.due = due
        self.chat_seen = []

    async def generate_timed(self, app):
        due, self.due = self.due, None
        return due

    async def generate(self, message, app):
        self.chat_seen.append(message)
        return 'chat reply'


class OneLineTailer:
    def __init__(self, line):
        self.lines = [line]

    def new_lines(self):
        lines, self.lines = self.lines, []
        return iter(lines)


def test_handle_tick_sends_due_timer_line_to_its_channel(monkeypatch):
    area = TimedArea(due=(['deal line'], 'team'))
    app = FakeApp(area)

    async def fake_send(reply, app_, channel='all'):
        app_.sent.append((reply, channel))

    monkeypatch.setattr(core, 'send_to_game', fake_send)
    asyncio.run(core.handle_tick(app))

    assert app.sent == [(['deal line'], 'team')]
    assert app.last_reply_at > 0


def test_due_timer_takes_the_tick_over_chat(monkeypatch):
    area = TimedArea(due=('turn over', 'all'))
    app = FakeApp(area)
    app.tailer = OneLineTailer('Bob‎  [ALL] Bob‎: !join')

    async def fake_send(reply, app_, channel='all'):
        app_.sent.append((reply, channel))

    monkeypatch.setattr(core, 'send_to_game', fake_send)
    asyncio.run(core.handle_tick(app))

    assert app.sent == [('turn over', 'all')]
    assert area.chat_seen == []


def test_timer_waits_out_the_cooldown(monkeypatch):
    area = TimedArea(due=('deal line', 'all'))
    app = FakeApp(area)
    app.cooldown_enabled = True
    app.cooldown_ms = 60_000
    app.last_reply_at = core.time.monotonic()

    async def fake_send(reply, app_, channel='all'):
        app_.sent.append((reply, channel))

    monkeypatch.setattr(core, 'send_to_game', fake_send)
    asyncio.run(core.handle_tick(app))

    assert app.sent == []
    assert area.due == ('deal line', 'all')    # not consumed: sent once the cooldown ends
