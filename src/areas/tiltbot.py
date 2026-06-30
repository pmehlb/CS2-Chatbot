"""Tilt Bot area: psychological-warfare taunts driven by CS2 Game State
Integration (your own in-game events) plus optional canned chat clapbacks.

GSI events (multi-kills, MVPs, round wins, low-HP survival, match point) arrive
via the local /gsi endpoint (see system/gsi.py) and are turned into cocky
all-chat lines here. Lines are plain ASCII for CS2 font compatibility. v1 is
canned (deterministic, no API key); AI-generated variety is a fast-follow.
"""
import logging
import random

from nicegui import ui

from ui.ui_util import area_header, notify_and_log, settings_card
from .base import ChatArea
from .event_prompts import event_to_prompt

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

# Selectable response sources for the per-section dropdowns. 'canned' uses the
# editable line pools; the others borrow that AI area's configured brain.
SOURCE_LABELS = {
    'canned': 'Canned (built-in lines)',
    'characterai': 'Character.AI',
    'chatgpt': 'ChatGPT',
    'claude': 'Claude',
}
AI_SOURCES = ('characterai', 'chatgpt', 'claude')

# Which {token}s each event kind's lines may use, shown as an editor hint.
EVENT_TOKENS = {
    'MULTI_KILL': '{kills}',
    'LOW_HP_SURVIVAL': '{hp}',
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
        self.clapback_source = 'canned'   # 'canned' | one of AI_SOURCES
        self.event_source = 'canned'      # 'canned' | one of AI_SOURCES
        # Editable line pools, defaulting to copies of the built-in defaults.
        self.clapback_lines = list(CLAPBACKS)
        self.event_lines = {k: list(CANNED[k]) for k in EVENT_LABELS}
        self._no_events_hint = None  # shown when every event is toggled off

    # ------------------------------------------------------------------ contract

    def is_ready(self):
        # Canned needs no key. If a *used* section points at an AI brain, that
        # brain must be ready (blocks power-on with its own reason); switch the
        # source back to Canned to run keyless.
        for source in self._active_ai_sources():
            brain = self.app.area_by_key(source) if self.app else None
            if brain is None:
                return False, f'{SOURCE_LABELS.get(source, source)} is unavailable.'
            ok, reason = brain.is_ready()
            if not ok:
                return False, f'{SOURCE_LABELS.get(source, source)}: {reason}'
        return True, None

    async def generate(self, message, app):
        self.app = app
        if not self.clapback:
            return None
        if self._is_ai(self.clapback_source):
            reply = await self._ai_reply(self.clapback_source, message, app)
            if reply:
                return reply
        return self._canned_clapback()

    async def generate_event(self, event, app):
        self.app = app
        if not self._enabled(event.kind):
            return None
        if self._is_ai(self.event_source):
            reply = await self._ai_reply(self.event_source, event_to_prompt(event), app)
            if reply:
                return reply
        return self._canned_event(event)

    # ------------------------------------------------------------------ tab UI

    def build_tab(self, app) -> None:
        self.app = app
        saved = app.load_area_settings(self.key)
        enabled = saved.get('enabled')
        self.enabled = dict(enabled) if isinstance(enabled, dict) else {}
        self.clapback = bool(saved.get('clapback', True))
        self.clapback_source = saved.get('clapback_source') or 'canned'
        self.event_source = saved.get('event_source') or 'canned'
        self.clapback_lines = self._restore_pool(saved.get('clapback_lines'), CLAPBACKS)
        saved_events = saved.get('event_lines') or {}
        self.event_lines = {k: self._restore_pool(saved_events.get(k), CANNED[k])
                            for k in EVENT_LABELS}

        area_header('Tilt Bot',
                    'Reacts to your live CS2 game events (multi-kills, MVPs, clutches) '
                    'with taunts, and optionally claps back at chat. Each section can use '
                    'the built-in lines or borrow an AI brain (C.AI / ChatGPT / Claude). '
                    'Game State Integration must be set up in Settings.')

        # Game events | Chat as 50/50 columns; the GSI requirement note spans full width below.
        with ui.grid(columns=2).classes('gap-4 w-full'):
            self._game_events_card()
            self._chat_card()
        self._gsi_required_note()

    def _game_events_card(self) -> None:
        with settings_card('Game events'):
            for kind, label in EVENT_LABELS.items():
                ui.checkbox(label, value=self._enabled(kind),
                            on_change=lambda e, k=kind: self._set_enabled(k, e.value))

            self._no_events_hint = ui.label(
                "No events enabled — Tilt Bot won't react to your play.") \
                .classes('text-sm text-orange')
            self._no_events_hint.set_visibility(not self._any_event_enabled())

            source_select = ui.select(SOURCE_LABELS, value=self.event_source, label='Taunt source',
                                      on_change=lambda e: self._set_source('event_source', e.value)) \
                .classes('w-full')
            with source_select:
                ui.tooltip('Where event taunts come from: the built-in lines, or an AI brain '
                           'you configured (it must have an API key set). AI falls back to a '
                           'canned line if it errors.')

            with ui.expansion('Edit lines', icon='edit').classes('w-full'):
                self._event_line_editors()

            with ui.expansion('Preview taunts', icon='visibility').classes('w-full'):
                for kind, label in EVENT_LABELS.items():
                    pool = self.event_lines.get(kind) or CANNED[kind]
                    example = self._safe_format(pool[0], {'kills': 5, 'hp': 7})
                    ui.label(f'{label}: "{example}"').classes('text-xs opacity-70')

    @ui.refreshable
    def _event_line_editors(self) -> None:
        ui.label('One taunt per line. Tokens: {kills} (multi-kills), {hp} (low-HP survival).') \
            .classes('text-xs opacity-70')
        for kind, label in EVENT_LABELS.items():
            hint = f'  {EVENT_TOKENS[kind]}' if kind in EVENT_TOKENS else ''
            ui.textarea(label + hint, value='\n'.join(self.event_lines[kind]),
                        on_change=lambda e, k=kind: self._set_event_lines(k, self._parse_lines(e.value))) \
                .classes('w-full').props('autogrow')
        ui.button('Restore default taunts', icon='restart_alt',
                  on_click=self._restore_event_lines).props('outline')

    def _chat_card(self) -> None:
        with settings_card('Chat'):
            ui.checkbox('Clap back at incoming chat', value=self.clapback,
                        on_change=lambda e: self._set_clapback(e.value))

            source_select = ui.select(SOURCE_LABELS, value=self.clapback_source, label='Clapback source',
                                      on_change=lambda e: self._set_source('clapback_source', e.value)) \
                .classes('w-full')
            with source_select:
                ui.tooltip('Where clapbacks come from: the built-in lines, or an AI brain you '
                           'configured. An AI brain replies in its own persona (and can name the '
                           'speaker if "Attribute messages to speakers" is on in Settings).')

            with ui.expansion('Edit clapback lines', icon='edit').classes('w-full'):
                self._clapback_line_editor()

    @ui.refreshable
    def _clapback_line_editor(self) -> None:
        ui.label('One clapback per line.').classes('text-xs opacity-70')
        ui.textarea('Clapback lines', value='\n'.join(self.clapback_lines),
                    on_change=lambda e: self._set_clapback_lines(self._parse_lines(e.value))) \
            .classes('w-full').props('autogrow')
        ui.button('Restore default clapbacks', icon='restart_alt',
                  on_click=self._restore_clapback_lines).props('outline')

    def _gsi_required_note(self) -> None:
        """Full-width notice that GSI (set up in Settings) is required for the
        event taunts to fire, with a button that jumps to the Settings tab."""
        with settings_card('Requires Game State Integration'):
            ui.label('Tilt Bot reacts to your live game events through CS2 Game State '
                     'Integration. Set it up in Settings (install the config, then fully '
                     'restart CS2) — otherwise these event taunts never fire.') \
                .classes('text-sm opacity-70')
            btn = ui.button('Open GSI settings', icon='settings',
                            on_click=self._open_settings).props('outline')
            with btn:
                ui.tooltip('Jump to Settings to install the GSI config and watch the live '
                           'connection light.')

    def _open_settings(self) -> None:
        if getattr(self.app, 'open_settings', None):
            self.app.open_settings()

    # ------------------------------------------------------------------ helpers

    def _enabled(self, kind: str) -> bool:
        return self.enabled.get(kind, True)

    @staticmethod
    def _is_ai(source) -> bool:
        return source in AI_SOURCES

    def _active_ai_sources(self):
        """The AI sources currently in use (so is_ready only gates on those)."""
        sources = []
        if self.clapback and self._is_ai(self.clapback_source):
            sources.append(self.clapback_source)
        if self._any_event_enabled() and self._is_ai(self.event_source):
            sources.append(self.event_source)
        return sources

    async def _ai_reply(self, source, prompt, app):
        """Borrow the brain named by ``source`` and ask it for a reply, or return
        None (missing/not-ready brain, or any error) so the caller falls back to
        a canned line -- an enabled event should never go un-taunted."""
        brain = app.area_by_key(source) if app else None
        if brain is None:
            return None
        ok, _ = brain.is_ready()
        if not ok:
            return None
        try:
            return await brain.generate(prompt, app)
        except Exception as e:
            logger.warning(f"Tilt Bot AI source '{source}' failed: {e}")
            return None

    def _canned_clapback(self):
        return random.choice(self.clapback_lines or CLAPBACKS)

    def _canned_event(self, event):
        pool = self.event_lines.get(event.kind) or CANNED.get(event.kind)
        if not pool:
            return None
        return self._safe_format(random.choice(pool), event.data or {})

    @staticmethod
    def _safe_format(line, data):
        """Format a (user-editable) line, leaving bad/unknown tokens literal."""
        try:
            return line.format(**data)
        except (KeyError, IndexError, ValueError):
            return line

    @staticmethod
    def _parse_lines(text):
        """Textarea body -> list of non-empty, stripped lines (one taunt each)."""
        return [ln.strip() for ln in (text or '').splitlines() if ln.strip()]

    @staticmethod
    def _restore_pool(saved, default):
        """Load a saved pool, falling back to a copy of ``default`` when the
        saved value is missing or empty (no silent empty pools)."""
        if isinstance(saved, list):
            cleaned = [str(s).strip() for s in saved if str(s).strip()]
            return cleaned if cleaned else list(default)
        return list(default)

    def _any_event_enabled(self) -> bool:
        return any(self._enabled(k) for k in EVENT_LABELS)

    def _save(self) -> None:
        data = self.app.load_area_settings(self.key)
        data.update({
            'enabled': self.enabled,
            'clapback': self.clapback,
            'clapback_source': self.clapback_source,
            'event_source': self.event_source,
            'clapback_lines': self.clapback_lines,
            'event_lines': self.event_lines,
        })
        self.app.save_area_settings(self.key, data)

    def _set_enabled(self, kind: str, value) -> None:
        self.enabled[kind] = bool(value)
        self._save()
        if self._no_events_hint is not None:
            self._no_events_hint.set_visibility(not self._any_event_enabled())

    def _set_clapback(self, value) -> None:
        self.clapback = bool(value)
        self._save()

    def _set_source(self, field: str, value) -> None:
        setattr(self, field, value or 'canned')
        self._save()

    def _set_event_lines(self, kind: str, lines) -> None:
        self.event_lines[kind] = lines
        self._save()

    def _set_clapback_lines(self, lines) -> None:
        self.clapback_lines = lines
        self._save()

    def _restore_event_lines(self) -> None:
        self.event_lines = {k: list(CANNED[k]) for k in EVENT_LABELS}
        self._save()
        self._event_line_editors.refresh()
        notify_and_log('Default taunts restored.', type='positive')

    def _restore_clapback_lines(self) -> None:
        self.clapback_lines = list(CLAPBACKS)
        self._save()
        self._clapback_line_editor.refresh()
        notify_and_log('Default clapbacks restored.', type='positive')
