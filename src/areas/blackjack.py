"""Blackjack for the C2 command bot: one table, one shoe, one round clock.

Pure game logic, no NiceGUI and no chat I/O, so the tests can drive it
directly. Every call takes ``now`` (a ``time.monotonic()`` value) instead of
reading the clock, which lets a test step through a join window or a round
timeout without sleeping.

A table runs in three states:
  * idle     -- no table. ``!blackjack`` opens one and seats the opener.
  * joining  -- the join window. ``!join`` seats more players; when the window
                closes, ``tick()`` deals.
  * playing  -- rounds. Everyone moves at the same time: each hand still in
                play takes one ``!hit`` / ``!stand`` / ``!double`` /
                ``!split``. Moves get no reply. When every open hand has a
                move, or the round clock runs out (a hand with no move
                stands), the moves apply in seat order and the next table view
                goes out. When no hand is left in play, the dealer plays and
                the results end the round.

The round clock starts when the table view shows in chat (``shown()``), not
when the table builds it. The keypresses and the console.log lag would
otherwise take time from the players. A view that never shows keeps the
clock from the build.

The table view: the dealer on one chat line, then every player, with ``>>`` on
each hand that needs a move and the moves at the end::

    [dealer] (4) 4♥ --.
    [schwagger] >>(18) K♦ 8♦. [bob] >>(5/15) A♠ 4♣. !hit/!stand/!double

After a split the hands carry numbers, and a move can name one: ``!hit 2``.
A move with no number takes the first hand that has no move yet::

    [schwagger] #1 >>(11) 8♠ 3♦ | #2 >>(18) 8♥ 10♣. !hit/!stand/!double [#]

The results use the same two parts::

    [dealer] (BUST, 22) 4♥ 8♣ K♠.
    [schwagger] (WIN, 18) K♦ 8♦. [bob] (WIN, 15) A♠ 4♣ K♦.

Casino rules: a shoe of several decks with a cut card, the dealer stands on
all 17s, and the dealer peeks for blackjack when the up card is an ace or a
ten. Double on any two cards, also after a split. Split any two cards of the
same value, with no limit. Split aces get one card each and no hit, but may
split again. 21 on a split hand is not a blackjack. No insurance, no
surrender.

A move that is not allowed gets a "you can't do that" line. Replies follow the
area contract: a str (one chat line), a list of str (one chat line each), or
None to stay silent.
"""
import math
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

SUITS = ('♠', '♥', '♦', '♣')
RANKS = ('A', '2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K')

DEFAULT_DECKS = 6
DEFAULT_TURN_SECONDS = 15
DEFAULT_JOIN_SECONDS = 15

# Cut card: a new round reshuffles the shoe when less than this share is left.
CUT_FRACTION = 0.25

# A deadline this far in the past means nobody drove the table for a while (the
# bot was off, or another tab was open). Replaying that round would surprise
# everyone, so the table closes without a word instead.
STALE_SECONDS = 120

# Marks each hand that needs a move in the players line.
CURRENT_MARK = '>>'

# The players line wraps between entries past this many characters, below the
# 221-character chat limit, so the chat chunker never cuts a name or a card.
LINE_LIMIT = 200

IDLE, JOINING, PLAYING = 'idle', 'joining', 'playing'
HIT, STAND, DOUBLE, SPLIT = 'hit', 'stand', 'double', 'split'


def card_value(card: str) -> int:
    """Hard value of one card: aces count 1 here (hand_total upgrades one)."""
    rank = card[:-1]
    if rank == 'A':
        return 1
    if rank in ('J', 'Q', 'K'):
        return 10
    return int(rank)


def hand_total(cards) -> int:
    """Best total for a hand: one ace counts 11 when that does not bust."""
    total = sum(card_value(c) for c in cards)
    if any(c[:-1] == 'A' for c in cards) and total + 10 <= 21:
        total += 10
    return total


def soft_text(cards) -> str:
    """The total of a hand still in play: both values while an ace can count
    11, e.g. '5/15', else one value."""
    hard = sum(card_value(c) for c in cards)
    if any(c[:-1] == 'A' for c in cards) and hard + 10 <= 21:
        return f'{hard}/{hard + 10}'
    return str(hard)


def is_blackjack(cards) -> bool:
    """21 on two cards. (Hand.natural also rules out a split hand.)"""
    return len(cards) == 2 and hand_total(cards) == 21


def show(cards) -> str:
    """Cards as chat text, e.g. 'K♠ 10♥'."""
    return ' '.join(cards)


def wrap(entries, tail='') -> List[str]:
    """Join entries with spaces into chat lines of at most LINE_LIMIT
    characters, breaking only between entries. ``tail`` goes at the end."""
    lines, current = [], ''
    for part in list(entries) + ([tail] if tail else []):
        if current and len(current) + 1 + len(part) > LINE_LIMIT:
            lines.append(current)
            current = part
        else:
            current = f'{current} {part}' if current else part
    if current:
        lines.append(current)
    return lines


class Shoe:
    """Several shuffled decks, drawn from the end."""

    def __init__(self, decks: int, rng: random.Random):
        self.decks = decks
        self.rng = rng
        self.cards: List[str] = []
        self.shuffle()

    def shuffle(self) -> None:
        self.cards = [r + s for r in RANKS for s in SUITS] * self.decks
        self.rng.shuffle(self.cards)

    def past_cut_card(self) -> bool:
        return len(self.cards) < CUT_FRACTION * 52 * self.decks

    def draw(self) -> str:
        # A huge table can run a short shoe dry mid-round: start a fresh one.
        if not self.cards:
            self.shuffle()
        return self.cards.pop()


@dataclass
class Hand:
    cards: List[str] = field(default_factory=list)
    split: bool = False     # came from a split: 21 on two cards is not a blackjack
    aces: bool = False      # split aces: no hit and no double, only a resplit
    doubled: bool = False
    done: bool = False      # played out: stood, bust, doubled, or nothing to decide

    @property
    def total(self) -> int:
        return hand_total(self.cards)

    @property
    def natural(self) -> bool:
        return not self.split and is_blackjack(self.cards)

    def can_hit(self) -> bool:
        return not self.aces

    def can_double(self) -> bool:
        return len(self.cards) == 2 and not self.aces

    def can_split(self) -> bool:
        return len(self.cards) == 2 and card_value(self.cards[0]) == card_value(self.cards[1])

    def allows(self, move: str) -> bool:
        return {HIT: self.can_hit, STAND: lambda: True, DOUBLE: self.can_double,
                SPLIT: self.can_split}[move]()

    def needs_decision(self) -> bool:
        """False for a hand with nothing left to choose: a natural, 21 or more,
        or split aces that cannot split again."""
        if self.natural or self.total >= 21:
            return False
        return self.can_hit() or self.can_split()


@dataclass
class Seat:
    name: str
    hands: List[Hand] = field(default_factory=lambda: [Hand()])


class Table:
    def __init__(self, decks=DEFAULT_DECKS, turn_seconds=DEFAULT_TURN_SECONDS,
                 join_seconds=DEFAULT_JOIN_SECONDS, rng: Optional[random.Random] = None):
        self.rng = rng or random.Random()
        self.decks = decks
        self.turn_seconds = turn_seconds
        self.join_seconds = join_seconds
        self.shoe = Shoe(decks, self.rng)
        self._reset()

    def _reset(self) -> None:
        self.state = IDLE
        self.seats: List[Seat] = []
        self.dealer: List[str] = []
        # This round's moves: (seat index, hand index) -> HIT/STAND/DOUBLE/SPLIT.
        self.moves: Dict[Tuple[int, int], str] = {}
        self.deadline: Optional[float] = None
        self.channel = 'all'    # where !blackjack was typed; timer lines go there
        # The table view that is not in chat yet: shown() starts its clock.
        self.view: Optional[List[str]] = None

    def seated(self, name: str) -> bool:
        return any(s.name == name for s in self.seats)

    # ------------------------------------------------------------------ joining

    def open(self, name: str, channel: str, now: float):
        """!blackjack: open a table, or join the one in its join window."""
        if self.state == JOINING:
            return self.join(name, now)
        if self.state == PLAYING:
            return 'Blackjack round in progress. Type !blackjack after it ends.'
        self.state = JOINING
        self.channel = channel
        self.seats = [Seat(name)]
        self.deadline = now + self.join_seconds
        return (f'Blackjack table open. !join in {self.join_seconds}s. '
                f'{self.turn_seconds}s per turn, then auto-stand.')

    def join(self, name: str, now: float):
        """!join: take a seat during the join window."""
        if self.state == IDLE:
            return 'No blackjack table open. Type !blackjack to start one.'
        if self.state == PLAYING:
            return 'Blackjack round in progress. Type !blackjack after it ends.'
        if self.seated(name):
            return None
        self.seats.append(Seat(name))
        left = max(1, math.ceil(self.deadline - now))
        return f'{name} joined ({len(self.seats)} seated). Dealing in {left}s.'

    # ------------------------------------------------------------------ moves

    def hit(self, name: str, now: float, hand: str = ''):
        """!hit [#]: one more card on the hand."""
        return self._move(name, HIT, hand, now)

    def stand(self, name: str, now: float, hand: str = ''):
        """!stand [#]: the hand takes no more cards."""
        return self._move(name, STAND, hand, now)

    def double(self, name: str, now: float, hand: str = ''):
        """!double [#]: exactly one more card on a two-card hand, then it stands."""
        return self._move(name, DOUBLE, hand, now)

    def split(self, name: str, now: float, hand: str = ''):
        """!split [#]: turn a pair into two hands, one new card on each."""
        return self._move(name, SPLIT, hand, now)

    def tick(self, now: float):
        """Timer work that is due: the deal, or the end of a round."""
        if self.state == IDLE or self.deadline is None or now < self.deadline:
            return None
        if now - self.deadline > STALE_SECONDS:
            self._reset()
            return None
        if self.state == JOINING:
            return self._deal(now)
        return self._resolve(now)

    def shown(self, reply, now: float) -> Optional[float]:
        """A reply reached chat. When it is the waiting table view, the round
        clock starts again from ``now``. Returns the seconds the view took to
        show, or None for any other reply."""
        if self.view is None or reply != self.view:
            return None
        self.view = None
        lag = now - (self.deadline - self.turn_seconds)
        self.deadline = now + self.turn_seconds
        return lag

    def _move(self, name: str, move: str, hand_arg: str, now: float):
        """Record one move for this round. Silent until the round is complete;
        the last move in shows the next table view."""
        target = self._target(name, hand_arg)
        if target is None:
            return self._refuse(name)
        seat_index, hand_index = target
        if not self.seats[seat_index].hands[hand_index].allows(move):
            return self._refuse(name)
        self.moves[target] = move
        if all(key in self.moves for key in self._open_keys()):
            return self._resolve(now)
        return None

    def _target(self, name: str, hand_arg: str) -> Optional[Tuple[int, int]]:
        """The (seat, hand) a move is for: the hand number given, or the
        first open hand with no move yet. None when there is no such hand."""
        if self.state != PLAYING:
            return None
        seat_index = next((i for i, s in enumerate(self.seats) if s.name == name), None)
        if seat_index is None:
            return None
        waiting = [key for key in self._open_keys()
                   if key[0] == seat_index and key not in self.moves]
        number = (hand_arg or '').strip().lstrip('#')
        if not number:
            return waiting[0] if waiting else None
        try:
            key = (seat_index, int(number) - 1)
        except ValueError:
            return None
        return key if key in waiting else None

    @staticmethod
    def _refuse(name: str) -> str:
        return f"{name}: You can't do that, dummy."

    # ------------------------------------------------------------------ round flow

    def _open_keys(self) -> List[Tuple[int, int]]:
        """(seat index, hand index) of every hand still in play."""
        return [(si, hi) for si, seat in enumerate(self.seats)
                for hi, hand in enumerate(seat.hands) if not hand.done]

    def _deal(self, now: float) -> List[str]:
        if self.shoe.decks != self.decks:
            self.shoe = Shoe(self.decks, self.rng)
        elif self.shoe.past_cut_card():
            self.shoe.shuffle()

        self.dealer = []
        for seat in self.seats:
            seat.hands = [Hand()]
        # Casino order: one card to each player then the dealer, twice.
        for _ in range(2):
            for seat in self.seats:
                seat.hands[0].cards.append(self.shoe.draw())
            self.dealer.append(self.shoe.draw())

        self.state = PLAYING
        # The dealer peeks under an ace or a ten. A dealer blackjack ends the
        # round before anyone acts.
        if card_value(self.dealer[0]) in (1, 10) and is_blackjack(self.dealer):
            return self._finish()
        return self._next_round(now)

    def _resolve(self, now: float) -> List[str]:
        """Apply this round's moves in seat order. An open hand with no move
        stands. Hand numbers stay the ones the players saw: a split only
        changes them for the next round."""
        for seat_index, seat in enumerate(self.seats):
            hands = []
            for hand_index, hand in enumerate(seat.hands):
                move = None if hand.done else self.moves.get((seat_index, hand_index), STAND)
                if move == SPLIT:
                    aces = card_value(hand.cards[0]) == 1
                    hands.extend(Hand([card, self.shoe.draw()], split=True, aces=aces)
                                 for card in hand.cards)
                    continue
                if move in (HIT, DOUBLE):
                    hand.cards.append(self.shoe.draw())
                if move in (STAND, DOUBLE):
                    hand.done = True
                hand.doubled = hand.doubled or move == DOUBLE
                hands.append(hand)
            seat.hands = hands
        return self._next_round(now)

    def _next_round(self, now: float) -> List[str]:
        """Close every hand with nothing to decide (bust, 21, a natural, split
        aces), then show the table for the next round, or the results when no
        hand is left in play."""
        self.moves = {}
        for seat in self.seats:
            for hand in seat.hands:
                if not hand.done and not hand.needs_decision():
                    hand.done = True
        if not self._open_keys():
            return self._finish()
        self.deadline = now + self.turn_seconds
        self.view = self._view()
        return self.view

    # ------------------------------------------------------------------ chat lines

    def _view(self) -> List[str]:
        """The table view: the dealer line, then every player with >> on each
        hand that needs a move, and the moves any of them can use."""
        up = self.dealer[0]
        open_hands = [self.seats[si].hands[hi] for si, hi in self._open_keys()]
        moves = [cmd for cmd, check in (('!hit', Hand.can_hit), ('!stand', None),
                                         ('!double', Hand.can_double), ('!split', Hand.can_split))
                 if check is None or any(check(h) for h in open_hands)]
        tail = '/'.join(moves)
        if any(len(s.hands) > 1 for s in self.seats):
            tail += ' [#]'
        entries = [self._entry(seat) for seat in self.seats]
        return [f'[dealer] ({soft_text([up])}) {up} --.'] + wrap(entries, tail)

    def _entry(self, seat: Seat) -> str:
        numbered = len(seat.hands) > 1
        parts = []
        for number, hand in enumerate(seat.hands, 1):
            part = ('' if hand.done else CURRENT_MARK) + \
                f'({self._play_label(hand)}) {show(hand.cards)}'
            parts.append(f'#{number} {part}' if numbered else part)
        return f'[{seat.name}] ' + ' | '.join(parts) + '.'

    @staticmethod
    def _play_label(hand: Hand) -> str:
        """A hand's label during play: a tag once it is decided, else its total."""
        x2 = ' x2' if hand.doubled else ''
        if hand.total > 21:
            return f'BUST{x2}, {hand.total}'
        if hand.natural:
            return 'BLACKJACK, 21'
        if hand.doubled:
            return f'x2, {hand.total}'
        return str(hand.total) if hand.done else soft_text(hand.cards)

    def _finish(self) -> List[str]:
        """Play out the dealer, build the results, and close the table."""
        # The dealer only draws when some hand still needs beating.
        live = [h for s in self.seats for h in s.hands if h.total <= 21 and not h.natural]
        if live and not is_blackjack(self.dealer):
            while hand_total(self.dealer) < 17:
                self.dealer.append(self.shoe.draw())

        dealer_total = hand_total(self.dealer)
        dealer_bj = is_blackjack(self.dealer)
        if dealer_bj:
            label = 'BLACKJACK, 21'
        elif dealer_total > 21:
            label = f'BUST, {dealer_total}'
        else:
            label = str(dealer_total)
        entries = [f'[{s.name}] ' + ' | '.join(
                       f'({self._outcome(h, dealer_total, dealer_bj)}) {show(h.cards)}'
                       for h in s.hands) + '.'
                   for s in self.seats]
        lines = [f'[dealer] ({label}) {show(self.dealer)}.'] + wrap(entries)
        self._reset()
        return lines

    @staticmethod
    def _outcome(hand: Hand, dealer_total: int, dealer_bj: bool) -> str:
        """One hand's result label, e.g. 'WIN, 20', 'BUST, 25', 'WIN x2, 19'."""
        total = hand.total
        x2 = ' x2' if hand.doubled else ''
        if total > 21:
            return f'BUST{x2}, {total}'
        if hand.natural:
            return 'PUSH, 21' if dealer_bj else 'BLACKJACK, 21'
        if dealer_bj or (dealer_total <= 21 and total < dealer_total):
            result = 'LOSE'
        elif dealer_total > 21 or total > dealer_total:
            result = 'WIN'
        else:
            result = 'PUSH'
        return f'{result}{x2}, {total}'
