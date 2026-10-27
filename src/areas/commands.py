"""C2 / Command Bot area: responds to !-prefixed chat commands.

Commands live in a small registry (name -> Command), so the enable checkboxes
and the !help listing both derive from one place; adding a command is one
registry entry plus one handler method. Replies are plain text (no emoji) for
CS2 font compatibility; the blackjack card suits are the one exception. A few
commands hit free web APIs via httpx; the rest are local.

!blackjack runs a table (areas/blackjack.py) with timers of its own: the deal
after the join window and the end of a round when its clock runs out. Those
lines go out through generate_timed(), which the chat loop polls on every tick.
"""
import logging
import random
import time
import urllib.parse
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Dict, List, Optional, Union

import httpx
from nicegui import ui

from ui.ui_util import area_header, settings_card
from . import blackjack
from .base import ChatArea

logger = logging.getLogger(__name__)

HTTP_TIMEOUT = 5  # seconds for network commands

# !dadjoke source. icanhazdadjoke asks API users to send a descriptive User-Agent.
DADJOKE_URL = 'https://icanhazdadjoke.com/'
DADJOKE_UA = 'CS2-Chatbot (https://github.com/pmehlb/CS2-Chatbot)'

# !fact source.
FACT_URL = 'https://uselessfacts.jsph.pl/api/v2/facts/random?language=en'

# !quote source. dummyjson has no length filter, so a long quote is re-rolled
# a few times before the bot settles for it.
QUOTE_URL = 'https://dummyjson.com/quotes/random'
QUOTE_MAX_LEN = 130
QUOTE_TRIES = 3

# !fortunecookie source.
FORTUNE_URL = 'https://api.adviceslip.com/advice'

# !ticker source. _ticker_url() adds the query string and the API key.
# The AlphaVantage key is user-provided, in-source by request. Free tier is
# rate-limited to ~25 requests/day; on limit the API returns a JSON body with
# a 'Note'/'Information' key instead of data (see _cmd_ticker).
TICKER_URL = 'https://www.alphavantage.co/query'
ALPHAVANTAGE_KEY = 'JCFJ95WG36YQ7166'

# The blackjack settings in the C2 tab: table attribute, label, bounds, tooltip.
BJ_SECONDS_RANGE = (5, 120)
BJ_DECKS_RANGE = (1, 8)
BJ_FIELDS = (
    ('join_seconds', 'Join window (s)', BJ_SECONDS_RANGE,
     'Time between !blackjack and the deal. Players type !join in this window.'),
    ('turn_seconds', 'Round timer (s)', BJ_SECONDS_RANGE,
     'Time for each round. All players move at the same time. The round ends when every '
     'hand has a move or the timer runs out. A hand with no move stands.'),
    ('decks', 'Decks in shoe', BJ_DECKS_RANGE,
     'Decks shuffled together. The shoe reshuffles when less than a quarter is left. '
     'A change takes effect at the next deal.'),
)

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

# SLOT_SYMBOLS = ['cherry', 'lemon', 'orange', 'bell', 'bar', 'seven']
SLOT_SYMBOLS = ['♠', '✿', '❤', '♿', '♛', '7']
SLOTS_JACKPOT = '★ JACKPOT ★'

FLIP_SIDES = ['Ⓗ Heads', 'Ⓣ Tails']
FORTUNE_MARK = '☘\ufe0e'
TICKER_UP, TICKER_DOWN = '↑', '↓'
FAIL_MARK = '✘'            # a fetch that failed, or no data for a symbol
WAIT_MARK = '⌛\ufe0e'      # the AlphaVantage rate limit

Reply = Optional[Union[str, List[str]]]

# !help gives one line per category, in this order.
HELP_CATEGORIES = ('Games', 'Random', 'Tools')


@dataclass
class Command:
    name: str                          # token after '!', lowercase (e.g. 'ping')
    usage: str                         # shown in !help (e.g. '!8ball [question]')
    desc: str                          # checkbox sub-label
    category: str                      # its !help line (HELP_CATEGORIES); '' = not listed
    handler: Callable[[str], Awaitable[Reply]]
    # Follow-up commands that only work while this one is enabled (!join,
    # !hit, !stand for !blackjack). No checkbox of their own.
    subcommands: Dict[str, Callable[[str], Awaitable[Reply]]] = field(default_factory=dict)


def tagged(tag: str, text: str) -> str:
    """One command reply: '[TAG] text'. Each handler gives its tag as the
    default of its ``tag`` parameter, so a tag changes in one place."""
    return f'[{tag}] {text}'


def _ticker_url(**params) -> str:
    """TICKER_URL with an AlphaVantage query string and the API key."""
    return f'{TICKER_URL}?' + urllib.parse.urlencode({**params, 'apikey': ALPHAVANTAGE_KEY})


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
    answers_own_lines = True   # you can use the commands too (e.g. sit at your own table)

    def __init__(self):
        self.app = None
        self.enabled = {}               # name -> bool (absent = on by default)
        self.table = blackjack.Table()

        # Ordered registry; order drives the checkbox list and the order
        # inside each !help line.
        ordered = [
            Command('help', '!help', 'list available commands', '', self._cmd_help),
            Command('ping', '!ping', 'replies "pong"', 'Tools', self._cmd_ping),
            Command('slots', '!slots', 'roll a slot machine', 'Games', self._cmd_slots),
            Command('8ball', '!8ball [question]', 'magic 8-ball', 'Games', self._cmd_8ball),
            Command('roll', '!roll [n]', 'roll a die (default d6)', 'Games', self._cmd_roll),
            Command('flip', '!flip', 'flip a coin', 'Games', self._cmd_flip),
            Command('dadjoke', '!dadjoke', 'random dad joke', 'Random', self._cmd_dadjoke),
            Command('fact', '!fact', 'random fact', 'Random', self._cmd_fact),
            Command('quote', '!quote', 'random quote', 'Random', self._cmd_quote),
            Command('fortunecookie', '!fortunecookie', 'fortune cookie advice', 'Random',
                    self._cmd_fortunecookie),
            Command('ticker', '!ticker [symbol | from to]', 'stock/currency lookup', 'Tools',
                    self._cmd_ticker),
            # The table itself tells players about !join and the moves.
            Command('blackjack', '!blackjack', 'blackjack vs the dealer', 'Games',
                    self._cmd_blackjack,
                    subcommands={'join': self._cmd_join, 'hit': self._cmd_hit,
                                 'stand': self._cmd_stand, 'double': self._cmd_double,
                                 'split': self._cmd_split}),
        ]
        self.registry = {c.name: c for c in ordered}
        # Sub-command name -> parent command name, for dispatch.
        self.parents = {sub: c.name for c in ordered for sub in c.subcommands}

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
        if name in self.parents:
            parent = self.parents[name]
            if not self._is_enabled(parent):
                return None
            handler = self.registry[parent].subcommands[name]
        else:
            cmd = self.registry.get(name)
            if cmd is None or not self._is_enabled(name):
                return None
            handler = cmd.handler

        # The reply cooldown is global and enforced by the chat loop, not here.
        return await handler(arg.strip())

    def queues_message(self, message: str) -> bool:
        """Blackjack commands go in order, so every !join and every move in one tick counts."""
        if not self._is_enabled('blackjack'):
            return False
        name = (message or '').strip()[1:].partition(' ')[0].lower()
        return message.strip().startswith('!') and \
            (name == 'blackjack' or self.parents.get(name) == 'blackjack')

    async def generate_timed(self, app):
        """The blackjack table's due timer line, sent to its own channel."""
        if not self._is_enabled('blackjack'):
            return None
        channel = self.table.channel   # read first: finishing a round resets it
        reply = self.table.tick(time.monotonic())
        return (reply, channel) if reply else None

    def reply_shown(self, reply, now: float) -> None:
        """The table view in chat starts the round clock."""
        lag = self.table.shown(reply, now)
        if lag is not None:
            logger.debug(f'Blackjack table view reached chat {lag:.1f}s after the table '
                         f'built it. The {self.table.turn_seconds}s round clock starts now.')

    # ------------------------------------------------------------------ commands

    async def _cmd_help(self, arg: str) -> Reply:
        return self._help_lines()

    def _help_lines(self) -> List[str]:
        """The help block: a divider, one line per category of enabled
        commands ('Games: !slots !flip ...'), and a divider. A category with
        no enabled commands gets no line.

        Shared by the !help command and the "Send help" button in the tab.
        """
        lines = []
        for category in HELP_CATEGORIES:
            usages = [c.usage for c in self.registry.values()
                      if c.category == category and self._is_enabled(c.name)]
            if usages:
                lines.append(f'{category}: ' + ' '.join(usages))
        bar = '=-' * 12
        return [bar, *lines, bar]

    async def _cmd_ping(self, arg: str, tag: str = 'PING') -> Reply:
        return tagged(tag, 'pong')

    async def _cmd_slots(self, arg: str, tag: str = 'SLOTS') -> Reply:
        reels = [random.choice(SLOT_SYMBOLS) for _ in range(3)]
        line = ' | '.join(reels)
        if reels[0] == reels[1] == reels[2]:
            line += f' {SLOTS_JACKPOT}'
        return tagged(tag, line)

    async def _cmd_8ball(self, arg: str, tag: str = '8BALL') -> Reply:
        return tagged(tag, random.choice(EIGHTBALL_ANSWERS))

    async def _cmd_roll(self, arg: str, tag: str = 'ROLL') -> Reply:
        parts = arg.split()
        sides = 6
        if parts:
            try:
                sides = int(parts[0])
            except ValueError:
                sides = 6
        sides = max(2, min(1000, sides))
        return tagged(tag, f'{random.randint(1, sides)} (d{sides})')

    async def _cmd_flip(self, arg: str, tag: str = 'FLIP') -> Reply:
        return tagged(tag, random.choice(FLIP_SIDES))

    async def _cmd_dadjoke(self, arg: str, tag: str = 'DADJOKE') -> Reply:
        try:
            text = await _http_get_text(
                DADJOKE_URL, headers={'Accept': 'text/plain', 'User-Agent': DADJOKE_UA})
            return tagged(tag, text.strip())
        except Exception as e:
            logger.warning(f'dadjoke fetch failed: {e}')
            return tagged(tag, f"{FAIL_MARK} couldn't fetch a joke right now")

    async def _cmd_fact(self, arg: str, tag: str = 'FACT') -> Reply:
        try:
            data = await _http_get_json(FACT_URL)
            return tagged(tag, (data.get('text') or '').strip())
        except Exception as e:
            logger.warning(f'fact fetch failed: {e}')
            return tagged(tag, f"{FAIL_MARK} couldn't fetch a fact right now")

    async def _cmd_quote(self, arg: str, tag: str = 'QUOTE') -> Reply:
        try:
            for _ in range(QUOTE_TRIES):
                data = await _http_get_json(QUOTE_URL)
                text = (data.get('quote') or '').strip()
                if len(text) <= QUOTE_MAX_LEN:
                    break
            author = (data.get('author') or '').strip()
            return tagged(tag, f'{text} - {author}' if author else text)
        except Exception as e:
            logger.warning(f'quote fetch failed: {e}')
            return tagged(tag, f"{FAIL_MARK} couldn't fetch a quote right now")

    async def _cmd_fortunecookie(self, arg: str, tag: str = 'FORTUNE') -> Reply:
        try:
            data = await _http_get_json(FORTUNE_URL)
            # adviceslip serves text/html, but _http_get_json parses it anyway.
            advice = (data.get('slip') or {}).get('advice') or ''
            return tagged(tag, f'{FORTUNE_MARK} {advice.strip()}')
        except Exception as e:
            logger.warning(f'fortunecookie fetch failed: {e}')
            return tagged(tag, f"{FAIL_MARK} couldn't fetch advice right now")

    async def _cmd_ticker(self, arg: str, tag: str = 'TICKER') -> Reply:
        # Only two AlphaVantage functions are supported: GLOBAL_QUOTE (one token)
        # and CURRENCY_EXCHANGE_RATE (two tokens). Free tier is ~25 req/day; on
        # rate-limit the API returns a 'Note'/'Information' key instead of data.
        tokens = [t.upper() for t in arg.split()]
        if not tokens:
            return tagged(tag, 'usage !ticker <SYMBOL>  or  !ticker <FROM> <TO>')
        try:
            if len(tokens) == 1:
                sym = tokens[0]
                data = await _http_get_json(_ticker_url(function='GLOBAL_QUOTE', symbol=sym))
                if self._alphavantage_rate_limited(data):
                    return tagged(tag, f'{WAIT_MARK} rate limit reached, try later')
                quote = data.get('Global Quote') or {}
                if not quote:
                    return tagged(tag, f'{FAIL_MARK} no data for {sym}')
                price = float(quote.get('05. price', 0))
                pct = (quote.get('10. change percent') or '').strip().rstrip('%')
                arrow = TICKER_DOWN if pct.startswith('-') else TICKER_UP
                return tagged(tag, f'{sym} ${price:.2f} ({arrow}{pct.lstrip("-")}%)')

            # Two (or more) tokens: treat the first two as a currency pair.
            frm, to = tokens[0], tokens[1]
            data = await _http_get_json(_ticker_url(
                function='CURRENCY_EXCHANGE_RATE', from_currency=frm, to_currency=to))
            if self._alphavantage_rate_limited(data):
                return tagged(tag, f'{WAIT_MARK} rate limit reached, try later')
            rate = float((data.get('Realtime Currency Exchange Rate') or {})
                         .get('5. Exchange Rate', 0))
            return tagged(tag, f'{frm}/{to} {rate:.4f}')
        except Exception as e:
            logger.warning(f'ticker fetch failed: {e}')
            return tagged(tag, f"{FAIL_MARK} couldn't fetch ticker data right now")

    @staticmethod
    def _alphavantage_rate_limited(data) -> bool:
        # On rate-limit AlphaVantage returns a body keyed by 'Note'/'Information'.
        return isinstance(data, dict) and ('Note' in data or 'Information' in data)

    # The blackjack commands act for whoever typed them, which the chat loop
    # records in app.last_speaker (the message text carries no name here).

    def _speaker(self) -> str:
        return getattr(self.app, 'last_speaker', '') or ''

    async def _cmd_blackjack(self, arg: str) -> Reply:
        if not self._speaker():
            return None
        channel = getattr(self.app, 'last_channel', 'all') or 'all'
        return self.table.open(self._speaker(), channel, time.monotonic())

    async def _cmd_join(self, arg: str) -> Reply:
        if not self._speaker():
            return None
        return self.table.join(self._speaker(), time.monotonic())

    def _table_move(self, move, arg: str) -> Reply:
        # A move needs a name: the table answers "you can't do that" by name.
        # ``arg`` is the optional hand number after a split ("!hit 2").
        if not self._speaker():
            return None
        return move(self._speaker(), time.monotonic(), arg)

    async def _cmd_hit(self, arg: str) -> Reply:
        return self._table_move(self.table.hit, arg)

    async def _cmd_stand(self, arg: str) -> Reply:
        return self._table_move(self.table.stand, arg)

    async def _cmd_double(self, arg: str) -> Reply:
        return self._table_move(self.table.double, arg)

    async def _cmd_split(self, arg: str) -> Reply:
        return self._table_move(self.table.split, arg)

    # ------------------------------------------------------------------ helpers

    def _is_enabled(self, name: str) -> bool:
        return self.enabled.get(name, True)

    # ------------------------------------------------------------------ tab UI

    def build_tab(self, app) -> None:
        self.app = app
        saved = app.load_area_settings(self.key)
        enabled = saved.get('enabled')
        self.enabled = dict(enabled) if isinstance(enabled, dict) else {}
        self._load_blackjack(saved.get('blackjack'))

        area_header('Command Bot',
                    'Responds to `!`-prefixed chat commands. Toggle which '
                    'commands are enabled. The reply cooldown lives in '
                    'Settings > Chatbot.')

        with settings_card('Commands'):
            # Two-column grid so the checkbox list stays compact instead of one
            # long single column. Tighter row gap, roomier column gap set inline
            # (beats the grid's default gap deterministically).
            with ui.grid(columns=2).classes('w-full').style('gap: 0.5rem 1.5rem'):
                for cmd in self.registry.values():
                    ui.checkbox(f'!{cmd.name} — {cmd.desc}',
                                value=self._is_enabled(cmd.name),
                                on_change=lambda e, n=cmd.name: self._set_enabled(n, e.value))

            help_btn = ui.button('Send help to chat', icon='campaign',
                                 on_click=self._send_help).props('outline').classes('mt-1')
            with help_btn:
                ui.tooltip('Write the help message to message.cfg now, to advertise the '
                           'commands and kick things off. Bot does not need to be on.')

        with settings_card('Blackjack'):
            # Three equal columns: the two timers and the shoe size.
            with ui.row().classes('w-full no-wrap gap-3'):
                for attr, label, (low, high), tip in BJ_FIELDS:
                    box = ui.number(label, value=getattr(self.table, attr), min=low, max=high,
                                    step=1, format='%.0f',
                                    on_change=lambda e, a=attr: self._set_blackjack(a, e.value)) \
                        .classes('flex-1')
                    with box:
                        ui.tooltip(tip)

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

    def _load_blackjack(self, saved) -> None:
        if isinstance(saved, dict):
            for attr, _label, bounds, _tip in BJ_FIELDS:
                if attr in saved:
                    self._apply_blackjack(attr, saved[attr], bounds)

    def _apply_blackjack(self, attr: str, value, bounds) -> bool:
        """Clamp and set one table setting. False if the value is not a number."""
        try:
            number = int(value)
        except (TypeError, ValueError):
            return False
        low, high = bounds
        setattr(self.table, attr, max(low, min(high, number)))
        return True

    def _set_blackjack(self, attr: str, value) -> None:
        # An emptied number box sends None: keep the old value until a number lands.
        bounds = next(f[2] for f in BJ_FIELDS if f[0] == attr)
        if not self._apply_blackjack(attr, value, bounds):
            return
        data = self.app.load_area_settings(self.key)
        data['blackjack'] = {f[0]: getattr(self.table, f[0]) for f in BJ_FIELDS}
        self.app.save_area_settings(self.key, data)
