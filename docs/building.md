# Building from Source

CS2-Chatbot ships as a single portable Windows `.exe` built with **PyInstaller**.
This page covers building it yourself.

> **Windows only.** The build (like the app) targets Windows and uses PowerShell,
> with Python 3.13.

## Quick start

From the top-level [`README.md`](../README.md):

```powershell
# 1. Clone the repo, then from its root:
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 2. Build the executable
powershell -ExecutionPolicy Bypass -File .\packaging\build.ps1
```

The finished executable lands in the **`release`** folder as `CS2-Chatbot.exe`,
alongside a copy of `README.md`.

## The build script

[`packaging/build.ps1`](../packaging/build.ps1) is the only build entry point. It
lives in `packaging/` but builds from the repo root (it `Set-Location`s there), so
you can run it from anywhere. It:

1. Accepts `-Clean` (remove `build/`, `dist/`, `release/` first), `-Run`, and `-Help`.
2. Verifies the virtual environment exists at `.\venv\Scripts\python.exe`.
3. Removes any stale `release\CS2-Chatbot.exe`.
4. Runs `pyinstaller --clean --noconfirm packaging\CS2-Chatbot.spec`.
5. On success, creates `release/`, copies the `.exe` plus `README.md` into it,
   and prints the final size.
6. With `-Run`, copies `.for_personal_use\chatbot_settings.json` into `release/`
   and starts the executable.

```powershell
.\packaging\build.ps1            # normal build
.\packaging\build.ps1 -Clean     # wipe build artifacts first
.\packaging\build.ps1 -Run       # build, load personal settings, launch
.\packaging\build.ps1 -Help      # usage
```

## Build and run

`-Run` is the local development loop: build the `.exe`, give it your real
settings, and launch it.

The app reads `chatbot_settings.json` from the folder the `.exe` sits in, so a
fresh `release/` starts with no API keys. `-Run` copies your personal copy from
`.for_personal_use\chatbot_settings.json` (a local, git-ignored folder) into
`release\chatbot_settings.json` first, and overwrites the file that is there.

Every step of `-Run` is optional and never fails the build:

| Situation | What happens |
| --- | --- |
| The personal file exists | The script copies it and starts the `.exe`. |
| The file is missing | The script prints a note and starts the `.exe` anyway. |
| The copy fails (file locked) | The script prints a warning and starts the `.exe` anyway. |
| The `.exe` will not start | The script prints the error and exits with code 1. |

PyCharm users get the same thing from the **Build and Run** shell-script
configuration in `.idea/runConfigurations/`. The `.idea/` folder is git-ignored,
so that file stays on your machine only.

## The PyInstaller spec file

[`CS2-Chatbot.spec`](../packaging/CS2-Chatbot.spec) is **required**; it isn't
optional boilerplate. NiceGUI, pywebview, PyDirectInput, PyCharacterAI, the
`keyboard` library, and the Anthropic SDK all ship data files, binaries, and
hidden imports that PyInstaller's automatic analysis misses, so the spec:

- Calls `collect_all(...)` for `nicegui`, `pywebview`, `pydirectinput`,
  `PyCharacterAI`, `keyboard`, and `anthropic` to gather their
  data/binaries/hidden imports.
- Adds an explicit `hiddenimports` list covering those packages plus `openai`,
  `requests`, `numerize`, `vdf`, and their trickier dependencies (`curl_cffi`,
  `bottle`, `proxy_tools`, `pythonnet`, `typing_extensions`, and several
  `nicegui.*` / `pydirectinput.*` submodules).
- Builds a **single windowed** executable: `console=False` (no terminal window),
  `upx=True` (compressed), and the app icon (`packaging/app.ico`).

The spec resolves `src/main.py` and `app.ico` relative to its own location
(`packaging/`), so the build works regardless of the directory PyInstaller is
invoked from.

> `.gitignore` normally excludes `*.spec`, but there is an explicit
> `!packaging/CS2-Chatbot.spec` rule keeping this one tracked, so do not delete it.

## Build output

| Path | Contents |
|------|----------|
| `build/` | PyInstaller's intermediate work (git-ignored). |
| `dist/` | PyInstaller's raw output: `dist/CS2-Chatbot.exe` (git-ignored). |
| `release/` | The distributable bundle: `CS2-Chatbot.exe` + `README.md` (git-ignored). |

## Releasing a new version

There is no CI or automated release pipeline in the repo, and the app has no
in-app update check or `current_version` constant. Cutting a release is manual:
run `packaging\build.ps1` and distribute the resulting `release\CS2-Chatbot.exe`.
Tag the commit (`vX.Y.Z`) if you want the version marked in git history.
