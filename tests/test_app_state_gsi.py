# tests/test_app_state_gsi.py
import os
import sys
from collections import deque

# Make the application package layout (src/) importable when run from anywhere.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from app_state import AppState


def _make_app():
    return AppState(cs_path='x', log_path='y', exec_path='z')


def test_gsi_fields_have_sane_defaults():
    app = _make_app()
    assert app.gsi_token == ''
    assert isinstance(app.gsi_events, deque)
    assert app.gsi_events.maxlen == 8
    assert app.gsi_prev == {}


def test_gsi_events_is_per_instance():
    a, b = _make_app(), _make_app()
    a.gsi_events.append('x')
    assert len(b.gsi_events) == 0
