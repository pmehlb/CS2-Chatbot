"""Tests that the chat loop actually runs replies through the command rules.

tests/test_rules.py covers the parsing itself; these cover the wiring -- that
both reply paths (chat and GSI events) apply the rules, and that a silencing
rule stops the send before any keystroke or cooldown is spent.

Run with:  venv\\Scripts\\python -m pytest tests/test_core_rules.py
"""
import asyncio
import os
import sys
from collections import deque

# Make the application package layout (src/) importable when run from anywhere.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import core
from system.gsi import TiltEvent

SILENT = {'label': 'SILENT', 'action': 'silent', 'text': ''}
TAUNT = {'label': 'TAUNT', 'action': 'say', 'text': 'get good'}


class FakeArea:
    key = 'fake'
    answerable = True
    attribute_speaker = True
    consumes_events = False

    def __init__(self, reply):
        self.reply = reply

    def is_ready(self):
        return True, None

    async def generate(self, message, app):
        return self.reply

    async def generate_event(self, event, app):
        return self.reply


class FakeTailer:
    """Yields one CS2 all-chat line, then nothing."""

    def __init__(self, lines=()):
        self.lines = list(lines)

    def new_lines(self):
        lines, self.lines = self.lines, []
        return iter(lines)


class FakeApp:
    def __init__(self, area, rules=(), chat=()):
        self.powered_on = True
        self.active_area = area
        self.areas = [area]
        self.tailer = FakeTailer(chat)
        self.steam_nick = 'me'
        self.roster = {}
        self.roster_version = 0
        self.attribute_speakers = False
        self.gsi_events = deque(maxlen=8)
        self.cooldown_enabled = False
        self.cooldown_ms = 0
        self.last_reply_at = 0.0
        self.can_exec = False
        self.exec_state_cb = None
        self.rules = list(rules)
        self.sent = []


def chat_line(text, name='Bob'):
    """A CS2 console.log all-chat line, including the U+200E after the name."""
    return f'  [ALL] {name}{core.NAME_END_MARKER}: {text}'


def run_tick(app, monkeypatch):
    async def fake_send(reply, app_, channel='all'):
        app_.sent.append((reply, channel))

    monkeypatch.setattr(core, 'send_to_game', fake_send)
    asyncio.run(core.handle_tick(app))


# ---------------------------------------------------------------- chat replies

def test_chat_reply_is_substituted_in_place(monkeypatch):
    app = FakeApp(FakeArea('nice try ([TAUNT]) loser'), rules=[TAUNT],
                  chat=[chat_line('hello')])
    run_tick(app, monkeypatch)
    assert app.sent == [('nice try get good loser', 'all')]


def test_silencing_rule_sends_nothing(monkeypatch):
    app = FakeApp(FakeArea('whatever ([SILENT]) man'), rules=[SILENT],
                  chat=[chat_line('hello')])
    run_tick(app, monkeypatch)
    assert app.sent == []


def test_silencing_rule_does_not_start_the_cooldown(monkeypatch):
    # A silenced turn must not stamp last_reply_at, or the bot would sit out the
    # cooldown for a reply it never sent.
    app = FakeApp(FakeArea('([SILENT])'), rules=[SILENT], chat=[chat_line('hello')])
    run_tick(app, monkeypatch)
    assert app.last_reply_at == 0.0


def test_reply_without_rules_is_sent_unchanged(monkeypatch):
    app = FakeApp(FakeArea('([TAUNT]) still goes out'), chat=[chat_line('hello')])
    run_tick(app, monkeypatch)
    assert app.sent == [('([TAUNT]) still goes out', 'all')]


def test_team_chat_channel_survives_substitution(monkeypatch):
    app = FakeApp(FakeArea('([TAUNT])'), rules=[TAUNT],
                  chat=[f'  [CT] Bob{core.NAME_END_MARKER}: hello'])
    run_tick(app, monkeypatch)
    assert app.sent == [('get good', 'team')]


# ---------------------------------------------------------------- event taunts

def test_event_taunt_is_substituted(monkeypatch):
    area = FakeArea('([TAUNT])')
    area.consumes_events = True
    app = FakeApp(area, rules=[TAUNT])
    app.gsi_events.append(TiltEvent('MVP'))
    run_tick(app, monkeypatch)
    assert app.sent == [('get good', 'all')]


def test_event_taunt_can_be_silenced(monkeypatch):
    area = FakeArea('([SILENT]) ace')
    area.consumes_events = True
    app = FakeApp(area, rules=[SILENT])
    app.gsi_events.append(TiltEvent('MULTI_KILL', {'kills': 5}))
    run_tick(app, monkeypatch)
    assert app.sent == []
    assert app.last_reply_at == 0.0
