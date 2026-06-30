"""C2 / Command Bot area: responds to !-prefixed chat commands.

Commands live in a small registry (name -> Command), so the enable checkboxes
and the !help listing both derive from one place; adding a command is one
registry entry plus one handler method. Replies are plain text (no emoji) for
CS2 font compatibility. Two commands hit free, keyless web APIs via httpx; the
rest are local.
"""
import logging
import random
import urllib.parse
from dataclasses import dataclass
from typing import Awaitable, Callable, List, Optional, Union

import httpx
from nicegui import ui

from ui.ui_util import area_header, settings_card
from .base import ChatArea

logger = logging.getLogger(__name__)

HTTP_TIMEOUT = 5  # seconds for network commands
# icanhazdadjoke asks API users to send a descriptive User-Agent.
DADJOKE_UA = 'CS2-Chatbot (https://github.com/)'
# AlphaVantage API key for !ticker (user-provided, in-source by request).
# Free tier is rate-limited to ~25 requests/day; on limit the API returns a
# JSON body with a 'Note'/'Information' key instead of data (see _cmd_ticker).
ALPHAVANTAGE_KEY = 'JCFJ95WG36YQ7166'

EIGHTBALL_ANSWERS = [
    'It is certain.', 'It is decidedly so.', 'Without a doubt.',
    'Yes definitely.', 'You may rely on it.', 'As I see it, yes.',
    'Most likely.', 'Outlook good.', 'Yes.', 'Signs point to yes.',
    'Reply hazy, try again.', 'Ask again later.',
    'Better not tell you now.', 'Cannot predict now.',
    'Concentrate and ask again.', "Don't count on it.",
    'My reply is no.', 'My sources say no.',
    'Outlook not so good.', 'Very doubtful.',
]

SLOT_SYMBOLS = ['cherry', 'lemon', 'orange', 'bell', 'bar', 'seven']

Reply = Optional[Union[str, List[str]]]


@dataclass
class Command:
    name: str                          # token after '!', lowercase (e.g. 'ping')
    usage: str                         # shown in !help (e.g. '!8ball [question]')
    desc: str                          # checkbox sub-label
    handler: Callable[[str], Awaitable[Reply]]


async def _http_get_text(url, headers=None) -> str:
    """GET a URL and return response text; raises on HTTP error/timeout."""
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        return resp.text


async def _http_get_json(url, headers=None):
    """GET a URL and return parsed JSON; raises on HTTP error/timeout."""
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        return resp.json()


class CommandBotArea(ChatArea):
    key = 'c2'
    label = 'C2'
    icon = 'terminal'
    attribute_speaker = False  # commands match a leading '!', so never prefix the message

    def __init__(self):
        self.app = None
        self.enabled = {}               # name -> bool (absent = on by default)

        # Ordered registry; order drives both the checkbox list and !help.
        ordered = [
            Command('help', '!help', 'list available commands', self._cmd_help),
            Command('ping', '!ping', 'replies "pong"', self._cmd_ping),
            Command('slots', '!slots', 'roll a slot machine', self._cmd_slots),
            Command('8ball', '!8ball [question]', 'magic 8-ball', self._cmd_8ball),
            Command('roll', '!roll [n]', 'roll a die (default d6)', self._cmd_roll),
            Command('flip', '!flip', 'flip a coin', self._cmd_flip),
            Command('dadjoke', '!dadjoke', 'random dad joke', self._cmd_dadjoke),
            Command('fact', '!fact', 'random fact', self._cmd_fact),
            Command('quote', '!quote', 'random quote', self._cmd_quote),
            Command('fortunecookie', '!fortunecookie', 'fortune cookie advice',
                    self._cmd_fortunecookie),
            Command('ticker', '!ticker [symbol | from to]', 'stock/currency lookup',
                    self._cmd_ticker),
        ]
        self.registry = {c.name: c for c in ordered}

    # ------------------------------------------------------------------ contract

    def is_ready(self):
        if not any(self._is_enabled(name) for name in self.registry):
            return False, 'Enable at least one command.'
        return True, None

    async def generate(self, message: str, app) -> Reply:
        self.app = app
        text = (message or '').strip()
        if not text.startswith('!'):
            return None

        name, _, arg = text[1:].partition(' ')
        name = name.lower()
        cmd = self.registry.get(name)
        if cmd is None or not self._is_enabled(name):
            return None

        # The reply cooldown is global and enforced by the chat loop, not here.
        return await cmd.handler(arg.strip())

    # ------------------------------------------------------------------ commands

    async def _cmd_help(self, arg: str) -> Reply:
        return self._help_lines()

    def _help_lines(self) -> List[str]:
        """The 3-line help block (divider / enabled commands / divider).

        Shared by the !help command and the "Send help" button in the tab.
        """
        usages = [c.usage for c in self.registry.values() if self._is_enabled(c.name)]
        bar = '=-' * 12
        return [bar, 'Commands: ' + '  '.join(usages), bar]

    async def _cmd_ping(self, arg: str) -> Reply:
        return 'pong'

    async def _cmd_slots(self, arg: str) -> Reply:
        reels = [random.choice(SLOT_SYMBOLS) for _ in range(3)]
        line = 'slots: ' + ' | '.join(reels)
        if reels[0] == reels[1] == reels[2]:
            line += ' - JACKPOT!'
        return line

    async def _cmd_8ball(self, arg: str) -> Reply:
        return '8ball: ' + random.choice(EIGHTBALL_ANSWERS)

    async def _cmd_roll(self, arg: str) -> Reply:
        parts = arg.split()
        sides = 6
        if parts:
            try:
                sides = int(parts[0])
            except ValueError:
                sides = 6
        sides = max(2, min(1000, sides))
        return f'roll: {random.randint(1, sides)} (d{sides})'

    async def _cmd_flip(self, arg: str) -> Reply:
        return 'flip: ' + random.choice(['Heads', 'Tails'])

    async def _cmd_dadjoke(self, arg: str) -> Reply:
        try:
            text = await _http_get_text(
                'https://icanhazdadjoke.com/',
                headers={'Accept': 'text/plain', 'User-Agent': DADJOKE_UA})
            return text.strip()
        except Exception as e:
            logger.warning(f'dadjoke fetch failed: {e}')
            return "[DADJOKE] couldn't fetch a joke right now"

    async def _cmd_fact(self, arg: str) -> Reply:
        try:
            data = await _http_get_json(
                'https://uselessfacts.jsph.pl/api/v2/facts/random?language=en')
            return '[FACT] ' + (data.get('text') or '').strip()
        except Exception as e:
            logger.warning(f'fact fetch failed: {e}')
            return "[FACT] couldn't fetch a fact right now"

    async def _cmd_quote(self, arg: str) -> Reply:
        try:
            data = await _http_get_json(
                'https://api.quotable.io/quotes/random?maxLength=130')
            # quotable may return a single object or a one-element array.
            if isinstance(data, list):
                data = data[0]
            return '[QUOTE] ' + (data.get('content') or '').strip()
        except Exception as e:
            logger.warning(f'quote fetch failed: {e}')
            return "[QUOTE] couldn't fetch a quote right now"

    async def _cmd_fortunecookie(self, arg: str) -> Reply:
        try:
            data = await _http_get_json('https://api.adviceslip.com/advice')
            # adviceslip serves text/html, but _http_get_json parses it anyway.
            advice = (data.get('slip') or {}).get('advice') or ''
            return '[FORTUNE] ' + advice.strip()
        except Exception as e:
            logger.warning(f'fortunecookie fetch failed: {e}')
            return "[FORTUNE] couldn't fetch advice right now"

    async def _cmd_ticker(self, arg: str) -> Reply:
        # Only two AlphaVantage functions are supported: GLOBAL_QUOTE (one token)
        # and CURRENCY_EXCHANGE_RATE (two tokens). Free tier is ~25 req/day; on
        # rate-limit the API returns a 'Note'/'Information' key instead of data.
        tokens = [t.upper() for t in arg.split()]
        if not tokens:
            return '[TICKER] usage !ticker <SYMBOL>  or  !ticker <FROM> <TO>'
        try:
            if len(tokens) == 1:
                sym = tokens[0]
                url = ('https://www.alphavantage.co/query?function=GLOBAL_QUOTE'
                       f'&symbol={urllib.parse.quote(sym)}&apikey={ALPHAVANTAGE_KEY}')
                data = await _http_get_json(url)
                if self._alphavantage_rate_limited(data):
                    return '[TICKER] rate limit reached, try later'
                quote = data.get('Global Quote') or {}
                if not quote:
                    return f'[TICKER] no data for {sym}'
                price = float(quote.get('05. price', 0))
                pct = (quote.get('10. change percent') or '').strip().rstrip('%')
                sign = '+' if not pct.startswith('-') else ''
                return f'[TICKER] {sym} ${price:.2f} ({sign}{pct}%)'

            # Two (or more) tokens: treat the first two as a currency pair.
            frm, to = tokens[0], tokens[1]
            url = ('https://www.alphavantage.co/query?function=CURRENCY_EXCHANGE_RATE'
                   f'&from_currency={urllib.parse.quote(frm)}'
                   f'&to_currency={urllib.parse.quote(to)}&apikey={ALPHAVANTAGE_KEY}')
            data = await _http_get_json(url)
            if self._alphavantage_rate_limited(data):
                return '[TICKER] rate limit reached, try later'
            rate = float((data.get('Realtime Currency Exchange Rate') or {})
                         .get('5. Exchange Rate', 0))
            return f'[TICKER] {frm}/{to} {rate:.4f}'
        except Exception as e:
            logger.warning(f'ticker fetch failed: {e}')
            return "[TICKER] couldn't fetch ticker data right now"

    @staticmethod
    def _alphavantage_rate_limited(data) -> bool:
        # On rate-limit AlphaVantage returns a body keyed by 'Note'/'Information'.
        return isinstance(data, dict) and ('Note' in data or 'Information' in data)

    # ------------------------------------------------------------------ helpers

    def _is_enabled(self, name: str) -> bool:
        return self.enabled.get(name, True)

    # ------------------------------------------------------------------ tab UI

    def build_tab(self, app) -> None:
        self.app = app
        saved = app.load_area_settings(self.key)
        enabled = saved.get('enabled')
        self.enabled = dict(enabled) if isinstance(enabled, dict) else {}

        area_header('Command Bot',
                    'Responds to `!`-prefixed chat commands. Toggle which '
                    'commands are enabled. The reply cooldown lives in '
                    'Settings > Chatbot.')

        with settings_card('Commands'):
            for cmd in self.registry.values():
                ui.checkbox(f'!{cmd.name} — {cmd.desc}',
                            value=self._is_enabled(cmd.name),
                            on_change=lambda e, n=cmd.name: self._set_enabled(n, e.value))

            help_btn = ui.button('Send help to chat', icon='campaign',
                                 on_click=self._send_help).props('outline').classes('mt-1')
            with help_btn:
                ui.tooltip('Write the help message to message.cfg now, to advertise the '
                           'commands and kick things off. Bot does not need to be on.')

    def _send_help(self) -> None:
        """Write the help message out now (a manual kickoff, independent of the
        power toggle and cooldown). All say lines are written to message.cfg at
        once -- not one-at-a-time like a live reply -- so a single in-game exec
        sends the whole help block. (The live send path execs each line via a
        keypress that only fires while CS2 is focused; from the GUI that left
        message.cfg holding only the last line, the closing divider.)"""
        import core  # local import: core never imports areas, so this is safe

        core.write_message_cfg(self._help_lines(), self.app, 'all')

    def _save(self) -> None:
        # Read-merge into this area's namespace (matching the C.AI/Reverser areas).
        data = self.app.load_area_settings(self.key)
        data['enabled'] = self.enabled
        self.app.save_area_settings(self.key, data)

    def _set_enabled(self, name: str, value) -> None:
        self.enabled[name] = bool(value)
        self._save()
