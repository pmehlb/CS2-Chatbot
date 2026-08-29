# How It Works

Counter-Strike 2 gives third-party programs no supported way to **read** in-game
chat or **send** a chat message. CS2-Chatbot works around both halves using
features the game already ships with:

- **Reading** relies on the `-condebug` launch option, which mirrors the in-game
  console (all-chat included) into a plain text log file.
- **Sending** relies on CS2 config files: the app writes a `say "..."` command
  into a `.cfg` file and presses a key the user bound to `exec` that file.

Everything else (the GUI, the AI areas, the safety checks) wires those two
channels together.

## End-to-end data flow

```
   ┌──────────────────────────┐   writes all-chat to console   ┌──────────────────────────┐
   │   Counter-Strike 2       │ ─────────────────────────────► │  game/csgo/console.log   │
   │   (launched with         │        (because -condebug)     │                          │
   │    -condebug)            │                                └─────────────┬────────────┘
   └──────────▲───────────────┘                                              │
              │                                                  polled every 0.1s by the
              │ presses bound key 'p'                            handle_tick() ui.timer
              │ via pydirectinput.write()                                     │
              │ (only if CS2 is the                                           ▼
              │  foreground window)                              ┌──────────────────────────┐
   ┌──────────┴───────────────┐                                 │ LogTailer.new_lines():   │
   │  CS2 runs: exec          │                                 │  newest [ALL]/[T]/[CT]   │
   │  message.cfg             │                                 └─────────────┬────────────┘
   │  → say "<chunk>"         │                                               │ split "sender: message"
   └──────────▲───────────────┘                                              ▼
              │ app writes the file                              ┌──────────────────────────┐
              │                                                  │ Skip if:                 │
   ┌──────────┴───────────────┐                                 │  • no new chat line      │
   │  game/csgo/cfg/          │                                 │  • not a chat line       │
   │  message.cfg             │ ◄───────────────────────────────│  • sender is yourself    │
   │   say "<response chunk>" │      write each chunk, then      └─────────────┬────────────┘
   └──────────────────────────┘      press the bound key                       │ new message, allowed sender
                                                                                ▼
                                                                  ┌──────────────────────────┐
                                                                  │ Active area produces the │
                                                                  │  reply (area output):    │
                                                                  │  a string, a list of     │
                                                                  │  lines, or None          │
                                                                  └─────────────┬────────────┘
                                                                                │ resolve ([LABEL]) rules,
                                                                                │ clean text, split into
                                                                                ▼ ≤221-char chunks
                                                                       (back up to message.cfg)
```

## The message loop

A NiceGUI timer in `main.py` calls `core.handle_tick(app)` ten times a second:

```python
ui.timer(0.1, lambda: core.handle_tick(app), active=True)
```

Each tick:

1. **Read new chat lines.** `core.LogTailer` reads only the bytes appended to
   `console.log` since the last tick, and `core.extract_latest_message` scans
   them for chat lines: `  [ALL] ` for all-chat, `  [T] ` / `  [CT] ` for team
   chat. It keeps the newest one and remembers its channel so the reply goes back
   to the same place. On startup the tailer skips whatever is already in the file;
   if CS2 recreates the log (it does each launch), it resets and keeps following.

2. **Filter.** The line splits on the first `': '` into sender and message. The
   name is cut at the `U+200E` mark CS2 appends after it, giving one stable entry
   per player whether they're alive or `[DEAD]`. Messages from your own Steam
   nick (read once at startup) are skipped so the bot never answers itself. Every
   other speaker is added to the session roster (Settings > Known Players),
   defaulting to respond; toggle someone off and their messages are ignored. The
   roster is in-memory only and resets each launch.

3. **Gate.** If the power button is off, a non-answerable tab like Settings is
   open (`active_area is None`), the active area isn't ready, or the global
   cooldown hasn't elapsed, the tick stops here. It still drained the tailer, so
   the byte offset and roster stay current even while the bot is off.

4. **Produce a reply.** If **Attribute messages to speakers** is on, the message
   is prefixed with `[Name] said: ` first (areas that parse raw text opt out).
   The tick then asks the active area for output via
   `active_area.generate(message, app)`. An area may return a string, a list of
   strings (each its own chat line), or `None` to stay silent. Areas that consume
   GSI game events check those first (see below), since a stale taunt is worse
   than none.

5. **Resolve command labels.** The reply is run through the rules you set in
   Settings > Command Rules (see below). This is where a bot can decide to say
   nothing, so a silenced reply costs no keystrokes and starts no cooldown.

6. **Clean and chunk.** Double quotes become two single quotes and newlines
   become spaces, so the text sits safely inside a `say "..."` command. The
   result is sliced into chunks of at most `chat_char_limit` (221; 222 was seen
   getting cut off).

7. **Inject each chunk.** For each chunk the app writes `message.cfg`
   (`say "<chunk>"` for all-chat, `say_team "<chunk>"` for team chat). If the
   foreground window is exactly `Counter-Strike 2`, it presses `bind_key` (`p`),
   which runs CS2's `bind p "exec message.cfg"` and posts the chunk. The
   foreground check keeps the synthetic keypress out of any app you've
   alt-tabbed into. An optional "thinking" pause (`response_delay_ms` plus a
   random `0..response_jitter_ms`, both `0`/off by default) runs before the
   first chunk; `chat_delay` (0.5s) separates chunks.

The power button has a companion **exec light**: red while a reply is being
generated or waiting out the delay, green once it lands in `message.cfg`.

## Human Control (auto-press off)

Turn **Auto-press execute key** off and the app never touches your keyboard.
Step 7 changes shape: the whole reply is written into `message.cfg` as one
block, so a single press of your bind key sends all of it, and the exec light
becomes a "ready to fire" light.

- **Red** while the bot works. The moment a reply starts, the app empties
  `message.cfg`, so an early keypress cannot fire a stale line.
- **Green** the moment the finished reply is in the file. Press your bind key
  when you want it in chat. The "thinking" pause is skipped: it exists to keep
  an instant reply from looking robotic, and here your keypress sets the timing.
- **Red again** once the app sees your own message come back through
  `console.log`. It matches the text, not only the name, so your own typing
  does not clear a reply that is still waiting.

A new incoming message overwrites a reply you never fired, so what sits in the
file is always the newest one. Detection needs your Steam name: the app reads it
from Steam at startup, and you can correct it in **Known Players** with the
person icon on a row. While the name is unknown, Settings shows a warning and
the light stays green after a send.

## Why the keypress + config trick

`pydirectinput` can't reliably type a whole message into CS2's chat box, and
there's no command-line way to make CS2 say something. But CS2 *will* run any
console commands in a config file when you `exec` it, and a key bind is a
supported way to trigger an `exec`. So the content travels through a file (no
fragile character-by-character typing) and only one reliable keypress is
simulated. The one-time `bind p "exec message.cfg"` (see
[setup-and-usage.md](setup-and-usage.md)) closes the loop.

## The areas

Each tab is a self-contained "area" (mapped in [code-reference.md](code-reference.md)).
What replies depends on which tab is open:

- **Character.AI** talks to a selected character through the unofficial
  PyCharacterAI library on a token-based session. Picking a character starts a
  fresh chat; the reset button starts another, which wipes the persona's memory.
  Name search needs a second `web-next-auth` cookie, or you can paste a character
  ID directly.
- **ChatGPT** and **Claude** answer through OpenAI / Anthropic with a trash-talk
  persona and a short rolling history. Each can also react to your own game
  events (see below). A **Conversation** block under the persona controls logs
  the last few exchanges — who said what and what the bot fired back — so the
  tab shows its own work without alt-tabbing to CS2.
- **Tilt Bot** reacts to live game events and optionally claps back at chat,
  using either its editable canned line pools or a borrowed AI brain.
- **Command Bot (C2)** answers `!`-prefixed commands (`!help`, `!8ball`,
  `!ticker`, and so on) and stays silent on anything else.
- **Mimic** randomizes each letter's case; **String Reverser** reverses the text,
  censoring configured words first.

## Command labels

Areas can only hand the loop text, which leaves a bot no way to say anything
*about* its reply — including "don't send this one". Command labels are that
channel. A reply may contain labels written `([LABEL])`, and **Settings > Command
Rules** points each one at an action:

| Action | What happens |
|--------|--------------|
| **Stay silent** | The whole reply is dropped. Nothing is typed, and the cooldown doesn't start. |
| **Say this** | The label is swapped for your text, in place, and the rest of the sentence survives. |

So with `TAUNT` → say `get good`, a reply of `nice try ([TAUNT]) loser` is sent as
`nice try get good loser`, while a bare `([TAUNT])` is sent as `get good`. A
label with no matching rule is sent to chat exactly as written — a typo shows up
rather than quietly changing what the bot does. Matching ignores case, and the
brackets are optional when you type the rule: `TAUNT`, `[TAUNT]` and `([TAUNT])`
all mean the same thing.

The rules are global: every area's reply runs through them, chat replies and GSI
event taunts alike, and they're saved with the rest of your settings.

A bot won't use a label unless it's been told the label exists. The Command Rules
card builds that instruction for you — open **Prompt snippet**, copy it, and
paste it into the area's system prompt (or a Character.AI persona, where there's
no system prompt field to append to).

Today an action is silence or fixed text. The parsing, storage, and UI don't
change if an action later calls an API and drops the result into the same slot —
that's the point of routing labels through one place.

## Game State Integration

Reading chat is one input channel. The **Tilt Bot** (and any AI area with **Also
react to my game events** on) also reacts to your own live game events
(multi-kills, MVPs, round wins, low-HP survival, match point) through **Game
State Integration (GSI)**, CS2's official read-only channel. It is as ban-safe as
the `console.log` read: GSI never touches game memory, and the game pushes state
to the app.

```
   ┌──────────────────────────┐   HTTP POST game-state JSON    ┌──────────────────────────┐
   │   Counter-Strike 2       │ ─────────────────────────────► │  POST /gsi               │
   │   (GSI cfg installed)    │   (auth token in the body)     │  (NiceGUI/uvicorn server,│
   └──────────▲───────────────┘                                │   pinned port 8765)      │
              │                                                 └─────────────┬────────────┘
              │ presses bound key 'p'                              system/gsi.py            │
              │ via pydirectinput.write()                          handle_payload():        │
              │ (same path as chat replies)                         • check auth token      │
   ┌──────────┴───────────────┐                                    • detect_events(payload, │
   │  send_to_game(reply,     │                                    │   prev) → [TiltEvent]   │
   │   app, 'all')            │                                    • append to gsi_events    │
   │  → message.cfg → say     │                                 └─────────────┬────────────┘
   └──────────▲───────────────┘                                              │ queued (bounded deque)
              │                                                               ▼
              │ TiltBot.generate_event(event)                    ┌──────────────────────────┐
              └──────────────────────────────────────────────────│ handle_tick() 10Hz loop  │
                            taunt string                          │  pops the newest event,  │
                                                                  │  drains stale ones       │
                                                                  └──────────────────────────┘
```

1. **CS2 POSTs game state.** Once the GSI config is installed and CS2 restarted,
   the game POSTs JSON to `POST /gsi`, a route `system/gsi.py` mounts on the same
   NiceGUI/uvicorn server as the GUI. The server is pinned to port **8765** so the
   config's `uri` always matches.
2. **Authenticate and detect.** `handle_payload()` checks the payload's
   `auth.token` against `app.gsi_token` (quietly returning 200 on a mismatch so
   CS2 never errors), then `detect_events(payload, prev)` diffs the new payload
   against the previous snapshot and emits edge-detected `TiltEvent`s (each fires
   once per transition). They go into `app.gsi_events`, a bounded `deque`.
3. **The loop consumes events.** The same 10Hz `handle_tick()` loop pops the
   **newest** pending event (draining stale ones) for any area that opts in and
   calls `area.generate_event(event, app)`, which takes priority over chat.
4. **Send it.** The taunt goes out through the same path as chat:
   `send_to_game(reply, app, 'all')`.

**Limitation: your own data only.** During a live match CS2's anti-cheat sends
GSI only the local player's data, so every event is derived from your own
`player` node plus the shared `round`/`map` state. Taunts are about your play,
not named opponents.

## Windows integration

CS2 and Steam are tied to Windows, so the app uses the OS directly:

- **Registry** (`winreg`) for the Steam and CS2 install paths, the active Steam
  user id, and the last-used Steam nickname.
- **`localconfig.vdf`** (via the `vdf` library) to verify the `-condebug` launch
  option for app `730` (CS2).
- **Win32 API** (via `ctypes`) for the foreground-window title, the elevation
  check, and readable Windows error messages.

That is why the project is Windows-only.

## Startup checks

After the UI builds, `gui.run_startup_checks()` shows two non-blocking warnings:
one if the app isn't elevated (some Win32 features may need admin), and one if
`-condebug` isn't in CS2's launch options.

## Known limitations & quirks

- **Long replies post in bursts.** A reply over 221 characters is chunked, with
  `chat_delay` (0.5s) between chunks while CS2 is focused, so a multi-chunk reply
  takes a couple of seconds. There is no per-character typing delay.
- **The bind key is `'p'` in code.** Changing it means editing the source and
  your CS2 bind to match.
- **Foreground-only sending.** If CS2 isn't focused, the chunk is written to the
  cfg but not sent, by design, to avoid leaking keystrokes into other apps.

For exact constants and file paths, see [configuration.md](configuration.md).
