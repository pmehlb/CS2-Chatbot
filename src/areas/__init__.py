"""Area registry.

To add a new AI behavior: create areas/<name>.py with a ChatArea subclass,
import it here, and add an instance to the list in build_areas(). It will get
its own tab and show up in the app automatically. The first area in the list is
the one selected on startup.
"""
from .characterai import CharacterAIArea
from .chatgpt import ChatGPTArea
from .claude import ClaudeArea
from .commands import CommandBotArea
from .mimic import MimicArea
from .settings import SettingsArea
from .string_reverser import StringReverserArea
from .tiltbot import TiltBotArea


def build_areas():
    # Chat behaviors first (the first one is selected on startup); the Settings
    # utility area is pinned last.
    return [
        CharacterAIArea(),
        ChatGPTArea(),
        ClaudeArea(),
        TiltBotArea(),
        CommandBotArea(),
        MimicArea(),
        StringReverserArea(),
        SettingsArea(),
    ]
