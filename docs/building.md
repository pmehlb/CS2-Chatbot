# Building from Source

CS2-Chatbot ships as a single portable Windows `.exe` built with **PyInstaller**.
This page covers building it yourself and how official releases are produced.

> **Windows only.** The build (like the app) targets Windows and uses
> PowerShell. The CI built with **Python 3.13**.

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

The finished executable lands in the **`release`** folder as
`CS2-Chatbot.exe`, alongside a copy of `README.md`.

## The build scripts

There are two equivalent entry points; both ultimately invoke PyInstaller with
the spec file.

### `build.ps1` (canonical, used by CI)

[`build.ps1`](../packaging/build.ps1) is the PowerShell build script and the one
the release pipeline uses. It lives in `packaging/` but builds from the repo root
(it `Set-Location`s there), so run it from the project root. It:

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

### `build.py` (cross-checking / alternative)

[`build.py`](../build.py) does the same job in Python. It warns if you're not
in a virtual environment, cleans `build/` and `dist/`, runs
`pyinstaller --noconfirm CS2-Chatbot.spec`, and then assembles the `release/`
folder. Useful if you'd rather not invoke PowerShell directly:

```powershell
python build.py
```

## The PyInstaller spec file

[`CS2-Chatbot.spec`](../packaging/CS2-Chatbot.spec) is **required**; it isn't optional
boilerplate. NiceGUI, pywebview, PyDirectInput, and PyCharacterAI all ship data
files, binaries, and hidden imports that PyInstaller's automatic analysis misses,
so the spec:

- Calls `collect_all(...)` for `nicegui`, `pywebview`, `pydirectinput`, and
  `PyCharacterAI` to gather their data/binaries/hidden imports.
- Adds an explicit `hiddenimports` list covering those packages plus their
  trickier dependencies (`curl_cffi`, `bottle`, `proxy_tools`, `pythonnet`,
  `typing_extensions`, and several `nicegui.*` / `pydirectinput.*` submodules).
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

## Release process (CI)

Releases were produced by a GitHub Actions workflow,
`.github/workflows/build.yml`. (At the time of writing this workflow is **staged
for deletion** in the working tree (`git status` shows it as deleted), so the
description below reflects its last committed form; revive or adapt it if you
want automated releases again.)

The workflow:

- **Triggered** on pushes of version tags matching `v*` (and manual
  `workflow_dispatch`).
- **Ran on** `windows-latest` with Python 3.13.
- **Steps:** create the venv → `pip install -r requirements.txt` →
  `packaging\build.ps1` → verify `release\CS2-Chatbot.exe` exists → generate a changelog
  from the commit range since the previous tag → upload the build artifact →
  create a GitHub Release (via `softprops/action-gh-release`) attaching
  `CS2-Chatbot.exe` and `README.md`.
- Tags containing `-` (e.g. `v1.4.0-beta`) were marked as **pre-releases**.

So a normal release was: commit, tag `vX.Y.Z`, and push the tag, and the pipeline
built and published the rest.

## Releasing a new version

The app has no in-app update check or `current_version` constant, so cutting a
release is just tagging and pushing: commit your changes, tag `vX.Y.Z`, and push
the tag.
