"""Tests for system.hotkey.HotkeyManager: register / clear / availability.

Run with:  venv\\Scripts\\python -m pytest tests/test_hotkey.py
(or plain `python tests/test_hotkey.py` to run them without pytest).
"""
import os
import sys

# Make the application package layout (src/) importable when run from anywhere.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from system import hotkey


class FakeKeyboard:
    """Minimal stand-in for the `keyboard` module: records add/remove calls."""

    def __init__(self):
        self.added = []      # list of (key, callback)
        self.removed = []    # list of handlers passed to remove_hotkey
        self._next = 0

    def add_hotkey(self, key, callback):
        self.added.append((key, callback))
        self._next += 1
        return f'handler-{self._next}'

    def remove_hotkey(self, handler):
        self.removed.append(handler)


def _with_keyboard(fake):
    """Swap the module-level `keyboard` and return the original to restore."""
    original = hotkey.keyboard
    hotkey.keyboard = fake
    return original


# --- keyboard library unavailable -------------------------------------------

def test_unavailable_when_keyboard_missing():
    original = _with_keyboard(None)
    try:
        mgr = hotkey.HotkeyManager()
        assert mgr.available is False
        assert mgr.rebind('f8') is False     # can't register without the lib
        assert mgr.rebind('') is True        # clearing is always fine
        mgr.clear()                          # safe no-op
    finally:
        hotkey.keyboard = original


def test_rebind_false_without_callback():
    fake = FakeKeyboard()
    original = _with_keyboard(fake)
    try:
        mgr = hotkey.HotkeyManager()         # bind_callback never called
        assert mgr.rebind('f8') is False
        assert fake.added == []              # never tried to register
    finally:
        hotkey.keyboard = original


# --- normal registration lifecycle ------------------------------------------

def test_rebind_registers_with_callback():
    fake = FakeKeyboard()
    original = _with_keyboard(fake)
    try:
        mgr = hotkey.HotkeyManager()
        cb = lambda: None
        mgr.bind_callback(cb)

        assert mgr.available is True
        assert mgr.rebind('f8') is True
        assert fake.added == [('f8', cb)]
        assert fake.removed == []           # nothing to remove the first time
    finally:
        hotkey.keyboard = original


def test_rebind_removes_previous_handler():
    fake = FakeKeyboard()
    original = _with_keyboard(fake)
    try:
        mgr = hotkey.HotkeyManager()
        mgr.bind_callback(lambda: None)

        mgr.rebind('f8')                     # -> handler-1
        mgr.rebind('home')                   # should remove handler-1 first

        assert fake.removed == ['handler-1']
        assert [k for k, _ in fake.added] == ['f8', 'home']
    finally:
        hotkey.keyboard = original


def test_clear_removes_and_is_idempotent():
    fake = FakeKeyboard()
    original = _with_keyboard(fake)
    try:
        mgr = hotkey.HotkeyManager()
        mgr.bind_callback(lambda: None)
        mgr.rebind('f8')                     # -> handler-1

        mgr.clear()
        mgr.clear()                          # second clear must not re-remove

        assert fake.removed == ['handler-1']
    finally:
        hotkey.keyboard = original


def test_empty_rebind_clears_existing():
    fake = FakeKeyboard()
    original = _with_keyboard(fake)
    try:
        mgr = hotkey.HotkeyManager()
        mgr.bind_callback(lambda: None)
        mgr.rebind('f8')                     # -> handler-1

        assert mgr.rebind('') is True        # clears, registers nothing new
        assert fake.removed == ['handler-1']
        assert len(fake.added) == 1
    finally:
        hotkey.keyboard = original


def test_remove_swallows_stale_handler_errors():
    class RaisingKeyboard(FakeKeyboard):
        def remove_hotkey(self, handler):
            raise KeyError(handler)          # keyboard raises if already gone

    fake = RaisingKeyboard()
    original = _with_keyboard(fake)
    try:
        mgr = hotkey.HotkeyManager()
        mgr.bind_callback(lambda: None)
        mgr.rebind('f8')
        mgr.clear()                          # must not propagate the KeyError
    finally:
        hotkey.keyboard = original


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
