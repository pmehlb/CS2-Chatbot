# CS2-Chatbot — Documentation

CS2-Chatbot is a **Windows desktop application that automatically replies to
in-game Counter-Strike 2 chat messages**. It reads what other players type,
generates a response with [Character.AI](https://character.ai/) (or echoes the
message back in "mimic" mode), and types that response into CS2's all-chat —
all on its own.

It is a small modular Python app (under `src/`) — a thin `main.py` entrypoint
plus focused modules (`system/winutil`, `app_state`, `core`, `ui/gui`,
`ui/ui_util`) and a pluggable `areas/` package of AI behaviours — with a
[NiceGUI](https://nicegui.io/)
interface rendered in a native desktop window.

```
Someone in CS2 types:        "anyone clutching this?"
                                      │
                                      ▼
CS2-Chatbot reads it, asks the selected Character.AI persona,
and types the reply straight into all-chat:

                              "watch me 1v3 nerd 😎"
```

---

## What's in this folder

| Document | What it covers |
|----------|----------------|
| [how-it-works.md](how-it-works.md) | **Start here.** The end-to-end architecture and the full lifecycle of a single chat message, including the console.log → cfg → keypress trick that makes input injection possible. |
| [setup-and-usage.md](setup-and-usage.md) | Prerequisites, one-time CS2 setup, getting a Character.AI token, running the app, and a tour of the UI and its modes. |
| [configuration.md](configuration.md) | Every tunable constant, the files the app reads/writes, and the Windows registry keys it queries — a quick reference. |
| [code-reference.md](code-reference.md) | A map of the codebase module by module — what each file is responsible for. |
| [building.md](building.md) | Building the portable `.exe` from source (PyInstaller), the build scripts, and the release process. |

---

## The 30-second version of "how it works"

CS2 has no public API for reading or sending chat, so the app uses two
file-based side channels that the game already supports:

1. **Reading chat** — Launching CS2 with `-condebug` makes it mirror its
   console (including all-chat) to `game/csgo/console.log`. The app polls that
   file ~10×/second and picks up the latest `[ALL]` message.
2. **Sending chat** — The app writes a CS2 config file
   (`cfg/message.cfg`) containing a `say "..."` command, then simulates a
   keypress of a key the user has bound to `exec message.cfg`. CS2 executes the
   config and the message appears in chat.

Between those two steps it generates the reply via Character.AI. See
[how-it-works.md](how-it-works.md) for the details.

---

## At a glance

- **Platform:** Windows only (uses the Win32 API, the Windows registry, and Steam/CS2 install paths).
- **Language / runtime:** Python 3 (the CI built with Python 3.13).
- **UI:** NiceGUI in `native=True` mode (a pywebview desktop window, 840×600).
- **Response engine:** Character.AI via the unofficial `PyCharacterAI` library.
- **Input injection:** `pydirectinput` keypress + a bound CS2 config exec.
- **Distribution:** A single windowed `.exe` produced by PyInstaller.

> **Can you be banned for this?** The project's own README answers "No" — it
> only reads a log file the game itself writes and presses a key you bound. It
> does not read or modify game memory. Use your own judgment and respect server
> rules regardless.
