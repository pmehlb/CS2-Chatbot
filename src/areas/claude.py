"""Claude area: answers in-game messages via Anthropic's Messages API.

Mirrors the ChatGPT area's control plane: a "Persona" card with a model
selector and a "first prompt" (system prompt) that defines who the bot is, plus
a short rolling history for continuity. The API key lives in the shared
Settings > API Tokens section like the other areas.

The module is named claude.py (not anthropic.py) so it doesn't shadow the SDK's
top-level ``anthropic`` package.
"""
import logging
import traceback

from anthropic import AsyncAnthropic
from nicegui import ui

from ui.ui_util import area_header, notify_and_log, settings_card
from .base import ChatArea, TokenField
from .event_prompts import event_to_prompt

logger = logging.getLogger(__name__)

# Selectable models -> friendly labels, shown in the dropdown. Opus 4.8 is the
# default (most capable); Haiku is the cheapest/fastest if you want snappier,
# lower-cost replies. Keep these as the bare model-id strings the API expects.
MODELS = {
    'claude-opus-4-8': 'Claude Opus 4.8 (most capable)',
    'claude-opus-4-7': 'Claude Opus 4.7',
    'claude-sonnet-4-6': 'Claude Sonnet 4.6 (balanced)',
    'claude-haiku-4-5': 'Claude Haiku 4.5 (fastest)',
}
DEFAULT_MODEL = 'claude-opus-4-8'

# Per-model tuning capabilities. The Opus 4.8/4.7 models reject sampling params
# (temperature returns a 400), while the effort parameter errors on Haiku. Effort
# levels also differ — "xhigh" is Opus-only. We only send a control to models that
# accept it, and the UI disables controls that don't apply to the chosen model.
MODEL_CAPS = {
    'claude-opus-4-8':   {'temperature': False, 'efforts': ['low', 'medium', 'high', 'xhigh', 'max']},
    'claude-opus-4-7':   {'temperature': False, 'efforts': ['low', 'medium', 'high', 'xhigh', 'max']},
    'claude-sonnet-4-6': {'temperature': True,  'efforts': ['low', 'medium', 'high', 'max']},
    'claude-haiku-4-5':  {'temperature': True,  'efforts': []},
}

# Anthropic temperature ranges 0.0–1.0 (1.0 is the API default). Effort defaults
# to "low": these are one-line replies, so minimal thinking keeps them snappy and
# cheap; bump it for sharper comebacks on the Opus/Sonnet models.
DEFAULT_TEMPERATURE = 1.0
DEFAULT_EFFORT = 'low'

# Replies must fit a single CS2 chat line, so the persona is told to be terse
# and the request caps tokens; the send layer still chunks anything too long.
# The "one short line" instruction also keeps Opus from spilling reasoning into
# the visible reply when thinking is off.
DEFAULT_SYSTEM_PROMPT = (
    "You are a player in a Counter-Strike 2 match, you're better than everyone else, "
    "and they need to know it - owning the opponents, beating them, and trash talking "
    "the whole time. Reply casually, and always attempt to infuriate the opponent - "
    "it's a long-term strategy. Feel free to curse, be aggressive, do your best to "
    "intimidate and get in their heads. Reply with one line where possible, multiple if "
    "appropriate. No emoji, markdown, or unicode/ascii art."
)

MAX_TOKENS = 150           # short replies, keeps within a CS2 chat line
MAX_HISTORY_MESSAGES = 20  # rolling window: 10 user/assistant exchanges

TOKEN_HELP_MD = '''
<h1 style="margin: 0 0 20px 0">Get an Anthropic API Key</h1>

<ol>
    <li> Visit <a style="text-decoration: none; color: hotpink;" target='_blank' href='https://console.anthropic.com/settings/keys'>https://console.anthropic.com/settings/keys</a> </li>
    <li> Sign in and click <b>Create Key</b> </li>
    <li> Copy the key (it's shown only once) and paste it here </li>
</ol>
'''


class ClaudeArea(ChatArea):
    key = 'claude'
    label = 'Claude'
    icon = 'auto_awesome'

    def __init__(self):
        self.app = None
        self.client = None
        self.api_key = ''                          # set via Settings > API Tokens
        self.model = DEFAULT_MODEL                  # persisted
        self.system_prompt = DEFAULT_SYSTEM_PROMPT  # persisted
        self.temperature = DEFAULT_TEMPERATURE      # persisted (temp-capable models only)
        self.effort = DEFAULT_EFFORT                # persisted (effort-capable models only)
        self.history = []                           # runtime-only rolling history
        self.react_to_events = False   # opt in to taunting your own GSI events
        self.consumes_events = False   # instance flag the chat loop reads

        # Widget refs, populated in build_tab.
        self.model_input = None
        self.system_prompt_input = None

    # ------------------------------------------------------------------ contract

    def tokens(self):
        return [TokenField(key='api_key', label='Anthropic API Key',
                           on_set=self.set_api_key, help_md=TOKEN_HELP_MD)]

    def is_ready(self):
        if not self.api_key:
            return False, 'Please set an Anthropic API key!'
        return True, None

    async def generate(self, message: str, app):
        if not self.client:
            notify_and_log('Please set an Anthropic API key!', type='negative')
            return None

        messages = self.history + [{'role': 'user', 'content': message}]

        kwargs = self._tuning_kwargs()

        try:
            logger.debug(f"Sending {len(messages)} messages to Anthropic model "
                         f"{self.model} (tuning: {kwargs or 'defaults'})")
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=MAX_TOKENS,
                system=self.system_prompt,
                messages=messages,
                **kwargs,
            )
            reply = next((b.text for b in response.content if b.type == 'text'), '').strip()
            logger.debug(f"Received response: {reply}")

            # Record the exchange and trim to the rolling window.
            self.history.append({'role': 'user', 'content': message})
            self.history.append({'role': 'assistant', 'content': reply})
            del self.history[:-MAX_HISTORY_MESSAGES]

            return reply
        except Exception as e:
            logger.error(f"Failed to get a response from Anthropic: {e}")
            logger.error(traceback.format_exc())
            notify_and_log(f'Failed to get a response: {e}', type='negative')
            return None

    async def generate_event(self, event, app):
        """React to a GSI game event by routing a synthesized prompt through this
        area's own persona (only called while this tab is active and the toggle
        is on)."""
        return await self.generate(event_to_prompt(event), app)

    # ------------------------------------------------------------------ tab UI

    def build_tab(self, app) -> None:
        self.app = app

        saved = app.load_area_settings(self.key)
        self.model = saved.get('model') or DEFAULT_MODEL
        self.system_prompt = saved.get('system_prompt') or DEFAULT_SYSTEM_PROMPT
        temp = saved.get('temperature', DEFAULT_TEMPERATURE)
        self.temperature = temp if isinstance(temp, (int, float)) else DEFAULT_TEMPERATURE
        self.effort = saved.get('effort') or DEFAULT_EFFORT
        self._sanitize_effort()  # keep a carried-over effort valid for the saved model
        self.react_to_events = bool(saved.get('react_to_events', False))
        self.consumes_events = self.react_to_events

        area_header('Claude',
                    'Answer in-game messages with Anthropic\'s Claude. Set your API key in '
                    'Settings > API Tokens, then pick a model and give the bot a persona below.')

        with settings_card('Persona'):
            self.model_input = ui.select(MODELS, value=self.model, label='Model',
                                         on_change=lambda e: self._set_model(e.value)) \
                .classes('w-full')
            with self.model_input:
                ui.tooltip('Which Claude model answers. Opus is most capable; Haiku is the '
                           'fastest and cheapest.')

            # Effort and temperature apply only to some models, so this row is
            # refreshable and re-renders (enabling/disabling controls) on model change.
            self._tuning_row()

            self.system_prompt_input = ui.textarea(
                'System prompt (first prompt)', value=self.system_prompt,
                on_change=lambda e: self._set_field('system_prompt', e.value)) \
                .classes('w-full').props('autogrow')
            with self.system_prompt_input:
                ui.tooltip('Defines who the bot is. Keep the "reply in one short '
                           'line" instruction so answers fit the CS2 chat.')

            clear_btn = ui.button('Clear conversation', icon='restart_alt',
                                  on_click=self._clear_history).props('outline')
            with clear_btn:
                ui.tooltip('Forget the running conversation history (also reset on app restart).')

            events_cb = ui.checkbox('Also react to my game events', value=self.react_to_events,
                                    on_change=lambda e: self._set_react_to_events(e.value))
            with events_cb:
                ui.tooltip('When on, this bot also taunts about your own GSI events '
                           '(multi-kills, MVPs, clutches) while its tab is active. '
                           'Set up Game State Integration in Settings first.')

    # ------------------------------------------------------------------ helpers

    async def set_api_key(self, value):
        self.api_key = value or ''
        if not self.api_key:
            self.client = None
            return
        # No network call here; the key is validated on the first real request.
        self.client = AsyncAnthropic(api_key=self.api_key)

    def _tuning_kwargs(self) -> dict:
        """Build the messages.create kwargs for tuning params the current model
        accepts. Temperature 400s on Opus 4.8/4.7; effort errors on Haiku. Thinking
        stays off for snappy replies — effort still tunes token spend where supported.
        """
        caps = MODEL_CAPS.get(self.model, {})
        kwargs = {}
        if caps.get('temperature') and self.temperature is not None:
            kwargs['temperature'] = self.temperature
        if self.effort in caps.get('efforts', []):
            kwargs['output_config'] = {'effort': self.effort}
        return kwargs

    @ui.refreshable
    def _tuning_row(self) -> None:
        """Render the effort selector and temperature slider for the current model.

        Each control is shown only when the chosen model supports it; otherwise a
        disabled placeholder explains why. Re-rendered on model change.
        """
        caps = MODEL_CAPS.get(self.model, {})
        efforts = caps.get('efforts', [])
        with ui.row().classes('w-full items-center gap-3'):
            if efforts:
                value = self.effort if self.effort in efforts else efforts[0]
                effort_select = ui.select(efforts, value=value, label='Effort',
                                          on_change=lambda e: self._set_field('effort', e.value)) \
                    .classes('flex-grow')
                with effort_select:
                    ui.tooltip('How hard the model reasons and how many tokens it spends. '
                               'Lower is faster and cheaper — good for one-line replies.')
            else:
                ui.input(label='Effort', value='Not supported by this model') \
                    .props('readonly disable').classes('flex-grow')

        with ui.row().classes('w-full items-center gap-3 q-mt-sm'):
            ui.label('Temperature').classes('text-sm')
            if caps.get('temperature'):
                ui.slider(min=0, max=1, step=0.05, value=self.temperature,
                          on_change=lambda e: self._set_field('temperature', e.value)) \
                    .props('label-always').classes('flex-grow')
            else:
                ui.label('Not supported by this model').classes('text-sm opacity-60 flex-grow')

    def _set_model(self, value) -> None:
        """Persist the chosen model, keep the effort value valid for it, and
        re-render the tuning controls so they match the new model's capabilities."""
        self._set_field('model', value)
        self._sanitize_effort()
        self._tuning_row.refresh()

    def _sanitize_effort(self) -> None:
        """Snap the stored effort to a level the current model supports, so a
        carried-over value (e.g. Opus-only 'xhigh') doesn't get sent to a model
        that would reject it."""
        efforts = MODEL_CAPS.get(self.model, {}).get('efforts', [])
        if efforts and self.effort not in efforts:
            self._set_field('effort', DEFAULT_EFFORT if DEFAULT_EFFORT in efforts else efforts[0])

    def _set_field(self, name: str, value) -> None:
        """Update a persisted field (model / system_prompt / effort / temperature)
        and save it. Non-string values (e.g. the temperature float) pass through."""
        setattr(self, name, value if not isinstance(value, str) else (value or ''))
        data = self.app.load_area_settings(self.key)
        data[name] = getattr(self, name)
        self.app.save_area_settings(self.key, data)

    def _set_react_to_events(self, value) -> None:
        self.react_to_events = bool(value)
        self.consumes_events = self.react_to_events
        self._set_field('react_to_events', self.react_to_events)

    def _clear_history(self) -> None:
        self.history = []
        notify_and_log('Conversation history cleared.', type='positive')
