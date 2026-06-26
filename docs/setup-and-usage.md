# Setup & Usage

This guide covers what you need, the one-time configuration, and how to drive
the app day to day. It targets the end user running the prebuilt `.exe`; for
building from source see [building.md](building.md).

## Prerequisites

- **Windows.** The app uses the Windows registry, the Win32 API, and Steam/CS2
  install paths — it does not run on macOS or Linux.
- **Counter-Strike 2** installed via Steam.
- **A [Character.AI](https://character.ai/) account**, used to obtain an API
  token (only needed for normal AI replies — *Mimic mode* works without one).
- Running the app **as administrator** is recommended; some Win32 features may
  not work otherwise (the app warns you on startup if it isn't elevated).

## One-time CS2 setup

The app reads and writes through two CS2 file channels, so CS2 needs two pieces
of configuration:

1. **Enable console logging.** In Steam, right-click Counter-Strike 2 →
   *Properties* → *Launch Options*, and add:

   ```
   -condebug
   ```

   This makes CS2 mirror its console (including all-chat) into
   `…/game/csgo/console.log`, which is the file the app reads.

2. **Bind a key to execute the message config.** Launch CS2, open the developer
   console, and run:

   ```
   bind p "exec message.cfg"
   ```

   The app writes each outgoing chunk into `cfg/message.cfg` and then simulates
   the `p` keypress, which makes CS2 execute that file and post the message.
   The key **must be `p`** unless you also change the `bind_key` constant in the
   source — see [configuration.md](configuration.md).

The app verifies the `-condebug` part for you on startup and shows a warning if
it can't find it.

## Getting your Character.AI token

The project documents this in its top-level [`README.md`](../README.md). The
current, recommended method:

1. Log in at [character.ai](https://character.ai/) and confirm you're signed in.
2. Open your browser's Developer Tools (`F12`).
3. Go to the **Application** tab (Chrome) or **Storage** tab (Firefox).
4. Click **Cookies** in the left sidebar and select the Character.AI domain.
5. Find the cookie named **`HTTP_AUTHORIZATION`**.
6. Copy the value **after** `Token ` (the long alphanumeric string).
7. That string is your API token.

> **Note — two methods exist.** The in-app *"Get API Token"* help dialog
> (in the **Character.AI** tab) describes an older route: visit `old.character.ai`, open
> DevTools → *Local Storage* → `char_token`, and copy that value. If the
> README's cookie method doesn't work for you, try the local-storage method, and
> vice versa — Character.AI's storage has changed over time.

Paste the token into the **Character.AI** tab's **C.AI Token** field. The app
validates it immediately: a valid token greets you by username, an invalid one
is reported. A valid token is saved to `chatbot_settings.json` so you don't have
to re-enter it next time.

## Running the app

- **Prebuilt:** double-click `CS2-Chatbot.exe`. It opens an 840×600 desktop
  window titled *CS2 Chatbot*.
- **From source:** with dependencies installed (`pip install -r requirements.txt`),
  run `python src/main.py`.

On launch it checks for admin rights, checks for `-condebug`, and each area
loads any saved settings (e.g. the Character.AI token).

## UI tour

The window has a vertical sidebar on the left and a content panel on the right.

### Sidebar

- **One tab per AI behaviour** — *Character.AI*, *Mimic*, and *String Reverser*.
  The tab you have open is the active behaviour; whatever it is replies to chat.
- **Settings tab** — appearance and chatbot toggles. Opening Settings selects no
  behaviour, so the bot does nothing while it's open.
- **Power button** (`⏻`) — the master on/off toggle. It refuses to turn on until
  the open behaviour is ready (e.g. *Character.AI* needs a token **and** a
  selected character) and tells you what's missing. When on, it turns green and
  the "OFF" badge disappears.
- **Exec status light** (●) — turns red while the bot is processing a reply
  (generating it and waiting out the "thinking" delay) and green once that
  reply has been written to `message.cfg`. A quick check of where the bot is in
  its reply cycle.

### Character.AI tab

- The **C.AI Token** field (password-masked) plus a help button with token
  instructions, and a **Reset** button (`↻`) that starts a fresh chat with the
  current character, wiping its memory (disabled until one is selected).
- A text input + search button to search characters by name.
- A dropdown to switch between **Recommended**, **Trending**, and **Recent**
  sources (searching by text uses the *Search* source).
- A grid of character cards; click one to select it. Selecting a character
  creates a new chat session for the bot to use.

### Mimic / String Reverser tabs

Two zero-config example behaviours. **Mimic** echoes the last message back with
randomized capitalization (`jUsT LiKe ThIs`); **String Reverser** sends it back
reversed. Open either tab and hit power — no token required.

### Settings tab

A 2-column grid of cards: **Logic** | **Known Players** on the top row, **API
Tokens** | **Appearance** below.

- **Logic** — bot behaviour and timing:
  - **Respond Delay** and **Respond Jitter** (ms, side by side) — a fixed
    "thinking" pause plus a random amount on top, so replies don't appear instantly.
  - **Auto-press execute key** — when on, the bot presses your bind key in-game;
    when off it only writes `message.cfg` and you press the key yourself.
  - **Reply cooldown** + **Cooldown (ms)** — a minimum time between any two
    replies, across every area.
  - **Toggle keybind** — click **Set**, then press a key to bind a **global**
    hotkey that turns the bot on/off even while CS2 is focused. The choice is
    saved between launches; **Clear** unbinds it. (Unset by default.)
- **Known Players** — one toggle per person seen in chat this session, plus a
  Clear button to forget everyone.
- **API Tokens** — secret inputs contributed by the areas (e.g. the Character.AI
  token); only shown when at least one area needs a token.
- **Appearance** — a *Dark Theme* switch and a primary-color picker (the default
  accent is pink, `#ec4899`).

## Typical session

1. Launch CS2 with `-condebug` and confirm your `bind p "exec message.cfg"` is set.
2. Launch CS2-Chatbot (ideally as administrator).
3. Open the **Character.AI** tab, paste your token, and pick a persona. (Or open
   **Mimic** / **String Reverser** for a no-token behaviour.)
4. Hit the **power button** to enable the bot.
5. Tab into CS2. When other players use all-chat, the bot reads the message,
   generates a reply, and types it into chat for you — but only while CS2 is the
   focused window.

## Troubleshooting

- **"Could not find `-condebug`…" warning** — add `-condebug` to CS2's launch
  options (see above) and restart CS2.
- **Messages are read but never sent** — make sure CS2 is the *foreground*
  window (the app deliberately won't send keystrokes to other apps), and that
  your `bind p "exec message.cfg"` is active in the current CS2 session.
- **"An invalid token has been set!"** — re-copy the token; try the alternate
  extraction method noted above.
- **"Not running as admin" warning** — relaunch the app as administrator.
- **Bot replies to itself / loops** — the app already skips messages whose
  sender matches your Steam nickname; if your displayed name differs from your
  Steam nick this guard can miss, so check your in-game name.
- **Need logs?** Every run writes a verbose `cs2_chatbot_debug.log` next to the
  executable.
