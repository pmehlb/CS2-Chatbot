"""CS2 Game State Integration: a local HTTP endpoint CS2 POSTs game-state to,
turned into TiltEvents the chat loop reacts to.

GSI is official and read-only -- no game memory, no ban risk; same posture as
the console.log read path. During a live match GSI only exposes the local
player's data (anti-cheat), so every event here is derived from your own
``player`` node plus the shared ``round``/``map`` state. Opponent-by-name
taunts are not possible in live play and are intentionally not attempted.
"""
import logging
import os
import secrets
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

GSI_PORT = 8765                                   # pinned; GUI + GSI share it
GSI_CFG_NAME = 'gamestate_integration_cs2chatbot.cfg'
LOW_HP_THRESHOLD = 20                             # "survived on fumes" cutoff
WIN_SCORE = 13                                    # MR12 default; match point at 12
GSI_FRESH_SECONDS = 15                            # within this of the last POST = "receiving"


@dataclass
class TiltEvent:
    kind: str
    data: dict = field(default_factory=dict)


def _player_team_score(payload):
    """The local player's team score from the map node, or None."""
    team = (payload.get('player') or {}).get('team')
    m = payload.get('map') or {}
    if team == 'CT':
        return (m.get('team_ct') or {}).get('score')
    if team == 'T':
        return (m.get('team_t') or {}).get('score')
    return None


def detect_events(payload, prev):
    """Pure: compare ``payload`` to the previous ``prev`` snapshot and return a
    list of TiltEvents. Edge-detected, so each event fires once per transition.
    """
    events = []
    player = payload.get('player') or {}
    state = player.get('state') or {}
    stats = player.get('match_stats') or {}
    rnd = payload.get('round') or {}

    pprev = prev.get('player') or {}
    stprev = (pprev.get('match_stats') or {})
    rprev = prev.get('round') or {}

    # Ignore frames where the observed player changed (spectator switching) and
    # the very first frame (prev empty): no baseline, so no taunts.
    if not prev:
        return events
    if player.get('steamid') and pprev.get('steamid') \
            and player.get('steamid') != pprev.get('steamid'):
        return events

    round_just_ended = rnd.get('phase') == 'over' and rprev.get('phase') != 'over'
    if round_just_ended:
        kills = state.get('round_kills') or 0
        if kills >= 3:
            events.append(TiltEvent('MULTI_KILL', {'kills': kills}))
        if rnd.get('win_team') and rnd.get('win_team') == player.get('team'):
            events.append(TiltEvent('ROUND_WIN', {}))
        hp = state.get('health')
        if isinstance(hp, int) and 0 < hp <= LOW_HP_THRESHOLD:
            events.append(TiltEvent('LOW_HP_SURVIVAL', {'hp': hp}))

    mvps = stats.get('mvps')
    if isinstance(mvps, int) and mvps > (stprev.get('mvps') or 0):
        events.append(TiltEvent('MVP', {}))

    score = _player_team_score(payload)
    pscore = _player_team_score(prev)
    if isinstance(score, int) and isinstance(pscore, int) and score > pscore:
        if score >= WIN_SCORE:
            events.append(TiltEvent('MATCH_WIN', {}))
        elif score == WIN_SCORE - 1:
            events.append(TiltEvent('MATCH_POINT', {}))

    return events


def ensure_token(app) -> str:
    """Return the persisted GSI auth token, generating + saving one if unset.

    Stored in the cross-cutting app settings namespace so it survives restarts
    and matches the token written into the GSI cfg.
    """
    token = app.load_app_settings().get('gsi_token')
    if not token:
        token = secrets.token_hex(16)
        app.save_app_setting('gsi_token', token)
    app.gsi_token = token
    return token


def is_receiving(app, now: float) -> bool:
    """True when a valid GSI POST arrived within the last GSI_FRESH_SECONDS.

    Pure helper (``now`` is a ``time.monotonic()`` value) so the tab's status
    light is trivially testable. False before the first POST (gsi_last_seen 0).
    """
    last = getattr(app, 'gsi_last_seen', 0.0) or 0.0
    return last > 0 and (now - last) < GSI_FRESH_SECONDS


def _snapshot(payload):
    """Keep only the nodes detect_events needs, to bound prev-state memory."""
    return {k: payload.get(k) for k in ('player', 'round', 'map')}


def handle_payload(app, payload) -> int:
    """Validate the token, detect events, enqueue them, update prev. Returns the
    number of events enqueued. Never raises into CS2's HTTP client."""
    token = (payload.get('auth') or {}).get('token')
    if not app.gsi_token or token != app.gsi_token:
        logger.debug('GSI POST with bad/missing token; ignoring')
        return 0
    # Any authenticated POST means CS2 is talking to us -- stamp it so the tab
    # can show a live "receiving" light even on rounds with no taunt-worthy event.
    app.gsi_last_seen = time.monotonic()
    events = detect_events(payload, app.gsi_prev)
    for ev in events:
        app.gsi_events.append(ev)
    app.gsi_prev = _snapshot(payload)
    return len(events)


def write_gsi_cfg(app) -> str:
    """Write the GSI config into CS2's cfg dir, pointing at our /gsi route.

    Returns the path written. CS2 must be restarted to pick up the change.
    """
    path = os.path.join(app.cs_path, 'cfg', GSI_CFG_NAME)
    body = (
        '"CS2 Chatbot Tilt Bot"\n'
        '{\n'
        f'    "uri"       "http://127.0.0.1:{GSI_PORT}/gsi"\n'
        '    "timeout"   "5.0"\n'
        '    "buffer"    "0.1"\n'
        '    "throttle"  "0.1"\n'
        '    "heartbeat" "30.0"\n'
        '    "auth"\n'
        '    {\n'
        f'        "token" "{app.gsi_token}"\n'
        '    }\n'
        '    "data"\n'
        '    {\n'
        '        "provider"           "1"\n'
        '        "map"                "1"\n'
        '        "round"              "1"\n'
        '        "player_id"          "1"\n'
        '        "player_state"       "1"\n'
        '        "player_match_stats" "1"\n'
        '    }\n'
        '}\n'
    )
    with open(path, 'w', encoding='utf-8') as f:
        f.write(body)
    return path


def register_gsi_route(app) -> None:
    """Register ``POST /gsi`` on NiceGUI's underlying FastAPI app. Call before
    ui.run. The handler delegates to handle_payload (unit-tested) and always
    returns 2xx so CS2's client is happy even on malformed input."""
    from nicegui import app as nicegui_app
    from fastapi import Request

    @nicegui_app.post('/gsi')
    async def _gsi_endpoint(request: Request):
        try:
            payload = await request.json()
        except Exception:
            return {'ok': True}
        try:
            handle_payload(app, payload)
        except Exception as e:
            logger.warning(f'GSI handling failed: {e}')
        return {'ok': True}
