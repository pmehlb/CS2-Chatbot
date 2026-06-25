"""Shared runtime state passed between the gui shell, the chat loop, and areas.

Keeping this in one plain object (instead of module globals + widget refs) is
what lets core.py run the loop without importing any widgets, and lets each
area read/write its own settings without knowing about the others.
"""
import json
import logging
import os
import sys
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


def default_settings_path() -> str:
    """Absolute path to the settings file, kept next to the executable.

    Frozen (PyInstaller build): alongside the .exe, so the config lives with the
    app the user actually launches. Running from source: the project directory
    (next to this module). Either way it's an absolute path, so persistence does
    not depend on the current working directory.
    """
    if getattr(sys, 'frozen', False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, 'chatbot_settings.json')


# Namespace for cross-cutting app settings (theme, typing flags) inside the same
# settings file the areas use; distinct from any area key.
APP_SETTINGS_KEY = 'app'


@dataclass
class AppState:
    # Game paths (filled in by main from winutil.get_cs_path()).
    cs_path: str
    log_path: str
    exec_path: str

    # Persistence / send configuration.
    settings_file: str = field(default_factory=default_settings_path)
    bind_key: str = 'p'
    chat_char_limit: int = 221  # Cut-off observed with 222
    chat_delay: float = 0.5

    # Artificial "thinking" pause before sending a reply: a fixed base plus a
    # random jitter on top (both in milliseconds; 0 disables).
    response_delay_ms: int = 0
    response_jitter_ms: int = 0

    # Runtime flags read by the chat loop.
    powered_on: bool = False
    auto_press: bool = True             # press the bind key ourselves vs. let the user press it
    steam_nick: str = ''

    # Wiring filled in at startup.
    active_area: object = None          # the ChatArea whose tab is currently open
    areas: list = field(default_factory=list)
    tailer: object = None               # core.LogTailer

    # Running roster of everyone seen in [ALL] chat this session, mapping the
    # exact display name -> whether to respond to them (True by default).
    # In-memory only: it resets each launch and is never persisted. The chat
    # loop adds names; the Settings panel toggles them and can clear the list.
    roster: dict = field(default_factory=dict)
    roster_version: int = 0             # bumped on add/clear so the GUI knows to redraw

    # Exec light: green once a response has been written to message.cfg,
    # red while a reply is being processed (generated/sent).
    cfg_written: bool = False           # has the app written message.cfg this session?
    can_exec: bool = False              # True = green (response written), False = red (processing)
    exec_state_cb: object = None        # gui callback, invoked with can_exec when it changes

    # GUI handles set during gui.build (the Settings area reaches them via app).
    theme: object = None                # ui.dark_mode() handle for theme toggling

    def _read_all(self) -> dict:
        try:
            with open(self.settings_file, encoding='utf-8') as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except FileNotFoundError:
            return {}
        except json.JSONDecodeError:
            logger.warning('Invalid settings JSON; ignoring existing file.')
            return {}

    def load_area_settings(self, key: str) -> dict:
        """Return the saved settings dict for one area (empty dict if none)."""
        value = self._read_all().get(key, {})
        return value if isinstance(value, dict) else {}

    def save_area_settings(self, key: str, data: dict) -> None:
        """Merge one area's settings into the shared settings file."""
        all_settings = self._read_all()
        all_settings[key] = data
        try:
            with open(self.settings_file, 'w', encoding='utf-8') as f:
                json.dump(all_settings, f, indent=2)
        except OSError as e:
            logger.error(f'Failed to save settings for {key}: {e}')

    def load_app_settings(self) -> dict:
        """Return the saved cross-cutting app settings (theme, typing flags)."""
        return self.load_area_settings(APP_SETTINGS_KEY)

    def save_app_setting(self, key: str, value) -> None:
        """Persist one cross-cutting app setting, merging with the rest."""
        data = self.load_app_settings()
        data[key] = value
        self.save_area_settings(APP_SETTINGS_KEY, data)
