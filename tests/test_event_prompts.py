"""Tests for areas.event_prompts.event_to_prompt: a GSI TiltEvent -> a one-line
instruction string for an AI brain.

Run with:  venv\\Scripts\\python -m pytest tests/test_event_prompts.py
(or plain `python tests/test_event_prompts.py` to run them without pytest).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from areas.event_prompts import event_to_prompt, EVENT_PROMPTS
from system.gsi import TiltEvent


def test_every_known_kind_has_a_nonempty_prompt():
    for kind in EVENT_PROMPTS:
        out = event_to_prompt(TiltEvent(kind, {'kills': 4, 'hp': 9}))
        assert isinstance(out, str) and out.strip()


def test_multi_kill_interpolates_kill_count():
    out = event_to_prompt(TiltEvent('MULTI_KILL', {'kills': 4}))
    assert '4' in out


def test_low_hp_interpolates_hp():
    out = event_to_prompt(TiltEvent('LOW_HP_SURVIVAL', {'hp': 7}))
    assert '7' in out


def test_unknown_kind_falls_back_to_generic_line():
    out = event_to_prompt(TiltEvent('NOPE', {}))
    assert isinstance(out, str) and out.strip()


def test_missing_data_token_does_not_raise():
    # MULTI_KILL template wants {kills}; with no data it must degrade, not crash.
    out = event_to_prompt(TiltEvent('MULTI_KILL', {}))
    assert isinstance(out, str) and out.strip()


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
