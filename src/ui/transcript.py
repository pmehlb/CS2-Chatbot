"""A live record of an area's exchanges -- what came in, what the bot said back.

The AI tabs configure a persona but otherwise show nothing of what the bot is
actually doing; you have to be looking at CS2 to know. This renders the last few
exchanges under an area's controls so the tab shows its own work.

Written to be shared: an area keeps a ``Transcript``, calls ``record()`` from
``generate()`` (no widgets involved -- it's plain state plus a version counter),
and calls ``build()`` once in ``build_tab``. The GUI side mirrors the state on a
~1s timer, the same idiom Settings' "Known Players" card uses for the roster,
because the chat loop that drives ``generate()`` runs outside any widget's
context and shouldn't be reaching into the UI itself.
"""
import re
import time
from dataclasses import dataclass

from nicegui import ui

# How many exchanges are kept. Deep history isn't the point -- this is a "what
# just happened" panel, so it holds only the handful you'd actually glance at.
MAX_ENTRIES = 3

# The prefix core.attribute_message adds when "Attribute messages to speakers"
# is on. Matching it back out lets the block label the line with who actually
# talked instead of showing the plumbing.
SPEAKER_RE = re.compile(r'^\[(?P<name>.+?)\] said: (?P<message>.*)$', re.DOTALL)

# Fixed-width gutter for the speaker labels, so the message text of every line
# starts at the same x regardless of name length.
NAME_CLASSES = 'text-xs w-16 shrink-0 text-right pt-px'


@dataclass
class Exchange:
    """One incoming message and the reply it produced."""
    who: str      # speaker name if known, else 'Them'
    said: str     # what they said (prefix stripped)
    replied: str  # what the bot answered
    at: str       # local clock time, HH:MM:SS


def _as_text(reply) -> str:
    """Flatten a reply to display text.

    ``generate()`` may return a list of lines (each sent as its own chat
    message), so join those the way they'll appear in chat rather than showing
    a Python list.
    """
    if reply is None:
        return ''
    if isinstance(reply, str):
        return reply
    return '\n'.join(str(line) for line in reply)


def split_speaker(message: str):
    """Split ``"[Name] said: hi"`` into ``('Name', 'hi')``.

    Falls back to ``('Them', message)`` when the speaker prefix isn't there
    (the attribute-speakers setting is off, or an event prompt came through).
    """
    match = SPEAKER_RE.match(message or '')
    if match:
        return match.group('name'), match.group('message')
    return 'Them', message or ''


class Transcript:
    """The rolling exchange log for one area: state, plus the card that shows it.

    ``version`` is bumped on every mutation; the card's timer watches it and
    redraws only when it changes, so an idle tab does no work.
    """

    def __init__(self, max_entries: int = MAX_ENTRIES):
        self.entries = []          # oldest first; rendered newest first
        self.version = 0
        self.max_entries = max_entries

    # ------------------------------------------------------------------ state

    def record(self, message, reply) -> None:
        """Log one exchange. Safe to call from the chat loop (no widget calls)."""
        who, said = split_speaker(message)
        self.entries.append(Exchange(who=who, said=said, replied=_as_text(reply),
                                     at=time.strftime('%H:%M:%S')))
        del self.entries[:-self.max_entries]
        self.version += 1

    def clear(self) -> None:
        self.entries.clear()
        self.version += 1

    # ------------------------------------------------------------------ tab UI

    def build(self, title: str = 'Conversation') -> None:
        """Render the card. Call once, inside the area's ``build_tab``."""

        @ui.refreshable
        def entry_list():
            if not self.entries:
                ui.label('Nothing yet — messages and replies show up here as they happen.') \
                    .classes('text-sm text-grey')
                return
            # Newest first: the line you care about is the one that just landed,
            # and putting it on top means the box never needs auto-scrolling.
            for index, exchange in enumerate(reversed(self.entries)):
                if index:
                    ui.separator()
                self._entry(exchange)

        with ui.card().tight().classes('shadow-sm shadow-black w-full'):
            with ui.card_section().classes('w-full'):
                with ui.column().classes('gap-3 w-full'):
                    with ui.row().classes('items-center justify-between w-full'):
                        badge = ui.badge(title)
                        with badge:
                            ui.tooltip('The last few in-game messages this bot saw and what '
                                       'it replied. Cleared when the app restarts.')
                        clear_btn = ui.button('Clear', icon='delete',
                                              on_click=lambda: (self.clear(), entry_list.refresh())) \
                            .props('outline dense').style('padding-left: 8px; padding-right: 4px')
                        with clear_btn:
                            ui.tooltip('Empty this log. The bot keeps its conversation memory '
                                       '— use "Clear conversation" above to forget that.')
                    # Capped height with its own scrollbar so a busy match can't
                    # push the persona controls off the tab.
                    with ui.column().classes('w-full gap-2 overflow-auto').style('max-height: 15rem'):
                        entry_list()

        last_version = self.version

        def poll():
            nonlocal last_version
            if self.version != last_version:
                last_version = self.version
                entry_list.refresh()

        # The chat loop records exchanges outside any widget context, so mirror
        # the state on a timer instead of refreshing from generate().
        ui.timer(1.0, poll)

    def _entry(self, exchange: Exchange) -> None:
        with ui.column().classes('w-full gap-1'):
            with ui.row().classes('w-full items-start gap-2 flex-nowrap'):
                ui.label(exchange.who).classes(f'{NAME_CLASSES} text-primary').style(
                    'overflow: hidden; text-overflow: ellipsis; white-space: nowrap')
                ui.label(exchange.said).classes(
                    'text-sm flex-grow whitespace-pre-wrap break-words')
                ui.label(exchange.at).classes('text-xs opacity-50 shrink-0 pt-px')
            with ui.row().classes('w-full items-start gap-2 flex-nowrap'):
                ui.label('Bot').classes(f'{NAME_CLASSES} opacity-60')
                ui.label(exchange.replied or '(silent)').classes(
                    'text-sm flex-grow whitespace-pre-wrap break-words'
                    + ('' if exchange.replied else ' opacity-50 italic'))
