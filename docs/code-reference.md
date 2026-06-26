# Code Reference

The app is split into focused modules, all under `src/`. `src/main.py` is a thin
entrypoint; the real work lives in the modules below. This page maps the code
file by file.

```
src/
  main.py          entrypoint
  app_state.py     shared state
  core.py          the chat loop
  ui/              the NiceGUI shell + shared GUI helpers (gui, ui_util)
  system/          Windows / registry / VDF helpers (winutil)
  areas/           pluggable AI behaviours
```

(`src/` is on the import path — modules import each other as `from ui.ui_util
import …`, `from system import winutil`, etc.)

## `main.py` — entrypoint

Configures `DEBUG` logging (to `cs2_chatbot_debug.log` and the terminal),
computes the CS2 paths from the registry, builds the shared `AppState`, creates
the areas and the `LogTailer`, builds the GUI, registers the 0.1s chat-loop
timer, runs the startup checks, and finally calls `ui.run(native=True, ...)` to
open the 840×600 window. Runs under `if __name__ == "__main__":`.

## `system/winutil.py` — Windows helpers

Pure functions with no GUI dependencies.

| Function | Purpose |
|----------|---------|
| `log_last_win_error()` | Formats the last Win32 error via `FormatMessageW` and logs it. |
| `is_running_as_admin()` | Inspects the process token's elevation to detect whether the app is elevated. |
| `get_steam_path()` | Steam install path from the registry. |
| `get_cs_path()` | CS2 install path from the registry. |
| `get_active_steam_id()` | Currently logged-in Steam user id. |
| `get_last_steam_nick()` | Last-used Steam nickname (used to avoid replying to yourself). |
| `is_condebug_in_game_args()` | Parses `localconfig.vdf` to confirm `-condebug` is in CS2's launch options. |
| `get_foreground_window_title()` | Title of the focused window; used so keystrokes only go to CS2. |

## `system/hotkey.py` — global toggle hotkey

`HotkeyManager` wraps the `keyboard` library so nothing else imports it directly,
and degrades to a no-op if the library is unavailable (`available` is `False`).
`bind_callback(fn)` sets the toggle callback once at startup; `rebind(key)`
(re)registers the single global hotkey (`''` clears it); `clear()` unregisters it;
and `async record()` awaits one keypress in a worker thread (for the
press-to-record Settings UI), returning the key/combo name. The hotkey callback
fires on the library's own thread, so it only sets `app.toggle_requested`; a GUI
timer marshals the actual toggle onto the UI thread.

## `app_state.py` — shared state

`AppState` is a dataclass passed between the GUI, the chat loop, and the areas
instead of module globals. It holds the CS2 paths, the send tunables
(`bind_key`, `chat_char_limit`, `chat_delay`, `response_delay_ms`,
`response_jitter_ms`), the runtime flags (`powered_on`, `auto_press`), the cached
`steam_nick`, the list of `areas`, the currently-active area (`active_area`), and
the `LogTailer`, and the `HotkeyManager` (`hotkeys`). It also holds the in-memory
`roster` (exact display name → whether to respond, populated as people talk) and
its `roster_version` counter; the roster is session-only and never persisted. The
global toggle hotkey is `toggle_key` (the chosen key, persisted; empty = unset)
and `toggle_requested` (a flag the hotkey callback sets and the GUI timer clears).
It provides `load_area_settings(key)` / `save_area_settings(key,
data)`, which read and write a per-area namespace inside `chatbot_settings.json`,
plus `load_app_settings()` / `save_app_setting(key, value)` for the cross-cutting
`app` namespace (theme, accent color, response delay/jitter, auto-press, cooldown,
toggle key).

## `core.py` — the chat loop (provider-agnostic)

| Symbol | Purpose |
|--------|---------|
| `LogTailer` | Incrementally tails `console.log`: remembers a byte offset and yields only newly-appended lines via `new_lines()`. `seek_to_end()` skips pre-launch chat; a shrunken file (CS2 recreates the log each launch) resets the offset; a half-written final line is buffered until its newline arrives. |
| `extract_latest_message(tailer, steam_nick, app)` | Drains the tailer, registers each new `[ALL]`/`[T]`/`[CT]` speaker (other than `steam_nick`) into `app.roster` defaulting to "respond", and returns `(message, channel)` for the newest message from a speaker still toggled on — `channel` is `'all'` or `'team'` — or `(None, None)`. |
| `chat_command_lines(reply, channel, char_limit)` | Pure helper: turns a `str` or `list[str]` reply into the ordered `message.cfg` command lines, cleaning each (quotes → `''`, newlines → spaces), chunking to `char_limit`, and prefixing with `say` (all) or `say_team` (team). |
| `send_to_game(reply, app, channel='all')` | Waits the "thinking" pause, then writes each line from `chat_command_lines(...)` into `message.cfg` and — only while CS2 is the foreground window — presses `bind_key` (when `auto_press` is on). Accepts a `str` or `list[str]` reply. |
| `cooldown_active(app, now)` | Returns `True` when the global reply cooldown is enabled and `cooldown_ms` hasn't elapsed since `app.last_reply_at` (a `time.monotonic()` value). One cooldown applies across every area; set in Settings > Chatbot. |
| `handle_tick(app)` | One timer tick: always drains the tailer (keeping the offset current), then — if the bot is on, the active area is ready, and the global cooldown isn't active — asks `active_area.generate(...)` for a reply, sends it, and records `last_reply_at`. |

## `areas/` — pluggable AI behaviours

Each area bundles its own tab UI, its response handler, and its state.

| File | Class | Behaviour |
|------|-------|-----------|
| `base.py` | `ChatArea` | The contract: `key` / `label` / `icon` attributes, `build_tab(app)`, `is_ready()` returning `(ok, reason)`, and an async `generate(message, app)` returning the reply text or `None`. |
| `characterai.py` | `CharacterAIArea` | The original Character.AI behaviour: token field, character search/selection, reset-memory button, and `generate()` via `client.chat.send_message(...)`. `is_ready()` requires a token and a selected character. |
| `mimic.py` | `MimicArea` | Echoes the last message back with randomized capitalization. No configuration. |
| `string_reverser.py` | `StringReverserArea` | Sends the last message back reversed — the minimal example area. |
| `commands.py` | `CommandBotArea` | "C2" command bot: parses `!`-prefixed chat (`!help`, `!ping`, `!slots`, `!8ball`, `!roll`, `!flip`, `!dadjoke`, `!fact`) via a small command registry, with per-command enable checkboxes. The reply cooldown is a global Settings option, not per-area. `!dadjoke`/`!fact` use free keyless web APIs (httpx). |
| `settings.py` | `SettingsArea` | The Settings tab (`answerable = False`, so it idles the bot). A 2-col card grid — **Logic** (timing fields, auto-press, reply cooldown, and the global toggle-keybind row), **Known Players** (live roster toggles), **API Tokens** (from each area's `tokens()`), **Appearance** (theme + accent). The keybind row records a key via `app.hotkeys.record()` and persists it as `toggle_key`. |
| `__init__.py` | — | `build_areas()` returns the list of areas; the first one is selected on startup. |

### Adding a new area

Create `areas/<name>.py` with a `ChatArea` subclass (implement `generate`, plus
`build_tab` / `is_ready` if it needs configuration), import it in
`areas/__init__.py`, and add an instance to `build_areas()`. It gets its own tab
automatically.

## `ui/gui.py` — the NiceGUI shell

| Symbol | Purpose |
|--------|---------|
| `build(app)` | Builds the splitter, the vertical tab bar (one tab per area + a Settings tab), and the power button. Switching to a provider tab makes that area active; switching to Settings sets `active_area = None`, so the loop idles. Also wires the global toggle hotkey: registers the saved `toggle_key` via `app.hotkeys` and runs a 0.1s timer that, when the hotkey sets `toggle_requested`, clicks the power button (same gate/notify path). |
| `_gate_power(...)` | The power toggle's gate: refuses to turn on unless an area is open and its `is_ready()` passes, notifying the reason otherwise. |
| `run_startup_checks(app)` | Shows the "not admin" and "no -condebug" startup warnings. |

## `ui/ui_util.py` — shared GUI helpers

`notify_and_log(...)` shows a NiceGUI notification and mirrors it to the log.
`ToggleButton` is the power button: it flips an on/off state, recolors itself,
and delegates the allow/deny decision to an `on_toggle` callback.

## Logging & settings files

- `cs2_chatbot_debug.log` — verbose `DEBUG` log, recreated each run.
- `chatbot_settings.json` — per-area settings, e.g. `{ "characterai": { "token": "…" } }`.

Both are git-ignored.
