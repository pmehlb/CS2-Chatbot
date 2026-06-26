"""CS2-Chatbot entrypoint: configure logging, build app state + areas, wire up
the GUI and the chat-loop timer, then launch the NiceGUI window.

The actual work lives in the focused modules:
  system/winutil.py  Win32 / registry / VDF helpers
  app_state.py       shared AppState passed around instead of globals
  core.py            LogTailer + the extract -> generate -> send chat loop
  areas/             pluggable tabs: AI behaviours + the Settings utility area
  ui/gui.py          the NiceGUI shell (splitter, tabs, power toggle, exec light)
"""
import logging
import os

from nicegui import ui

import core
from app_state import AppState
from areas import build_areas
from system import winutil
from system.hotkey import HotkeyManager
from ui import gui

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s',
        handlers=[
            logging.FileHandler('cs2_chatbot_debug.log', 'w'),
            logging.StreamHandler()
        ]
    )
    logger = logging.getLogger(__name__)
    logger.info("=== CS2-Chatbot Starting with Debug Logging ===")

    # Game data.
    cs_path = os.path.join(winutil.get_cs_path(), 'game', 'csgo')
    logger.debug(f"CS path - {cs_path}")

    app = AppState(
        cs_path=cs_path,
        log_path=os.path.join(cs_path, 'console.log'),
        exec_path=os.path.join(cs_path, 'cfg', 'message.cfg'),
    )
    logger.debug(f"Log path - {app.log_path}")
    logger.debug(f"Exec path - {app.exec_path}")

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

    # The chat loop: one tick every 0.1s reads new log lines and may reply.
    ui.timer(0.1, lambda: core.handle_tick(app), active=True)

    gui.run_startup_checks(app)

    logger.info("Starting CS2-Chatbot...")
    ui.run(native=True, show=True, window_size=(840, 600), title='CS2 Chatbot', reload=False,
           show_welcome_message=False)
