# Configuration Reference

A quick reference for the tunable constants, the files the app touches, and the
system locations it reads. Most of these are fields on `AppState`
(`src/app_state.py`); a few are set in `src/main.py` or `src/ui/gui.py`.

## Tunable constants

Defined as `AppState` defaults in `src/app_state.py` (a few are set in
`src/main.py` / `src/ui/gui.py`).

| Constant | Value | Meaning |
|----------|-------|---------|
| `settings_file` | `chatbot_settings.json` next to the executable | Where settings are persisted: each area's settings (e.g. the Character.AI token) plus cross-cutting app settings (theme, primary color, typing flags) under an `app` key. Path is absolute (resolved next to the `.exe`, or the project dir when run from source), so persistence doesn't depend on the working directory. |
| `bind_key` | `'p'` | The key the app simulates; **must match** your CS2 `bind <key> "exec message.cfg"`. |
| `chat_char_limit` | `221` | Max characters per chat chunk (222 was observed being cut off). Long replies are split into pieces of this size. |
| `chat_delay` | `0.5` | Seconds to wait between sending consecutive chunks. |
| `response_delay_ms` | `0` | Fixed "thinking" pause (milliseconds) before the bot sends a reply. `0` disables it. Editable in Settings. |
| `response_jitter_ms` | `0` | Random extra delay (milliseconds), between `0` and this value, added on top of `response_delay_ms` so the wait varies each time. Editable in Settings. |
| timer interval | `0.1` | How often `core.handle_tick()` runs (10×/second), set in `main.py`. |
| window size | `(840, 600)` | Native window dimensions, set in the final `ui.run(...)` in `main.py`. |
| accent color | `'#ec4899'` (pink) | Default UI primary color (`ui.colors(primary=...)`). |

> To change the bind key, edit `bind_key` **and** update your CS2 bind to match.

## Files the app reads & writes

| Path | Direction | Purpose |
|------|-----------|---------|
| `<CS2>/game/csgo/console.log` | read | CS2's console mirror (requires `-condebug`); source of incoming chat. |
| `<CS2>/game/csgo/cfg/message.cfg` | write | Holds the `say "<chunk>"` command CS2 executes when the bound key is pressed. |
| `chatbot_settings.json` | read/write | Per-area settings, namespaced by area key, e.g. `{ "characterai": { "token": "<C.AI token>" } }`. Created automatically if missing or invalid JSON. |
| `cs2_chatbot_debug.log` | write | Verbose debug log, recreated each run (`logging` is configured at `DEBUG` level in `main.py`). |

`<CS2>` is the CS2 install path discovered from the registry; the app computes
`cs_path = <CS2>/game/csgo` in `main.py`.

Both `chatbot_settings.json` and `cs2_chatbot_debug.log` are git-ignored (see
`.gitignore`), so secrets and logs never get committed.

## Windows registry keys

Read via `winreg` to locate Steam/CS2 and identify the active user:

| Function (`system/winutil.py`) | Hive & key | Value |
|----------------------|------------|-------|
| `get_steam_path()` | `HKLM\SOFTWARE\Wow6432Node\Valve\Steam` | `InstallPath` |
| `get_cs_path()` | `HKLM\SOFTWARE\WOW6432Node\Valve\cs2` | `installpath` |
| `get_active_steam_id()` | `HKCU\SOFTWARE\Valve\Steam\ActiveProcess` | `ActiveUser` |
| `get_last_steam_nick()` | `HKCU\SOFTWARE\Valve\Steam` | `LastGameNameUsed` |

## Steam config parsing

`is_condebug_in_game_args()` (`system/winutil.py`) reads
`<Steam>/userdata/<userId>/config/localconfig.vdf` with the `vdf` library and
inspects the `LaunchOptions` for app **`730`** (CS2) to confirm `-condebug` is
present. It handles both the `Steam` and `steam` casing variants seen in that
file.

## External endpoints

| Endpoint | Used by | Purpose |
|----------|---------|---------|
| Character.AI (via `PyCharacterAI`) | `CharacterAIArea` in `areas/characterai.py` (`set_token` / `search` / `select_character` / `generate`) | Authentication, character browsing, chat session creation, and message generation. |

## Dependencies

From [`requirements.txt`](../requirements.txt):

| Package | Role |
|---------|------|
| `PyCharacterAI` | Unofficial Character.AI client (auth, characters, chat). |
| `nicegui` | The GUI framework. |
| `pywebview` | Renders NiceGUI as a native desktop window (`native=True`). |
| `PyDirectInput` | Simulates the keypress that triggers the CS2 config exec. |
| `vdf` | Parses Steam's `localconfig.vdf`. |
| `numerize` | Formats large interaction counts on character cards (e.g. `1.2M`). |
| `pyinstaller` | Build-time only — packages the app into an `.exe`. |
