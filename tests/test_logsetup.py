"""Tests for logsetup: the switch that decides whether a log file exists.

Run with:  venv\\Scripts\\python -m pytest tests/test_logsetup.py
(or plain `python tests/test_logsetup.py` to run them without pytest).
"""
import logging
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import logsetup


class Sandbox:
    """A temp directory plus a clean root logger, restored on close.

    logsetup writes to the root logger and keeps module state (the live
    handler, and whether this run already started the file), so each test needs
    both put back the way it found them.
    """

    def __init__(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, logsetup.LOG_FILENAME)
        root = logging.getLogger()
        self._saved = list(root.handlers)
        root.handlers.clear()
        logsetup._handler = None
        logsetup._truncated = False

    def write(self, message: str) -> None:
        logging.getLogger('test').warning(message)

    def contents(self) -> str:
        with open(self.path, encoding='utf-8') as f:
            return f.read()

    def close(self):
        logsetup.set_enabled(False)
        root = logging.getLogger()
        root.handlers.clear()
        root.handlers.extend(self._saved)
        if os.path.exists(self.path):
            os.remove(self.path)
        os.rmdir(self.dir)


def test_disabled_writes_no_file():
    box = Sandbox()
    try:
        assert logsetup.configure(box.path, False) is False
        box.write('nothing should keep this')
        assert not os.path.exists(box.path), 'a log file appeared while the setting was off'
        assert logsetup.is_enabled() is False
    finally:
        box.close()


def test_enabled_writes_the_file():
    box = Sandbox()
    try:
        assert logsetup.configure(box.path, True) is True
        box.write('hello from the test')
        assert 'hello from the test' in box.contents()
    finally:
        box.close()


def test_turning_it_off_stops_writing():
    box = Sandbox()
    try:
        logsetup.configure(box.path, True)
        box.write('before')
        logsetup.set_enabled(False)
        box.write('after')

        text = box.contents()
        assert 'before' in text
        assert 'after' not in text, 'lines were still written after the switch went off'
        assert logsetup.is_enabled() is False
    finally:
        box.close()


def test_turning_it_back_on_keeps_the_earlier_half():
    # The file is truncated once per run, not once per toggle: the lines that
    # led up to the problem are the ones worth keeping.
    box = Sandbox()
    try:
        logsetup.configure(box.path, True)
        box.write('first half')
        logsetup.set_enabled(False)
        logsetup.set_enabled(True)
        box.write('second half')

        text = box.contents()
        assert 'first half' in text
        assert 'second half' in text
    finally:
        box.close()


def test_a_second_enable_does_not_add_a_second_handler():
    box = Sandbox()
    try:
        logsetup.configure(box.path, True)
        logsetup.set_enabled(True)
        box.write('once only')
        assert box.contents().count('once only') == 1
    finally:
        box.close()


def test_unwritable_path_reports_failure_instead_of_raising():
    box = Sandbox()
    try:
        missing = os.path.join(box.dir, 'no-such-folder', logsetup.LOG_FILENAME)
        assert logsetup.configure(missing, True) is False
        assert logsetup.is_enabled() is False
        box.write('this has nowhere to go')      # must not raise
    finally:
        box.close()


def test_log_path_reports_where_the_file_goes():
    box = Sandbox()
    try:
        logsetup.configure(box.path, False)
        assert logsetup.log_path() == box.path
    finally:
        box.close()


def test_default_log_path_sits_next_to_the_settings_file():
    import app_state

    assert os.path.dirname(app_state.default_log_path()) == \
           os.path.dirname(app_state.default_settings_path())
    assert os.path.basename(app_state.default_log_path()) == logsetup.LOG_FILENAME


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
