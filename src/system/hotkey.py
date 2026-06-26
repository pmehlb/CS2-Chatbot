"""Global (system-wide) hotkey registration via the `keyboard` library.

Isolated here so the rest of the app depends on a tiny set/clear/record
interface rather than on `keyboard` directly, and so the feature degrades
cleanly to a no-op when the library can't be imported (e.g. non-Windows, or a
build that didn't bundle it).

The single registered hotkey toggles the bot. Its callback fires on the
`keyboard` library's own thread, so the callback only flips a flag on AppState;
the GUI marshals that back onto the UI thread via a timer (see ui/gui.py).
"""
import logging

try:
    import keyboard
except Exception:  # not installed / unsupported platform
    keyboard = None

logger = logging.getLogger(__name__)


class HotkeyManager:
    """Owns at most one global hotkey and the callback it fires.

    ``bind_callback`` is called once at startup; ``rebind`` (re)points the hotkey
    at a new key, and ``record`` captures the next keypress for the press-to-set
    UI. All methods are safe to call when the ``keyboard`` library is missing.
    """

    def __init__(self):
        self._handler = None
        self._callback = None

    @property
    def available(self) -> bool:
        """True when global hotkeys can actually be registered."""
        return keyboard is not None

    def bind_callback(self, callback) -> None:
        """Set the function fired when the hotkey is pressed (once, at startup)."""
        self._callback = callback

    def rebind(self, key: str) -> bool:
        """(Re)register the global hotkey to ``key``; ``''`` just clears it.

        Returns True on success (a successful clear counts), False if the key
        couldn't be registered (library missing, no callback, or an error).
        """
        self.clear()
        if not key:
            return True
        if keyboard is None or self._callback is None:
            return False
        try:
            self._handler = keyboard.add_hotkey(key, self._callback)
            return True
        except Exception as e:
            logger.error(f"Failed to register hotkey {key!r}: {e}")
            return False

    def clear(self) -> None:
        """Unregister the current hotkey, if any."""
        if self._handler is not None and keyboard is not None:
            try:
                keyboard.remove_hotkey(self._handler)
            except (KeyError, ValueError):
                pass  # already gone
        self._handler = None

    async def record(self) -> str:
        """Block (in a worker thread) until a key/combo is pressed; return its
        name (e.g. ``'f8'``, ``'ctrl+b'``), or ``''`` if hotkeys are unavailable.
        """
        if keyboard is None:
            return ''
        from nicegui import run
        return await run.io_bound(keyboard.read_hotkey, False)
