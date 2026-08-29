"""Tests for core.LogTailer: incremental reads of a growing console.log.

Run with:  venv\\Scripts\\python -m pytest tests/test_log_tailer.py
(or plain `python tests/test_log_tailer.py` to run them without pytest).
"""
import os
import sys
import tempfile

# Make the application package layout (src/) importable when run from anywhere.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import core


class GrowingLog:
    """A real file on disk that we append raw bytes to, like CS2 does."""

    def __init__(self):
        fd, self.path = tempfile.mkstemp(suffix='console.log')
        os.close(fd)
        self.tailer = core.LogTailer(self.path)

    def append(self, data: bytes):
        with open(self.path, 'ab') as f:
            f.write(data)

    def truncate(self):
        with open(self.path, 'wb'):
            pass

    def read(self):
        return list(self.tailer.new_lines())

    def close(self):
        os.remove(self.path)


# A real CS2 chat line: the name is terminated by U+200E, which is three bytes
# (E2 80 8E) in UTF-8 -- the only multi-byte character on most chat lines.
CHAT_LINE = '08/09 20:52:23  [ALL] twitch.tv/HNTR__1‎: hahaha\r\n'
LRM_OFFSET = CHAT_LINE.encode('utf-8').index(b'\xe2\x80\x8e')


def test_yields_only_complete_lines():
    log = GrowingLog()
    try:
        log.append(b'first\nsecond')
        assert log.read() == ['first']      # 'second' has no newline yet
        log.append(b' half\n')
        assert log.read() == ['second half']
    finally:
        log.close()


def test_multibyte_char_split_across_reads_survives():
    # CS2 flushes mid-character: the boundary lands inside the 3-byte U+200E.
    # The held-back bytes must be joined with the next read, not replaced with
    # U+FFFD -- otherwise the name-end marker is destroyed and the speaker is
    # rostered under a mangled name.
    raw = CHAT_LINE.encode('utf-8')
    for cut in (LRM_OFFSET + 1, LRM_OFFSET + 2):
        log = GrowingLog()
        try:
            log.append(raw[:cut])
            log.read()                       # partial line, nothing complete yet
            log.append(raw[cut:])
            assert log.read() == [CHAT_LINE.rstrip('\r\n')], f'cut at +{cut - LRM_OFFSET}'
        finally:
            log.close()


def test_split_name_still_rosters_the_clean_name():
    # End to end: a mid-character flush must not create a second roster entry.
    class FakeApp:
        roster = None
        roster_version = 0

    raw = CHAT_LINE.encode('utf-8')
    log = GrowingLog()
    app = FakeApp()
    app.roster = {}
    try:
        log.append(raw[:LRM_OFFSET + 1])
        core.extract_latest_message(log.tailer, 'fast typer', app)
        log.append(raw[LRM_OFFSET + 1:])
        msg, channel, name = core.extract_latest_message(log.tailer, 'fast typer', app)

        assert name == 'twitch.tv/HNTR__1'
        assert msg == 'hahaha'
        assert list(app.roster) == ['twitch.tv/HNTR__1']
    finally:
        log.close()


def test_truncation_resets_offset_and_decode_state():
    # CS2 recreates console.log on launch; a held-back partial character from
    # the old file must not be prepended to the new one.
    log = GrowingLog()
    try:
        log.append(b'old line\n' + b'\xe2\x80')   # trailing partial character
        assert log.read() == ['old line']
        log.truncate()
        log.append(b'new line\n')
        assert log.read() == ['new line']
    finally:
        log.close()


def test_seek_to_end_skips_existing_content():
    log = GrowingLog()
    try:
        log.append(b'already here\n')
        log.tailer.seek_to_end()
        assert log.read() == []
        log.append(b'brand new\n')
        assert log.read() == ['brand new']
    finally:
        log.close()


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
