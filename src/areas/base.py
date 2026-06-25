"""The contract every AI "area" implements.

An area is a self-contained module that bundles three things:
  * its own GUI tab (build_tab)
  * a response handler (generate)
  * a readiness check used by the power toggle (is_ready)

Add a new behaviour by subclassing ChatArea in a new file under areas/ and
registering it in areas/__init__.py -- nothing else needs to change.
"""
from dataclasses import dataclass
from typing import Callable, Optional


@dataclass
class TokenField:
    """A secret an area needs, rendered generically in Settings > API Tokens.

    ``on_set`` is an async callable invoked with the value on change and on
    startup-restore (e.g. to authenticate). The Settings section owns the input
    widget and persistence, so areas don't build their own token fields.
    """
    key: str                       # sub-key inside the area's settings namespace
    label: str                     # input label, e.g. "C.AI Token"
    on_set: Callable               # async on_set(value) -> authenticate / react
    help_md: Optional[str] = None  # optional markdown shown in a help dialog


class ChatArea:
    key = ''            # stable id, also the settings namespace (e.g. "characterai")
    label = ''          # tab label shown in the GUI (e.g. "Character.AI")
    icon = 'chat'       # material icon name for the tab
    answerable = True   # False for utility tabs (e.g. Settings) that never reply;
                        # the GUI then idles the chat loop while such a tab is open

    def build_tab(self, app) -> None:
        """Render this area's settings/UI. Called inside its ui.tab_panel."""

    def tokens(self):
        """Return a list of TokenField this area needs (default: none).

        Settings > API Tokens renders these; the area never builds its own
        token input.
        """
        return []

    def is_ready(self):
        """Return (ok, reason). The power toggle refuses to turn on when not ok.

        reason is a short message shown to the user explaining what's missing.
        """
        return True, None

    async def generate(self, message: str, app):
        """Produce a reply to `message`, or return None to stay silent."""
        raise NotImplementedError
