"""Debug-log wiring: one setting decides whether a log file exists at all.

Logging itself is always configured -- the terminal handler stays on whenever
there is a console to write to -- but the *file* handler is attached only while
Settings > Debug Log is on. Turn it off and the handler is detached, so nothing
more is written; a fresh install that never turns it on writes no file at all.

The file is truncated once per run, the first time the handler attaches. So
toggling the switch mid-session appends to the same file instead of discarding
whatever led up to the problem you are trying to capture.

Kept in its own module (rather than in main.py) because the Settings tab flips
the switch at runtime and main.py must configure it before anything else runs.
"""
import logging
import os
import platform
import sys

LOG_FILENAME = 'cs2_chatbot_debug.log'

# Module name included on purpose: "which file said this" is the first question
# you ask of a log line, and funcName alone does not answer it.
LOG_FORMAT = '%(asctime)s - %(levelname)s - %(name)s.%(funcName)s:%(lineno)d - %(message)s'

# Third-party loggers turned down. Two reasons, both about a log a user is going
# to paste into an issue: uvicorn's access log records every GSI POST (ten a
# second, forever), and the HTTP clients log request details at DEBUG that can
# carry an API key. Neither belongs in a chat-bot debug log.
NOISY_LOGGERS = {
    'httpx': logging.WARNING,
    'httpcore': logging.WARNING,
    'openai': logging.INFO,
    'anthropic': logging.INFO,
    'urllib3': logging.WARNING,
    'asyncio': logging.INFO,
    'uvicorn': logging.INFO,
    'uvicorn.access': logging.WARNING,
    'uvicorn.error': logging.INFO,
    'websockets': logging.WARNING,
    'watchfiles': logging.WARNING,
    'curl_cffi': logging.WARNING,
    'PyCharacterAI': logging.INFO,
    'python_multipart': logging.WARNING,
    'nicegui': logging.INFO,
}

logger = logging.getLogger(__name__)

_path = LOG_FILENAME     # absolute path to the log file, set by configure()
_handler = None          # the live FileHandler, or None while the setting is off
_truncated = False       # has this run already started the file?


def configure(path: str, enabled: bool) -> bool:
    """Install the handlers once at startup. Returns whether the file is on.

    ``path`` is where the log file goes (see ``app_state.default_log_path``);
    ``enabled`` is the persisted setting. A False return with ``enabled`` True
    means the file could not be opened -- the app keeps running without it.
    """
    global _path
    _path = path

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    for name, level in NOISY_LOGGERS.items():
        logging.getLogger(name).setLevel(level)

    # A windowed PyInstaller build has no stderr; a StreamHandler bound to None
    # would fail on every record it tried to emit.
    if sys.stderr is not None:
        stream = logging.StreamHandler()
        stream.setFormatter(logging.Formatter(LOG_FORMAT))
        root.addHandler(stream)

    return set_enabled(enabled)


def set_enabled(enabled: bool) -> bool:
    """Attach or detach the log file handler. Returns the state actually reached.

    Called by Settings when the switch flips, so the setting takes effect at
    once rather than on the next launch.
    """
    global _handler, _truncated

    root = logging.getLogger()

    if not enabled:
        if _handler is not None:
            # Logged before the handler goes away, so the file says why it ends.
            logger.info('Debug log stopped: the Settings switch was turned off.')
            root.removeHandler(_handler)
            _handler.close()
            _handler = None
        return False

    if _handler is not None:
        return True

    try:
        # 'w' the first time each run, 'a' after that: one file per launch, but
        # flipping the switch off and on again does not erase the earlier half.
        handler = logging.FileHandler(_path, 'a' if _truncated else 'w', encoding='utf-8')
    except OSError as e:
        logger.error(f'Could not open the debug log at {_path}: {e}')
        return False

    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    root.addHandler(handler)
    _handler = handler
    _truncated = True
    logger.info(f'Debug log started -> {_path}')
    return True


def is_enabled() -> bool:
    """True while the log file is being written."""
    return _handler is not None


def log_path() -> str:
    """Where the log file is (or would be) written."""
    return _path


def log_environment(app) -> None:
    """Write the snapshot every bug report needs, as one block of lines.

    Called at startup and again whenever the log is switched on mid-session, so
    a log that starts halfway through a session still opens with the context to
    read the rest of it: which build, which paths, and whether the two things
    people forget -- ``-condebug`` and running as admin -- are actually set.

    winutil is imported here, not at module scope, so this module stays free of
    Win32 imports for the tests.
    """
    from system import winutil

    frozen = getattr(sys, 'frozen', False)
    logger.info('--- environment ---')
    logger.info(f'Build: {"packaged exe" if frozen else "source"} | '
                f'Python {platform.python_version()} | {platform.platform()}')
    logger.info(f'Log file: {_path}')
    logger.info(f'Settings file: {app.settings_file} (exists={os.path.exists(app.settings_file)})')

    # The three things that break the chat loop when they are wrong, each with
    # the evidence that says whether it is wrong.
    logger.info(f'CS2 path: {app.cs_path} (exists={os.path.isdir(app.cs_path)})')
    logger.info(f'console.log: {app.log_path} ({_describe_file(app.log_path)})')
    logger.info(f'message.cfg: {app.exec_path} '
                f'(cfg dir writable={os.access(os.path.dirname(app.exec_path), os.W_OK)})')

    logger.info(f'Admin: {_safe(winutil.is_running_as_admin)} | '
                f'-condebug set: {_safe(winutil.is_condebug_in_game_args)}')
    logger.info(f'Steam nick: {app.steam_nick or "(unknown -- self-filter is off)"}')

    logger.info(f'Areas: {[getattr(a, "key", "?") for a in app.areas]}')
    logger.info(f'Bind key: {app.bind_key!r} | auto-press: {app.auto_press} | '
                f'toggle hotkey: {app.toggle_key or "(unset)"}')
    logger.info(f'Delay: {app.response_delay_ms}ms +0-{app.response_jitter_ms}ms jitter | '
                f'cooldown: {app.cooldown_ms}ms (on={app.cooldown_enabled}) | '
                f'char limit: {app.chat_char_limit}')
    logger.info(f'Attribute speakers: {app.attribute_speakers} | '
                f'command rules: {len(app.rules)}')
    # Presence only. The token is a shared secret with CS2 and this file gets
    # pasted into bug reports.
    logger.info(f'GSI token set: {bool(app.gsi_token)}')
    logger.info('--- end environment ---')


def _describe_file(path: str) -> str:
    """'exists, N bytes' or why it cannot be read -- for the environment block."""
    try:
        return f'exists, {os.path.getsize(path)} bytes'
    except OSError as e:
        return f'unreadable: {e.strerror or e}'


def _safe(check):
    """Run a diagnostic check, reporting the failure instead of raising.

    The environment block is written on the startup path, so a registry read
    that throws must not take the app down with it.
    """
    try:
        return check()
    except Exception as e:  # noqa: BLE001 - diagnostics must never raise
        return f'check failed: {e}'