"""Tests for answering your own chat lines (ChatArea.answers_own_lines).

Lines from steam_nick are yours. The Command Bot answers what you type, so you
can sit at your own blackjack table. The echo of a reply the app sent also
comes from steam_nick and is never answered. Other areas keep ignoring you.

Run with:  venv\\Scripts\\python -m pytest tests/test_answer_self.py
"""
import asyncio
import os
import sys
import time
from collections import deque

# Make the application package layout (src/) importable when run from anywhere.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import core
from areas.base import ChatArea
from areas.commands import CommandBotArea

ME = 'schwagger'


def line(name, text):
    return f'{core.ALL_CHAT_MARKER}{name}{core.NAME_END_MARKER}: {text}'


class Tailer:
    def __init__(self, *lines):
        self.batches = deque([list(lines)])

    def new_lines(self):
        return iter(self.batches.popleft() if self.batches else ())


class FakeApp:
    def __init__(self, area=None, *lines):
        self.exec_path = ''
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
        self.recent_sends = deque(maxlen=16)
        self.shown_watch = []
        self.last_chat_at = 0.0
        self.powered_on = True
        self.active_area = area
        self.tailer = Tailer(*lines)
        self.steam_nick = ME
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
        self.sent = []

    def load_area_settings(self, key):
        return {}

    def save_area_settings(self, key, data):
        pass


def extract(app, answer_self):
    return core.extract_latest_message(app.tailer, ME, app, answer_self=answer_self)


# ---------------------------------------------------------------------- flags

def test_only_the_command_bot_answers_you():
    assert ChatArea.answers_own_lines is False
    assert CommandBotArea.answers_own_lines is True


# ---------------------------------------------------------------------- extract

def test_your_line_is_answered_when_the_area_opts_in():
    app = FakeApp(None, line(ME, '!ping'))
    before = time.monotonic()
    assert extract(app, answer_self=True) == ('!ping', 'all', ME)
    assert app.last_chat_at >= before          # the reply keeps the chat gap
    assert app.roster == {}                    # you are not a roster entry


def test_your_line_is_ignored_by_default():
    app = FakeApp(None, line(ME, '!ping'))
    assert extract(app, answer_self=False) == (None, None, None)


def test_the_echo_of_our_reply_is_never_answered():
    app = FakeApp(None, line(ME, 'pong'), line('Bob', '!flip'))
    app.recent_sends.append('pong')
    assert extract(app, answer_self=True) == ('!flip', 'all', 'Bob')
    assert not app.recent_sends                # the echo used up its match


def test_the_echo_of_a_human_control_reply_is_never_answered():
    app = FakeApp(None, line(ME, 'pong'))
    app.pending_sends = ['pong']
    assert extract(app, answer_self=True) == (None, None, None)
    assert app.pending_sends == []


# ---------------------------------------------------------------------- sends

def test_auto_press_records_each_sent_line(tmp_path, monkeypatch):
    app = FakeApp()
    app.exec_path = str(tmp_path / 'message.cfg')
    monkeypatch.setattr(core, 'get_foreground_window_title', lambda: 'Counter-Strike 2')
    monkeypatch.setattr(core.pydirectinput, 'write', lambda key: None)

    async def no_sleep(seconds):
        pass

    monkeypatch.setattr(core.asyncio, 'sleep', no_sleep)
    asyncio.run(core.send_to_game(['one', 'two'], app, 'all'))
    assert list(app.recent_sends) == ['one', 'two']


def test_the_echo_of_a_replys_last_line_reports_it_shown(tmp_path):
    app = FakeApp(None, line(ME, 'one'), line(ME, 'two'))
    app.exec_path = str(tmp_path / 'message.cfg')
    app.auto_press = False                      # Human Control: you press the key
    asyncio.run(core.send_to_game(['one', 'two'], app, 'all'))
    shown = []
    core.extract_latest_message(app.tailer, ME, app, answer_self=True,
                                on_shown=lambda reply, now: shown.append(reply))
    assert shown == [['one', 'two']]            # once, for the last line only
    assert not app.shown_watch


def test_help_button_records_its_lines(tmp_path):
    app = FakeApp()
    app.exec_path = str(tmp_path / 'message.cfg')
    core.write_message_cfg(['=-=', 'Commands: !help', '=-='], app, 'all')
    assert list(app.recent_sends) == ['=-=', 'Commands: !help', '=-=']


# ---------------------------------------------------------------------- chat loop

def test_you_can_open_your_own_blackjack_table(monkeypatch):
    area = CommandBotArea()
    app = FakeApp(area, line(ME, '!blackjack'))

    async def fake_send(reply, app_, channel='all'):
        app_.sent.append(reply)

    monkeypatch.setattr(core, 'send_to_game', fake_send)
    asyncio.run(core.handle_tick(app))

    assert app.sent and app.sent[0].startswith('Blackjack table open.')
    assert [s.name for s in area.table.seats] == [ME]


def test_other_areas_still_ignore_you(monkeypatch):
    class Persona:
        key = 'ai'

        def is_ready(self):
            return True, None

        async def generate(self, message, app):
            return 'hi'

    app = FakeApp(Persona(), line(ME, 'hello'))

    async def fake_send(reply, app_, channel='all'):
        app_.sent.append(reply)

    monkeypatch.setattr(core, 'send_to_game', fake_send)
    asyncio.run(core.handle_tick(app))

    assert app.sent == []


def test_the_round_clock_starts_when_the_table_view_reaches_chat(tmp_path, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(core, 'get_foreground_window_title', lambda: 'Counter-Strike 2')
    monkeypatch.setattr(core.pydirectinput, 'write', lambda key: None)

    async def no_sleep(seconds):
        pass

    monkeypatch.setattr(core.asyncio, 'sleep', no_sleep)
    area = CommandBotArea()
    area.table.turn_seconds = 10
    app = FakeApp(area)
    app.exec_path = str(tmp_path / 'message.cfg')
    app.tailer.batches.clear()

    def tick_at(t, *lines):
        clock[0] = t
        app.tailer.batches.append(list(lines))
        asyncio.run(core.handle_tick(app))

    tick_at(1000, line(ME, '!blackjack'))
    tick_at(1001, line('Bob', '!join'))
    area.table.shoe.cards += ['10♦', '9♠', '4♥', '7♣', '5♦', 'K♠']
    tick_at(1015)                        # the deal: the view goes out
    view = list(app.recent_sends)[-2:]
    # The view shows in chat 3s later, and you stand at once. Bob gets 10s
    # from the view in chat, not from the deal.
    tick_at(1018, line(ME, view[0]), line(ME, view[1]), line(ME, '!stand'))
    tick_at(1026)
    assert area.table.state == 'playing'
    tick_at(1028)
    assert area.table.state == 'idle'    # Bob stood on the clock: results out
