# How It Works

This is the core of the documentation: how CS2-Chatbot reads chat, decides what
to say, and gets that text back into the game — none of which Counter-Strike 2
exposes through an official API.

## The central problem

CS2 gives third-party programs no supported way to **read** in-game chat or
**send** a chat message. CS2-Chatbot works around both halves of that problem
using features the game already ships with:

- **Reading** relies on the `-condebug` launch option, which mirrors the
  in-game console (all-chat included) into a plain text log file.
- **Sending** relies on CS2 config files: the app writes a `say "..."` command
  into a `.cfg` file and presses a key the user has bound to `exec` that file.

Everything else — the GUI, Character.AI, the various safety checks — exists to
wire those two channels together.

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
   │  CS2 runs: exec          │                                 │  find newest "[ALL]" line│
   │  message.cfg             │                                 └─────────────┬────────────┘
   │  → say "<chunk>"         │                                               │ split "sender: message"
   └──────────▲───────────────┘                                              ▼
              │ app writes the file                              ┌──────────────────────────┐
              │                                                  │ Skip if:                 │
   ┌──────────┴───────────────┐                                 │  • no [ALL] line is new  │
   │  game/csgo/cfg/          │                                 │  • not an [ALL] line     │
   │  message.cfg             │ ◄───────────────────────────────│  • sender is yourself    │
   │   say "<response chunk>" │      write each chunk, then      └─────────────┬────────────┘
   └──────────────────────────┘      press the bound key                       │ new message from someone else
                                                                                ▼
                                                                  ┌──────────────────────────┐
                                                                  │ Active area generates    │
                                                                  │  the reply:              │
                                                                  │  CharacterAI / Mimic /   │
                                                                  │  String Reverser         │
                                                                  └─────────────┬────────────┘
                                                                                │ clean text, split into
                                                                                ▼ ≤221-char chunks
                                                                       (back up to message.cfg)
```

## The message lifecycle, step by step

The heartbeat of the app is a NiceGUI timer registered in `main.py`:

```python
ui.timer(0.1, lambda: core.handle_tick(app), active=True)
```

This calls `core.handle_tick(app)` ten times a second. On each tick:

1. **Gate on the toggle.** If the power button isn't on (`app.powered_on` is
   `False`) — or the Settings tab is open, so no behaviour is selected
   (`app.active_area` is `None`) — the tick does nothing. The timer keeps firing,
   but nothing is sent until you enable the bot on a behaviour's tab.

2. **Read new chat lines.** `core.LogTailer` reads only the bytes appended to
   `console.log` since the previous tick (no whole-file re-read), and the loop
   takes the newest line containing the marker `  [ALL] ` — how CS2 tags all-chat
   messages. On startup the tailer skips everything already in the file, and if
   CS2 recreates the log (which it does each launch) it resets and keeps
   following.

3. **Filter.** (Handled by `core.extract_latest_message`.)
   - If no new `[ALL]` line arrived this tick, there's nothing to do. The tailer
     only ever yields genuinely new lines, so the old "same as last message"
     guard is no longer needed.
   - The line is split on the first `': '` — the part before is the sender, the
     part after is the full message (so a message that itself contains `': '` is
     kept intact).
   - The sender name is cleaned for the roster: CS2 appends a `U+200E`
     left-to-right mark right after the name (followed by status decoration like
     ` [DEAD]`), so the name is cut at that mark — giving one stable entry per
     player whether they're alive or dead.
   - If the sender contains your own Steam nickname (read once at startup via
     `get_last_steam_nick()`), it's skipped — this stops the bot replying to
     itself in a loop.
   - Every other sender is added to the session **roster** (`app.roster`) the
     first time they speak, defaulting to "respond". The **Known Players** card
     in Settings lists everyone seen and lets you toggle individuals off (or
     **Clear** the list). Messages from someone toggled off are skipped, so the
     loop answers the newest message from a sender who's still allowed. The
     roster is in-memory only and resets each launch.

4. **Generate a response.** The loop calls `active_area.generate(message, app)`
   — whichever behaviour's tab is open:
   - **Character.AI** sends the message to the selected character on the active
     chat session (`client.chat.send_message(...)`) and returns
     `answer.get_primary_candidate().text`.
   - **Mimic** returns the message with each character's case randomized
     (`tExT LiKe ThIs`); **String Reverser** returns it reversed.
   - A handler may return `None` to stay silent. Errors are logged, surfaced as a
     GUI notification, and the tick aborts.

5. **Clean the text.** Double quotes are replaced with two single quotes
   (`"` → `''`) and newlines with spaces, so the text can sit safely inside a
   `say "..."` command.

6. **Chunk it.** CS2's chat has a character limit (the app uses 221, with a note
   that 222 was observed being cut off), so the response is sliced into
   ≤221-character pieces.

7. **Inject each chunk into the game.** For every chunk:
   - Write the chunk into `cfg/message.cfg` as `say "<chunk>"`.
   - **Only if** the foreground window title is exactly `Counter-Strike 2`
     (checked with `get_foreground_window_title()`), simulate the bound key
     (`pydirectinput.write('p')`). That keypress triggers CS2's
     `bind p "exec message.cfg"`, which runs the `say` command and posts the
     chunk to all-chat.
   - The foreground-window check ensures the synthetic keypress is never sent to
     some other application you've alt-tabbed into.
   - Before sending a reply, the app waits a "thinking" pause of
     `response_delay_ms` plus a random `0..response_jitter_ms` (both set in
     Settings; `0` disables it), then waits `chat_delay` (0.5s) between chunks.

## Why the keypress + config trick is needed

`pydirectinput` cannot simply "type the message" into CS2's chat box reliably,
and there's no command-line way to make CS2 say something. But CS2 *will*
execute any console commands placed in a config file when you `exec` it, and a
key bind is a first-class, supported way to trigger an `exec`. So the app:

1. Puts the command it wants CS2 to run (`say "..."`) into `message.cfg`.
2. Presses the one key the user bound to `exec message.cfg`.

This means the *content* is delivered through a file (no fragile character-by-
character typing), and only a single, reliable keypress is simulated. The user's
one-time setup (`bind p "exec message.cfg"`, described in
[setup-and-usage.md](setup-and-usage.md)) is what closes the loop.

## Character.AI integration

Character.AI is reached through the unofficial **PyCharacterAI** library, using a
token-based session:

- **Authentication** — `CharacterAIArea.set_token()` calls `get_client(token=...)`
  and then `fetch_me()`. If the account comes back as `ANONYMOUS`, the token is
  treated as invalid. A valid token greets you by username and (optionally)
  persists to `chatbot_settings.json` (under the `characterai` key).
- **Browsing characters** — `CharacterAIArea.search()` populates the
  Character.AI tab with cards. The dropdown maps to different library calls:
  - `Recommended` → `fetch_recommended_characters()`
  - `Trending` → `fetch_featured_characters()`
  - `Recent` → `fetch_recent_chats()` (wrapped into character-like objects)
  - `Search` → `search_characters(<query>)`
- **Selecting a character** — `CharacterAIArea.select_character()` stores the
  character and calls `create_chat()` to start a fresh conversation. This is what
  the bot replies as.
- **Resetting memory** — the reset button re-runs character selection, which
  creates a brand-new chat and therefore wipes the persona's conversational
  memory.

## Startup checks

After the UI is built, `gui.run_startup_checks()` shows two non-blocking
warnings:

- **Admin check** (`is_running_as_admin()`) — warns (but doesn't block) if the
  app isn't elevated; some Win32 features may not work without admin rights.
- **`-condebug` check** (`is_condebug_in_game_args()`) — parses Steam's
  `localconfig.vdf` to confirm `-condebug` is present in CS2's launch options,
  warning you if it isn't.

Each area loads its own saved settings when its tab is built — the Character.AI
area, for example, restores your token from `chatbot_settings.json`.

## Windows integration

Because CS2 and Steam are tightly coupled to Windows, the app leans on the OS
directly:

- **Registry** (`winreg`) locates the Steam install path, the CS2 install path,
  the active Steam user id, and the last-used Steam nickname.
- **`localconfig.vdf`** (parsed with the `vdf` library) is read to verify the
  `-condebug` launch option for app `730` (CS2).
- **Win32 API** (via `ctypes`) is used for the foreground-window title, the
  admin/elevation check (process token inspection), and human-readable Windows
  error messages.

All of this is why the project is Windows-only.

## Known limitations & quirks

These are worth knowing when reading the code or extending it:

- **Humanized typing is slow.** The `0.2s × length` delay means a long chunk can
  take tens of seconds before it's sent.
- **Single hard-coded bind key.** The bound key is `'p'` in code; changing it
  requires editing the source (and your CS2 bind to match).
- **Foreground-only sending.** If CS2 isn't the focused window, the chunk is
  written to the cfg but never sent — by design, to avoid leaking keystrokes
  into other apps.

For exact constants and file paths referenced above, see
[configuration.md](configuration.md).
