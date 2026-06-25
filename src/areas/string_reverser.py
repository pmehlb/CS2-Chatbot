"""String Reverser area: sends the last message back, reversed.

Optionally censors words first: each censored word is replaced (whole-word,
case-insensitive) in the original message, then the whole thing is reversed --
so the replacement un-reverses to clean text on the reader's end. The censor
list is editable in the tab and persists across launches.
"""
import re

from nicegui import ui

from ui.ui_util import area_header
from .base import ChatArea


class StringReverserArea(ChatArea):
    key = 'reverse'
    label = 'Reverser'
    icon = 'swap_horiz'

    def __init__(self):
        self.app = None
        self.censors = []          # list of {'word': str, 'replacement': str}
        self.list_container = None

    async def generate(self, message: str, app):
        return self._apply_censors(message)[::-1]

    def _apply_censors(self, text: str) -> str:
        for entry in self.censors:
            word = entry.get('word', '')
            if not word:
                continue
            text = re.sub(rf'\b{re.escape(word)}\b', entry.get('replacement', ''),
                          text, flags=re.IGNORECASE)
        return text

    def _save(self) -> None:
        # Read-merge into this area's namespace (matching the C.AI area) so the
        # censor list survives even if other keys ever get stored under 'reverse'.
        data = self.app.load_area_settings(self.key)
        data['censors'] = self.censors
        self.app.save_area_settings(self.key, data)

    def build_tab(self, app) -> None:
        self.app = app

        saved = app.load_area_settings(self.key).get('censors')
        self.censors = saved if isinstance(saved, list) else []

        area_header('String Reverser',
                    'Reverses the chat message - find/replacing words first. '
                    'Leave "Replace with" blank to delete the word.')

        with ui.row().classes('items-center gap-2 w-full'):
            word_input = ui.input('Word').classes('w-40')
            repl_input = ui.input('Replace with').classes('w-40')

            def add():
                word = (word_input.value or '').strip()
                if not word:
                    return
                self.censors.append({'word': word, 'replacement': (repl_input.value or '').strip()})
                self._save()
                word_input.value = ''
                repl_input.value = ''
                self._refresh_list()

            word_input.on('keydown.enter', add)
            repl_input.on('keydown.enter', add)
            ui.button(icon='add', on_click=add).props('rounded')

        self.list_container = ui.column().classes('gap-1 w-full mt-3')
        self._refresh_list()

    def _refresh_list(self) -> None:
        self.list_container.clear()
        with self.list_container:
            if not self.censors:
                ui.label('No censored words yet.').classes('text-italic opacity-60')
                return
            for i, entry in enumerate(self.censors):
                shown = entry.get('replacement') or '(removed)'
                with ui.row().classes('items-center gap-2 w-full'):
                    ui.label(f"{entry.get('word', '')}  →  {shown}")
                    ui.button(icon='delete', on_click=lambda idx=i: self._remove(idx)) \
                        .props('flat round dense color=grey').classes('ml-auto')

    def _remove(self, idx: int) -> None:
        if 0 <= idx < len(self.censors):
            self.censors.pop(idx)
            self._save()
            self._refresh_list()
