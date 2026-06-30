"""Tests for core.extract_latest_message: speaker roster + ignore filtering.

Run with:  venv\\Scripts\\python -m pytest tests/test_roster.py
(or plain `python tests/test_roster.py` to run them without pytest).
"""
import os
import sys

# Make the application package layout (src/) importable when run from anywhere.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import core


class FakeTailer:
    """Stands in for core.LogTailer, yielding a fixed list of lines once."""

    def __init__(self, lines):
        self._lines = lines

    def new_lines(self):
        yield from self._lines


class FakeApp:
    def __init__(self, roster=None):
        self.roster = roster or {}
        self.roster_version = 0


M = core.ALL_CHAT_MARKER


def test_registers_new_speakers_and_returns_latest():
    app = FakeApp()
    tailer = FakeTailer([
        f'{M}Steve: hello',
        f'{M}Bob: hi there',
        'some unrelated console spam',
    ])

    msg, channel, name = core.extract_latest_message(tailer, 'Me', app)

    assert msg == 'hi there'
    assert channel == 'all'
    assert name == 'Bob'
    assert list(app.roster) == ['Steve', 'Bob']
    assert app.roster == {'Steve': True, 'Bob': True}
    assert app.roster_version == 2


def test_skips_our_own_messages():
    app = FakeApp()
    tailer = FakeTailer([
        f'{M}MyNick: this is me',
    ])

    msg, channel, name = core.extract_latest_message(tailer, 'MyNick', app)

    assert msg is None
    assert app.roster == {}  # we never add ourselves


def test_ignored_speaker_falls_through_to_latest_allowed():
    # Bob is muted; the newest line is his, but we answer Steve's earlier line.
    app = FakeApp({'Bob': False})
    tailer = FakeTailer([
        f'{M}Steve: answer me',
        f'{M}Bob: ignore me',
    ])

    msg, channel, name = core.extract_latest_message(tailer, 'Me', app)

    assert msg == 'answer me'
    assert channel == 'all'
    assert app.roster['Bob'] is False        # still tracked
    assert app.roster['Steve'] is True       # newly registered, allowed


def test_returns_none_when_only_speaker_is_ignored():
    app = FakeApp({'Bob': False})
    tailer = FakeTailer([f'{M}Bob: nope'])

    msg, channel, name = core.extract_latest_message(tailer, 'Me', app)

    assert msg is None


# --- Real CS2 console.log samples --------------------------------------------
# Names carry a trailing U+200E (‎) and a " [DEAD]" status suffix; the bot's
# own nick here is "gelatinous boob".
LRM = '‎'


def test_real_log_cleans_names_and_strips_dead_suffix():
    app = FakeApp()
    # Real lines: timestamp + [ALL] marker + name + U+200E + optional status.
    lines = [
        '06/25 06:31:03 PlagueDoctor603 connected',
        f'06/25 06:31:07{M}Gl0ck That{LRM} [DEAD]: gg daddies',
        f'06/25 06:31:07{M}gelatinous boob{LRM} [DEAD]: seiddad gg',
        f'06/25 06:31:21{M}Farva{LRM} [DEAD]: gg ',
        f'06/25 06:31:24{M}Babs{LRM} [DEAD]: gg',
        f'06/25 06:31:26{M}LogicaL{LRM} [DEAD]: gg',
        f'06/25 06:31:27{M}♛ COTACATE ♛{LRM} [DEAD]: ggwp',
        f'06/25 06:31:27{M}slaab{LRM} [DEAD]: geegee',
        '06/25 06:31:27 [InputService] execing message.cfg',
        f'06/25 06:31:31{M}PlagueDoctor603{LRM} [DEAD]: damn ggs',
        f'06/25 06:31:31{M}slaab{LRM} [DEAD]: eegeeg',
        f'06/25 06:31:32{M}gelatinous boob{LRM} [DEAD]: geegee',  # ours, last line
    ]

    msg, channel, name = core.extract_latest_message(tailer=FakeTailer(lines),
                                                steam_nick='gelatinous boob', app=app)

    # Last allowed (non-self) message wins.
    assert msg == 'eegeeg'
    assert channel == 'all'
    # Clean names, no LRM, no " [DEAD]", and the bot itself is absent.
    assert list(app.roster) == [
        'Gl0ck That', 'Farva', 'Babs', 'LogicaL', '♛ COTACATE ♛',
        'slaab', 'PlagueDoctor603',
    ]
    assert all(v is True for v in app.roster.values())
    assert 'gelatinous boob' not in app.roster


def test_same_player_alive_then_dead_is_one_entry():
    app = FakeApp()
    lines = [
        f'06/25 06:31:26{M}Gl0ck That{LRM} [DEAD]: nt nt',  # dead
        f'06/25 06:31:10{M}Gl0ck That{LRM}: its ARNOLD!',   # alive
    ]

    core.extract_latest_message(FakeTailer(lines), 'Me', app)

    assert list(app.roster) == ['Gl0ck That']


def test_team_chat_is_captured_and_rostered():
    # [T]/[CT] chat now drives the bot too; the newest allowed line still wins.
    app = FakeApp()
    lines = [
        f'06/25 06:17:29  [T] LogicaL{LRM}﹫T Start: damn lol',
        f'06/25 06:17:35{M}slaab{LRM}: loop activated',
    ]

    msg, channel, name = core.extract_latest_message(FakeTailer(lines), 'Me', app)

    # Newest allowed line is the [ALL] one from slaab.
    assert msg == 'loop activated'
    assert channel == 'all'
    assert list(app.roster) == ['LogicaL', 'slaab']


def test_team_message_returns_team_channel():
    app = FakeApp()
    lines = [f'06/25 06:17:29  [CT] Babs{LRM}: rotate B']

    msg, channel, name = core.extract_latest_message(FakeTailer(lines), 'Me', app)

    assert msg == 'rotate B'
    assert channel == 'team'
    assert name == 'Babs'
    assert list(app.roster) == ['Babs']


# --- attribute_message: optional "[Name] said:" prefix -----------------------

class _AttribApp:
    def __init__(self, on):
        self.attribute_speakers = on


class _Area:
    def __init__(self, opts_in=True):
        self.attribute_speaker = opts_in


def test_attribute_message_prefixes_when_enabled_and_area_opts_in():
    out = core.attribute_message('hello', 'Bob', _AttribApp(True), _Area(opts_in=True))
    assert out == '[Bob] said: hello'


def test_attribute_message_unchanged_when_disabled():
    out = core.attribute_message('hello', 'Bob', _AttribApp(False), _Area(opts_in=True))
    assert out == 'hello'


def test_attribute_message_unchanged_when_area_opts_out():
    # e.g. the Command Bot, whose "!ping" must stay at the start of the line.
    out = core.attribute_message('!ping', 'Bob', _AttribApp(True), _Area(opts_in=False))
    assert out == '!ping'


def test_attribute_message_unchanged_without_a_name():
    out = core.attribute_message('hello', None, _AttribApp(True), _Area(opts_in=True))
    assert out == 'hello'


def test_attribute_message_defaults_to_opt_in_when_flag_missing():
    # An area with no attribute_speaker attribute is treated as opting in.
    out = core.attribute_message('hello', 'Bob', _AttribApp(True), object())
    assert out == '[Bob] said: hello'


# --- chat_command_lines: str|list -> say/say_team cfg lines -------------------

def test_chat_command_lines_str_all_channel():
    lines = core.chat_command_lines('hello', 'all', char_limit=221)
    assert lines == ['say "hello"']


def test_chat_command_lines_list_team_channel():
    lines = core.chat_command_lines(['---', 'hi'], 'team', char_limit=221)
    assert lines == ['say_team "---"', 'say_team "hi"']


def test_chat_command_lines_cleans_and_chunks():
    # Quotes -> '', newlines -> space, and split at the char limit.
    lines = core.chat_command_lines('ab"c\nd' + 'x' * 3, 'all', char_limit=4)
    # cleaned text: ab''c d xxx  -> first 4 chars then the rest
    assert lines[0] == 'say "ab\'\'"'
    assert all(s.startswith('say "') for s in lines)


def test_chat_command_lines_skips_empty():
    assert core.chat_command_lines('', 'all', char_limit=221) == []
    assert core.chat_command_lines(['', 'x'], 'all', char_limit=221) == ['say "x"']


# --- cooldown_active: the global reply cooldown gate -------------------------

class _CooldownApp:
    def __init__(self, enabled, ms, last):
        self.cooldown_enabled = enabled
        self.cooldown_ms = ms
        self.last_reply_at = last


def test_cooldown_active_when_enabled_and_within_window():
    app = _CooldownApp(enabled=True, ms=3000, last=100.0)
    assert core.cooldown_active(app, 101.0) is True    # 1000 ms elapsed < 3000
    assert core.cooldown_active(app, 104.0) is False   # 4000 ms elapsed >= 3000


def test_cooldown_inactive_when_disabled():
    app = _CooldownApp(enabled=False, ms=3000, last=100.0)
    assert core.cooldown_active(app, 100.0) is False   # disabled -> never blocks


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
