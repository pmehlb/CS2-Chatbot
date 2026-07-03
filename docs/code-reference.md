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
  system/          Windows / registry / VDF helpers (winutil, hotkey, gsi)
  areas/           pluggable AI behaviors
```

(`src/` is on the import path; modules import each other as `from ui.ui_util
import …`, `from system import winutil`, etc.)

## `main.py`: entrypoint

Configures `DEBUG` logging (to `cs2_chatbot_debug.log` and the terminal),
computes the CS2 paths from the registry, builds the shared `AppState`, creates
the areas and the `LogTailer`, builds the GUI, registers the 0.1s chat-loop
timer, runs the startup checks, and finally calls `ui.run(native=True, ...)` to
open the 840×600 window. Runs under `if __name__ == "__main__":`.

## `system/winutil.py`: Windows helpers

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

## `system/hotkey.py`: global toggle hotkey

`HotkeyManager` wraps the `keyboard` library so nothing else imports it directly,
and degrades to a no-op if the library is unavailable (`available` is `False`).
`bind_callback(fn)` sets the toggle callback once at startup; `rebind(key)`
(re)registers the single global hotkey (`''` clears it); `clear()` unregisters it;
and `async record()` awaits one keypress in a worker thread (for the
press-to-record Settings UI), returning the key/combo name. The hotkey callback
fires on the library's own thread, so it only sets `app.toggle_requested`; a GUI
timer marshals the actual toggle onto the UI thread.

## `system/gsi.py`: Game State Integration

CS2's official, read-only push channel: a local HTTP endpoint the game POSTs
game-state JSON to, turned into `TiltEvent`s the chat loop reacts to (consumed by
the Tilt Bot area). It never touches game memory, so it is as ban-safe as the
`console.log` read path. During live play GSI only exposes the local player's
data, so events derive from your own `player` node plus the shared `round`/`map`
state.

| Symbol | Purpose |
|--------|---------|
| `TiltEvent` | Small dataclass with a `kind: str` and a `data: dict` (e.g. kill count, HP). |
| `detect_events(payload, prev)` | Pure, unit-testable: diffs the new GSI `payload` against the `prev` snapshot and returns edge-detected `TiltEvent`s (MULTI_KILL, ROUND_WIN, LOW_HP_SURVIVAL, MVP, MATCH_POINT, MATCH_WIN). Returns nothing on the first frame or when the observed player changes. |
| `handle_payload(app, payload)` | Validates `auth.token` against `app.gsi_token`, stamps `gsi_last_seen`, runs `detect_events`, appends results to `app.gsi_events`, and refreshes `app.gsi_prev`. Never raises into CS2's HTTP client; returns the number of events enqueued. |
| `write_gsi_cfg(app)` | Writes `<CS2>/cfg/gamestate_integration_cs2chatbot.cfg` pointing CS2's GSI `uri` at `http://127.0.0.1:8765/gsi` with the app's `gsi_token`. Returns the path written; CS2 must be restarted to pick it up. |
| `ensure_token(app)` | Returns the persisted `gsi_token`, generating a random hex one (and saving it to the `app` settings namespace) if unset. |
| `register_gsi_route(app)` | Registers `POST /gsi` on NiceGUI's underlying FastAPI app (call before `ui.run`). The handler delegates to `handle_payload` and always returns 2xx. |
| `is_receiving(app, now)` | Pure helper: `True` when a valid GSI POST arrived within `GSI_FRESH_SECONDS`. Drives the Settings GSI connection light. |

Module constants: `GSI_PORT` (`8765`), `GSI_CFG_NAME`, `LOW_HP_THRESHOLD`,
`WIN_SCORE`, `GSI_FRESH_SECONDS`. See [configuration.md](configuration.md).

## `app_state.py`: shared state

`AppState` is a dataclass passed between the GUI, the chat loop, and the areas
instead of module globals. It holds the CS2 paths, the send tunables
(`bind_key`, `chat_char_limit`, `chat_delay`, `response_delay_ms`,
`response_jitter_ms`), the global reply cooldown (`cooldown_enabled`,
`cooldown_ms`), the speaker-attribution flag (`attribute_speakers`), the runtime
flags (`powered_on`, `auto_press`), the cached `steam_nick`, the list of `areas`,
the currently-active area (`active_area`), the `LogTailer`, and the
`HotkeyManager` (`hotkeys`). It also holds the in-memory
`roster` (exact display name → whether to respond, populated as people talk) and
its `roster_version` counter; the roster is session-only and never persisted. The
global toggle hotkey is `toggle_key` (the chosen key, persisted; empty = unset)
and `toggle_requested` (a flag the hotkey callback sets and the GUI timer clears).
It provides `area_by_key(key)` (returns a registered area by its `key`, e.g.
`'claude'`, so one area can borrow another's behavior, used by Tilt Bot to
route a taunt through a configured AI area). It also provides
`load_area_settings(key)` / `save_area_settings(key,
data)`, which read and write a per-area namespace inside `chatbot_settings.json`,
plus `load_app_settings()` / `save_app_setting(key, value)` for the cross-cutting
`app` namespace (theme, accent color, response delay/jitter, cooldown, auto-press,
speaker attribution, toggle key). For Game State Integration it holds `gsi_token` (the shared secret,
persisted in the `app` namespace), `gsi_events` (a bounded `deque` of detected
`TiltEvent`s drained by the chat loop), `gsi_prev` (the last payload snapshot for
delta detection), and `gsi_last_seen` (the `time.monotonic()` of the last valid
GSI POST, for the connection light).

## `core.py`: the chat loop (provider-agnostic)

| Symbol | Purpose |
|--------|---------|
| `LogTailer` | Incrementally tails `console.log`: remembers a byte offset and yields only newly-appended lines via `new_lines()`. `seek_to_end()` skips pre-launch chat; a shrunken file (CS2 recreates the log each launch) resets the offset; a half-written final line is buffered until its newline arrives. |
| `extract_latest_message(tailer, steam_nick, app)` | Drains the tailer, registers each new `[ALL]`/`[T]`/`[CT]` speaker (other than `steam_nick`) into `app.roster` defaulting to "respond", and returns `(message, channel, name)` for the newest message from a speaker still toggled on (`channel` is `'all'` or `'team'`, `name` is the clean display name), or `(None, None, None)`. |
| `attribute_message(message, name, app, area)` | When `attribute_speakers` is on and the area opts in (`attribute_speaker`, default `True`), prefixes the message with `[Name] said: ` so AI areas can track the speaker; the Command Bot and Reverser opt out. Returns the message unchanged otherwise. |
| `chat_command_lines(reply, channel, char_limit)` | Pure helper: turns a `str` or `list[str]` reply into the ordered `message.cfg` command lines, cleaning each (quotes → `''`, newlines → spaces), chunking to `char_limit`, and prefixing with `say` (all) or `say_team` (team). |
| `send_to_game(reply, app, channel='all')` | Waits the "thinking" pause, then writes each line from `chat_command_lines(...)` into `message.cfg` and (only while CS2 is the foreground window) presses `bind_key` (when `auto_press` is on). Accepts a `str` or `list[str]` reply. |
| `cooldown_active(app, now)` | Returns `True` when the global reply cooldown is enabled and `cooldown_ms` hasn't elapsed since `app.last_reply_at` (a `time.monotonic()` value). One cooldown applies across every area; set in Settings > Chatbot. |
| `handle_tick(app)` | One timer tick: always drains the tailer (keeping the offset current), then, if the bot is on, the active area is ready, and the global cooldown isn't active, handles output. If the active area `consumes_events`, it first pops the newest pending GSI event (dropping stale ones, via `_next_event`) and reacts to it via `_react_to_event`/`generate_event`, which takes priority over chat; otherwise it optionally tags the message with the speaker (`attribute_message`) and asks `active_area.generate(...)` for a chat reply. Either path sends via `send_to_game` and records `last_reply_at`. |

## `areas/`: pluggable AI behaviors

Each area bundles its own tab UI, its response handler, and its state.

| File | Class | behavior |
|------|-------|-----------|
| `base.py` | `ChatArea` | The contract: `key` / `label` / `icon` attributes, `build_tab(app)`, `tokens()` (the `TokenField`s the area needs), `is_ready()` returning `(ok, reason)`, and an async `generate(message, app)` returning the reply text or `None`. Class flags: `answerable` (default `True`; `False` for utility tabs like Settings that idle the loop), `attribute_speaker` (default `True`; `False` for command/transform areas that opt out of the `[Name] said: ` prefix), and `consumes_events` (default `False`; `True` for areas that react to GSI game events). Also an async `generate_event(event, app)` (default returns `None`) that produces a taunt for a `system.gsi.TiltEvent`; the chat loop only pops events for areas that opt in. |
| `event_prompts.py` | (functions) | `event_to_prompt(event)`: pure. Turns a `system.gsi.TiltEvent` into a one-line AI instruction (e.g. "I just got a 4-kill… brag in all chat"). Shared by Tilt Bot's AI taunt source and the AI areas' event reactions; unknown kinds/missing `{tokens}` degrade to a generic brag rather than raising. |
| `characterai.py` | `CharacterAIArea` | The base Character.AI behavior: token field, character search/selection, reset-memory button, and `generate()` via `client.chat.send_message(...)`. `is_ready()` requires a token and a selected character. An opt-in "Also react to my game events" toggle sets instance `consumes_events` and routes `generate_event()` (`event_prompts.event_to_prompt`) through the selected character. |
| `chatgpt.py` | `ChatGPTArea` | Replies via OpenAI's API: a persona card (model selector + system "first prompt") plus rolling history. `is_ready()` requires an OpenAI API key (in Settings > API Tokens). An opt-in "Also react to my game events" toggle sets instance `consumes_events` and routes `generate_event()` through this persona. |
| `claude.py` | `ClaudeArea` | Replies via Anthropic's Messages API: persona card with a model selector (Opus/Sonnet/Haiku) and per-model tuning (temperature/effort where supported), plus rolling history. `is_ready()` requires an Anthropic API key. (Named `claude.py` so it doesn't shadow the `anthropic` SDK package.) Same opt-in "Also react to my game events" toggle as the other AI areas. |
| `tiltbot.py` | `TiltBotArea` | The Tilt Bot: `consumes_events = True`, so it reacts to GSI game events via `generate_event(event, app)`. Per-section **Taunt source** and **Clapback source** dropdowns (`Canned`/C.AI/ChatGPT/Claude): canned uses the editable line pools, an AI source borrows that area's `generate()` via `app.area_by_key` (with a canned fallback on error). `is_ready()` blocks power-on if a *used* section points at an AI brain that isn't ready. Tab is a 2-column layout (Game events \| Chat) over a full-width "Requires Game State Integration" note whose button calls `app.open_settings` to jump to the GSI setup (in Settings); per-event checkboxes and editable + restorable line pools live in the two cards. |
| `mimic.py` | `MimicArea` | Echoes the last message back with randomized capitalization. No configuration. |
| `string_reverser.py` | `StringReverserArea` | Sends the last message back reversed; the minimal example area. |
| `commands.py` | `CommandBotArea` | "C2" command bot: parses `!`-prefixed chat (`!help`, `!ping`, `!slots`, `!8ball`, `!roll`, `!flip`, `!dadjoke`, `!fact`) via a small command registry, with per-command enable checkboxes. The reply cooldown is a global Settings option, not per-area. `!dadjoke`/`!fact` use free keyless web APIs (httpx). |
| `settings.py` | `SettingsArea` | The Settings tab (`answerable = False`, so it idles the bot). A 2-col card grid sits over a full-width **Game State Integration (GSI)** card. The grid holds **Logic** (the delay/jitter timing fields, the reply cooldown, auto-press, the "Attribute messages to speakers" toggle, and the global toggle-keybind row), **Known Players** (live roster toggles), **API Tokens** (from each area's `tokens()`), and **Appearance** (theme + accent). The GSI card has "Install GSI config" (`gsi.write_gsi_cfg`), the endpoint/config paths, and the live connection light (`gsi.is_receiving`). GSI is app-wide (Tilt Bot plus opt-in AI areas), so its setup lives here. The keybind row records a key via `app.hotkeys.record()` and persists it as `toggle_key`. |
| `__init__.py` | (functions) | `build_areas()` returns the list of areas; the first one is selected on startup. |

### Adding a new area

Create `areas/<name>.py` with a `ChatArea` subclass (implement `generate`, plus
`build_tab` / `is_ready` if it needs configuration), import it in
`areas/__init__.py`, and add an instance to `build_areas()`. It gets its own tab
automatically.

## `ui/gui.py`: the NiceGUI shell

| Symbol | Purpose |
|--------|---------|
| `build(app)` | Builds the splitter, the vertical tab bar (one tab per area + a Settings tab), and the power button. Switching to a provider tab makes that area active; switching to Settings sets `active_area = None`, so the loop idles. Wires `app.open_settings` (switches to the Settings tab, used by Tilt Bot's GSI notice). Also wires the global toggle hotkey: registers the saved `toggle_key` via `app.hotkeys` and runs a 0.1s timer that, when the hotkey sets `toggle_requested`, clicks the power button (same gate/notify path). |
| `_gate_power(...)` | The power toggle's gate: refuses to turn on unless an area is open and its `is_ready()` passes, notifying the reason otherwise. |
| `run_startup_checks(app)` | Shows the "not admin" and "no -condebug" startup warnings. |

## `ui/ui_util.py`: shared GUI helpers

`notify_and_log(...)` shows a NiceGUI notification and mirrors it to the log.
`ToggleButton` is the power button: it flips an on/off state, recolors itself,
and delegates the allow/deny decision to an `on_toggle` callback.

## Logging & settings files

- `cs2_chatbot_debug.log`: verbose `DEBUG` log, recreated each run.
- `chatbot_settings.json`: per-area settings, e.g. `{ "characterai": { "token": "…" } }`.

Both are git-ignored.
