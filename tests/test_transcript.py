"""Tests for the shared conversation transcript shown under the AI areas' controls.

Run with:  venv\\Scripts\\python -m pytest tests/test_transcript.py
(or plain `python tests/test_transcript.py` to run them without pytest).

Only the state side is exercised -- record/clear/trim and the speaker-prefix
parsing. ``build()`` is widgets, and needs a live NiceGUI client.
"""
import os
import sys

# Make the application package layout (src/) importable when run from anywhere.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ui.transcript import Transcript, split_speaker


def test_record_keeps_message_and_reply():
    t = Transcript()
    t.record('ez noob', 'sit down')
    assert len(t.entries) == 1
    assert (t.entries[0].who, t.entries[0].said, t.entries[0].replied) == ('Them', 'ez noob', 'sit down')


def test_record_bumps_version_so_the_card_redraws():
    t = Transcript()
    before = t.version
    t.record('hi', 'hey')
    assert t.version != before


def test_record_splits_the_attributed_speaker_prefix():
    t = Transcript()
    t.record('[SomeGuy] said: ez noob', 'sit down')
    assert (t.entries[0].who, t.entries[0].said) == ('SomeGuy', 'ez noob')


def test_split_speaker_falls_back_when_unprefixed():
    assert split_speaker('just a message') == ('Them', 'just a message')
    assert split_speaker('') == ('Them', '')


def test_split_speaker_keeps_a_colon_in_the_message():
    # The prefix is non-greedy, so "said: " in the text itself can't fool it.
    assert split_speaker('[Guy] said: ratio: 0-14') == ('Guy', 'ratio: 0-14')


def test_multi_line_reply_is_flattened_for_display():
    t = Transcript()
    t.record('!help', ['line one', 'line two'])
    assert t.entries[0].replied == 'line one\nline two'


def test_entries_trim_to_the_window_newest_kept():
    t = Transcript(max_entries=2)
    for i in range(5):
        t.record(f'msg {i}', f'reply {i}')
    assert len(t.entries) == 2
    assert t.entries[0].said == 'msg 3'
    assert t.entries[-1].said == 'msg 4'


def test_default_window_is_the_last_three_exchanges():
    t = Transcript()
    for i in range(6):
        t.record(f'msg {i}', f'reply {i}')
    assert [e.said for e in t.entries] == ['msg 3', 'msg 4', 'msg 5']


def test_clear_empties_and_bumps_version():
    t = Transcript()
    t.record('hi', 'hey')
    version = t.version
    t.clear()
    assert t.entries == []
    assert t.version != version


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
