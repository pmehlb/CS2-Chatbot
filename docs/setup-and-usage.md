# Setup & Usage

This guide covers what you need, the one-time configuration, and how to drive
the app day to day. It targets the end user running the prebuilt `.exe`; for
building from source see [building.md](building.md).

## Prerequisites

- **Windows.** The app uses the Windows registry, the Win32 API, and Steam/CS2
  install paths; it does not run on macOS or Linux.
- **Counter-Strike 2** installed via Steam.
- **An API account** for whichever AI area you use: a
  [Character.AI](https://character.ai/), OpenAI, or Anthropic key (only needed
  for AI replies). *Tilt Bot*, *Command Bot*, *Mimic*, and *String Reverser*
  work without one.
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
   source. See [configuration.md](configuration.md).

The app verifies the `-condebug` part for you on startup and shows a warning if
it can't find it.

## Optional: Tilt Bot setup (Game State Integration)

The **Tilt Bot** area reacts to your *own* live game events (multi-kills, MVPs,
round wins, low-HP survival, match point) using CS2's official, read-only Game
State Integration. To enable it:

1. Open **Settings** and find the **Game State Integration (GSI)** card.
2. Click **Install GSI config**. This writes
   `gamestate_integration_cs2chatbot.cfg` into CS2's `cfg/` folder, pointing the
   game at the app's local `/gsi` endpoint.
3. **Fully restart CS2** (GSI config is only read at launch).
4. Watch the card's connection light: it turns green and reads **"Receiving game
   data"** once CS2 starts POSTing game state to the app.
5. On the **Tilt Bot** tab, under **Game events**, toggle which events to react
   to (all on by default), pick a **Taunt source**, and optionally **Clap back at
   incoming chat**. (Character.AI / ChatGPT / Claude can also opt in via "Also
   react to my game events".)

This is just as ban-safe as the chat read path: GSI is official and read-only.
Note that during live matchmaking GSI exposes only *your own* player data, which
is why Tilt Bot taunts about your play rather than named opponents.

## Getting your Character.AI token

The current, recommended method:

1. Log in at [character.ai](https://character.ai/) and confirm you're signed in.
2. Open your browser's Developer Tools (`F12`).
3. Go to the **Application** tab (Chrome) or **Storage** tab (Firefox).
4. Click **Cookies** in the left sidebar and select the Character.AI domain.
5. Find the cookie named **`HTTP_AUTHORIZATION`**.
6. Copy the value **after** `Token ` (the long alphanumeric string).
7. That string is your API token.

> **Note: two methods exist.** The in-app *"Get API Token"* help dialog
> (in the **Character.AI** tab) describes an older route: visit `old.character.ai`, open
> DevTools → *Local Storage* → `char_token`, and copy that value. If the
> cookie method above doesn't work for you, try the local-storage method, and
> vice versa; Character.AI's storage has changed over time.

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

- **One tab per behavior:** *Character.AI*, *ChatGPT*, *Claude*, *Tilt Bot*,
  *Command Bot*, *Mimic*, and *String Reverser*. The tab you have open is the
  active behavior; whatever it is replies to chat (and, for *Tilt Bot*, reacts
  to game events).
- **Settings tab.** Appearance and chatbot toggles. Opening Settings selects no
  behavior, so the bot does nothing while it's open.
- **Power button** (`⏻`). The master on/off toggle. It refuses to turn on until
  the open behavior is ready (e.g. *Character.AI* needs a token **and** a
  selected character) and tells you what's missing. When on, it turns green and
  the "OFF" badge disappears.
- **Exec status light** (●). Turns red while the bot is processing a reply
  (generating it and waiting out the "thinking" delay) and green once that
  reply has been written to `message.cfg`. It's a quick check of where the bot
  is in its reply cycle.

### Character.AI tab

- The **C.AI Token** field (password-masked) plus a help button with token
  instructions, and a **Reset** button (`↻`) that starts a fresh chat with the
  current character, wiping its memory (disabled until one is selected).
- A text input + search button to search characters by name.
- A dropdown to switch between **Recommended**, **Trending**, and **Recent**
  sources (searching by text uses the *Search* source).
- A grid of character cards; click one to select it. Selecting a character
  creates a new chat session for the bot to use.

### Tilt Bot tab

Reacts to your own live game events via Game State Integration (set up in
**Settings**; see [above](#optional-tilt-bot-setup-game-state-integration)).
Cards:

- **Game events.** A checkbox per event type (multi-kills, MVP, round win,
  low-HP survival, match point, match win), all on by default; a **Taunt
  source** dropdown; and an editable taunt-line pool.
- **Chat.** A **Clap back at incoming chat** toggle, a **Clapback source**
  dropdown, and an editable clapback-line pool.
- **Requires Game State Integration.** A note with a button that jumps to the
  Settings GSI card.

Each source can be **Canned** (the editable built-in lines, no API key) or an AI
brain (C.AI / ChatGPT / Claude).

### Mimic / String Reverser tabs

Two zero-config example behaviors. **Mimic** echoes the last message back with
randomized capitalization (`jUsT LiKe ThIs`); **String Reverser** sends it back
reversed. Open either tab and hit power; no token required.

### Settings tab

A 2-column grid of cards: **Logic** | **Known Players** on the top row, **API
Tokens** | **Appearance** below.

- **Logic.** Bot behavior and timing:
  - **Respond Delay** and **Respond Jitter** (ms, side by side): a fixed
    "thinking" pause plus a random amount on top, so replies don't appear
    instantly. Both default to `0` (off), which sends a reply as soon as it's
    generated.
  - **Cooldown** and **Cooldown (ms)**: when the switch is on, the bot waits at
    least this long (default 3000 ms) between any two replies, across every area.
    Useful against command spam. Off by default.
  - **Auto-press execute key:** when on, the bot presses your bind key in-game;
    when off it only writes `message.cfg` and you press the key yourself.
  - **Attribute messages to speakers:** when on, each incoming chat message is
    fed to the AI areas as `[Name] said: message`, so replies can track who said
    what. The Command Bot and Reverser opt out so it doesn't break their parsing.
    Off by default.
  - **Toggle keybind:** click **Set**, then press a key to bind a **global**
    hotkey that turns the bot on/off even while CS2 is focused. The choice is
    saved between launches; **Clear** unbinds it. (Unset by default.)
- **Known Players.** One toggle per person the bot has seen in chat this session;
  everyone defaults to on (respond). Turn someone off and the bot ignores their
  messages. **Clear** forgets the whole list. The roster is in-memory only and
  resets when you relaunch.
- **API Tokens.** Secret inputs contributed by the areas (e.g. the Character.AI
  token); only shown when at least one area needs a token.
- **Appearance.** A *Dark Theme* switch and a primary-color picker (the default
  accent is pink, `#ec4899`).

## Typical session

1. Launch CS2 with `-condebug` and confirm your `bind p "exec message.cfg"` is set.
2. Launch CS2-Chatbot (ideally as administrator).
3. Open the **Character.AI** tab, paste your token, and pick a persona. (Or open
   **Mimic** / **String Reverser** for a no-token behavior.)
4. Hit the **power button** to enable the bot.
5. Tab into CS2. When other players use all-chat, the bot reads the message,
   generates a reply, and types it into chat for you, but only while CS2 is the
   focused window.

## Troubleshooting

- **"Could not find `-condebug`…" warning.** Add `-condebug` to CS2's launch
  options (see above) and restart CS2.
- **Messages are read but never sent.** Make sure CS2 is the *foreground*
  window (the app deliberately won't send keystrokes to other apps), and that
  your `bind p "exec message.cfg"` is active in the current CS2 session.
- **"An invalid token has been set!"** Re-copy the token, and try the alternate
  extraction method noted above.
- **"Not running as admin" warning.** Relaunch the app as administrator.
- **Bot replies to itself / loops.** The app already skips messages whose
  sender matches your Steam nickname; if your displayed name differs from your
  Steam nick this guard can miss, so check your in-game name.
- **Need logs?** Every run writes a verbose `cs2_chatbot_debug.log` next to the
  executable.
