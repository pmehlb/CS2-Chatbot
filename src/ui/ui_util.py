"""Small NiceGUI helpers shared by the gui shell and the area modules.

Lives in its own module so areas can use notify_and_log / ToggleButton without
importing gui.py (which imports the areas) and creating a circular import.

Layout convention (the "framework of thought" used across the UI): Quasar
*props* style components (outline, flat, dense, rounded), Tailwind *classes*
handle layout and spacing. Spacing sticks to one scale -- gap-2 between
controls in a row, gap-3 between stacked controls in a card -- instead of
ad-hoc margins or <br> spacers, so similar things line up the same way
everywhere.
"""
import logging
from contextlib import contextmanager

from nicegui import ui

logger = logging.getLogger(__name__)

_LOG_LEVEL_MAP = {
    'positive': 'info',
    'negative': 'error',
    'warning': 'warning',
    'info': 'info',
}
_VALID_NOTIFY_TYPES = ['positive', 'negative', 'warning', 'info', 'ongoing']


def notify_and_log(message, type='info', level='info', **kwargs):
    """Show a notification in the GUI and mirror it to the terminal/log file."""
    log_level = _LOG_LEVEL_MAP.get(type, level)

    if log_level == 'error':
        logger.error(f"GUI Notification: {message}")
    elif log_level == 'warning':
        logger.warning(f"GUI Notification: {message}")
    else:
        logger.info(f"GUI Notification: {message}")

    if type in _VALID_NOTIFY_TYPES:
        ui.notify(message, type=type, **kwargs)  # type: ignore
    else:
        ui.notify(message, type='info', **kwargs)


def area_header(title: str, description: str = '') -> None:
    """Render an area tab's heading: title, optional muted description, divider.

    Every area calls this so all tabs open with identical typography and the
    same vertical rhythm before their controls, instead of each hand-rolling a
    label/markdown/separator combo with slightly different spacing.
    """
    # Tight column (override NiceGUI's default gap-4) so the title, description
    # and divider sit close together instead of a screenful apart.
    with ui.column().classes('w-full').style('gap: 0.25rem'):
        ui.label(title).classes('text-h6')
        if description:
            # 'area-desc' is targeted by CSS in gui.build() to zero the markdown
            # paragraph margins (which otherwise add ~1em above and below).
            ui.markdown(description).classes('area-desc text-sm opacity-70 w-full')
        ui.separator().classes('mt-1 mb-2')


@contextmanager
def settings_card(title: str):
    """A Settings-panel card: consistent elevation, padding and a title badge.

    Yields inside a ``gap-3`` column, so callers just add their controls and the
    spacing between them (and below the badge) is uniform across every card.
    """
    with ui.card().tight().classes('shadow-sm shadow-black w-full'):
        with ui.card_section().classes('w-full'):
            with ui.column().classes('gap-3 w-full'):
                ui.badge(title)
                yield


class ToggleButton(ui.button):
    """A button that flips an on/off state and recolours itself.

    The gating decision (is the bot allowed to turn on?) is delegated to an
    ``on_toggle(new_state) -> bool`` callback that returns the state to settle
    on, so the button itself stays free of any area-specific logic.
    """

    def __init__(self, *args, on_toggle=None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._state = False
        self.on_toggle = on_toggle
        self.on('click', self._handle_click)

    def _handle_click(self) -> None:
        new_state = not self._state
        if self.on_toggle is not None:
            new_state = bool(self.on_toggle(new_state))
        self.set_state(new_state)

    def set_state(self, state: bool) -> None:
        self._state = state
        if state:
            self.classes(remove='animate-pulse')
        self.update()

    def update(self) -> None:
        self.props(f'color={"green" if self._state else "pink"}')
        super().update()
