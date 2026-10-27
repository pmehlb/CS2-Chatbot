"""Tests for the C2 / Command Bot area: dispatch and command output.

Run with:  venv\\Scripts\\python -m pytest tests/test_commands.py
(or plain `python tests/test_commands.py` to run them without pytest).
"""
import asyncio
import contextlib
import os
import random
import sys
import time

# Make the application package layout (src/) importable when run from anywhere.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import areas.commands as commands
from areas import blackjack, trivia
from areas.commands import CommandBotArea


class FakeApp:
    """In-memory stand-in for AppState's area-settings persistence."""

    def __init__(self):
        self._store = {}
        self.last_speaker = ''
        self.last_channel = 'all'
        self.recent_sends = []
        self.shown_watch = []

    def load_area_settings(self, key):
        value = self._store.get(key, {})
        return dict(value) if isinstance(value, dict) else {}

    def save_area_settings(self, key, data):
        self._store[key] = data


def run(coro):
    return asyncio.run(coro)


def make_area():
    area = CommandBotArea()
    area.app = FakeApp()
    return area


def test_non_command_returns_none():
    area = make_area()
    assert run(area.generate('hello world', area.app)) is None


def test_bang_only_returns_none():
    area = make_area()
    assert run(area.generate('!', area.app)) is None


def test_unknown_command_returns_none():
    area = make_area()
    assert run(area.generate('!nope', area.app)) is None


def test_disabled_command_returns_none():
    area = make_area()
    area.enabled = {'ping': False}
    assert run(area.generate('!ping', area.app)) is None


def test_ping():
    area = make_area()
    assert run(area.generate('!ping', area.app)) == '[PING] pong'


def test_command_is_case_insensitive():
    area = make_area()
    assert run(area.generate('!PING', area.app)) == '[PING] pong'


def test_flip_seeded():
    area = make_area()
    random.seed(1)
    assert run(area.generate('!flip', area.app)) in ['[FLIP] ' + side for side in commands.FLIP_SIDES]


def test_roll_default_and_arg():
    area = make_area()
    random.seed(0)
    assert run(area.generate('!roll', area.app)).startswith('[ROLL] ')
    assert run(area.generate('!roll', area.app)).endswith('(d6)')
    assert run(area.generate('!roll 20', area.app)).endswith('(d20)')


def test_roll_clamps_out_of_range():
    area = make_area()
    assert run(area.generate('!roll 99999', area.app)).endswith('(d1000)')
    assert run(area.generate('!roll 1', area.app)).endswith('(d2)')


def test_roll_bad_arg_defaults_d6():
    area = make_area()
    assert run(area.generate('!roll abc', area.app)).endswith('(d6)')


def test_slots_jackpot_format():
    area = make_area()
    original = commands.random.choice
    commands.random.choice = lambda seq: 'seven'
    try:
        out = run(area.generate('!slots', area.app))
    finally:
        commands.random.choice = original
    assert out == f'[SLOTS] seven | seven | seven {commands.SLOTS_JACKPOT}'


def test_8ball_prefix_and_known_answer():
    area = make_area()
    out = run(area.generate('!8ball will I win', area.app))
    assert out.startswith('[8BALL] ')
    assert out[len('[8BALL] '):] in commands.EIGHTBALL_ANSWERS


def test_help_is_one_line_per_category_of_enabled_only():
    area = make_area()
    area.enabled = {'fact': False, 'dadjoke': False}
    out = run(area.generate('!help', area.app))
    assert out[0] == out[-1] and set(out[0]) == {'=', '-'}
    # !help itself is not listed, and the blackjack moves and trivia answers
    # are not either.
    assert out[1:-1] == [
        'Games: !slots !8ball [question] !roll [n] !flip !blackjack !trivia',
        'Random: !fiction !quote !fortunecookie !bible !confucius',
        'Tools: !ping !ticker [symbol | from to]',
    ]


def test_help_skips_a_category_with_nothing_enabled():
    area = make_area()
    area.enabled = {name: False for name in ('dadjoke', 'fact', 'fiction', 'quote',
                                             'fortunecookie', 'bible', 'confucius')}
    assert not any(line.startswith('Random:') for line in area._help_lines())


def test_help_button_source_matches_help_command():
    # The "Send help to chat" button writes _help_lines(); it must match !help.
    area = make_area()
    assert area._help_lines() == run(area.generate('!help', area.app))


def test_send_help_writes_all_say_lines_at_once():
    # Regression: the button must write EVERY help line to message.cfg in one
    # file so a single in-game exec sends the whole block. The bug left only the
    # last line (the closing '-----' divider) because each line overwrote the
    # previous one via core.send_to_game's per-line, exec-as-you-go writes.
    import tempfile

    area = make_area()
    area.enabled = {'fact': False, 'dadjoke': False}
    with tempfile.TemporaryDirectory() as d:
        cfg = os.path.join(d, 'message.cfg')
        area.app.exec_path = cfg
        area.app.chat_char_limit = 221
        area.app.cfg_written = False
        area.app.can_exec = False
        area.app.exec_state_cb = None
        area.app.bind_key = 'p'
        area.app.auto_press = True   # not Human Control: no pending-send tracking
        area._send_help()
        with open(cfg, encoding='utf-8') as f:
            content = f.read()

    say_lines = [ln for ln in content.splitlines() if ln.startswith('say "')]
    assert len(say_lines) == 5
    assert 'Games:' in content and '!ping' in content


def test_is_ready_requires_one_enabled():
    area = make_area()
    area.enabled = {name: False for name in area.registry}
    ok, reason = area.is_ready()
    assert ok is False and reason
    area.enabled['ping'] = True
    assert area.is_ready() == (True, None)


def test_dadjoke_success():
    area = make_area()

    async def fake_text(url, headers=None):
        return '  Why did the chicken cross the road?  '

    original = commands._http_get_text
    commands._http_get_text = fake_text
    try:
        out = run(area.generate('!dadjoke', area.app))
    finally:
        commands._http_get_text = original
    assert out == '[DADJOKE] Why did the chicken cross the road?'


def test_dadjoke_failure_returns_error():
    area = make_area()

    async def boom(url, headers=None):
        raise RuntimeError('network down')

    original = commands._http_get_text
    commands._http_get_text = boom
    try:
        out = run(area.generate('!dadjoke', area.app))
    finally:
        commands._http_get_text = original
    assert out == f"[DADJOKE] {commands.FAIL_MARK} couldn't fetch a joke right now"


def test_fact_success():
    area = make_area()

    async def fake_json(url, headers=None):
        return {'text': 'Honey never spoils.'}

    original = commands._http_get_json
    commands._http_get_json = fake_json
    try:
        out = run(area.generate('!fact', area.app))
    finally:
        commands._http_get_json = original
    assert out == '[FACT] Honey never spoils.'


def test_fact_failure_returns_error():
    area = make_area()

    async def boom(url, headers=None):
        raise RuntimeError('network down')

    original = commands._http_get_json
    commands._http_get_json = boom
    try:
        out = run(area.generate('!fact', area.app))
    finally:
        commands._http_get_json = original
    assert out == f"[FACT] {commands.FAIL_MARK} couldn't fetch a fact right now"


def test_fiction_file_lines_fit_a_reply():
    lines = commands.load_fiction()
    assert len(lines) >= 500
    assert len(set(lines)) == len(lines)
    for line in lines:
        assert line.isascii(), line
        assert len(commands.tagged('FICTION', line)) <= commands.REPLY_MAX_LEN, line


def test_fiction_skips_blank_and_comment_lines():
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, 'fiction.txt')
        with open(path, 'w', encoding='utf-8') as f:
            f.write('# header\n\nFish can fly.\n  # indented comment\n  Rocks are soft.  \n')
        assert commands.load_fiction(path) == ['Fish can fly.', 'Rocks are soft.']
        assert commands.load_fiction(os.path.join(tmp, 'missing.txt')) == []


def test_fiction_no_repeat_until_every_line_is_out():
    area = make_area()
    area.fiction = ['a', 'b', 'c']
    first = [run(area.generate('!fiction', area.app)) for _ in range(3)]
    assert sorted(first) == ['[FICTION] a', '[FICTION] b', '[FICTION] c']
    # The bag refills after the last line.
    assert run(area.generate('!fiction', area.app)) in first


def test_fiction_with_no_lines_returns_error():
    area = make_area()
    area.fiction = []
    out = run(area.generate('!fiction', area.app))
    assert out == f'[FICTION] {commands.FAIL_MARK} no fiction lines loaded'


def test_quote_success():
    area = make_area()
    urls = []

    async def fake_json(url, headers=None):
        urls.append(url)
        return {'id': 1, 'quote': 'The unexamined life is not worth living.',
                'author': 'Socrates'}

    original = commands._http_get_json
    commands._http_get_json = fake_json
    try:
        out = run(area.generate('!quote', area.app))
    finally:
        commands._http_get_json = original
    assert out == '[QUOTE] The unexamined life is not worth living. - Socrates'
    assert urls == [commands.QUOTE_URL]


def test_quote_rerolls_a_long_quote():
    area = make_area()
    replies = iter([{'quote': 'x' * commands.REPLY_MAX_LEN}, {'quote': 'Be kind.'}])

    async def fake_json(url, headers=None):
        return next(replies)

    original = commands._http_get_json
    commands._http_get_json = fake_json
    try:
        out = run(area.generate('!quote', area.app))
    finally:
        commands._http_get_json = original
    assert out == '[QUOTE] Be kind.'


def test_quote_failure_returns_error():
    area = make_area()

    async def boom(url, headers=None):
        raise RuntimeError('network down')

    original = commands._http_get_json
    commands._http_get_json = boom
    try:
        out = run(area.generate('!quote', area.app))
    finally:
        commands._http_get_json = original
    assert out == f"[QUOTE] {commands.FAIL_MARK} couldn't fetch a quote right now"


def test_fortunecookie_success():
    area = make_area()

    async def fake_json(url, headers=None):
        return {'slip': {'advice': 'Always be yourself.'}}

    original = commands._http_get_json
    commands._http_get_json = fake_json
    try:
        out = run(area.generate('!fortunecookie', area.app))
    finally:
        commands._http_get_json = original
    assert out == f'[FORTUNE] {commands.FORTUNE_MARK} Always be yourself.'


def test_fortunecookie_failure_returns_error():
    area = make_area()

    async def boom(url, headers=None):
        raise RuntimeError('network down')

    original = commands._http_get_json
    commands._http_get_json = boom
    try:
        out = run(area.generate('!fortunecookie', area.app))
    finally:
        commands._http_get_json = original
    assert out == f"[FORTUNE] {commands.FAIL_MARK} couldn't fetch advice right now"


def test_ticker_stock_success():
    area = make_area()

    urls = []

    async def fake_json(url, headers=None):
        urls.append(url)
        return {'Global Quote': {'01. symbol': 'AAPL', '05. price': '195.1200',
                                 '10. change percent': '1.2300%'}}

    original = commands._http_get_json
    commands._http_get_json = fake_json
    try:
        out = run(area.generate('!ticker AAPL', area.app))
    finally:
        commands._http_get_json = original
    assert out == f'[TICKER] AAPL $195.12 ({commands.TICKER_UP}1.2300%)'
    assert urls == [f'{commands.TICKER_URL}?function=GLOBAL_QUOTE&symbol=AAPL'
                    f'&apikey={commands.ALPHAVANTAGE_KEY}']


def test_ticker_stock_down():
    area = make_area()

    async def fake_json(url, headers=None):
        return {'Global Quote': {'05. price': '88.5000', '10. change percent': '-0.4500%'}}

    original = commands._http_get_json
    commands._http_get_json = fake_json
    try:
        out = run(area.generate('!ticker XYZ', area.app))
    finally:
        commands._http_get_json = original
    assert out == f'[TICKER] XYZ $88.50 ({commands.TICKER_DOWN}0.4500%)'


def test_ticker_currency_success():
    area = make_area()

    urls = []

    async def fake_json(url, headers=None):
        urls.append(url)
        return {'Realtime Currency Exchange Rate': {'5. Exchange Rate': '157.20000000'}}

    original = commands._http_get_json
    commands._http_get_json = fake_json
    try:
        out = run(area.generate('!ticker USD JPY', area.app))
    finally:
        commands._http_get_json = original
    assert out == '[TICKER] USD/JPY 157.2000'
    assert urls == [f'{commands.TICKER_URL}?function=CURRENCY_EXCHANGE_RATE'
                    f'&from_currency=USD&to_currency=JPY&apikey={commands.ALPHAVANTAGE_KEY}']


def test_ticker_no_arg_returns_usage():
    area = make_area()
    out = run(area.generate('!ticker', area.app))
    assert out == '[TICKER] usage !ticker <SYMBOL>  or  !ticker <FROM> <TO>'


def test_ticker_invalid_symbol_returns_no_data():
    area = make_area()

    async def fake_json(url, headers=None):
        return {'Global Quote': {}}

    original = commands._http_get_json
    commands._http_get_json = fake_json
    try:
        out = run(area.generate('!ticker ZZZZ', area.app))
    finally:
        commands._http_get_json = original
    assert out == f'[TICKER] {commands.FAIL_MARK} no data for ZZZZ'


def test_ticker_rate_limit_note():
    area = make_area()

    async def fake_json(url, headers=None):
        return {'Note': 'Our standard API rate limit is 25 requests per day.'}

    original = commands._http_get_json
    commands._http_get_json = fake_json
    try:
        out = run(area.generate('!ticker AAPL', area.app))
    finally:
        commands._http_get_json = original
    assert out == f'[TICKER] {commands.WAIT_MARK} rate limit reached, try later'


def test_ticker_rate_limit_information():
    area = make_area()

    async def fake_json(url, headers=None):
        return {'Information': 'rate limited, please try later'}

    original = commands._http_get_json
    commands._http_get_json = fake_json
    try:
        out = run(area.generate('!ticker USD JPY', area.app))
    finally:
        commands._http_get_json = original
    assert out == f'[TICKER] {commands.WAIT_MARK} rate limit reached, try later'


def test_ticker_failure_returns_error():
    area = make_area()

    async def boom(url, headers=None):
        raise RuntimeError('network down')

    original = commands._http_get_json
    commands._http_get_json = boom
    try:
        out = run(area.generate('!ticker AAPL', area.app))
    finally:
        commands._http_get_json = original
    assert out == f"[TICKER] {commands.FAIL_MARK} couldn't fetch ticker data right now"


@contextlib.contextmanager
def fake_http(name, fake):
    """Swap commands._http_get_json / _http_get_text for ``fake`` in a block."""
    original = getattr(commands, name)
    setattr(commands, name, fake)
    try:
        yield
    finally:
        setattr(commands, name, original)


def bible_verse(text, book='John', chapter=3, verse=16):
    return {'random_verse': {'book': book, 'chapter': chapter, 'verse': verse, 'text': text}}


def test_bible_success():
    area = make_area()
    urls = []

    async def fake_json(url, headers=None):
        urls.append(url)
        return bible_verse('Jesus wept.\n', book='John', chapter=11, verse=35)

    with fake_http('_http_get_json', fake_json):
        out = run(area.generate('!bible', area.app))
    assert out == '[BIBLE] Jesus wept. - John 11:35'
    assert urls == [commands.BIBLE_URL]


def test_bible_joins_the_lines_of_a_verse():
    area = make_area()

    async def fake_json(url, headers=None):
        return bible_verse('In the beginning\nGod created  the heavens.\n')

    with fake_http('_http_get_json', fake_json):
        out = run(area.generate('!bible', area.app))
    assert out == '[BIBLE] In the beginning God created the heavens. - John 3:16'


def test_bible_rerolls_a_long_verse():
    area = make_area()
    replies = iter([bible_verse('x' * commands.REPLY_MAX_LEN), bible_verse('Pray.')])

    async def fake_json(url, headers=None):
        return next(replies)

    with fake_http('_http_get_json', fake_json):
        out = run(area.generate('!bible', area.app))
    assert out == '[BIBLE] Pray. - John 3:16'


def test_bible_failure_returns_error():
    area = make_area()

    async def boom(url, headers=None):
        raise RuntimeError('network down')

    with fake_http('_http_get_json', boom):
        out = run(area.generate('!bible', area.app))
    assert out == f"[BIBLE] {commands.FAIL_MARK} couldn't fetch a verse right now"


def test_bible_empty_verse_returns_error():
    area = make_area()

    async def fake_json(url, headers=None):
        return {'random_verse': {}}

    with fake_http('_http_get_json', fake_json):
        out = run(area.generate('!bible', area.app))
    assert out == f"[BIBLE] {commands.FAIL_MARK} couldn't fetch a verse right now"


CONFUCIUS_FILE = (
    '3 entries\n'
    'Confucius says "Man who drop watch in toilet have shitty time."\n'
    'Confucius says "To prevent hangover stay drunk!" \n'
    '\n'
    'Confucius says "Man who drive like hell bound to get there!"\n'
)


def test_parse_confucius_takes_the_quoted_sayings():
    assert commands.parse_confucius(CONFUCIUS_FILE) == [
        'Man who drop watch in toilet have shitty time.',
        'To prevent hangover stay drunk!',
        'Man who drive like hell bound to get there!',
    ]


def test_confucius_fetches_the_file_once():
    area = make_area()
    urls = []

    async def fake_text(url, headers=None):
        urls.append(url)
        return CONFUCIUS_FILE

    with fake_http('_http_get_text', fake_text):
        first = run(area.generate('!confucius', area.app))
        second = run(area.generate('!confucius', area.app))
    sayings = commands.parse_confucius(CONFUCIUS_FILE)
    for out in (first, second):
        assert out.startswith('[CONFUCIUS] ')
        assert out[len('[CONFUCIUS] '):] in sayings
    assert urls == [commands.CONFUCIUS_URL]


def test_confucius_failure_returns_error_and_tries_again():
    area = make_area()
    calls = []

    async def boom(url, headers=None):
        calls.append(url)
        raise RuntimeError('network down')

    with fake_http('_http_get_text', boom):
        out = run(area.generate('!confucius', area.app))
        run(area.generate('!confucius', area.app))
    assert out == f"[CONFUCIUS] {commands.FAIL_MARK} couldn't fetch a saying right now"
    assert len(calls) == 2


def test_confucius_file_with_no_sayings_returns_error():
    area = make_area()

    async def fake_text(url, headers=None):
        return '<html>404</html>'

    with fake_http('_http_get_text', fake_text):
        out = run(area.generate('!confucius', area.app))
    assert out == f"[CONFUCIUS] {commands.FAIL_MARK} couldn't fetch a saying right now"


def test_help_includes_new_commands_when_enabled():
    area = make_area()
    text = ' '.join(run(area.generate('!help', area.app)))
    assert '!quote' in text
    assert '!fortunecookie' in text
    assert '!ticker' in text


# ---------------------------------------------------------------------- reply length

LONG = 'x' * (commands.REPLY_MAX_LEN + 1)


def fake_handler(replies):
    """A handler that gives ``replies`` in turn, and the list of its calls."""
    calls = []

    async def handler(arg):
        calls.append(arg)
        return replies[len(calls) - 1]
    return handler, calls


def test_long_reply_reruns_the_command_until_it_fits():
    area = make_area()
    area.registry['fact'].handler, calls = fake_handler([LONG, 'short', LONG])
    assert run(area.generate('!fact', area.app)) == 'short'
    assert len(calls) == 2


def test_every_try_too_long_sends_the_shortest():
    area = make_area()
    replies = [LONG + 'x' * i for i in range(commands.REPLY_TRIES)]
    area.registry['fact'].handler, calls = fake_handler(replies)
    assert run(area.generate('!fact', area.app)) == LONG
    assert len(calls) == commands.REPLY_TRIES


def test_a_list_reply_is_measured_by_its_longest_line():
    area = make_area()
    area.registry['fact'].handler, calls = fake_handler([['ok', LONG], ['ok', 'ok']])
    assert run(area.generate('!fact', area.app)) == ['ok', 'ok']


def test_a_command_with_reroll_off_runs_once():
    area = make_area()
    for name in ('blackjack', 'ticker'):
        area.registry[name].handler, calls = fake_handler([LONG])
        assert run(area.generate(f'!{name}', area.app)) == LONG
        assert len(calls) == 1


def test_a_subcommand_runs_once():
    area = make_area()
    area.registry['blackjack'].subcommands['hit'], calls = fake_handler([LONG])
    assert run(area.generate('!hit', area.app)) == LONG
    assert len(calls) == 1


# ---------------------------------------------------------------------- blackjack

def say(area, name, text, channel='all'):
    """Send ``text`` to the area as ``name``, the way the chat loop does."""
    area.app.last_speaker = name
    area.app.last_channel = channel
    return run(area.generate(text, area.app))


def test_blackjack_opens_table_for_the_speaker():
    area = make_area()
    out = say(area, 'Pat', '!blackjack', channel='team')
    assert out.startswith('Blackjack table open.')
    assert [s.name for s in area.table.seats] == ['Pat']
    assert area.table.channel == 'team'


def test_join_seats_the_speaker():
    area = make_area()
    say(area, 'Pat', '!blackjack')
    assert say(area, 'Bob', '!join').startswith('Bob joined (2 seated)')


def test_blackjack_subcommands_follow_the_blackjack_checkbox():
    area = make_area()
    area.enabled = {'blackjack': False}
    assert say(area, 'Pat', '!blackjack') is None
    assert say(area, 'Pat', '!join') is None
    assert say(area, 'Pat', '!hit') is None
    assert run(area.generate_timed(area.app)) is None


def test_subcommands_have_no_checkbox_or_help_entry():
    area = make_area()
    assert set(area.registry) >= {'blackjack'}
    assert not {'join', 'hit', 'stand', 'double', 'split'} & set(area.registry)
    text = ' '.join(area._help_lines())
    assert '!blackjack' in text
    assert not any(f'!{sub}' in text for sub in ('join', 'hit', 'stand', 'double', 'split'))


def test_generate_timed_deals_into_the_table_channel():
    area = make_area()
    say(area, 'Pat', '!blackjack', channel='team')
    assert run(area.generate_timed(area.app)) is None     # join window still open
    # Stack the shoe: a random deal can be a natural or a dealer blackjack,
    # which ends the round before the first prompt.
    area.table.shoe.cards += list(reversed(['10♠', '7♣', '4♥', '9♦']))
    area.table.deadline = time.monotonic() - 1            # window just closed
    reply, channel = run(area.generate_timed(area.app))
    assert channel == 'team'
    assert reply == ['[dealer] (7) 7♣ --.', '[Pat] >>(14) 10♠ 4♥. !hit/!stand/!double']


def test_hit_and_stand_act_for_the_speaker():
    area = make_area()
    say(area, 'Pat', '!blackjack')
    area.table.shoe.cards += list(reversed(['10♠', '7♣', '4♥', 'K♦']))
    area.table.deadline = time.monotonic() - 1
    run(area.generate_timed(area.app))
    assert say(area, 'Bob', '!stand') == 'Bob: ' + blackjack.REFUSED_MARK
    assert say(area, 'Pat', '!stand') == ['[dealer] (17) 7♣ K♦.', '[Pat] (LOSE, 14) 10♠ 4♥.']


def test_a_move_passes_the_hand_number():
    area = make_area()
    say(area, 'Pat', '!blackjack')
    area.table.shoe.cards += list(reversed(['8♠', '7♣', '8♥', '10♦', '3♦', '10♣']))
    area.table.deadline = time.monotonic() - 1
    run(area.generate_timed(area.app))
    say(area, 'Pat', '!split')
    assert say(area, 'Pat', '!hit 2') is None
    assert area.table.moves == {(0, 1): 'hit'}


def test_blackjack_settings_load_clamped():
    area = make_area()
    area._load_game('blackjack', {'turn_seconds': 2, 'join_seconds': 30, 'decks': 99})
    assert area.table.turn_seconds == commands.BJ_SECONDS_RANGE[0]
    assert area.table.join_seconds == 30
    assert area.table.decks == commands.BJ_DECKS_RANGE[1]


def test_blackjack_setting_change_is_saved():
    area = make_area()
    area._set_game('blackjack', 'turn_seconds', 20)
    area._set_game('blackjack', 'decks', None)      # emptied box: ignored
    saved = area.app.load_area_settings(area.key)['blackjack']
    assert saved == {'join_seconds': 15, 'turn_seconds': 20, 'decks': 6}


# ---------------------------------------------------------------------- trivia

TRIVIA_ITEM = {'category': 'science', 'correctAnswer': 'Saturn',
               'incorrectAnswers': ['Mars', 'Venus', 'Earth'],
               'question': {'text': 'Which planet has the most moons?'}}


def trivia_area():
    """An area whose trivia keeps the answer order: the right answer is A."""
    area = make_area()
    area.trivia.rng.shuffle = lambda items: None
    return area


def ask_trivia(area, name='Pat', channel='all', item=TRIVIA_ITEM):
    urls = []

    async def fake_json(url, headers=None):
        urls.append(url)
        return [item]

    with fake_http('_http_get_json', fake_json):
        out = say(area, name, '!trivia', channel=channel)
    return out, urls


def test_trivia_asks_a_fetched_question():
    area = trivia_area()
    out, urls = ask_trivia(area)
    assert urls == [commands.TRIVIA_URL]
    assert out == ['[TRIVIA] (Science) Which planet has the most moons?',
                   '[TRIVIA] Ⓐ Saturn  Ⓑ Mars  Ⓒ Venus  Ⓓ Earth | !a !b !c !d, 20s']


def test_trivia_during_a_question_is_refused_without_a_fetch():
    area = trivia_area()
    ask_trivia(area)
    out, urls = ask_trivia(area, name='Bob')
    assert out == trivia.BUSY
    assert urls == []


def test_trivia_failure_returns_error():
    area = trivia_area()

    async def boom(url, headers=None):
        raise RuntimeError('network down')

    with fake_http('_http_get_json', boom):
        out = say(area, 'Pat', '!trivia')
    assert out == f"[TRIVIA] {commands.FAIL_MARK} couldn't fetch a question right now"
    assert not area.trivia.asking


def test_trivia_bad_question_returns_error():
    area = trivia_area()
    out, _ = ask_trivia(area, item={'question': {'text': 'no answers'}})
    assert out == f"[TRIVIA] {commands.FAIL_MARK} couldn't fetch a question right now"


def test_a_long_trivia_question_is_asked_once():
    # A second run would only give the shorter "in progress" line.
    area = trivia_area()
    item = dict(TRIVIA_ITEM, question={'text': 'Why? ' * commands.REPLY_MAX_LEN})
    out, urls = ask_trivia(area, item=item)
    assert out == area.trivia.view
    assert len(urls) == 1


def test_answers_act_for_the_speaker():
    area = trivia_area()
    ask_trivia(area)
    assert say(area, 'Bob', '!A') is None
    assert say(area, 'Bob', '!b') == 'Bob: ' + trivia.REFUSED_MARK
    assert say(area, 'Pat', '!c') is None
    assert area.trivia.answers == {'Bob': 0, 'Pat': 2}


def test_trivia_answers_are_queued():
    area = trivia_area()
    for text in ('!trivia', '!a', '!B', '!d'):
        assert area.queues_message(text)
    area.enabled = {'trivia': False}
    assert not area.queues_message('!a')
    assert not area.queues_message('!trivia')
    assert area.queues_message('!join')       # blackjack still queues


def test_answers_need_trivia_enabled():
    area = trivia_area()
    ask_trivia(area)
    area.enabled = {'trivia': False}
    assert say(area, 'Bob', '!a') is None
    assert area.trivia.answers == {}


def test_generate_timed_gives_the_answer_in_the_trivia_channel():
    area = trivia_area()
    ask_trivia(area, channel='team')
    say(area, 'Bob', '!a')
    assert run(area.generate_timed(area.app)) is None     # clock still running
    area.trivia.deadline = time.monotonic() - 1
    reply, channel = run(area.generate_timed(area.app))
    assert channel == 'team'
    assert reply == '[TRIVIA] Answer: Ⓐ Saturn. Right: Bob.'


def test_generate_timed_runs_both_games():
    area = trivia_area()
    say(area, 'Pat', '!blackjack')                        # join window open
    ask_trivia(area)
    area.trivia.deadline = time.monotonic() - 1
    reply, _ = run(area.generate_timed(area.app))
    assert reply == '[TRIVIA] Answer: Ⓐ Saturn. Nobody got it.'
    assert area.table.state == blackjack.JOINING


def test_reply_shown_starts_the_trivia_clock():
    area = trivia_area()
    lines, _ = ask_trivia(area)
    area.reply_shown(lines, 1000.0)
    assert area.trivia.deadline == 1000.0 + area.trivia.answer_seconds


def test_trivia_settings_load_clamped_and_save():
    area = make_area()
    area._load_game('trivia', {'answer_seconds': 999})
    assert area.trivia.answer_seconds == commands.TRIVIA_SECONDS_RANGE[1]
    area._set_game('trivia', 'answer_seconds', 30)
    assert area.trivia.answer_seconds == 30
    assert area.app.load_area_settings(area.key)['trivia'] == {'answer_seconds': 30}


if __name__ == '__main__':
    import traceback

    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            try:
                fn()
                print(f'PASS {name}')
            except Exception:
                failures += 1
                print(f'FAIL {name}')
                traceback.print_exc()
    raise SystemExit(1 if failures else 0)
