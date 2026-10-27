"""The provider-agnostic chat loop: read new console.log lines, ask the active
area to generate a reply, and type it back into CS2.

Knows nothing about any specific AI provider or any widget -- it reads
everything it needs from AppState and calls ``app.active_area.generate(...)``.
"""
import asyncio
import codecs
import logging
import os
import random
import time
import traceback

import pydirectinput

import rules
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

# Throttle for the per-read log line. The loop ticks ten times a second, so an
# unthrottled read log would be most of the debug file.
READ_LOG_SECONDS = 1.0

# CS2 drops a chat line that an account sends too soon after its previous one,
# with no error. In console.log (2026-10-10), a reply sent 0-0.1 s after the
# account's own line never showed, and one sent 0.5 s after did. After a chat
# line from steam_nick (you), each keypress waits until this much time passes.
# Replies to other players go out at once.
MIN_CHAT_GAP = 0.6


class LogTailer:
    """Incrementally reads a growing log file, yielding only newly-appended lines.

    Remembers a byte offset between calls so each tick reads just the bytes
    added since the last read (no whole-file re-read). Handles CS2 recreating
    ``console.log`` on launch: if the file shrinks below the stored offset we
    reset to the start. A partially-written final line is buffered and not
    yielded until its newline arrives.

    Decoding is incremental for the same reason. We poll ten times a second
    while CS2 flushes whenever it likes, so a read routinely stops in the
    middle of a multi-byte UTF-8 character -- most often the U+200E that ends
    every chat name. Decoding each chunk on its own would turn those split
    bytes into U+FFFD and destroy the name delimiter, so the incremental
    decoder holds them back until the next read completes the character.
    """

    def __init__(self, path: str):
        self.path = path
        self.offset = 0
        self._buffer = ''
        self._decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
        # Diagnostics. "console.log never appears" and "console.log stops
        # growing" are the two ways the bot goes quiet with nothing else to
        # show for it, so both are logged -- but only when the state changes,
        # because this runs ten times a second.
        self._present = None      # None = not checked yet, then True/False
        self._last_read_log = 0.0

    def seek_to_end(self) -> None:
        """Skip whatever is already in the file (don't replay old chat)."""
        try:
            self.offset = os.path.getsize(self.path)
        except OSError:
            self.offset = 0
        self._reset_read_state()

    def _reset_read_state(self) -> None:
        """Drop the partial line and any held-back partial character.

        Called whenever the next read won't continue from where the last one
        stopped (seek_to_end, or CS2 recreating the file), so leftovers from
        the old position can't be glued onto the new one.
        """
        self._buffer = ''
        self._decoder.reset()

    def new_lines(self):
        """Yield each complete line appended since the previous call."""
        try:
            size = os.path.getsize(self.path)
        except OSError as e:
            self._note_presence(False, str(e))
            return  # file not present yet
        self._note_presence(True, f'{size} bytes')

        if size < self.offset:  # rotation / truncation -> start over
            logger.info(f'console.log shrank to {size} bytes (was at {self.offset}); '
                        'CS2 recreated it. Reading from the start.')
            self.offset = 0
            self._reset_read_state()

        if size == self.offset:
            return  # nothing new

        try:
            with open(self.path, 'rb') as f:
                f.seek(self.offset)
                data = f.read()
                self.offset = f.tell()
        except OSError as e:
            self._log_throttled(logging.WARNING, f'Could not read {self.path}: {e}')
            return

        text = self._buffer + self._decoder.decode(data)
        *complete, self._buffer = text.split('\n')
        self._log_throttled(logging.DEBUG,
                            f'console.log: +{len(data)} bytes, {len(complete)} lines '
                            f'(offset now {self.offset})')
        for line in complete:
            yield line.rstrip('\r')

    def _note_presence(self, present: bool, detail: str) -> None:
        """Log console.log appearing or vanishing -- once per change, not per tick.

        A missing console.log is the single most common reason the bot never
        answers, and the fix is always the same, so the warning carries it.
        """
        if present == self._present:
            return
        self._present = present
        if present:
            logger.info(f'Reading CS2 chat from {self.path} ({detail}).')
        else:
            logger.warning(f'No console.log to read at {self.path} ({detail}). CS2 only '
                           'writes it with -condebug in its Steam launch options, and it '
                           'appears when the game starts.')

    def _log_throttled(self, level: int, message: str) -> None:
        """Log at most once a second.

        Reads happen on every 0.1s tick, and a busy match writes to console.log
        constantly. Throttling keeps "is the file still growing?" answerable
        without burying the interesting lines.
        """
        now = time.monotonic()
        if now - self._last_read_log < READ_LOG_SECONDS:
            return
        self._last_read_log = now
        logger.log(level, message)


def _channel_for(line: str):
    """Return (channel, marker) for a chat line: ('all'|'team', the matched
    marker), or (None, None) if the line isn't an answerable chat line."""
    if ALL_CHAT_MARKER in line:
        return 'all', ALL_CHAT_MARKER
    for marker in TEAM_CHAT_MARKERS:
        if marker in line:
            return 'team', marker
    return None, None


def extract_latest_message(tailer: LogTailer, steam_nick: str, app, queues=None,
                           answer_self=False, on_shown=None):
    """Drain the tailer and return the newest answerable chat line as
    ``(message, channel, name)`` where channel is 'all' or 'team' and name is the
    clean display name of the speaker.

    Always consumes all new lines so the byte offset stays current even when the
    bot is off. Every speaker (except us) is registered in ``app.roster`` with a
    default of "respond" the first time they're seen. Messages from people whose
    roster toggle is off are skipped, so we fall through to the newest message
    from someone still allowed.

    ``queues`` is the active area's ``queues_message`` (or None). A line it
    claims goes onto ``app.chat_queue`` to be answered in arrival order, and
    takes no part in the newest-wins pick.

    A line from ``steam_nick`` (you) starts the chat gap. The echo of a line the
    app sent is never answered. Anything else you type is answered only when
    ``answer_self`` is set (the active area's ``answers_own_lines``); it is
    never added to the roster.

    ``on_shown`` is the active area's ``reply_shown`` (or None). The echo of the
    last chunk of a reply calls it with that reply.

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

        # A line from you: the next keypress keeps the chat gap after it. The
        # echo of our own reply is never answered (it also confirms a reply
        # waiting under Human Control). What you typed yourself is answered
        # only by areas that opt in (the Command Bot).
        own = bool(steam_nick) and steam_nick in name_part
        if own:
            app.last_chat_at = time.monotonic()
            if take_own_echo(app, message):
                logger.debug(f'Own reply reached {channel} chat: {message!r}')
                reply = take_shown_reply(app, message)
                if reply is not None and on_shown is not None:
                    on_shown(reply, time.monotonic())
                continue
            if not answer_self:
                logger.debug(f'Own message in {channel} chat, not answering: {message!r}')
                continue

        # The display name follows the channel marker; cut at the U+200E that CS2
        # appends after it so the name is clean and identical alive or "[DEAD]".
        raw_name = name_part.partition(marker)[2]
        name = raw_name.split(NAME_END_MARKER, 1)[0].strip()
        if not name:
            continue

        # Register newcomers (default: respond), keeping insertion order. You
        # are not a roster entry: you cannot mute yourself.
        if not own and name not in app.roster:
            app.roster[name] = True
            app.roster_version += 1
            logger.info(f'New player in chat: {name!r} (answering them by default)')
        allowed = own or app.roster[name]

        # Only the newest message from an allowed speaker is answerable --
        # unless the area queues it (the blackjack commands).
        if allowed and queues is not None and queues(message):
            app.chat_queue.append((message, channel, name))
            logger.debug(f'[{channel}] {name}: {message!r} (queued, '
                         f'{len(app.chat_queue)} waiting)')
        elif allowed:
            logger.debug(f'[{channel}] {name}: {message!r}')
            latest = message
            latest_channel = channel
            latest_name = name
        else:
            logger.debug(f'[{channel}] {name} is muted in Known Players, skipping: {message!r}')
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


def chat_message_chunks(reply, char_limit: int):
    """Turn a reply into the exact text chunks CS2 will show in chat.

    ``reply`` is a str (one chat line) or a list of strings (each its own chat
    line, e.g. the !help block). Each line is cleaned so it sits safely inside a
    quoted console command (" -> '', newline -> space) and split into
    <=char_limit pieces. Empty lines are skipped.

    The chunks are the text of the message itself, without the say verb, so
    Human Control can compare them against the chat lines that come back in
    console.log and know the reply reached the server.
    """
    messages = [reply] if isinstance(reply, str) else list(reply)
    chunks = []
    for msg in messages:
        clean = msg.replace('"', "''").replace('\n', ' ')
        if not clean:
            continue
        for i in range(0, len(clean), char_limit):
            chunks.append(clean[i:i + char_limit])
    return chunks


def chat_command_lines(reply, channel: str, char_limit: int):
    """Turn a reply into the ordered message.cfg command lines to write.

    Each chunk from ``chat_message_chunks`` gets the channel verb: 'say' for
    all-chat, 'say_team' for team chat.
    """
    verb = 'say_team' if channel == 'team' else 'say'
    return [f'{verb} "{chunk}"' for chunk in chat_message_chunks(reply, char_limit)]


def human_control(app) -> bool:
    """True while the human fires the reply (the auto-press switch is off)."""
    return not app.auto_press


async def send_to_game(reply, app, channel: str = 'all') -> None:
    """Clean, chunk and hand a reply to CS2 via the message.cfg + bind trick.

    ``reply`` may be a str or a list of strings. With auto-press on, each cfg
    line is written and execed in turn (one keypress per line). Under Human
    Control the whole reply is written at once so a single keypress sends all
    of it, and the chunks are remembered so the exec light can drop back to red
    once they appear in chat. ``channel`` selects say vs say_team.
    """
    chunks = chat_message_chunks(reply, app.chat_char_limit)
    if not chunks:
        logger.debug('Nothing left to send after cleaning the reply.')
        return
    verb = 'say_team' if channel == 'team' else 'say'
    lines = [f'{verb} "{chunk}"' for chunk in chunks]
    # The echo of the last chunk tells the area that the reply reached chat.
    app.shown_watch.append((chunks[-1], reply))

    if human_control(app):
        # One file, one exec: the human presses the bind key when they want to.
        # The "thinking" pause is skipped here on purpose -- it exists to keep an
        # instant reply from looking robotic in chat, and under Human Control the
        # person pressing the key already sets that timing. Waiting would only
        # hide a finished reply from them.
        logger.debug(f'Writing {len(chunks)} chunk(s) for {channel} chat as {verb!r} '
                     '(Human Control: no keypress)')
        if not _write_cfg(app, '\n'.join(lines) + '\n'):
            return
        app.pending_sends = list(chunks)
        logger.info(f'Reply is ready in message.cfg. Press {app.bind_key!r} in CS2 to send it.')
        set_exec_state(app, True)
        return

    # "Thinking" pause before responding: a fixed base plus random jitter on top.
    delay_ms = app.response_delay_ms + random.uniform(0, max(0, app.response_jitter_ms))
    logger.debug(f'Sending {len(chunks)} chunk(s) to {channel} chat as {verb!r} after '
                 f'{delay_ms:.0f}ms (key={app.bind_key!r})')
    if delay_ms > 0:
        await asyncio.sleep(delay_ms / 1000)

    for chunk, line in zip(chunks, lines):
        await _wait_for_chat_gap(app)
        if not _write_cfg(app, line):
            return

        # Don't send keypresses to other windows.
        title = get_foreground_window_title()
        if title == 'Counter-Strike 2':
            pydirectinput.write(app.bind_key)
            app.recent_sends.append(chunk)   # so its echo is not answered
            await asyncio.sleep(app.chat_delay)
        else:
            # The single most confusing failure: the reply is written, nothing
            # is typed, and nothing says why. Name the window that had focus.
            logger.warning(f'CS2 is not the focused window ({title!r}), so the '
                           f'{app.bind_key!r} keypress was skipped. This chunk stays in '
                           'message.cfg until the next reply overwrites it.')

    # Response output is now in message.cfg: exec light goes green.
    set_exec_state(app, True)


async def _wait_for_chat_gap(app) -> None:
    """Hold the next keypress until MIN_CHAT_GAP has passed since your last
    chat line (a line from steam_nick, see app.last_chat_at)."""
    wait = app.last_chat_at + MIN_CHAT_GAP - time.monotonic()
    if wait > 0:
        logger.debug(f'Holding the keypress {wait * 1000:.0f}ms: CS2 drops a chat line '
                     'that comes too soon after the last one.')
        await asyncio.sleep(wait)


def write_message_cfg(reply, app, channel: str = 'all') -> bool:
    """Write a whole reply to message.cfg as a single file (every say line at once).

    Unlike ``send_to_game``, which writes and execs one line at a time for live
    replies (relying on a keypress + delay between lines while CS2 is focused),
    this lays down all lines together so one in-game ``exec`` sends the whole
    block. Used by the Command Bot's "Send help to chat" button, a manual
    kickoff that runs while the GUI -- not CS2 -- is the foreground window.

    Returns True if anything was written.
    """
    chunks = chat_message_chunks(reply, app.chat_char_limit)
    if not chunks:
        return False
    verb = 'say_team' if channel == 'team' else 'say'
    if not _write_cfg(app, '\n'.join(f'{verb} "{chunk}"' for chunk in chunks) + '\n'):
        return False
    logger.info(f'Wrote {len(chunks)} chunk(s) to message.cfg for {channel} chat; '
                f'press {app.bind_key!r} in CS2 to send.')
    if human_control(app):
        app.pending_sends = list(chunks)
    else:
        app.recent_sends.extend(chunks)
    set_exec_state(app, True)
    return True


def _write_cfg(app, text: str) -> bool:
    """Write message.cfg, reporting a failure instead of raising into the tick.

    The chat loop runs inside a NiceGUI timer, where a raised OSError is easy to
    miss. A cfg folder that has moved or is locked is worth one clear line in
    the log and one notification, and the loop keeps running.
    """
    try:
        with open(app.exec_path, 'w', encoding='utf-8') as f:
            f.write(text)
    except OSError as e:
        notify_and_log(f'Could not write {app.exec_path}: {e}', type='negative')
        return False
    app.cfg_written = True
    return True


def clear_message_cfg(app) -> None:
    """Empty message.cfg so an early keypress cannot fire a stale reply.

    Only used under Human Control, where the file sits there until the human
    presses the bind key. A missing folder or a locked file is not worth
    stopping a reply for, so failures are logged and ignored.
    """
    try:
        with open(app.exec_path, 'w', encoding='utf-8') as f:
            f.write('')
    except OSError as e:
        logger.warning(f'Could not clear {app.exec_path}: {e}')


def begin_reply(app) -> None:
    """Start a reply: exec light red, and under Human Control an empty cfg.

    Called the moment the app commits to generating, for both chat replies and
    event taunts. The previous reply is dropped here (the newest reply wins),
    so anything still waiting in message.cfg goes away with it.
    """
    set_exec_state(app, False)
    if human_control(app):
        app.pending_sends = []
        clear_message_cfg(app)


def note_own_chat_line(app, text: str) -> bool:
    """Tick off one pending chunk when our own message shows up in chat.

    Under Human Control the exec light means "ready to fire", so it stays green
    until CS2 echoes the text we wrote. Matching the text (not just the nick)
    keeps your own typing from clearing a reply that is still waiting.

    Returns True if ``text`` matched a pending chunk.
    """
    pending = getattr(app, 'pending_sends', None)
    if not pending:
        return False
    clean = (text or '').strip()
    matched = False
    for index, chunk in enumerate(pending):
        if chunk.strip() == clean:
            del pending[index]
            matched = True
            logger.debug(f'Reply chunk reached chat; {len(pending)} still waiting.')
            break
    if not pending:
        logger.info('The whole reply reached chat: the exec light goes back to red.')
        set_exec_state(app, False)
    return matched


def take_own_echo(app, text: str) -> bool:
    """True if ``text`` is the echo of a line the app sent, not something you
    typed. Consumes the match: a pending Human Control chunk, or a recent
    auto-press send."""
    if note_own_chat_line(app, text):
        return True
    clean = (text or '').strip()
    for index, chunk in enumerate(app.recent_sends):
        if chunk.strip() == clean:
            del app.recent_sends[index]
            return True
    return False


def take_shown_reply(app, text: str):
    """The reply whose last chunk is ``text``, or None. Consumes the match."""
    clean = (text or '').strip()
    for index, (chunk, reply) in enumerate(app.shown_watch):
        if chunk.strip() == clean:
            del app.shown_watch[index]
            return reply
    return None


def set_exec_state(app, ready: bool) -> None:
    """Flip the exec light and notify the GUI only when the state changes.

    Green (ready=True) once a response has been written to message.cfg; red
    (ready=False) while a reply is being processed. Under Human Control green
    also means "not sent yet": the light goes red again once the message
    appears in chat (see ``note_own_chat_line``).
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
    if app.gsi_events:
        logger.debug(f'Dropped {len(app.gsi_events)} older game event(s) in favour of '
                     f'{event.kind}.')
    app.gsi_events.clear()
    return event


async def _react_to_event(app, area, event) -> None:
    """Generate and send a taunt for a GSI event via the same path as chat."""
    begin_reply(app)
    try:
        logger.debug(f"[{area.key}] reacting to event: {event.kind}")
        reply = await area.generate_event(event, app)
    except Exception as e:
        logger.error(f"Event handler '{area.key}' failed: {e}")
        logger.error(traceback.format_exc())
        notify_and_log(f'Failed to react to a game event: {e}', type='negative')
        return

    # Event taunts go through the same command-label pass as chat replies.
    ruled = rules.apply_rules(reply, app.rules)
    if ruled != reply:
        logger.info(f'A command rule silenced the {event.kind} taunt.' if not ruled
                    else f'A command rule rewrote the {event.kind} taunt to {ruled!r}')
    reply = ruled
    if not reply:
        logger.debug(f'No taunt sent for {event.kind}.')
        return
    await send_to_game(reply, app, 'all')
    app.last_reply_at = time.monotonic()


async def _run_timers(app, area) -> bool:
    """Send whatever the area's timers have due. True if a reply went out.

    Same path as a chat reply: exec light, command rules, send, cooldown.
    """
    generate_timed = getattr(area, 'generate_timed', None)
    if generate_timed is None:
        return False
    try:
        due = await generate_timed(app)
    except Exception as e:
        logger.error(f"Timer handler '{area.key}' failed: {e}")
        logger.error(traceback.format_exc())
        notify_and_log(f'Failed to send a timed message: {e}', type='negative')
        return False
    if not due:
        return False

    reply, channel = due
    logger.debug(f'[{area.key}] timer fired with {reply!r}')
    begin_reply(app)
    reply = rules.apply_rules(reply, app.rules)
    if not reply:
        logger.debug('A command rule silenced the timed message.')
        return False
    await send_to_game(reply, app, channel)
    app.last_reply_at = time.monotonic()
    return True


def _reply_waiting(app) -> bool:
    """True while a Human Control reply sits in message.cfg, not yet in chat.

    The queue and the area timers hold until it goes out: the next reply would
    overwrite it. Without a Steam nickname the app never sees its own lines come
    back, so nothing is held.
    """
    return human_control(app) and bool(app.steam_nick) and bool(app.pending_sends)


async def _answer_queue(app, area) -> bool:
    """Answer queued chat lines, oldest first, until one sends a reply.

    A line that gets no reply costs nothing, so the next one goes in the same
    tick. A blackjack move gets no reply, so every move typed in one tick
    locks in that tick. True if a reply went out.
    """
    while app.chat_queue:
        message, channel, name = app.chat_queue.popleft()
        # The tab may have changed since the line was queued.
        if not area.queues_message(message):
            logger.debug(f'Dropped queued {message!r}: the open tab does not queue it.')
            continue
        if await _answer_chat(app, area, message, channel, name):
            return True
    return False


async def _answer_chat(app, area, message, channel, name) -> bool:
    """Generate and send the area's reply to one chat line. True if sent."""
    # Who is talking and where, for areas that gate on identity or track a
    # player (the blackjack table). Set before generate() and
    # separate from the optional speaker prefix below, which command areas
    # opt out of.
    app.last_speaker = name or ''
    app.last_channel = channel or 'all'

    # Optionally tag the message with who said it, so AI chatbots can track the
    # speaker. Areas that parse/transform the raw text opt out (see helper).
    message = attribute_message(message, name, app, area)

    # We're committing to generate + send a reply: exec light goes red until
    # the response lands in message.cfg. Under Human Control this also empties
    # the cfg, so the newest reply is the only one you can fire.
    begin_reply(app)

    started = time.monotonic()
    try:
        logger.debug(f"[{area.key}] generating a reply to {message!r}")
        reply = await area.generate(message, app)
    except Exception as e:
        # The elapsed time separates "the API refused us" from "the API never
        # answered", which are different problems with the same symptom.
        logger.error(f"Handler '{area.key}' failed after "
                     f'{(time.monotonic() - started) * 1000:.0f}ms: {type(e).__name__}: {e}')
        logger.error(traceback.format_exc())
        notify_and_log(f'Failed to generate a reply: {e}', type='negative')
        return False

    logger.debug(f'[{area.key}] answered in {(time.monotonic() - started) * 1000:.0f}ms '
                 f'with {reply!r}')

    # Command labels the bot wrote into its own reply (e.g. "([SILENT])") are
    # resolved here, before anything is typed: a silencing rule returns None and
    # falls into the guard below, so no keystrokes and no cooldown are spent.
    ruled = rules.apply_rules(reply, app.rules)
    if ruled != reply:
        logger.info('A command rule silenced the reply.' if not ruled
                    else f'A command rule rewrote the reply to {ruled!r}')
    reply = ruled

    if not reply:
        logger.debug('Nothing to send: the area returned no reply, or a rule dropped it.')
        return False

    await send_to_game(reply, app, channel)
    app.last_reply_at = time.monotonic()
    return True


async def handle_tick(app) -> None:
    """One timer tick: extract -> generate -> send."""
    # Always drain the tailer so the offset (and roster) stays current even while
    # off. Only the area that answers may queue lines, and only while the bot is on.
    area = app.active_area if app.powered_on else None
    queues = getattr(area, 'queues_message', None)
    message, channel, name = extract_latest_message(
        app.tailer, app.steam_nick, app, queues,
        answer_self=getattr(area, 'answers_own_lines', False),
        on_shown=getattr(area, 'reply_shown', None))

    # Each guard below explains itself, but only when a message was actually
    # waiting: the loop ticks ten times a second and an idle tick tells nobody
    # anything. "Why did it not answer that?" is the question worth answering.
    if area is None:
        app.chat_queue.clear()
        if message is not None:
            logger.debug('Not answering %r: %s', message,
                         'the bot is switched off' if not app.powered_on
                         else 'the open tab does not answer chat (Settings is a utility tab)')
        return

    ready, reason = area.is_ready()
    if not ready:
        if message is not None:
            logger.warning(f"[{area.key}] is not ready ({reason or 'no reason given'}), "
                           f'so {message!r} goes unanswered.')
        return

    # Global cooldown applies to every reply. Queued lines and area timers wait
    # it out; the newest-wins chat line is dropped.
    now = time.monotonic()
    if cooldown_active(app, now):
        if message is not None:
            remaining = app.cooldown_ms - (now - app.last_reply_at) * 1000
            logger.debug(f'Cooldown has {remaining:.0f}ms left, so {message!r} goes unanswered.')
        return

    # GSI game-event reactions take priority over chat: they're time-sensitive
    # (an ace taunt is worthless several rounds later). Only areas that opt in
    # (consumes_events) ever pop the queue.
    if getattr(area, 'consumes_events', False):
        event = _next_event(app)
        if event is not None:
            await _react_to_event(app, area, event)
            return

    # Queued lines (the blackjack commands) come next, oldest first, with at
    # most one reply per tick. Then the area timers (the deal, a round clock
    # running out). The queue goes first so a !hit typed before the round
    # clock ran out still counts.
    # Like an event, either one takes this tick from the newest-wins chat line.
    if not _reply_waiting(app):
        if await _answer_queue(app, area) or await _run_timers(app, area):
            if message is not None:
                logger.debug(f'A queued or timed reply took this tick, so {message!r} '
                             'goes unanswered.')
            return

    if message is None:
        return
    await _answer_chat(app, area, message, channel, name)
