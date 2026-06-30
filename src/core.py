"""The provider-agnostic chat loop: read new console.log lines, ask the active
area to generate a reply, and type it back into CS2.

Knows nothing about any specific AI provider or any widget -- it reads
everything it needs from AppState and calls ``app.active_area.generate(...)``.
"""
import asyncio
import logging
import os
import random
import time
import traceback

import pydirectinput

from system.winutil import get_foreground_window_title
from ui.ui_util import notify_and_log

logger = logging.getLogger(__name__)

ALL_CHAT_MARKER = '  [ALL] '
# CS2 tags team chat with these instead of [ALL]; we reply in the same channel.
TEAM_CHAT_MARKERS = ('  [T] ', '  [CT] ')
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


def _channel_for(line: str):
    """Return (channel, marker) for a chat line: ('all'|'team', the matched
    marker), or (None, None) if the line isn't an answerable chat line."""
    if ALL_CHAT_MARKER in line:
        return 'all', ALL_CHAT_MARKER
    for marker in TEAM_CHAT_MARKERS:
        if marker in line:
            return 'team', marker
    return None, None


def extract_latest_message(tailer: LogTailer, steam_nick: str, app):
    """Drain the tailer and return the newest answerable chat line as
    ``(message, channel, name)`` where channel is 'all' or 'team' and name is the
    clean display name of the speaker.

    Always consumes all new lines so the byte offset stays current even when the
    bot is off. Every speaker (except us) is registered in ``app.roster`` with a
    default of "respond" the first time they're seen. Messages from people whose
    roster toggle is off are skipped, so we fall through to the newest message
    from someone still allowed.

    Returns (None, None, None) if there's nothing to answer.
    """
    latest = None
    latest_channel = None
    latest_name = None
    for line in tailer.new_lines():
        channel, marker = _channel_for(line)
        if channel is None:
            continue

        name_part, _, message = line.partition(': ')
        if not message:
            continue

        # Don't respond to our own messages.
        if steam_nick and steam_nick in name_part:
            continue

        # The display name follows the channel marker; cut at the U+200E that CS2
        # appends after it so the name is clean and identical alive or "[DEAD]".
        raw_name = name_part.partition(marker)[2]
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
            latest_channel = channel
            latest_name = name
    return latest, latest_channel, latest_name


def attribute_message(message: str, name, app, area) -> str:
    """Optionally prefix ``message`` with the speaker's name for AI chatbots.

    Returns the message unchanged unless the global ``attribute_speakers`` setting
    is on, a ``name`` is known, and the active ``area`` opts in via its
    ``attribute_speaker`` flag. Areas that parse or transform the raw text (the
    Command Bot, Reverser and Mimic) opt out so the prefix can't break them.
    """
    if app.attribute_speakers and name and getattr(area, 'attribute_speaker', True):
        return f'[{name}] said: {message}'
    return message


def chat_command_lines(reply, channel: str, char_limit: int):
    """Turn a reply into the ordered message.cfg command lines to write.

    ``reply`` is a str (one chat line) or a list of strings (each its own chat
    line, e.g. the !help block). Each line is cleaned so it sits safely inside a
    quoted console command (" -> '', newline -> space), split into <=char_limit
    chunks, and prefixed with the channel verb: 'say' for all-chat, 'say_team'
    for team chat. Empty/whitespace-only lines are skipped.
    """
    verb = 'say_team' if channel == 'team' else 'say'
    messages = [reply] if isinstance(reply, str) else list(reply)
    lines = []
    for msg in messages:
        clean = msg.replace('"', "''").replace('\n', ' ')
        if not clean:
            continue
        for i in range(0, len(clean), char_limit):
            lines.append(f'{verb} "{clean[i:i + char_limit]}"')
    return lines


async def send_to_game(reply, app, channel: str = 'all') -> None:
    """Clean, chunk and type a reply into CS2 via the message.cfg + bind trick.

    ``reply`` may be a str or a list of strings; each resulting cfg line is
    written and execed in turn. ``channel`` selects say vs say_team.
    """
    lines = chat_command_lines(reply, channel, app.chat_char_limit)
    if not lines:
        return

    # "Thinking" pause before responding: a fixed base plus random jitter on top.
    delay_ms = app.response_delay_ms + random.uniform(0, max(0, app.response_jitter_ms))
    if delay_ms > 0:
        await asyncio.sleep(delay_ms / 1000)

    for line in lines:
        with open(app.exec_path, 'w', encoding='utf-8') as f:
            f.write(line)
        app.cfg_written = True

        # Don't send keypresses to other windows.
        if get_foreground_window_title() == 'Counter-Strike 2':
            # Auto-press the bind key, or leave it for the user (exec light shows when ready).
            if app.auto_press:
                pydirectinput.write(app.bind_key)
            await asyncio.sleep(app.chat_delay)

    # Response output is now in message.cfg: exec light goes green.
    set_exec_state(app, True)


def write_message_cfg(reply, app, channel: str = 'all') -> bool:
    """Write a whole reply to message.cfg as a single file (every say line at once).

    Unlike ``send_to_game``, which writes and execs one line at a time for live
    replies (relying on a keypress + delay between lines while CS2 is focused),
    this lays down all lines together so one in-game ``exec`` sends the whole
    block. Used by the Command Bot's "Send help to chat" button, a manual
    kickoff that runs while the GUI -- not CS2 -- is the foreground window.

    Returns True if anything was written.
    """
    lines = chat_command_lines(reply, channel, app.chat_char_limit)
    if not lines:
        return False
    with open(app.exec_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    app.cfg_written = True
    set_exec_state(app, True)
    return True


def set_exec_state(app, ready: bool) -> None:
    """Flip the exec light and notify the GUI only when the state changes.

    Green (ready=True) once a response has been written to message.cfg; red
    (ready=False) while a reply is being processed.
    """
    if ready != app.can_exec:
        app.can_exec = ready
        if app.exec_state_cb is not None:
            app.exec_state_cb(ready)


def cooldown_active(app, now: float) -> bool:
    """True when the global reply cooldown is on and hasn't elapsed yet.

    ``now`` is a ``time.monotonic()`` value compared against ``last_reply_at``.
    A single cooldown applies across every area, set in Settings > Chatbot.
    """
    return app.cooldown_enabled and (now - app.last_reply_at) * 1000 < app.cooldown_ms


def _next_event(app):
    """Pop the newest pending GSI event and drop the rest (stale taunts are
    worse than none -- an ace shout three rounds late just looks broken)."""
    if not app.gsi_events:
        return None
    event = app.gsi_events.pop()   # newest
    app.gsi_events.clear()
    return event


async def _react_to_event(app, area, event) -> None:
    """Generate and send a taunt for a GSI event via the same path as chat."""
    set_exec_state(app, False)
    try:
        logger.debug(f"[{area.key}] reacting to event: {event.kind}")
        reply = await area.generate_event(event, app)
    except Exception as e:
        logger.error(f"Event handler '{area.key}' failed: {e}")
        logger.error(traceback.format_exc())
        notify_and_log(f'Failed to react to a game event: {e}', type='negative')
        return
    if not reply:
        return
    await send_to_game(reply, app, 'all')
    app.last_reply_at = time.monotonic()


async def handle_tick(app) -> None:
    """One timer tick: extract -> generate -> send."""
    # Always drain the tailer so the offset (and roster) stays current even while off.
    message, channel, name = extract_latest_message(app.tailer, app.steam_nick, app)

    if not app.powered_on or app.active_area is None:
        return

    area = app.active_area
    ready, _ = area.is_ready()
    if not ready:
        return

    # Global cooldown applies to both event taunts and chat replies.
    if cooldown_active(app, time.monotonic()):
        return

    # GSI game-event reactions take priority over chat: they're time-sensitive
    # (an ace taunt is worthless several rounds later). Only areas that opt in
    # (consumes_events) ever pop the queue.
    if getattr(area, 'consumes_events', False):
        event = _next_event(app)
        if event is not None:
            await _react_to_event(app, area, event)
            return

    if message is None:
        return

    # Optionally tag the message with who said it, so AI chatbots can track the
    # speaker. Areas that parse/transform the raw text opt out (see helper).
    message = attribute_message(message, name, app, area)

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

    await send_to_game(reply, app, channel)
    app.last_reply_at = time.monotonic()
