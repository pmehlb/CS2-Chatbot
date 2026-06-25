"""Mimic area: echoes the last message back with random capitalisation.

Replaces the old "Mimic Mode" switch. Needs no configuration, so it's a good
minimal example of an area with only a generate() method.
"""
import random

from ui.ui_util import area_header
from .base import ChatArea


class MimicArea(ChatArea):
    key = 'mimic'
    label = 'Mimic'
    icon = 'format_quote'

    async def generate(self, message: str, app):
        return ''.join(c.upper() if random.randint(0, 1) else c.lower() for c in message)

    def build_tab(self, app) -> None:
        area_header('Mimic',
                    'RePeaT ThE LaSt MeSsAgE BaCk WiTh RaNdOmLy ApPlIeD CaPiTaLiZaTiOn.')
