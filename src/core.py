"""The provider-agnostic chat loop: read new console.log lines, ask the active
area to generate a reply, and type it back into CS2.

Knows nothing about any specific AI provider or any widget -- it reads
everything it needs from AppState and calls ``app.active_area.generate(...)``.
"""
import asyncio
import logging
import os
import random
import traceback

import pydirectinput

from system.winutil import get_foreground_window_title
from ui.ui_util import notify_and_log

logger = logging.getLogger(__name__)

ALL_CHAT_MARKER = '  [ALL] '
# CS2 appends a LEFT-TO-RIGHT MARK directly after each chat name, before any
# status decoration like " [DEAD]". It's a reliable end-of-name delimiter, so we
# cut there to get a clean name that's stable whether the player is alive or dead.
NAME_END_MARKER = '‎'


class LogTailer:
    """Incrementally reads a growing log file, yielding only newly-appended lines.

    Remembers a byte offset between calls so each tick reads just the bytes
    added since the last read (no whole-file re-read). Handles CS2 recreating
    ``console.log`` on launch: if the file shrinks below the stored offset we
    reset to the start. A partially-written final line is buffered and not
    yielded until its newline arrives.
    """

    def __init__(self, path: str):
        self.path = path
        self.offset = 0
        self._buffer = ''

    def seek_to_end(self) -> None:
        """Skip whatever is already in the file (don't replay old chat)."""
        try:
            self.offset = os.path.getsize(self.path)
        except OSError:
            self.offset = 0
        self._buffer = ''

    def new_lines(self):
        """Yield each complete line appended since the previous call."""
        try:
            size = os.path.getsize(self.path)
        except OSError:
            return  # file not present yet

        if size < self.offset:  # rotation / truncation -> start over
            self.offset = 0
            self._buffer = ''

        if size == self.offset:
            return  # nothing new

        try:
            with open(self.path, 'rb') as f:
                f.seek(self.offset)
                data = f.read()
                self.offset = f.tell()
        except OSError:
            return

        text = self._buffer + data.decode('utf-8', errors='replace')
        *complete, self._buffer = text.split('\n')
        for line in complete:
            yield line.rstrip('\r')


def extract_latest_message(tailer: LogTailer, steam_nick: str, app):
    """Drain the tailer and return the newest answerable [ALL] chat line.

    Always consumes all new lines so the byte offset stays current even when the
    bot is off. Every speaker (except us) is registered in ``app.roster`` with a
    default of "respond" the first time they're seen, so the Settings list keeps
    a running tally. Messages from people whose roster toggle is off are skipped,
    so we fall through to the newest message from someone still allowed.

    Returns that message text, or None if there's nothing to answer.
    """
    latest = None
    for line in tailer.new_lines():
        if ALL_CHAT_MARKER not in line:
            continue

        name_part, _, message = line.partition(': ')
        if not message:
            continue

        # Don't respond to our own messages.
        if steam_nick and steam_nick in name_part:
            continue

        # The display name follows the [ALL] marker; cut at the U+200E that CS2
        # appends after it so the name is clean and identical alive or "[DEAD]".
        raw_name = name_part.partition(ALL_CHAT_MARKER)[2]
        name = raw_name.split(NAME_END_MARKER, 1)[0].strip()
        if not name:
            continue

        # Register newcomers (default: respond), keeping insertion order.
        if name not in app.roster:
            app.roster[name] = True
            app.roster_version += 1

        # Only the newest message from an allowed speaker is answerable.
        if app.roster[name]:
            latest = message
    return latest


async def send_to_game(text: str, app) -> None:
    """Clean, chunk and type a reply into CS2 via the message.cfg + bind trick."""
    text = text.replace('"', "''").replace('\n', ' ')

    # "Thinking" pause before responding: a fixed base plus random jitter on top.
    delay_ms = app.response_delay_ms + random.uniform(0, max(0, app.response_jitter_ms))
    if delay_ms > 0:
        await asyncio.sleep(delay_ms / 1000)

    chunks = [text[i:i + app.chat_char_limit] for i in range(0, len(text), app.chat_char_limit)]

    for chunk in chunks:
        with open(app.exec_path, 'w', encoding='utf-8') as f:
            f.write(f'say "{chunk}"')
        app.cfg_written = True

        # Don't send keypresses to other windows.
        if get_foreground_window_title() == 'Counter-Strike 2':
            # Auto-press the bind key, or leave it for the user (exec light shows when ready).
            if app.auto_press:
                pydirectinput.write(app.bind_key)
            await asyncio.sleep(app.chat_delay)

    # Response output is now in message.cfg: exec light goes green.
    set_exec_state(app, True)


def set_exec_state(app, ready: bool) -> None:
    """Flip the exec light and notify the GUI only when the state changes.

    Green (ready=True) once a response has been written to message.cfg; red
    (ready=False) while a reply is being processed.
    """
    if ready != app.can_exec:
        app.can_exec = ready
        if app.exec_state_cb is not None:
            app.exec_state_cb(ready)


async def handle_tick(app) -> None:
    """One timer tick: extract -> generate -> send."""
    # Always drain the tailer so the offset (and roster) stays current even while off.
    message = extract_latest_message(app.tailer, app.steam_nick, app)

    if not app.powered_on or app.active_area is None:
        return

    if message is None:
        return

    area = app.active_area
    ready, _ = area.is_ready()
    if not ready:
        return

    # We're committing to generate + send a reply: exec light goes red until
    # the response lands in message.cfg.
    set_exec_state(app, False)

    try:
        logger.debug(f"[{area.key}] generating reply to: {message}")
        reply = await area.generate(message, app)
    except Exception as e:
        logger.error(f"Handler '{area.key}' failed: {e}")
        logger.error(traceback.format_exc())
        notify_and_log(f'Failed to generate a reply: {e}', type='negative')
        return

    if not reply:
        return

    await send_to_game(reply, app)
