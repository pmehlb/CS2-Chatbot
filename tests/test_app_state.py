"""Tests for AppState helpers that don't need the GUI.

Run with:  venv\\Scripts\\python -m pytest tests/test_app_state.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from app_state import AppState


def _app():
    return AppState(cs_path='', log_path='', exec_path='')


def test_area_by_key_finds_registered_area():
    app = _app()
    claude = type('A', (), {'key': 'claude'})()
    chatgpt = type('A', (), {'key': 'chatgpt'})()
    app.areas = [claude, chatgpt]
    assert app.area_by_key('claude') is claude
    assert app.area_by_key('chatgpt') is chatgpt


def test_area_by_key_returns_none_for_unknown():
    app = _app()
    app.areas = [type('A', (), {'key': 'claude'})()]
    assert app.area_by_key('nope') is None


def test_area_by_key_empty_registry():
    assert _app().area_by_key('claude') is None


if __name__ == '__main__':
    import traceback

    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            try:
                fn()
                print(f'PASS {name}')
            except Exception:
                failures += 1
                print(f'FAIL {name}')
                traceback.print_exc()
    raise SystemExit(1 if failures else 0)
