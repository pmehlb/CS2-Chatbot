import importlib
import os
import sys

# Make the application package layout (src/) importable when run from anywhere.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

mods = [
    "system.winutil", "ui.ui_util", "app_state", "core", "ui.gui", "areas",
    "areas.base", "areas.characterai", "areas.commands", "areas.mimic",
    "areas.string_reverser", "areas.settings", "main",
]
for m in mods:
    importlib.import_module(m)
    print("OK import", m)

from areas import build_areas
areas = build_areas()
print("OK build_areas ->", [a.key for a in areas])

from app_state import AppState
app = AppState(cs_path="x", log_path="x", exec_path="x")
print("OK AppState construct; bind_key=", app.bind_key)

print("PYTHON", sys.version)
print("SMOKE TEST PASSED")
