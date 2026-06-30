# tests/test_gsi.py
import os
import sys

# Make the application package layout (src/) importable when run from anywhere.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from system.gsi import (TiltEvent, detect_events, is_receiving,
                        GSI_FRESH_SECONDS, WIN_SCORE)


class _SeenApp:
    def __init__(self, last_seen):
        self.gsi_last_seen = last_seen


def test_is_receiving_false_before_first_post():
    assert is_receiving(_SeenApp(0.0), now=100.0) is False


def test_is_receiving_true_within_fresh_window():
    assert is_receiving(_SeenApp(100.0), now=100.0 + GSI_FRESH_SECONDS - 1) is True


def test_is_receiving_false_when_stale():
    assert is_receiving(_SeenApp(100.0), now=100.0 + GSI_FRESH_SECONDS + 1) is False


def _payload(round_phase='live', win_team=None, team='CT',
             round_kills=0, health=100, mvps=0, ct_score=0, t_score=0,
             steamid='123'):
    return {
        'player': {
            'steamid': steamid, 'team': team,
            'state': {'health': health, 'round_kills': round_kills},
            'match_stats': {'mvps': mvps},
        },
        'round': {'phase': round_phase, 'win_team': win_team},
        'map': {'team_ct': {'score': ct_score}, 'team_t': {'score': t_score}},
    }


def _kinds(events):
    return [e.kind for e in events]


def test_multikill_fires_on_round_over():
    prev = _payload(round_phase='live', round_kills=4)
    cur = _payload(round_phase='over', round_kills=4)
    events = detect_events(cur, prev)
    assert 'MULTI_KILL' in _kinds(events)
    mk = next(e for e in events if e.kind == 'MULTI_KILL')
    assert mk.data['kills'] == 4


def test_no_multikill_below_three():
    events = detect_events(_payload(round_phase='over', round_kills=2),
                           _payload(round_phase='live', round_kills=2))
    assert 'MULTI_KILL' not in _kinds(events)


def test_round_win_only_when_our_team_wins():
    won = detect_events(_payload('over', win_team='CT', team='CT'),
                        _payload('live', team='CT'))
    lost = detect_events(_payload('over', win_team='T', team='CT'),
                         _payload('live', team='CT'))
    assert 'ROUND_WIN' in _kinds(won)
    assert 'ROUND_WIN' not in _kinds(lost)


def test_low_hp_survival():
    survived = detect_events(_payload('over', health=7), _payload('live', health=7))
    dead = detect_events(_payload('over', health=0), _payload('live', health=0))
    healthy = detect_events(_payload('over', health=80), _payload('live', health=80))
    assert 'LOW_HP_SURVIVAL' in _kinds(survived)
    assert 'LOW_HP_SURVIVAL' not in _kinds(dead)
    assert 'LOW_HP_SURVIVAL' not in _kinds(healthy)


def test_mvp_fires_on_increment_only():
    up = detect_events(_payload(mvps=2), _payload(mvps=1))
    same = detect_events(_payload(mvps=2), _payload(mvps=2))
    assert 'MVP' in _kinds(up)
    assert 'MVP' not in _kinds(same)


def test_match_point_and_match_win_from_score():
    point = detect_events(_payload(team='CT', ct_score=WIN_SCORE - 1),
                          _payload(team='CT', ct_score=WIN_SCORE - 2))
    win = detect_events(_payload(team='CT', ct_score=WIN_SCORE),
                        _payload(team='CT', ct_score=WIN_SCORE - 1))
    assert 'MATCH_POINT' in _kinds(point)
    assert 'MATCH_WIN' in _kinds(win)


def test_round_events_fire_once_across_repeated_over_payloads():
    # First 'over' payload (prev was live) fires; a second 'over' (prev also
    # over) must not re-fire.
    first = detect_events(_payload('over', round_kills=5), _payload('live', round_kills=5))
    again = detect_events(_payload('over', round_kills=5), _payload('over', round_kills=5))
    assert 'MULTI_KILL' in _kinds(first)
    assert 'MULTI_KILL' not in _kinds(again)


def test_empty_prev_emits_nothing():
    assert detect_events(_payload('over', round_kills=5), {}) == []
