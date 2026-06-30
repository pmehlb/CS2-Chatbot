"""ChatGPT area: answers in-game messages via OpenAI's Chat Completions API.

A persona-driven chat behaviour. The settings tab carries an editable model
field and a "first prompt" (system prompt) text area that defines who the bot
is; the API key lives in the shared Settings > API Tokens section like the C.AI
token. A short rolling history gives replies some continuity within a session.

The module is named chatgpt.py (not openai.py) so it doesn't shadow the SDK's
top-level ``openai`` package.
"""
import logging
import traceback

from nicegui import ui
from openai import AsyncOpenAI

from ui.ui_util import area_header, notify_and_log, settings_card
from .base import ChatArea, TokenField
from .event_prompts import event_to_prompt

logger = logging.getLogger(__name__)

# Selectable models -> friendly labels, shown in the dropdown. gpt-4o-mini is the
# default (cheapest/fastest); gpt-4o is the most capable. Keep these as the bare
# model-id strings the API expects.
MODELS = {
    'gpt-4o-mini': 'GPT-4o mini (fastest/cheapest)',
    'gpt-4o': 'GPT-4o (most capable)',
    'gpt-4.1': 'GPT-4.1',
    'gpt-4.1-mini': 'GPT-4.1 mini',
}
DEFAULT_MODEL = 'gpt-4o-mini'

# Replies must fit a single CS2 chat line, so the persona is told to be terse
# and the request caps tokens; the send layer still chunks anything too long.
DEFAULT_SYSTEM_PROMPT = (
    "You are a player in a Counter-Strike 2 match, chatting in the in-game text "
    "chat. Reply in ONE short, casual line — no more than a sentence. No emoji, "
    "no markdown, no line breaks. Stay in character and keep it snappy."
)

# OpenAI temperature ranges 0.0–2.0 (1.0 is the API default). 0.8 gives a little
# personality without going off the rails; lower is more focused and consistent.
DEFAULT_TEMPERATURE = 0.8

MAX_TOKENS = 150          # short replies, keeps within a CS2 chat line
MAX_HISTORY_MESSAGES = 20  # rolling window: 10 user/assistant exchanges

TOKEN_HELP_MD = '''
<h1 style="margin: 0 0 20px 0">Get an OpenAI API Key</h1>

<ol>
    <li> Visit <a style="text-decoration: none; color: hotpink;" target='_blank' href='https://platform.openai.com/api-keys'>https://platform.openai.com/api-keys</a> </li>
    <li> Sign in and click <b>Create new secret key</b> </li>
    <li> Copy the key (it's shown only once) and paste it here </li>
</ol>
'''


class ChatGPTArea(ChatArea):
    key = 'chatgpt'
    label = 'ChatGPT'
    icon = 'smart_toy'

    def __init__(self):
        self.app = None
        self.client = None
        self.api_key = ''                          # set via Settings > API Tokens
        self.model = DEFAULT_MODEL                  # persisted
        self.system_prompt = DEFAULT_SYSTEM_PROMPT  # persisted
        self.temperature = DEFAULT_TEMPERATURE      # persisted
        self.history = []                           # runtime-only rolling history
        self.react_to_events = False   # opt in to taunting your own GSI events
        self.consumes_events = False   # instance flag the chat loop reads

        # Widget refs, populated in build_tab.
        self.model_input = None
        self.system_prompt_input = None

    # ------------------------------------------------------------------ contract

    def tokens(self):
        return [TokenField(key='api_key', label='OpenAI API Key',
                           on_set=self.set_api_key, help_md=TOKEN_HELP_MD)]

    def is_ready(self):
        if not self.api_key:
            return False, 'Please set an OpenAI API key!'
        return True, None

    async def generate(self, message: str, app):
        if not self.client:
            notify_and_log('Please set an OpenAI API key!', type='negative')
            return None

        messages = (
            [{'role': 'system', 'content': self.system_prompt}]
            + self.history
            + [{'role': 'user', 'content': message}]
        )

        try:
            logger.debug(f"Sending {len(messages)} messages to OpenAI model {self.model}")
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=MAX_TOKENS,
                temperature=self.temperature,
            )
            reply = (response.choices[0].message.content or '').strip()
            logger.debug(f"Received response: {reply}")

            # Record the exchange and trim to the rolling window.
            self.history.append({'role': 'user', 'content': message})
            self.history.append({'role': 'assistant', 'content': reply})
            del self.history[:-MAX_HISTORY_MESSAGES]

            return reply
        except Exception as e:
            logger.error(f"Failed to get a response from OpenAI: {e}")
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
        self.react_to_events = bool(saved.get('react_to_events', False))
        self.consumes_events = self.react_to_events

        area_header('ChatGPT',
                    'Answer in-game messages with OpenAI. Set your API key in '
                    'Settings > API Tokens, then give the bot a persona below.')

        with settings_card('Persona'):
            self.model_input = ui.select(MODELS, value=self.model, label='Model',
                                         on_change=lambda e: self._set_field('model', e.value)) \
                .classes('w-full')
            with self.model_input:
                ui.tooltip('Which OpenAI model answers. gpt-4o-mini is the fastest and '
                           'cheapest; gpt-4o is the most capable.')

            with ui.row().classes('w-full items-center gap-3'):
                ui.label('Temperature').classes('text-sm')
                ui.slider(min=0, max=2, step=0.1, value=self.temperature,
                          on_change=lambda e: self._set_field('temperature', e.value)) \
                    .props('label-always').classes('flex-grow')

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
        self.client = AsyncOpenAI(api_key=self.api_key)

    def _set_field(self, name: str, value) -> None:
        """Update a persisted field (model / system_prompt / temperature) and save
        it. Non-string values (e.g. the temperature float) pass through."""
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
