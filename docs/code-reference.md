# Code Reference

The app is split into focused modules, all under `src/`. `src/main.py` is a thin
entrypoint; the real work lives in the modules below. This page maps the code
file by file.

```
src/
  main.py          entrypoint
  app_state.py     shared state
  core.py          the chat loop
  logsetup.py      the debug-log switch + the startup environment snapshot
  rules.py         command-label parsing applied to every reply
  ui/              the NiceGUI shell + shared GUI parts (gui, ui_util, transcript)
  system/          Windows / registry / VDF / GSI helpers (winutil, hotkey, gsi)
  areas/           pluggable AI behaviors
```

(`src/` is on the import path; modules import each other as `from ui.ui_util
import ...`, `from system import winutil`, etc.)

## `main.py`: entrypoint

Reads the `debug_log` setting straight from the settings file and hands it to
`logsetup.configure()` **before anything else runs**, so a failure during
startup still lands in the log. Then computes the CS2 paths from the registry,
builds the shared `AppState`, creates the areas and the `LogTailer`, builds the
GUI, sets up GSI (token + `/gsi` route), registers the 0.1s chat-loop timer,
runs the startup checks, writes the environment snapshot
(`logsetup.log_environment`), and finally calls `ui.run(native=True, ...)` to
open the 840x600 window on port `GSI_PORT`. Runs under
`if __name__ == "__main__":`.

## `logsetup.py`: the debug log

One switch owns the log file: while Settings > Debug Log is off, no file is
written at all. The terminal handler is separate and always on when there is a
console to write to (a windowed build has none, so it is skipped).

| Function | Purpose |
|----------|---------|
| `configure(path, enabled)` | Installs the handlers once at startup. Returns the state the log actually reached (`False` if the file could not be opened). |
| `set_enabled(enabled)` | Attaches or detaches the file handler at runtime, so the Settings switch takes effect without a restart. Returns the state reached. |
| `is_enabled()` / `log_path()` | Whether a file is being written, and where it goes. |
| `log_environment(app)` | Writes the block every bug report needs: build, versions, paths, `-condebug`, admin, areas and timing settings. Called at startup and again whenever the log is switched on mid-session. |

The file is truncated once per run, on the first attach, so turning the switch
off and on again appends instead of discarding the earlier half. Third-party
loggers (`httpx`, `uvicorn.access`, the API clients) are turned down in
`NOISY_LOGGERS`: they would otherwise bury the app's own lines and can log
request details that carry an API key.

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
game-state JSON to, turned into `TiltEvent`s the chat loop reacts to. It never
touches game memory, so it is as ban-safe as the `console.log` read path. During
live play GSI only exposes the local player's data, so events derive from your
own `player` node plus the shared `round`/`map` state.

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
instead of module globals. It holds the CS2 paths, the send tunables (`bind_key`,
`chat_char_limit`, `chat_delay`, `response_delay_ms`, `response_jitter_ms`), the
global reply cooldown (`cooldown_enabled`, `cooldown_ms`), the speaker-attribution
flag (`attribute_speakers`), the command-label `rules` list (see `rules.py`), the
runtime flags (`powered_on`, `auto_press`), the cached `steam_nick`, the list of
`areas`, the currently-active area (`active_area`), the `LogTailer`, and the
`HotkeyManager` (`hotkeys`).

It also holds the in-memory `roster` (exact display name -> whether to respond,
populated as people talk) and its `roster_version` counter; the roster is
session-only and never persisted. `last_speaker` is the name behind the message
being answered, set by the chat loop before `generate()` for areas that gate on
identity; it
is runtime only, and separate from the optional `[Name] said: ` prefix, which
command areas opt out of. `last_channel` is the channel of that message. The
blackjack table posts its timer lines there. `last_chat_at` is the time of your last chat line (a line from `steam_nick`). `recent_sends` holds the text of the last 16 lines sent with auto-press, so their echoes are not answered as your own typing. `shown_watch` holds `(last chunk, reply)` for the last 8 replies `send_to_game` wrote. The echo of that chunk calls the area's `reply_shown`. `chat_queue` holds the chat lines
the active area answers in arrival order (`ChatArea.queues_message`), as
`(message, channel, name)`. It is runtime only and holds at most 32 lines. The global toggle hotkey is `toggle_key` (the
chosen key, persisted; empty = unset) and `toggle_requested` (a flag the hotkey
callback sets and the GUI timer clears).

For Game State Integration it holds `gsi_token` (the shared secret, persisted in
the `app` namespace), `gsi_events` (a bounded `deque` of detected `TiltEvent`s
drained by the chat loop), `gsi_prev` (the last payload snapshot for delta
detection), and `gsi_last_seen` (the `time.monotonic()` of the last valid GSI
POST, for the connection light). For the **exec light** it holds `can_exec`
(green when a reply has been written to `message.cfg`, red while processing),
`cfg_written`, and `exec_state_cb` (the GUI callback fired when `can_exec`
changes). Under Human Control (`auto_press` off) `pending_sends` holds the chat
text the app wrote and still waits to see in chat, which keeps the light green
until the message lands. It is runtime only. Two GUI handles are set during `gui.build`: `theme` (the
`ui.dark_mode()` handle) and `open_settings` (a callable that jumps to the
Settings tab).

Methods: `area_by_key(key)` returns a registered area by its `key` (e.g.
`'claude'`), so one area can borrow another's behavior (used by Tilt Bot to route
a taunt through a configured AI area). `load_area_settings(key)` /
`save_area_settings(key, data)` read and write a per-area namespace inside
`chatbot_settings.json`; `load_app_settings()` / `save_app_setting(key, value)`
do the same for the cross-cutting `app` namespace (theme, accent color, timing,
cooldown, auto-press, speaker attribution, toggle key, command `rules`,
`gsi_token`).

## `core.py`: the chat loop (provider-agnostic)

| Symbol | Purpose |
|--------|---------|
| `LogTailer` | Incrementally tails `console.log`: remembers a byte offset and yields only newly-appended lines via `new_lines()`. `seek_to_end()` skips pre-launch chat; a shrunken file (CS2 recreates the log each launch) resets the offset; a half-written final line is buffered until its newline arrives. |
| `extract_latest_message(tailer, steam_nick, app, queues=None, answer_self=False, on_shown=None)` | Drains the tailer, registers each new `[ALL]`/`[T]`/`[CT]` speaker (other than `steam_nick`) into `app.roster` defaulting to "respond", and returns `(message, channel, name)` for the newest message from a speaker still toggled on (`channel` is `'all'` or `'team'`, `name` is the clean display name), or `(None, None, None)`. A line from `steam_nick` sets `app.last_chat_at` (the chat gap). If `take_own_echo` matches it to a reply the app sent (`pending_sends` under Human Control, `recent_sends` with auto-press), it is never answered. When that echo is the last chunk of a reply (`take_shown_reply`), `on_shown` (the active area's `reply_shown`) gets the reply. Otherwise you typed it, and it is answered only with `answer_self` (the active area's `answers_own_lines`). You never go into the roster. A line that `queues` (the active area's `queues_message`) claims goes onto `app.chat_queue` and takes no part in the newest-wins pick. |
| `attribute_message(message, name, app, area)` | When `attribute_speakers` is on and the area opts in (`attribute_speaker`, default `True`), prefixes the message with `[Name] said: ` so AI areas can track the speaker; the Command Bot, Mimic, and Reverser opt out. Returns the message unchanged otherwise. |
| `chat_message_chunks(reply, char_limit)` | Pure helper: turns a `str` or `list[str]` reply into the exact chat text chunks, cleaning each (quotes -> `''`, newlines -> spaces) and slicing to `char_limit`. The text carries no `say` verb, so Human Control can match it against the chat lines that come back in `console.log`. |
| `chat_command_lines(reply, channel, char_limit)` | Pure helper: prefixes each `chat_message_chunks(...)` chunk with `say` (all) or `say_team` (team) to give the ordered `message.cfg` command lines. |
| `human_control(app)` | `True` while the human fires the reply, which is `auto_press` turned off. |
| `send_to_game(reply, app, channel='all')` | Hands the reply to CS2. With `auto_press` on, it waits the "thinking" pause, then writes one `say` line at a time and presses `bind_key` for each (only while CS2 is the foreground window). Each keypress first waits until `MIN_CHAT_GAP` (0.6 s) has passed since your last chat line (`app.last_chat_at`), because CS2 drops a chat line that comes too soon after the account's previous one. Replies to other players go out at once. Under Human Control it skips that pause (the keypress sets the timing), writes every line in one file, presses nothing, and records the chunks in `app.pending_sends`. Turns the exec light green when done. Accepts a `str` or `list[str]` reply. |
| `write_message_cfg(reply, app, channel='all')` | Writes a whole reply to `message.cfg` as one file (every `say` line at once) so a single in-game `exec` sends the block. Used by the Command Bot's "Send help to chat" button, a manual kickoff that runs while the GUI, not CS2, is focused. Under Human Control it also fills `app.pending_sends`. |
| `clear_message_cfg(app)` | Empties `message.cfg` so an early keypress cannot fire a stale reply. Logs and ignores an `OSError`, because a locked file is no reason to drop a reply. |
| `begin_reply(app)` | Starts a reply: exec light red, and under Human Control an empty `pending_sends` and an empty `message.cfg`. The newest reply wins, so anything still waiting goes away here. |
| `note_own_chat_line(app, text)` | Removes one matching chunk from `app.pending_sends` when our own chat line comes back through the log, and turns the light red once the list empties. Matching the text, not only the nick, keeps your own typing from clearing a waiting reply. |
| `set_exec_state(app, ready)` | Flips `app.can_exec` and notifies the GUI only when the state changes (green once a reply is written, red while processing). Under Human Control green also means "not sent yet". |
| `cooldown_active(app, now)` | Returns `True` when the global reply cooldown is enabled and `cooldown_ms` hasn't elapsed since `app.last_reply_at`. One cooldown applies across every area; set in Settings > Logic. |
| `handle_tick(app)` | One timer tick: always drains the tailer (keeping the offset current), then, if the bot is on, the active area is ready, and the global cooldown isn't active, handles output. If the active area `consumes_events`, it first pops the newest pending GSI event (dropping stale ones, via `_next_event`) and reacts via `_react_to_event`/`generate_event`, which takes priority over chat. Next come the queued lines (`_answer_queue`, oldest first, until one sends a reply) and then the area timers (`_run_timers`, which calls `generate_timed`). Both hold while a Human Control reply waits for its keypress (`_reply_waiting`). Last, `_answer_chat` records the speaker and channel in `app.last_speaker` / `app.last_channel`, optionally tags the message with the speaker (`attribute_message`), and asks `active_area.generate(...)` for a chat reply. The bot switched off clears the queue. Both paths then run the reply through `rules.apply_rules(reply, app.rules)` before sending via `send_to_game` and recording `last_reply_at` — so a reply silenced by a command label costs no keystrokes and starts no cooldown. |

## `rules.py`: command labels

A bot's reply may carry command labels written `([LABEL])`. A user-editable rule
list, in Settings > Command Rules, points each label at an action, and the chat
loop applies the rules to every area's reply between `generate(...)` and
`send_to_game(...)`. Pure functions only: no widgets, no `AppState`.

| Symbol | Purpose |
|--------|---------|
| `LABEL_PATTERN` | The `([LABEL])` regex, tolerating whitespace inside the brackets. Its character class excludes further brackets and parens, so a malformed marker can only fail to match, never swallow the rest of the line. |
| `ACTIONS` | The supported actions, mapped to their Settings dropdown labels: `silent` ("Stay silent") and `say` ("Say this"). Adding an action (e.g. an HTTP call) is an entry here plus a branch in `_apply_to_line`. |
| `normalize_label(text)` | Reduces whatever was typed to the bare uppercase name, stripping wrappers until the value settles, so `TAUNT`, `[TAUNT]` and `([ taunt ])` are all one rule. |
| `index_rules(rules)` | Maps normalized label -> rule for lookup. Junk entries (non-dicts, blank labels) are skipped rather than raising, so a hand-edited settings file can't break the chat loop; first rule wins on duplicates. |
| `apply_rules(reply, rules)` | Runs a reply (a `str` or `list[str]`) through the rules and returns what should actually be sent, or `None` to stay silent. Per line: if **any** label present maps to a `silent` rule the whole reply is dropped; otherwise each known label is replaced in place with its rule's text, unknown labels are left exactly as written, and the leftover whitespace is collapsed. Lines that empty out are dropped. |
| `describe_rule(rule)` | One short phrase for the Settings list (`stay silent`, `say "get good"`). |
| `prompt_snippet(rules)` | Builds the copyable block that teaches a bot which labels it may emit, for pasting into an area's system prompt (or a Character.AI persona, where there's no system prompt to append to). |

## `areas/`: pluggable AI behaviors

Each area bundles its own tab UI, its response handler, and its state.

| File | Class | Behavior |
|------|-------|-----------|
| `base.py` | `ChatArea` | The contract: `key` / `label` / `icon` attributes, `build_tab(app)`, `tokens()` (the `TokenField`s the area needs), `is_ready()` returning `(ok, reason)`, and an async `generate(message, app)` returning the reply (a `str`, a `list[str]`, or `None`). Class flags: `answerable` (default `True`; `False` for utility tabs like Settings that idle the loop), `attribute_speaker` (default `True`; `False` for command/transform areas that opt out of the `[Name] said: ` prefix), `consumes_events` (default `False`; `True` for areas that react to GSI game events), and `answers_own_lines` (default `False`; `True` for the Command Bot, which answers what you type yourself). Also an async `generate_event(event, app)` (default returns `None`) that produces a taunt for a `system.gsi.TiltEvent`; the chat loop only pops events for areas that opt in. `queues_message(message)` (default `False`) claims a chat line for the ordered queue. An async `generate_timed(app)` (default `None`) returns `(reply, channel)` when an area timer is due. `reply_shown(reply, now)` (default: nothing) hears when a reply reached chat. |
| `blackjack.py` | `Table`, `Seat`, `Hand`, `Shoe` | Pure blackjack logic, no GUI and no chat I/O. Every call takes `now` (a `time.monotonic()` value), so tests step the clock. States: idle, joining (the join window), playing (rounds). In a round everyone moves at the same time: each open hand takes one move. The move locks at once in `moves` and gets no reply. When every open hand has a move, or the round clock runs out (a hand with no move stands), `_resolve` applies the moves in seat order and the next table view goes out (the results, when no hand is left in play). The round clock starts when the view shows in chat: `shown(reply, now)`, from the area's `reply_shown`. A view that never shows keeps the clock from the build. A `Seat` holds a list of `Hand`s because a split has no limit. The table view: a `[dealer] (4) 4♥ --.` line, then a players line such as `[schwagger] >>(18) K♦ 8♦. [bob] >>(5/15) A♠ 4♣. !hit/!stand/!double`. `>>` marks each hand that needs a move, a soft total shows both values, and the line ends with the moves any open hand can use. After a split the hands carry numbers (`#1 >>(11) 8♠ 3♦ | #2 ...`) and a move can name one (`!hit 2`). A move with no number takes the first open hand with no move yet. The players line wraps between entries at `LINE_LIMIT` (200 characters). Casino rules: a multi-deck shoe with a cut card, the dealer stands on all 17s and peeks for blackjack under an ace or a ten. Double on any two cards, also after a split. Split any two cards of the same value. Split aces get one card each and no hit, but can split again. A move that is not allowed gets `<name>: ✘` (`REFUSED_MARK`). `tick(now)` deals when the join window closes and resolves the round when its clock runs out. The first move for a hand counts: a second one is refused. The results use the same two lines: `[dealer] (BUST, 22) 4♥ 8♣ K♠.`, then `[schwagger] (WIN, 18) K♦ 8♦. ...`. The tags are `WIN`, `LOSE`, `PUSH`, `BUST` and `BLACKJACK`, with `x2` on a doubled hand. |
| `trivia.py` | `Trivia`, `Question` | Pure trivia logic, no GUI and no chat I/O, like `blackjack.py`. Every call takes `now`. `Question.from_trivia_api(item)` reads one The Trivia API item (a `ValueError` unless it has a text, 1 right and 3 wrong answers). `ask()` shuffles the four answers and returns the two chat lines (the question, then `Ⓐ`-`Ⓓ` and the answer time). `answer()` locks the first answer of each player with no reply, and refuses a second one. The answer clock starts when the question shows in chat (`shown()`). When it runs out, `tick()` gives the right answer and who chose it, and a question more than `STALE_SECONDS` overdue closes with no message. |
| `event_prompts.py` | (functions) | `event_to_prompt(event)`: pure. Turns a `system.gsi.TiltEvent` into a one-line AI instruction (e.g. "I just got a 4-kill... brag in all chat"). Shared by Tilt Bot's AI taunt source and the AI areas' event reactions; unknown kinds/missing `{tokens}` degrade to a generic brag rather than raising. |
| `characterai.py` | `CharacterAIArea` | The Character.AI behavior: two token fields (C.AI token plus the `web-next-auth` cookie needed for name search), a search box that either loads a pasted character ID directly or searches by name, a persisted "recents" grid of previously selected characters, a reset-memory button, and `generate()` via `client.chat.send_message(...)`. `is_ready()` requires a token and a selected character. An opt-in "Also react to my game events" toggle sets instance `consumes_events` and routes `generate_event()` through the selected character. |
| `chatgpt.py` | `ChatGPTArea` | Replies via OpenAI's Chat Completions API: a "Persona" card (model dropdown, temperature slider, system "first prompt", clear-conversation button) plus a rolling history, over a "Conversation" block (`ui/transcript.py`) logging the last 3 exchanges. `is_ready()` requires an OpenAI API key (in Settings > API Tokens). An opt-in "Also react to my game events" toggle sets instance `consumes_events` and routes `generate_event()` through this persona. |
| `claude.py` | `ClaudeArea` | Replies via Anthropic's Messages API: a "Persona" card with a model dropdown (Opus 5/4.8/4.7, Sonnet 5/4.6, Haiku 4.5) and per-model tuning, a system prompt, clear-conversation button, and rolling history, over a "Conversation" block (`ui/transcript.py`) logging the last 3 exchanges. `MODEL_CAPS` records what each model accepts, since sending the wrong control is a 400: temperature (rejected on Opus 5/4.8/4.7 and Sonnet 5), which effort levels exist (no `xhigh` on Sonnet 4.6; effort errors outright on Haiku), and whether the model thinks unless told not to. Opus 5 and Sonnet 5 do, and `MAX_TOKENS` caps thinking *plus* reply text, so those two are sent `thinking: disabled` or a 150-token budget gets spent reasoning and the chat line arrives truncated; Opus 5 only accepts that below `xhigh`, so its effort list stops at `high`. Controls the chosen model doesn't support are disabled in the UI. `is_ready()` requires an Anthropic API key. (Named `claude.py` so it doesn't shadow the `anthropic` SDK package.) Same opt-in "Also react to my game events" toggle as the other AI areas. |
| `tiltbot.py` | `TiltBotArea` | The Tilt Bot: `consumes_events = True`, so it reacts to GSI game events via `generate_event(event, app)`. Per-section **Taunt source** and **Clapback source** dropdowns (`Canned`/C.AI/ChatGPT/Claude): canned uses the editable line pools, an AI source borrows that area's `generate()` via `app.area_by_key` (with a canned fallback on error). `is_ready()` blocks power-on if a *used* section points at an AI brain that isn't ready. Tab is a 2-column layout (Game events \| Chat) over a full-width "Requires Game State Integration" note whose button calls `app.open_settings` to jump to the GSI setup; per-event checkboxes and editable + restorable line pools live in the two cards. |
| `commands.py` | `CommandBotArea` | "C2" command bot: parses `!`-prefixed chat via a small ordered registry (`!help`, `!ping`, `!slots`, `!8ball`, `!roll`, `!flip`, `!dadjoke`, `!fact`, `!quote`, `!fortunecookie`, `!bible`, `!confucius`, `!ticker`, `!blackjack`, `!trivia`) with per-command enable checkboxes. Each `Command` has a `category`: `!help` gives one line per category in `HELP_CATEGORIES` (Games, Random, Tools) between two dividers, and lists only the enabled commands. `!help` itself has no category, so it is not listed. A reply longer than `REPLY_MAX_LEN` (160 characters) runs the command again, up to `REPLY_TRIES` (3) runs, and the shortest reply goes out. A `Command` with `reroll=False` (`!ticker`, `!blackjack`, `!trivia`) and the sub-commands run once. A `Command` can carry `subcommands` that follow its checkbox: `!join`, `!hit`, `!stand`, `!double`, and `!split` belong to `!blackjack`, and `!a` to `!d` belong to `!trivia`. It sets `answers_own_lines`, so your own commands work too. The game commands (`games`: blackjack and trivia) go through the ordered queue (`queues_message`), act for `app.last_speaker`, and the due timer lines of each game go out through `generate_timed`. `reply_shown` gives each echo to both games. A card for each game holds its `GAME_FIELDS`: "Blackjack" sets the join window, the round timer, and the decks in the shoe, and "Trivia" sets the answer time. `!dadjoke`/`!fact`/`!quote`/`!fortunecookie`/`!bible`/`!trivia` hit free keyless web APIs, `!confucius` fetches its sayings file once per session (`parse_confucius`), and `!ticker` hits AlphaVantage (with an in-source free-tier key), all via `httpx`; the rest are local. The reply cooldown is the global Settings option, not per-area. A "Send help to chat" button writes the help block out now via `core.write_message_cfg`. |
| `mimic.py` | `MimicArea` | Echoes the last message back with randomized capitalization. No configuration; the minimal example of an area with only a `generate()` method. |
| `string_reverser.py` | `StringReverserArea` | Sends the last message back reversed. An editable, persisted censor list find/replaces whole words (case-insensitive) first, so a replacement un-reverses to clean text on the reader's end. |
| `settings.py` | `SettingsArea` | The Settings tab (`answerable = False`, so it idles the bot). A 2-col card grid sits over the full-width **Command Rules** and **Game State Integration (GSI)** cards. The grid holds **Logic** (the delay/jitter timing fields, the reply cooldown, auto-press, the "Attribute messages to speakers" toggle, the global toggle-keybind row, and an amber warning shown only while `steam_nick` is empty), **Known Players** (live roster toggles, plus a person icon on each row that promotes that name to `steam_nick`, saves it, and drops the row), **API Tokens** (from each area's `tokens()`), and **Appearance** (theme + accent). **Command Rules** edits the global `([LABEL])` -> action list (see `rules.py`): a label box, an action dropdown, a "Say this" box that enables only for the `say` action, the current rules with delete buttons, and a collapsible prompt snippet with a copy button. Rules are global, so they persist in the `app` namespace via `save_app_setting('rules', ...)` rather than any one area's. The GSI card has "Install GSI config" (`gsi.write_gsi_cfg`), the endpoint/config paths, and the live connection light (`gsi.is_receiving`). GSI is app-wide (Tilt Bot plus opt-in AI areas), so its setup lives here. The keybind row records a key via `app.hotkeys.record()` and persists it as `toggle_key`. |
| `__init__.py` | (functions) | `build_areas()` returns the list of areas; the first one is selected on startup. |

### Adding a new area

Create `areas/<name>.py` with a `ChatArea` subclass (implement `generate`, plus
`build_tab` / `is_ready` if it needs configuration), import it in
`areas/__init__.py`, and add an instance to `build_areas()`. It gets its own tab
automatically.

## `ui/gui.py`: the NiceGUI shell

| Symbol | Purpose |
|--------|---------|
| `build(app)` | Builds the splitter, the vertical tab bar (one tab per area + a Settings tab), the power button, and the exec-status light. Switching to a provider tab makes that area active; switching to Settings sets `active_area = None`, so the loop idles. Wires `app.exec_state_cb` to recolor the exec light and `app.open_settings` to switch to the Settings tab (used by Tilt Bot's GSI notice). Loads the saved `app` settings, where a promoted `steam_nick` wins over the name `main` read from Steam. Also wires the global toggle hotkey: registers the saved `toggle_key` via `app.hotkeys` and runs a 0.1s timer that, when the hotkey sets `toggle_requested`, clicks the power button (same gate/notify path). |
| `_gate_power(...)` | The power toggle's gate: refuses to turn on unless an area is open and its `is_ready()` passes, notifying the reason otherwise. |
| `run_startup_checks(app)` | Shows the "not admin" and "no -condebug" startup warnings. |

## `ui/transcript.py`: the Conversation block

The live "what came in / what went out" log shown under the ChatGPT and Claude
persona controls. Shared, so any area can adopt it: keep a `Transcript`, call
`record()` from `generate()`, call `build()` once in `build_tab`.

| Symbol | Purpose |
|--------|---------|
| `Transcript.record(message, reply)` | Logs one exchange (state only — no widget calls, so it's safe from the chat loop): splits the `[Name] said: ` prefix back off via `split_speaker`, flattens a `list[str]` reply to the lines it'll appear as in chat, stamps the local time, trims to `max_entries` (3) and bumps `version`. |
| `Transcript.clear()` | Empties the log. Separate from an area's "Clear conversation" button, which forgets the model's history instead. |
| `Transcript.build(title)` | Renders the card: a title badge, a Clear button, and a height-capped scroll box listing the exchanges newest-first (speaker + message + time over the bot's reply, an empty reply shown as *(silent)*). Because `generate()` runs outside any widget context, the card doesn't refresh from `record()` — a 1s timer watches `version` and redraws only on a change, the same idiom as Settings' Known Players roster. |
| `split_speaker(message)` | `"[Name] said: hi"` -> `('Name', 'hi')`; falls back to `('Them', message)` when the attribute-speakers prefix isn't there. |

## `ui/ui_util.py`: shared GUI helpers

Lives in its own module so areas can use these without importing `gui.py` (which
imports the areas) and creating a cycle.

| Symbol | Purpose |
|--------|---------|
| `notify_and_log(...)` | Shows a NiceGUI notification and mirrors it to the log. |
| `copy_to_clipboard(text, what)` | Copies text from the webview via JS (NiceGUI 1.4 has no clipboard helper), falling back to a hidden textarea outside a secure context, then notifies. Used by the Settings prompt snippet / log path. |
| `area_header(title, description)` | Renders an area tab's heading (title, optional muted description, divider) so every tab opens with identical typography and rhythm. |
| `settings_card(title)` | Context manager for a titled card with consistent elevation, padding, and inner spacing, used across Settings and the area tabs. |
| `ToggleButton` | The power button: flips an on/off state, recolors itself, and delegates the allow/deny decision to an `on_toggle` callback. |

## Logging & settings files

- `cs2_chatbot_debug.log`: verbose `DEBUG` log, next to the executable. Written
  only while Settings > Debug Log is on (off by default), and recreated each run.
- `chatbot_settings.json`: per-area settings, e.g. `{ "characterai": { "token": "..." } }`.
  The `app` namespace holds `debug_log`, the switch above.

Both are git-ignored.
