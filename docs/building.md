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

1. Accepts `-Clean` (remove `build/`, `dist/`, `release/` first) and `-Help`.
2. Verifies the virtual environment exists at `.\venv\Scripts\python.exe`.
3. Removes any stale `release\CS2-Chatbot.exe`.
4. Runs `pyinstaller --clean --noconfirm packaging\CS2-Chatbot.spec`.
5. On success, creates `release/`, copies the `.exe` plus `README.md` into it,
   and prints the final size.

```powershell
.\packaging\build.ps1            # normal build
.\packaging\build.ps1 -Clean     # wipe build artifacts first
.\packaging\build.ps1 -Help      # usage
```

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
