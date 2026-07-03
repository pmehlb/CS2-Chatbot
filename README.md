# CS2-Chatbot

Automatically reply to in-game Counter-Strike 2 chat — on Windows.

![image](https://github.com/skelcium/CS2-Chatbot/assets/141345390/aaaea781-60a2-4fcb-881b-178f3c0b621d)
![image](https://github.com/skel-sys/CS2-Chatbot/assets/141345390/9b8a3948-cf43-4960-a786-b87e83be4abb)

CS2-Chatbot is a Windows desktop app that reads Counter-Strike 2's all-chat,
generates a reply, and types it back into chat for you. It needs no CS2 API: it
reads the console log the game already writes and presses a key you've bound to
run a config. See **[`docs/`](docs/README.md)** for the full story.

It ships with several pluggable chat behaviours ("areas"), each on its own tab:

- **Character.AI** — replies as any [Character.AI](https://character.ai/) persona.
- **ChatGPT** — replies via OpenAI's API.
- **Claude** — replies via Anthropic's API.
- The three AI areas above can also **react to your own live game events** (tick
  "Also react to my game events"), so your persona bot gloats over your aces too.
- **Tilt Bot** — reacts to your *own live game events* (multi-kills, MVPs, round
  wins, clutches, match point) via CS2 Game State Integration; see below. Each
  section (event taunts / chat clapback) uses **built-in lines you can edit**, or
  borrows a **C.AI / ChatGPT / Claude** brain from a dropdown.
- **Command Bot (C2)** — answers `!`-prefixed commands (`!help`, `!roll`,
  `!8ball`, …) in chat.
- **Mimic** / **String Reverser** — no-account example modes that echo the last
  message back (randomized capitalization, or reversed).

The tab you have open is the active behaviour; whatever it is replies to chat.

## Requirements

- **Windows** — uses the Win32 API, the registry, and Steam/CS2 paths (no macOS/Linux).
- **Counter-Strike 2** installed via Steam.
- An **API account** for whichever AI area you use — a
  [Character.AI](https://character.ai/), OpenAI, or Anthropic key. *Tilt Bot*,
  *Command Bot*, *Mimic*, and *String Reverser* work without one.
- Running **as administrator** is recommended (the app warns you if it isn't).

## One-time CS2 setup

1. Add `-condebug` to your CS2 launch options (Steam → CS2 → *Properties* →
   *Launch Options*). This makes CS2 mirror all-chat to `console.log`, the file the app reads.
2. In the CS2 developer console, bind a key to run the message config:

   ```
   bind p "exec message.cfg"
   ```

   The key **must be `p`** unless you also change the `bind_key` constant in the source.

## Tilt Bot & Game State Integration (GSI)

*Tilt Bot* doesn't wait for someone to type — it reacts to **your own live game
events** and fires off a cocky all-chat line: multi-kills (3K / 4K / ace), round
MVPs, round wins, surviving a round on low HP, and reaching match point.

It does this through **Game State Integration (GSI)**, CS2's official,
read-only channel: the game POSTs structured game-state JSON to a small local
endpoint inside the app. To enable it:

1. In **Settings**, under **Game State Integration (GSI)**, click **Install GSI
   config** — this writes a `gamestate_integration_cs2chatbot.cfg` into CS2's
   `cfg/` folder.
2. **Fully restart CS2** (GSI config is only picked up at launch).
3. Back in Settings, the connection light turns green ("Receiving game data")
   once CS2 starts POSTing.
4. On the **Tilt Bot** tab, toggle which events to react to and pick a taunt
   source. (The Character.AI / ChatGPT / Claude tabs can opt in too, via "Also
   react to my game events".)

**Ban-safe.** GSI is official and read-only — it never touches game memory, the
same safety posture as the console.log read path.

**Limitation — your own play only.** During live matchmaking, GSI exposes
**only your own player data** (opponent-by-name data is sent only while
spectating). That's why Tilt Bot's event taunts are about *your* performance;
name-targeted trash talk still comes from the chat behaviours (Character.AI /
ChatGPT / Claude) — though Tilt Bot's chat clapback can now borrow one of those
same brains, so it can name the speaker too when "Attribute messages to
speakers" is on.

## Getting your Character.AI token

1. Log in at [character.ai](https://character.ai/) and confirm you're signed in.
2. Open DevTools (`F12`) → **Application** tab (Chrome) or **Storage** tab (Firefox).
3. Click **Cookies** and select the Character.AI domain.
4. Find the **`HTTP_AUTHORIZATION`** cookie and copy the value **after** `Token `.

Paste that into the app's **Character.AI** tab. If it doesn't work, try the
[alternate method](docs/setup-and-usage.md#getting-your-characterai-token).

## Build from source (Windows, PowerShell)

From the repository root:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
powershell -ExecutionPolicy Bypass -File .\packaging\build.ps1
```

The executable is written to the `release/` folder. To run without building, use
`python src\main.py` from the activated venv. See [`docs/building.md`](docs/building.md)
for details.

## Can I be banned for this?

No. It only reads a log file CS2 itself writes and presses a key you bound — it
never touches game memory. See [how it works](docs/how-it-works.md).

## Documentation

Full documentation lives in **[`docs/`](docs/README.md)**:
[how it works](docs/how-it-works.md) ·
[setup & usage](docs/setup-and-usage.md) ·
[configuration](docs/configuration.md) ·
[code reference](docs/code-reference.md) ·
[building](docs/building.md)

## License & credits

CS2-Chatbot is free software, licensed under the **[GNU General Public License
v3.0](LICENSE)** (GPL-3.0).

It is a fork of the original
**[CS2-Chatbot](https://github.com/skel-sys/CS2-Chatbot)** by **skel (SkelV7)**
and contributors — SmalltimeTommie, Saumitra Topinkatti, and Matt Borle — which
is also GPL-3.0.

**Significant changes in this fork:** restructured the original single-file app
into a modular `core` / `gui` / `areas` layout; added the ChatGPT, Claude,
Command Bot (C2), and GSI-driven Tilt Bot areas plus cross-area composition; and
reworked the Settings tab. Per the terms of the GPL, the full license text is
retained in [`LICENSE`](LICENSE) and this project remains licensed under
GPL-3.0.
