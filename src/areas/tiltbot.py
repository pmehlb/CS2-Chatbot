"""Tilt Bot area: psychological-warfare taunts driven by CS2 Game State
Integration (your own in-game events) plus optional canned chat clapbacks.

GSI events (multi-kills, MVPs, round wins, low-HP survival, match point) arrive
via the local /gsi endpoint (see system/gsi.py) and are turned into cocky
all-chat lines here. Lines are plain ASCII for CS2 font compatibility. v1 is
canned (deterministic, no API key); AI-generated variety is a fast-follow.
"""
import logging
import os
import random
import time

from nicegui import ui

from system import gsi
from ui.ui_util import area_header, notify_and_log, settings_card
from .base import ChatArea

logger = logging.getLogger(__name__)

# Canned taunt pools per GSI event kind. {kills}/{hp} are filled from event data.
CANNED = {
    'MULTI_KILL': [
        '{kills}k. who let bots queue ranked',
        '{kills} down before they blinked. ez',
        'thats a {kills}k, you can spectate now',
    ],
    'MVP': [
        'mvp again, get used to it',
        'another round carried by me, shocking',
    ],
    'ROUND_WIN': [
        'too easy. round is ours',
        'gg go next. oh wait theres more',
    ],
    'LOW_HP_SURVIVAL': [
        'clutched on {hp} hp, embarrassing for you',
        '{hp} hp and you still couldnt finish it',
    ],
    'MATCH_POINT': [
        'match point. warm up your alt f4',
        'one more and you can uninstall',
    ],
    'MATCH_WIN': [
        'gg ez. better luck in silver',
        'thanks for the free win',
    ],
}

# Generic clapbacks for incoming chat (name-targeting via AI is a fast-follow).
CLAPBACKS = [
    'cope', 'cry about it', 'said the guy going 2 and 15',
    'crazy how you typed that instead of getting a kill',
    'whatever helps you sleep at 0-5',
]

# Display order + labels for the per-event enable checkboxes.
EVENT_LABELS = {
    'MULTI_KILL': 'Multi-kills (3K / 4K / ace)',
    'MVP': 'Round MVP',
    'ROUND_WIN': 'Round win',
    'LOW_HP_SURVIVAL': 'Low-HP survival',
    'MATCH_POINT': 'Match point',
    'MATCH_WIN': 'Match win',
}


class TiltBotArea(ChatArea):
    key = 'tiltbot'
    label = 'Tilt Bot'
    icon = 'whatshot'
    consumes_events = True
    attribute_speaker = True

    def __init__(self):
        self.app = None
        self.enabled = {}        # event kind -> bool (absent = on by default)
        self.clapback = True     # also reply to incoming chat
        self._status_icon = None   # GSI connection light, set in build_tab
        self._status_label = None
        self._no_events_hint = None  # shown when every event is toggled off

    # ------------------------------------------------------------------ contract

    def is_ready(self):
        # Canned mode needs no API key; the GSI cfg can't be verified from here,
        # so the bot is always ready to react to whatever events arrive.
        return True, None

    async def generate(self, message, app):
        self.app = app
        if not self.clapback:
            return None
        return random.choice(CLAPBACKS)

    async def generate_event(self, event, app):
        self.app = app
        if not self._enabled(event.kind):
            return None
        pool = CANNED.get(event.kind)
        if not pool:
            return None
        return random.choice(pool).format(**(event.data or {}))

    # ------------------------------------------------------------------ tab UI

    def build_tab(self, app) -> None:
        self.app = app
        saved = app.load_area_settings(self.key)
        enabled = saved.get('enabled')
        self.enabled = dict(enabled) if isinstance(enabled, dict) else {}
        self.clapback = bool(saved.get('clapback', True))

        area_header('Tilt Bot',
                    'Reacts to your live CS2 game events (multi-kills, MVPs, clutches) '
                    'with taunts via Game State Integration, and optionally claps back at '
                    'chat. Install the GSI config below, then fully restart CS2.')

        with settings_card('Game events'):
            for kind, label in EVENT_LABELS.items():
                ui.checkbox(label, value=self._enabled(kind),
                            on_change=lambda e, k=kind: self._set_enabled(k, e.value))

            self._no_events_hint = ui.label(
                "No events enabled — Tilt Bot won't react to your play.") \
                .classes('text-sm text-orange')
            self._no_events_hint.set_visibility(not self._any_event_enabled())

            with ui.expansion('Preview taunts', icon='visibility').classes('w-full'):
                for kind, label in EVENT_LABELS.items():
                    example = CANNED[kind][0].format(kills=5, hp=7)
                    ui.label(f'{label}: "{example}"').classes('text-xs opacity-70')

        with settings_card('Chat'):
            ui.checkbox('Clap back at incoming chat', value=self.clapback,
                        on_change=lambda e: self._set_clapback(e.value))

        with settings_card('Setup'):
            ui.label('GSI sends your game state to this app on a local port. '
                     'Install the config, then fully restart CS2 to activate.') \
                .classes('text-sm opacity-70')
            install_btn = ui.button('Install GSI config', icon='download',
                                    on_click=self._install_gsi).props('outline')
            with install_btn:
                ui.tooltip("Writes gamestate_integration_cs2chatbot.cfg into CS2's cfg folder.")

            # Where the config goes and which local endpoint CS2 posts to, so the
            # setup is transparent (and debuggable if a taunt never fires).
            cfg_path = os.path.join(app.cs_path, 'cfg', gsi.GSI_CFG_NAME)
            ui.label(f'Endpoint: 127.0.0.1:{gsi.GSI_PORT}/gsi').classes('text-xs opacity-60')
            ui.label(f'Config: {cfg_path}').classes('text-xs opacity-60 break-all')

            # Live connection light: confirms CS2 is actually POSTing to us, so
            # setup success is visible without waiting for a taunt to fire.
            with ui.row().classes('items-center gap-2'):
                self._status_icon = ui.icon('circle').classes('text-sm').props('color=grey')
                self._status_label = ui.label('Waiting for CS2…').classes('text-sm opacity-70')
            ui.timer(1.0, self._refresh_status)

    def _refresh_status(self) -> None:
        """Poll the GSI freshness and recolour the connection light (1s timer)."""
        receiving = gsi.is_receiving(self.app, time.monotonic())
        self._status_icon.props(f'color={"green" if receiving else "grey"}')
        self._status_label.text = 'Receiving game data' if receiving else 'Waiting for CS2…'

    def _install_gsi(self) -> None:
        try:
            path = gsi.write_gsi_cfg(self.app)
            notify_and_log(f'Installed GSI config — restart CS2 to activate. ({path})',
                           type='positive')
        except OSError as e:
            notify_and_log(f'Could not write GSI config: {e}', type='negative')

    # ------------------------------------------------------------------ helpers

    def _enabled(self, kind: str) -> bool:
        return self.enabled.get(kind, True)

    def _any_event_enabled(self) -> bool:
        return any(self._enabled(k) for k in EVENT_LABELS)

    def _set_enabled(self, kind: str, value) -> None:
        self.enabled[kind] = bool(value)
        self._save()
        if self._no_events_hint is not None:
            self._no_events_hint.set_visibility(not self._any_event_enabled())

    def _set_clapback(self, value) -> None:
        self.clapback = bool(value)
        self._save()

    def _save(self) -> None:
        data = self.app.load_area_settings(self.key)
        data['enabled'] = self.enabled
        data['clapback'] = self.clapback
        self.app.save_area_settings(self.key, data)
