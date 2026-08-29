"""CS2-Chatbot entrypoint: configure logging, build app state + areas, wire up
the GUI and the chat-loop timer, then launch the NiceGUI window.

The actual work lives in the focused modules:
  system/winutil.py  Win32 / registry / VDF helpers
  logsetup.py        the debug-log switch and the startup environment snapshot
  app_state.py       shared AppState passed around instead of globals
  core.py            LogTailer + the extract -> generate -> send chat loop
  areas/             pluggable tabs: AI behaviors + the Settings utility area
  ui/gui.py          the NiceGUI shell (splitter, tabs, power toggle, exec light)
"""
import logging
import os

from nicegui import ui

import app_state
import core
import logsetup
from app_state import AppState
from areas import build_areas
from system import gsi
from system import winutil
from system.hotkey import HotkeyManager
from ui import gui

if __name__ == "__main__":
    # The debug-log setting is read straight from the settings file, before an
    # AppState exists: everything below this line can log, including the CS2
    # path lookup that is the most common thing to go wrong.
    settings_path = app_state.default_settings_path()
    app_settings = app_state.read_settings_file(settings_path).get(app_state.APP_SETTINGS_KEY, {})
    debug_log = logsetup.configure(app_state.default_log_path(),
                                   bool(app_settings.get('debug_log', False)))

    logger = logging.getLogger(__name__)
    logger.info("=== CS2-Chatbot starting ===")

    # Game data.
    cs_path = os.path.join(winutil.get_cs_path(), 'game', 'csgo')

    app = AppState(
        cs_path=cs_path,
        log_path=os.path.join(cs_path, 'console.log'),
        exec_path=os.path.join(cs_path, 'cfg', 'message.cfg'),
        debug_log=debug_log,
    )

    try:
        app.steam_nick = winutil.get_last_steam_nick()
    except Exception as e:
        logger.warning(f"Could not read Steam nick (self-filter disabled): {e}")
        app.steam_nick = ''

    app.areas = build_areas()
    app.tailer = core.LogTailer(app.log_path)
    app.tailer.seek_to_end()  # don't replay chat from before launch
    app.hotkeys = HotkeyManager()  # toggle hotkey; gui.build registers the saved key

    gui.build(app)

    # Game State Integration: persist/generate the auth token and mount the
    # /gsi route on the same server the GUI runs on, so CS2 can POST game-state.
    gsi.ensure_token(app)
    gsi.register_gsi_route(app)

    # The chat loop: one tick every 0.1s reads new log lines and may reply.
    ui.timer(0.1, lambda: core.handle_tick(app), active=True)

    gui.run_startup_checks(app)

    # Last, so the snapshot reports the settings the GUI has already loaded
    # rather than the dataclass defaults.
    logsetup.log_environment(app)

    logger.info("Starting the GUI window...")
    ui.run(native=True, show=True, window_size=(840, 600), title='CS2 Chatbot',
           reload=False, show_welcome_message=False, port=gsi.GSI_PORT)
