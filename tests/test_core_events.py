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
        self.cooldown_enabled = False
        self.cooldown_ms = 0
        self.last_reply_at = 0.0
        self.can_exec = False
        self.exec_state_cb = None
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
