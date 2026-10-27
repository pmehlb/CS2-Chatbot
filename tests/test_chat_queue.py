"""Tests for the ordered chat queue: blackjack commands answered one at a time.

Drives the real chat loop (core.handle_tick) with the real Command Bot area.
Each tick reads one batch of console.log lines from a fake tailer.

Run with:  venv\\Scripts\\python -m pytest tests/test_chat_queue.py
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
from areas.commands import CommandBotArea


def chat_line(text, name):
    """A CS2 console.log all-chat line, including the U+200E after the name."""
    return f'  [ALL] {name}{core.NAME_END_MARKER}: {text}'


class BatchTailer:
    """Hands out one batch of lines per tick."""

    def __init__(self):
        self.batches = deque()

    def new_lines(self):
        return iter(self.batches.popleft() if self.batches else ())


class FakeApp:
    def __init__(self, area):
        self.powered_on = True
        self.active_area = area
        self.areas = [area]
        self.tailer = BatchTailer()
        self.steam_nick = 'me'
        self.roster = {}
        self.roster_version = 0
        self.attribute_speakers = False
        self.gsi_events = deque(maxlen=8)
        self.chat_queue = deque(maxlen=32)
        self.pending_sends = []
        self.cooldown_enabled = False
        self.cooldown_ms = 0
        self.last_reply_at = 0.0
        self.last_chat_at = 0.0
        self.recent_sends = []
        self.shown_watch = []
        self.last_speaker = ''
        self.last_channel = 'all'
        self.auto_press = True
        self.can_exec = False
        self.exec_state_cb = None
        self.rules = []
        self.sent = []

    def load_area_settings(self, key):
        return {}

    def save_area_settings(self, key, data):
        pass


@pytest.fixture
def app(monkeypatch):
    async def fake_send(reply, app_, channel='all'):
        app_.sent.append(reply)

    monkeypatch.setattr(core, 'send_to_game', fake_send)
    return FakeApp(CommandBotArea())


def tick(app, *lines):
    """Run one chat-loop tick that reads ``lines`` as (name, text) pairs."""
    app.tailer.batches.append([chat_line(text, name) for name, text in lines])
    asyncio.run(core.handle_tick(app))


def deal(app, *cards):
    """Open a table for Pat, stack the shoe with ``cards``, and deal now."""
    tick(app, ('Pat', '!blackjack'))
    table = app.active_area.table
    table.shoe.cards += list(reversed(cards))
    table.deadline = time.monotonic() - 1
    tick(app)
    app.sent.clear()


def test_two_joins_in_one_tick_are_both_answered_in_order(app):
    tick(app, ('Pat', '!blackjack'))
    tick(app, ('Bob', '!join'), ('Al', '!join'))
    tick(app)
    assert [line.split(' (')[0] for line in app.sent[1:]] == ['Bob joined', 'Al joined']
    assert [s.name for s in app.active_area.table.seats] == ['Pat', 'Bob', 'Al']


def test_other_commands_keep_newest_wins(app):
    tick(app, ('Bob', '!ping'), ('Al', '!flip'))
    tick(app)
    assert len(app.sent) == 1
    assert app.sent[0].startswith('[FLIP] ')
    assert not app.chat_queue


def test_queued_hit_beats_a_turn_timer_due_in_the_same_tick(app):
    deal(app, '10♠', '7♣', '4♥', '9♦', '2♣')
    app.active_area.table.deadline = time.monotonic() - 1   # Pat's turn just ran out
    tick(app, ('Pat', '!hit'))
    assert app.sent == [['[dealer] (7) 7♣ --.', '[Pat] >>(16) 10♠ 4♥ 2♣. !hit/!stand']]


def test_out_of_turn_command_is_refused_then_the_queue_moves_on(app):
    deal(app, '10♠', '7♣', '4♥', 'K♦')
    tick(app, ('Bob', '!hit'), ('Pat', '!stand'))
    tick(app)
    assert app.sent[0] == "Bob: You can't do that, dummy."
    assert app.sent[1] == ['[dealer] (17) 7♣ K♦.', '[Pat] (LOSE, 14) 10♠ 4♥.']


def test_silent_queued_line_does_not_take_the_tick(app):
    tick(app, ('Pat', '!blackjack'))
    tick(app, ('Pat', '!join'), ('Bob', '!join'))   # Pat is seated: no reply
    assert app.sent[-1].startswith('Bob joined (2 seated)')


def test_queue_waits_out_the_cooldown(app):
    tick(app, ('Pat', '!blackjack'))
    app.cooldown_enabled = True
    app.cooldown_ms = 60_000
    tick(app, ('Bob', '!join'))
    assert len(app.sent) == 1
    assert len(app.chat_queue) == 1          # held, not dropped


def test_queue_holds_while_human_control_reply_waits(app):
    app.auto_press = False
    app.pending_sends = ['an earlier reply']
    tick(app, ('Pat', '!blackjack'))
    assert app.sent == []
    assert len(app.chat_queue) == 1


def test_bot_off_queues_nothing(app):
    app.powered_on = False
    tick(app, ('Pat', '!blackjack'))
    assert not app.chat_queue
