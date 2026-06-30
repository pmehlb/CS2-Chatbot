"""Character.AI area: the original chatbot behaviour, now self-contained.

Bundles the PyCharacterAI client, character search/selection, the reset-memory
button and the send logic. The C.AI token is declared via tokens() and lives in
the shared Settings > API Tokens section rather than this tab.
"""
import logging
import re
import traceback

from nicegui import ui
from numerize import numerize
from PyCharacterAI import get_client

from ui.ui_util import area_header, notify_and_log
from .base import ChatArea, TokenField
from .event_prompts import event_to_prompt

logger = logging.getLogger(__name__)

DEFAULT_AVATAR = 'https://characterai.io/i/80/static/topic-pics/cai-light-on-dark.jpg'

MAX_RECENTS = 12  # how many recently-used characters to keep on the main page


def _avatar_url(char) -> str:
    """Avatar URL for either a real C.AI character (avatar object with get_url())
    or a stored recent (avatar already a plain URL string)."""
    avatar = getattr(char, 'avatar', None)
    if not avatar:
        return DEFAULT_AVATAR
    if isinstance(avatar, str):
        return avatar
    try:
        return avatar.get_url()
    except Exception:
        return DEFAULT_AVATAR


def _char_from_recent(entry: dict):
    """Rebuild a minimal character object from a stored recents entry so it can
    be rendered as a card and re-selected (avatar kept as a plain URL)."""
    return type('Character', (), {
        'character_id': entry.get('character_id'),
        'name': entry.get('name', ''),
        'title': '',
        'description': '',
        'num_interactions': entry.get('num_interactions', 0) or 0,
        'avatar': entry.get('avatar') or DEFAULT_AVATAR,
    })()

TOKEN_HELP_MD = '''
<h1 style="margin: 0 0 20px 0">Get C.AI Token</h1>

<ol>
    <li> Visit <a style="text-decoration: none; color: hotpink;" target='_blank' href='https://old.character.ai/'>https://old.character.ai/</a> </li>
    <li> Open DevTools in your browser </li>
    <li> Go to Storage → Local Storage → char_token </li>
    <li> Copy value </li>
</ol>
'''

WEB_NEXT_AUTH_HELP_MD = '''
<h1 style="margin: 0 0 20px 0">Get C.AI Web-Next-Auth</h1>

<p style="margin: 0 0 12px 0">Searching characters by name needs this second token (a browser cookie) in addition to the C.AI Token above.</p>

<ol>
    <li> Visit <a style="text-decoration: none; color: hotpink;" target='_blank' href='https://character.ai/'>https://character.ai/</a> while logged in </li>
    <li> Open DevTools in your browser </li>
    <li> Go to Storage → Cookies → <code>web-next-auth</code> </li>
    <li> Copy value </li>
</ol>
'''


class CharacterAIArea(ChatArea):
    key = 'characterai'
    label = 'C.AI'
    icon = 'group'

    def __init__(self):
        self.app = None
        self.client = None
        self.token = ''             # set via the Settings > API Tokens section
        self.web_next_auth = ''     # second C.AI token, required for name search
        self.current_character_id = None
        self.current_char = None
        self.current_chat = None
        self.recents = []           # recently selected characters, persisted, newest first
        self.react_to_events = False   # opt in to taunting your own GSI events
        self.consumes_events = False   # instance flag the chat loop reads

        # Widget refs, populated in build_tab.
        self.character_input = None
        self.search_btn = None
        self.clear_btn = None
        self.count_badge = None
        self.results = None
        self.reset_button = None
        self.status_label = None

    # ------------------------------------------------------------------ contract

    def tokens(self):
        return [TokenField(key='token', label='C.AI Token',
                           on_set=self.set_token, help_md=TOKEN_HELP_MD),
                TokenField(key='web_next_auth', label='C.AI Web-Next-Auth (search)',
                           on_set=self.set_web_next_auth, help_md=WEB_NEXT_AUTH_HELP_MD)]

    def is_ready(self):
        if not self.token:
            return False, 'Please set a C.AI token!'
        if not self.current_char or not self.current_chat:
            return False, 'Please select a character to use first!'
        return True, None

    async def generate(self, message: str, app):
        if not self.current_chat or not self.current_character_id:
            notify_and_log('No character selected or chat not initialized!', type='negative')
            return None

        try:
            logger.debug(f"Sending message to character {self.current_character_id}: {message}")
            answer = await self.client.chat.send_message(
                self.current_character_id, self.current_chat.chat_id, message
            )
            response = answer.get_primary_candidate().text
            logger.debug(f"Received response: {response}")
            return response
        except Exception as e:
            logger.error(f"Failed to send message to Character.AI: {e}")
            logger.error(traceback.format_exc())
            notify_and_log(f'Failed to send message: {e}', type='negative')
            return None

    async def generate_event(self, event, app):
        """React to a GSI game event by sending a synthesized prompt to the
        selected character (only called while this tab is active and the toggle
        is on). With no character selected, generate() notifies and returns
        None -- i.e. no taunt."""
        return await self.generate(event_to_prompt(event), app)

    # ------------------------------------------------------------------ tab UI

    def build_tab(self, app) -> None:
        self.app = app

        saved = app.load_area_settings(self.key).get('recents')
        self.recents = saved if isinstance(saved, list) else []
        self.react_to_events = bool(app.load_area_settings(self.key).get('react_to_events', False))
        self.consumes_events = self.react_to_events

        area_header('Character.AI',
                    'Search for a character / paste a character ID, and select it.')

        # All controls in one row; the C.AI token lives in Settings > API Tokens.
        with ui.row().classes('items-center gap-2 w-full'):
            self.character_input = ui.input('Character', placeholder='name or character ID') \
                .on('keypress.enter', self.search).classes('grow')
            self.search_btn = ui.button(on_click=self.search, icon='search').props('outline')
            self.clear_btn = ui.button(on_click=self.clear_search, icon='clear').props('outline')
            with self.clear_btn:
                ui.tooltip('Clear search — show recently used characters')
            self.count_badge = ui.badge('0')
            # Sort-by dropdown disabled for now.
            # self.character_select = ui.select(['Recommended', 'Trending', 'Recent'], value='Trending',
            #                                   on_change=lambda e: self.search(query_type=e.value)).classes(
            #     'ml-auto').props('filled')

            self.reset_button = ui.button(icon='restart_alt',
                                          on_click=lambda: self.select_character_sync(self.current_char)) \
                .props('outline').classes('ml-auto')
            self.reset_button.disable()
            with self.reset_button:
                ui.tooltip("⚠️ Reset Character's memory").classes('bg-red')

        # Small status line: which character the bot is currently chatting as.
        self.status_label = ui.label().classes('text-sm opacity-70 mt-2 w-full')
        self._update_status()

        events_cb = ui.checkbox('Also react to my game events', value=self.react_to_events,
                                on_change=lambda e: self._set_react_to_events(e.value)) \
            .classes('mt-2')
        with events_cb:
            ui.tooltip('When on, this character also taunts about your own GSI events '
                       '(multi-kills, MVPs, clutches) while this tab is active. '
                       'Set up Game State Integration in Settings first.')

        self.results = ui.row().classes('justify-center gap-3 mt-3 w-full')
        self._show_recents()

    def _update_status(self) -> None:
        """Reflect the currently-selected character in the status line."""
        if self.status_label is None:
            return
        if self.current_char:
            self.status_label.text = f'💬 Currently chatting with: {self.current_char.name}'
        else:
            self.status_label.text = 'No character selected — search and pick one to start chatting.'

    # ------------------------------------------------------------------ helpers

    async def set_token(self, token):
        self.token = token or ''
        if not self.token:
            self.client = None
            return

        try:
            self.client = await get_client(token=token)
            me = await self.client.account.fetch_me()
            username = me.username

            if username == 'ANONYMOUS':
                ui.notify('An invalid token has been set!', type='negative')
            else:
                ui.notify(f'Welcome {username}!', type='positive', color='pink')
        except Exception as e:
            ui.notify(f'Authentication failed: {e}', type='negative')
            self.client = None

    async def set_web_next_auth(self, web_next_auth):
        # Stored only; the C.AI search endpoint reads it per-call (see search()),
        # so there's nothing to authenticate here.
        self.web_next_auth = web_next_auth or ''

    def select_character_sync(self, char):
        """Run the async select_character from a sync click handler."""
        async def wrapper():
            await self.select_character(char)

        ui.timer(0.01, wrapper, once=True)

    async def select_character(self, char):
        logger.debug(f"Attempting to select character: {char.name} (ID: {char.character_id})")
        if not self.client:
            notify_and_log('Please set a C.AI token!', type='negative')
            return

        try:
            self.current_character_id = char.character_id
            self.current_char = char

            logger.debug(f"Creating chat for character {char.character_id}")
            self.current_chat, _ = await self.client.chat.create_chat(self.current_character_id)
            logger.debug(f"Chat created successfully: {self.current_chat.chat_id}")

            self.reset_button.enable()
            self._record_recent(char)
            self._update_status()

            avatar = _avatar_url(char)
            notify_and_log(f'Selected <b>{char.name}</b> as your character.', type='positive', avatar=avatar,
                           color='pink', html=True)
        except Exception as e:
            logger.error(f"Failed to create chat for character {char.name}: {e}")
            logger.error(traceback.format_exc())
            notify_and_log(f'Failed to create chat: {e}', type='negative')

    @staticmethod
    def _looks_like_id(text: str) -> bool:
        # C.AI character IDs are long, URL-safe base64-ish tokens with no spaces
        # (e.g. "0kQ_5gZj5RjkLL8mfrf4qQ8Q7JoKyV87bfaPt9kb-14").
        return bool(re.fullmatch(r'[A-Za-z0-9_-]{20,}', text or ''))

    async def _load_by_id(self, char_id: str) -> None:
        if not self.client:
            notify_and_log('Please set a C.AI token first!', type='negative')
            return

        self.search_btn.disable()
        try:
            logger.debug(f"Loading character by ID: {char_id}")
            char = await self.client.character.fetch_character_info(char_id)
            await self.select_character(char)
        except Exception as e:
            logger.error(f"Failed to load character by ID {char_id}: {e}")
            logger.error(traceback.format_exc())
            notify_and_log(f'Could not load character by ID: {e}', type='negative')
        finally:
            self.search_btn.enable()

    async def search(self, query_type='Search'):
        if not self.token:
            notify_and_log('Please set a C.AI token!', type='negative')
            return

        # A pasted character ID loads that character directly instead of searching.
        query = (self.character_input.value or '').strip()
        if query_type == 'Search' and self._looks_like_id(query):
            await self._load_by_id(query)
            return

        # Name search hits a tRPC endpoint that only authenticates via the
        # web-next-auth cookie; without it the request fails and shows nothing.
        if query_type == 'Search' and not self.web_next_auth:
            notify_and_log('Set your C.AI "Web-Next-Auth" token in Settings > API Tokens to search by name.',
                           type='warning')
            return

        self.search_btn.disable()

        try:
            if not self.client:
                notify_and_log('Please set a C.AI token first!', type='negative')
                return

            if query_type == 'Recommended':
                logger.debug("Fetching recommended characters")
                characters = await self.client.character.fetch_recommended_characters()
            elif query_type == 'Recent':
                logger.debug("Fetching recent chats")
                recent_chats = await self.client.chat.fetch_recent_chats()
                characters = []
                for chat in recent_chats:
                    char_obj = type('Character', (), {
                        'character_id': chat.character_id,
                        'name': chat.character_name,
                        'title': '',
                        'description': '',
                        'num_interactions': 0,
                        'avatar': chat.character_avatar if hasattr(chat, 'character_avatar') else None
                    })()
                    characters.append(char_obj)
            elif query_type == 'Trending':
                logger.debug("Fetching featured characters (trending)")
                characters = await self.client.character.fetch_featured_characters()
            elif query_type == 'Search':
                logger.debug(f"Searching for characters with query: {self.character_input.value}")
                characters = await self.client.character.search_characters(
                    self.character_input.value, web_next_auth=self.web_next_auth)
            else:
                characters = []

            logger.debug(f"Retrieved {len(characters)} characters for query_type: {query_type}")
            self._render_cards(characters)

        except Exception as e:
            logger.error(f"Character search failed: {e}")
            logger.error(traceback.format_exc())
            notify_and_log(f'Search failed: {e}', type='negative')
        finally:
            self.search_btn.enable()

    # ------------------------------------------------------------------ recents + rendering

    def _render_cards(self, characters) -> None:
        """Render a grid of character cards into self.results (shared by search
        results and the recents view)."""
        self.results.clear()
        with self.results:
            for character in characters:
                avatar = _avatar_url(character)
                with ui.link().on('click', lambda char=character: self.select_character_sync(char)).classes(
                        'no-underline hover:scale-105 duration-100 active:scale-100 text-pink-600'):
                    with ui.card().tight().classes('w-36 h-48 text-center').classes(
                            'shadow-md shadow-black dark:bg-[#121212]'):
                        ui.image(avatar).classes('h-32')
                        with ui.row().classes('absolute right-2 top-1'):
                            if getattr(character, 'num_interactions', 0):
                                interaction_label = f'🗨️{numerize.numerize(character.num_interactions)}'
                            else:
                                interaction_label = ''
                            ui.label(interaction_label).classes('text-center drop-shadow-[0_1.2px_1.2px_rgba(0,0,0,1)]')
                        with ui.card_section().classes('h-6 w-full font-bold'):
                            ui.label(character.name).classes('drop-shadow-[0_1.2px_1.2px_rgba(0,0,0,0.8)] break-words')
        self.count_badge.text = str(len(characters))

    def _show_recents(self) -> None:
        """Render the recently-used characters, or an empty-state hint."""
        if not self.recents:
            self.results.clear()
            with self.results:
                ui.label('No recent characters yet — search above to find one.') \
                    .classes('text-italic opacity-60')
            self.count_badge.text = '0'
            return
        self._render_cards([_char_from_recent(e) for e in self.recents])

    def clear_search(self) -> None:
        """Clear the search box/results and return to the recents view."""
        self.character_input.value = ''
        self._show_recents()

    def _record_recent(self, char) -> None:
        """Move the just-selected character to the front of the recents list and
        persist it (dedup by id, capped at MAX_RECENTS)."""
        entry = {
            'character_id': char.character_id,
            'name': char.name,
            'avatar': _avatar_url(char),
            'num_interactions': getattr(char, 'num_interactions', 0) or 0,
        }
        self.recents = [e for e in self.recents if e.get('character_id') != entry['character_id']]
        self.recents.insert(0, entry)
        self.recents = self.recents[:MAX_RECENTS]

        data = self.app.load_area_settings(self.key)
        data['recents'] = self.recents
        self.app.save_area_settings(self.key, data)

    def _set_react_to_events(self, value) -> None:
        self.react_to_events = bool(value)
        self.consumes_events = self.react_to_events
        data = self.app.load_area_settings(self.key)
        data['react_to_events'] = self.react_to_events
        self.app.save_area_settings(self.key, data)
