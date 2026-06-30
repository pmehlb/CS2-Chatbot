# tests/test_gsi_io.py
import os
import sys
from collections import deque

# Make the application package layout (src/) importable when run from anywhere.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from system import gsi


class FakeApp:
    """Minimal stand-in for AppState for GSI I/O tests."""
    def __init__(self, cs_path, token='tok123'):
        self.cs_path = cs_path
        self.gsi_token = token
        self.gsi_events = deque(maxlen=8)
        self.gsi_prev = {}
        self.gsi_last_seen = 0.0


def _live_then_over():
    base = {
        'player': {'steamid': '1', 'team': 'CT',
                   'state': {'health': 100, 'round_kills': 5},
                   'match_stats': {'mvps': 0}},
        'round': {'phase': 'live', 'win_team': None},
        'map': {'team_ct': {'score': 0}, 'team_t': {'score': 0}},
        'auth': {'token': 'tok123'},
    }
    over = {**base, 'round': {'phase': 'over', 'win_team': 'CT'}}
    return base, over


def test_write_gsi_cfg_contains_port_token_and_route(tmp_path):
    cfg_dir = tmp_path / 'cfg'
    cfg_dir.mkdir()
    app = FakeApp(str(tmp_path), token='secret42')
    path = gsi.write_gsi_cfg(app)
    assert os.path.basename(path) == gsi.GSI_CFG_NAME
    text = open(path, encoding='utf-8').read()
    assert f'127.0.0.1:{gsi.GSI_PORT}/gsi' in text
    assert 'secret42' in text
    assert '"player_state"' in text


def test_handle_payload_rejects_bad_token(tmp_path):
    app = FakeApp(str(tmp_path), token='right')
    base, over = _live_then_over()
    over['auth'] = {'token': 'wrong'}
    n = gsi.handle_payload(app, over)
    assert n == 0
    assert len(app.gsi_events) == 0
    assert app.gsi_last_seen == 0.0           # bad token never stamps "receiving"


def test_handle_payload_stamps_last_seen_on_valid_token(tmp_path):
    app = FakeApp(str(tmp_path), token='tok123')
    base, _ = _live_then_over()
    gsi.handle_payload(app, base)             # zero events, but a valid POST
    assert app.gsi_last_seen > 0.0


def test_handle_payload_enqueues_events_and_updates_prev(tmp_path):
    app = FakeApp(str(tmp_path), token='tok123')
    base, over = _live_then_over()
    assert gsi.handle_payload(app, base) == 0       # first frame: baseline only
    assert app.gsi_prev != {}
    n = gsi.handle_payload(app, over)               # live -> over with 5k + win
    assert n >= 1
    kinds = [e.kind for e in app.gsi_events]
    assert 'MULTI_KILL' in kinds and 'ROUND_WIN' in kinds
