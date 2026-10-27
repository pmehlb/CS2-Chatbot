# Configuration Reference

Beyond what you can change on the Settings tab, this is what the code exposes:
the tunable constants, the files the app touches, and the system locations it
reads. Most of these are fields on `AppState` (`src/app_state.py`); a few are set
in `src/main.py` or `src/ui/gui.py`.

## Tunable constants

| Constant | Value | Meaning |
|----------|-------|---------|
| `settings_file` | `chatbot_settings.json` next to the executable | Where settings are persisted: each area's settings (e.g. the Character.AI token) plus cross-cutting app settings (theme, primary color, timing flags) under an `app` key. Path is absolute (resolved next to the `.exe`, or the project dir when run from source), so persistence doesn't depend on the working directory. |
| `bind_key` | `'p'` | The key the app simulates; **must match** your CS2 `bind <key> "exec message.cfg"`. |
| `chat_char_limit` | `221` | Max characters per chat chunk (222 was observed being cut off). Long replies are split into pieces of this size. |
| `chat_delay` | `0.5` | Seconds to wait between sending consecutive chunks. |
| `MIN_CHAT_GAP` | `0.6` | Seconds the bot waits after a chat line from `steam_nick` (you) before it presses the key (`core.py`). CS2 drops a line from the account that comes sooner, with no error. Replies to other players go out at once. |
| `response_delay_ms` | `0` | Fixed "thinking" pause (milliseconds) before the bot sends a reply. `0` disables it. Editable in Settings. |
| `response_jitter_ms` | `0` | Random extra delay (milliseconds), between `0` and this value, added on top of `response_delay_ms` so the wait varies each time. Editable in Settings. |
| `cooldown_enabled` | `False` | Whether the global reply cooldown is enforced. Editable in Settings. |
| `cooldown_ms` | `3000` | Minimum milliseconds between any two replies (across all areas) while the cooldown is on. Editable in Settings. |
| `auto_press` | `True` | When on, the app presses `bind_key` itself after writing `message.cfg`. When off (**Human Control**) the app writes the whole reply at once and presses no key. The exec light then means "ready to fire". It goes red again when your message reaches chat. Editable in Settings. |
| `steam_nick` | read from Steam | Your in-game name. The app uses it to spot the echo of its own replies (never answered), to keep the chat gap after your lines, and to confirm a sent reply under Human Control. The Command Bot answers what you type. The other tabs ignore you. The registry gives the startup value. The person icon in Settings > Known Players saves a name that wins over it. |
| `attribute_speakers` | `False` | When on, prefixes each message fed to the AI areas with `[Name] said: ` so replies can track the speaker. The Command Bot, Mimic, and Reverser opt out. Editable in Settings. |
| `toggle_key` | `''` (unset) | Global hotkey that toggles the bot on/off, even while CS2 is focused. Recorded and cleared in Settings; persisted. |
| `debug_log` | `False` (off) | The only control over the log file. While it is off, the app writes no log file at all. Turn it on in Settings > Debug Log and the file starts at once, without a restart. Persisted. |
| `rules` | `[]` (none) | Command-label rules applied to every area's reply, edited in Settings > Command Rules and persisted. Each entry is `{"label": "SILENT", "action": "silent"\|"say", "text": "..."}`; see [how-it-works.md](how-it-works.md#command-labels). |
| timer interval | `0.1` | How often `core.handle_tick()` runs (10x/second), set in `main.py`. |
| window size | `(840, 600)` | Native window dimensions, set in the final `ui.run(...)` in `main.py`. |
| accent color | `'#ec4899'` (pink) | Default UI primary color (`ui.colors(primary=...)`). |
| `GSI_PORT` | `8765` | Pinned local port (`system/gsi.py`) that serves **both** the GUI and the `POST /gsi` Game State Integration endpoint. The GSI cfg's `uri` points here, so it must match. |
| `GSI_CFG_NAME` | `gamestate_integration_cs2chatbot.cfg` | Filename written into CS2's `cfg/` by the Settings "Install GSI config" button. |
| `LOW_HP_THRESHOLD` | `20` | Max end-of-round HP that still counts as a "low-HP survival" event (`system/gsi.py`). |
| `WIN_SCORE` | `13` | Round score that ends the match (MR12); `WIN_SCORE - 1` is match point. |
| `GSI_FRESH_SECONDS` | `15` | A GSI POST within this many seconds counts as "receiving"; drives the Settings GSI connection light. |
| `DEFAULT_DECKS` / `DEFAULT_TURN_SECONDS` / `DEFAULT_JOIN_SECONDS` | `6` / `15` / `15` | Blackjack defaults (`areas/blackjack.py`). The C2 tab changes all three, within `BJ_DECKS_RANGE` (1-8) and `BJ_SECONDS_RANGE` (5-120 s) in `areas/commands.py`. |
| `LINE_LIMIT` | `200` | The blackjack players line wraps between entries past this many characters (`areas/blackjack.py`). It stays below `chat_char_limit`, so the chat chunker never cuts a name or a card. |
| `CUT_FRACTION` | `0.25` | The blackjack cut card. A new round reshuffles the shoe when less than this share of it is left. |
| `STALE_SECONDS` | `120` | A blackjack table whose timer is this many seconds overdue closes without a message. This happens when the bot was off or another tab was open. |

> To change the bind key, edit `bind_key` **and** update your CS2 bind to match.

## Files the app reads & writes

| Path | Direction | Purpose |
|------|-----------|---------|
| `<CS2>/game/csgo/console.log` | read | CS2's console mirror (requires `-condebug`); source of incoming chat. |
| `<CS2>/game/csgo/cfg/message.cfg` | write | Holds the `say "<chunk>"` (or `say_team "<chunk>"`) command CS2 executes when the bound key is pressed. |
| `<CS2>/game/csgo/cfg/gamestate_integration_cs2chatbot.cfg` | write | The Game State Integration config, written by the Settings "Install GSI config" button (`gsi.write_gsi_cfg`). Points CS2's GSI `uri` at `http://127.0.0.1:8765/gsi` with the app's `gsi_token`. CS2 must be restarted to pick it up. |
| `chatbot_settings.json` | read/write | Per-area settings, namespaced by area key, e.g. `{ "characterai": { "token": "<C.AI token>", "web_next_auth": "<web-next-auth cookie>" } }`. The `web_next_auth` value is the `web-next-auth` cookie from character.ai and is required for name search. The cross-cutting `app` namespace also holds `gsi_token`, a random hex token generated once (`gsi.ensure_token`) and written into the GSI cfg so CS2's POSTs can be authenticated, and `rules`, the command-label list. The `c2` namespace holds the command checkboxes (`enabled`) and the blackjack settings (`blackjack`: `join_seconds`, `turn_seconds`, `decks`). Created automatically if missing or invalid JSON. |
| `cs2_chatbot_debug.log` | write | Verbose debug log next to the executable, recreated each run. Written **only** while `debug_log` is on; with it off the file is never created. Wiring lives in `src/logsetup.py`. |

`<CS2>` is the CS2 install path discovered from the registry; the app computes
`cs_path = <CS2>/game/csgo` in `main.py`.

Both `chatbot_settings.json` and `cs2_chatbot_debug.log` are git-ignored (see
`.gitignore`), so secrets and logs never get committed. The log itself keeps no
secrets either: it records the *presence* of a token, never its value, and the
HTTP clients that log request details are turned down in `logsetup.NOISY_LOGGERS`.

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
| Character.AI (via `PyCharacterAI`) | `CharacterAIArea` in `areas/characterai.py` | Authentication, character browsing, chat session creation, and message generation. |
| OpenAI API (via `openai`) | `ChatGPTArea` in `areas/chatgpt.py` | Generates ChatGPT replies (needs an OpenAI API key). |
| Anthropic Messages API (via `anthropic`) | `ClaudeArea` in `areas/claude.py` | Generates Claude replies (needs an Anthropic API key). |
| Free keyless web APIs (icanhazdadjoke, uselessfacts, dummyjson, adviceslip, bible-api.com) | `CommandBotArea` in `areas/commands.py` (via `httpx`) | Back `!dadjoke`, `!fact`, `!quote`, `!fortunecookie`, and `!bible`. |
| AlphaVantage | `CommandBotArea` (`!ticker`) | Stock quote / currency rate. Uses an in-source free-tier key (rate-limited to ~25 requests/day). |

## Local endpoints

The app also *serves* one local endpoint for Game State Integration:

| Endpoint | Served by | Purpose |
|----------|-----------|---------|
| `POST http://127.0.0.1:8765/gsi` | `gsi.register_gsi_route` on the NiceGUI/uvicorn server (`system/gsi.py`) | Receives CS2's game-state POSTs. Port `8765` (`GSI_PORT`) is pinned and shared with the GUI; the handler validates `auth.token` against `gsi_token` and always returns 2xx. |

## Dependencies

From [`requirements.txt`](../requirements.txt):

| Package | Role |
|---------|------|
| `PyDirectInput` | Simulates the keypress that triggers the CS2 config exec. |
| `nicegui` | The GUI framework (also serves the `/gsi` route via its FastAPI app). |
| `PyCharacterAI` | Unofficial Character.AI client (auth, characters, chat). |
| `openai` | OpenAI client for the ChatGPT area (`AsyncOpenAI`). |
| `anthropic` | Anthropic client for the Claude area (`AsyncAnthropic`). |
| `httpx` | HTTP client for the Command Bot's web-backed commands. |
| `numerize` | Formats large interaction counts on character cards (e.g. `1.2M`). |
| `vdf` | Parses Steam's `localconfig.vdf`. |
| `pywebview` | Renders NiceGUI as a native desktop window (`native=True`). |
| `keyboard` | Registers the global hotkey that toggles the bot on/off. |
| `pyinstaller` | Build-time only; packages the app into an `.exe`. |
