# CS2-Chatbot

Automatically reply to in-game Counter-Strike 2 chat — on Windows.

![image](https://github.com/skelcium/CS2-Chatbot/assets/141345390/aaaea781-60a2-4fcb-881b-178f3c0b621d)
![image](https://github.com/skel-sys/CS2-Chatbot/assets/141345390/9b8a3948-cf43-4960-a786-b87e83be4abb)

CS2-Chatbot is a Windows desktop app that reads Counter-Strike 2's all-chat,
generates a reply — via [Character.AI](https://character.ai/), or a no-account
*Mimic* / *String Reverser* mode — and types it back into chat for you. It needs
no CS2 API: it reads the console log the game already writes and presses a key
you've bound to run a config. See **[`docs/`](docs/README.md)** for the full story.

## Requirements

- **Windows** — uses the Win32 API, the registry, and Steam/CS2 paths (no macOS/Linux).
- **Counter-Strike 2** installed via Steam.
- A **[Character.AI](https://character.ai/) account** — only for AI replies;
  *Mimic* and *String Reverser* work without one.
- Running **as administrator** is recommended (the app warns you if it isn't).

## One-time CS2 setup

1. Add `-condebug` to your CS2 launch options (Steam → CS2 → *Properties* →
   *Launch Options*). This makes CS2 mirror all-chat to `console.log`, the file the app reads.
2. In the CS2 developer console, bind a key to run the message config:

   ```
   bind p "exec message.cfg"
   ```

   The key **must be `p`** unless you also change the `bind_key` constant in the source.

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
