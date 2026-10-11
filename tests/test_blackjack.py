"""Tests for the blackjack table (areas/blackjack.py).

The shoe is stacked so every draw is known, and ``now`` is passed in, so the
join window and the round clock run without sleeping.

Run with:  venv\\Scripts\\python -m pytest tests/test_blackjack.py
"""
import os
import random
import sys

# Make the application package layout (src/) importable when run from anywhere.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from areas import blackjack
from areas.blackjack import Table, hand_total, is_blackjack, soft_text, wrap

REFUSAL = "{}: You can't do that, dummy."


def stack(table, *cards):
    """Make the shoe deal ``cards`` in this order (draws pop from the end)."""
    table.shoe.cards = table.shoe.cards + list(reversed(cards))


def table_with(*names, turn=15, join=15):
    """A table in its join window with ``names`` seated, opened at t=0."""
    table = Table(turn_seconds=turn, join_seconds=join, rng=random.Random(1))
    table.open(names[0], 'all', 0)
    for name in names[1:]:
        table.join(name, 1)
    return table


# ---------------------------------------------------------------------- totals

def test_hand_total_counts_one_ace_as_eleven_when_it_fits():
    assert hand_total(['A♠', 'K♥']) == 21
    assert hand_total(['A♠', '6♥']) == 17
    assert hand_total(['A♠', '6♥', 'K♦']) == 17
    assert hand_total(['A♠', 'A♥', '9♦']) == 21
    assert hand_total(['K♠', 'Q♥', '5♦']) == 25


def test_soft_text_shows_both_values_while_an_ace_can_count_11():
    assert soft_text(['A♠', '4♣']) == '5/15'
    assert soft_text(['A♠', 'A♦']) == '2/12'
    assert soft_text(['A♠', '4♣', 'K♦']) == '15'
    assert soft_text(['K♠', '8♦']) == '18'


def test_blackjack_needs_two_cards():
    assert is_blackjack(['A♠', 'Q♥'])
    assert not is_blackjack(['7♠', '7♥', '7♦'])


def test_six_deck_shoe_by_default():
    assert len(Table().shoe.cards) == 6 * 52


def test_wrap_breaks_only_between_entries():
    entries = [f'[player{i:02d}] (18) K♦ 8♦.' for i in range(12)]
    lines = wrap(entries, '!hit/!stand')
    assert len(lines) > 1
    assert all(len(line) <= blackjack.LINE_LIMIT for line in lines)
    assert ' '.join(lines) == ' '.join(entries + ['!hit/!stand'])
    assert lines[-1].endswith('!hit/!stand')


# ---------------------------------------------------------------------- joining

def test_open_announces_join_window_and_turn_timer():
    table = Table(turn_seconds=20, join_seconds=10)
    assert table.open('Pat', 'team', 0) == \
        'Blackjack table open. !join in 10s. 20s per turn, then auto-stand.'
    assert table.state == blackjack.JOINING
    assert table.channel == 'team'


def test_join_reports_seat_count_and_time_left():
    table = table_with('Pat')
    assert table.join('Bob', 5.5) == 'Bob joined (2 seated). Dealing in 10s.'


def test_join_twice_is_silent():
    table = table_with('Pat', 'Bob')
    assert table.join('Bob', 2) is None
    assert len(table.seats) == 2


def test_blackjack_during_join_window_joins():
    table = table_with('Pat')
    assert table.open('Bob', 'all', 3).startswith('Bob joined (2 seated)')


def test_join_without_table_says_how_to_start():
    assert Table().join('Bob', 0) == 'No blackjack table open. Type !blackjack to start one.'


def test_no_deal_before_join_window_closes():
    table = table_with('Pat')
    assert table.tick(14.9) is None
    assert table.state == blackjack.JOINING


# ---------------------------------------------------------------------- rounds

def test_deal_shows_the_table_with_the_hole_card_hidden():
    table = table_with('Pat', 'Bob')
    stack(table, 'K♠', '5♦', '7♣', '4♥', '9♠', '10♦')
    assert table.tick(15) == [
        '[dealer] (7) 7♣ --.',
        '[Pat] >>(14) K♠ 4♥. [Bob] >>(14) 5♦ 9♠. !hit/!stand/!double',
    ]
    assert table.state == blackjack.PLAYING
    assert table.deadline == 30


def test_soft_hands_show_both_totals():
    table = table_with('Pat')
    stack(table, 'A♠', 'A♣', '4♣', '6♦')
    assert table.tick(15) == [
        '[dealer] (1/11) A♣ --.',
        '[Pat] >>(5/15) A♠ 4♣. !hit/!stand/!double',
    ]


def test_moves_are_silent_until_every_hand_has_one():
    table = table_with('Pat', 'Bob')
    stack(table, 'K♠', '5♦', '7♣', '4♥', '9♠', '10♦')
    table.tick(15)
    assert table.stand('Pat', 16) is None
    assert table.stand('Bob', 17) == [
        '[dealer] (17) 7♣ 10♦.',
        '[Pat] (LOSE, 14) K♠ 4♥. [Bob] (LOSE, 14) 5♦ 9♠.',
    ]


def test_the_first_move_counts():
    table = table_with('Pat', 'Bob')
    stack(table, 'K♠', '5♦', '7♣', '4♥', '9♠', '10♦')
    table.tick(15)
    table.stand('Pat', 16)
    assert table.hit('Pat', 17) == REFUSAL.format('Pat')
    assert table.moves == {(0, 0): blackjack.STAND}


def test_strangers_and_moves_without_a_round_are_refused():
    table = table_with('Pat')
    assert table.split('Pat', 1) == REFUSAL.format('Pat')      # still joining
    stack(table, 'K♠', '7♣', '4♥', '10♦')
    table.tick(15)
    assert table.double('Stranger', 16) == REFUSAL.format('Stranger')
    assert Table().hit('Pat', 0) == REFUSAL.format('Pat')


def test_a_new_round_shows_the_table_and_resets_the_clock():
    table = table_with('Pat', 'Bob')
    stack(table, 'K♠', '5♦', '7♣', '2♥', '9♠', '10♦', '3♣')
    table.tick(15)
    table.hit('Pat', 20)
    assert table.stand('Bob', 21) == [
        '[dealer] (7) 7♣ --.',
        '[Pat] >>(15) K♠ 2♥ 3♣. [Bob] (14) 5♦ 9♠. !hit/!stand',
    ]
    assert table.deadline == 36


def test_cards_go_out_in_seat_order_not_move_order():
    table = table_with('Pat', 'Bob')
    stack(table, 'K♠', '5♦', '7♣', '2♥', '9♠', '10♦', '3♣', '4♦')
    table.tick(15)
    table.hit('Bob', 16)            # Bob moves first ...
    lines = table.hit('Pat', 17)    # ... but Pat sits first and draws first
    assert lines[1] == '[Pat] >>(15) K♠ 2♥ 3♣. [Bob] >>(18) 5♦ 9♠ 4♦. !hit/!stand'


def test_bust_closes_the_hand():
    table = table_with('Pat', 'Bob')
    stack(table, 'K♠', '5♦', '7♣', '6♥', '9♠', '10♦', 'Q♣', '2♣')
    table.tick(15)
    table.hit('Pat', 16)
    assert table.hit('Bob', 17) == [
        '[dealer] (7) 7♣ --.',
        '[Pat] (BUST, 26) K♠ 6♥ Q♣. [Bob] >>(16) 5♦ 9♠ 2♣. !hit/!stand',
    ]


def test_hit_to_21_closes_the_hand():
    table = table_with('Pat', 'Bob')
    stack(table, 'K♠', '5♦', '7♣', '6♥', '9♠', '10♦', '5♣', '2♣')
    table.tick(15)
    table.hit('Pat', 16)
    assert table.hit('Bob', 17)[1] == \
        '[Pat] (21) K♠ 6♥ 5♣. [Bob] >>(16) 5♦ 9♠ 2♣. !hit/!stand'


def test_round_timeout_stands_every_hand_without_a_move():
    table = table_with('Pat', 'Bob')
    stack(table, 'K♠', '5♦', '7♣', '4♥', '9♠', '10♦', '3♣')
    table.tick(15)
    table.hit('Pat', 16)
    assert table.tick(29) is None
    assert table.tick(30) == [
        '[dealer] (7) 7♣ --.',
        '[Pat] >>(17) K♠ 4♥ 3♣. [Bob] (14) 5♦ 9♠. !hit/!stand',
    ]
    assert table.deadline == 45


def test_round_clock_starts_when_the_view_shows_in_chat():
    table = table_with('Pat', 'Bob')
    stack(table, 'K♠', '5♦', '7♣', '4♥', '9♠', '10♦')
    view = table.tick(15)
    assert table.shown(view, 18) == 3       # 3s from the deal to the chat
    table.stand('Pat', 19)
    assert table.tick(30) is None           # 15s from the deal: Bob still has time
    assert table.tick(33) is not None       # 15s from the view in chat


def test_only_the_waiting_view_starts_the_clock():
    table = table_with('Pat', 'Bob')
    stack(table, 'K♠', '5♦', '7♣', '4♥', '9♠', '10♦')
    view = table.tick(15)
    assert table.shown("Bob: You can't do that, dummy.", 16) is None
    assert table.shown(list(view), 17) == 2
    assert table.shown(view, 19) is None    # the clock started once
    assert table.deadline == 32


def test_last_move_plays_the_dealer_and_shows_the_results():
    table = table_with('Pat', 'Bob', 'Al')
    # Pat 20, Bob 14 (hits to bust), Al 17; dealer 7 + 10 = 17, stands.
    stack(table, 'K♠', '5♦', '10♥', '7♣', 'Q♥', '9♠', '7♦', '10♦', 'K♣')
    table.tick(15)
    table.stand('Pat', 16)
    table.hit('Bob', 17)
    assert table.stand('Al', 18) == [
        '[dealer] (17) 7♣ 10♦.',
        '[Pat] (WIN, 20) K♠ Q♥. [Bob] (BUST, 24) 5♦ 9♠ K♣. [Al] (PUSH, 17) 10♥ 7♦.',
    ]
    assert table.state == blackjack.IDLE


def test_dealer_draws_to_17_and_can_bust():
    table = table_with('Pat')
    stack(table, '10♠', '6♣', '8♥', '10♦', 'K♣')
    table.tick(15)
    assert table.stand('Pat', 16) == [
        '[dealer] (BUST, 26) 6♣ 10♦ K♣.',
        '[Pat] (WIN, 18) 10♠ 8♥.',
    ]


def test_dealer_stands_on_soft_17():
    table = table_with('Pat')
    stack(table, '10♠', 'A♣', '8♥', '6♦', 'K♣')
    table.tick(15)
    assert table.stand('Pat', 16) == ['[dealer] (17) A♣ 6♦.', '[Pat] (WIN, 18) 10♠ 8♥.']


def test_dealer_does_not_draw_when_every_hand_is_bust():
    table = table_with('Pat')
    stack(table, '10♠', '6♣', '8♥', '5♦', 'K♣')
    table.tick(15)
    assert table.hit('Pat', 16) == ['[dealer] (11) 6♣ 5♦.', '[Pat] (BUST, 28) 10♠ 8♥ K♣.']


def test_natural_shows_blackjack_and_needs_no_move():
    table = table_with('Pat', 'Bob')
    stack(table, 'A♠', '5♦', '7♣', 'K♥', '9♠', '10♦')
    assert table.tick(15) == [
        '[dealer] (7) 7♣ --.',
        '[Pat] (BLACKJACK, 21) A♠ K♥. [Bob] >>(14) 5♦ 9♠. !hit/!stand/!double',
    ]
    assert table.stand('Pat', 16) == REFUSAL.format('Pat')
    assert table.stand('Bob', 16) == [
        '[dealer] (17) 7♣ 10♦.',
        '[Pat] (BLACKJACK, 21) A♠ K♥. [Bob] (LOSE, 14) 5♦ 9♠.',
    ]


def test_dealer_peek_ends_round_at_the_deal():
    table = table_with('Pat', 'Bob')
    # Dealer shows an ace with a king underneath. Bob's natural pushes.
    stack(table, '10♠', 'A♦', 'A♣', '9♥', 'Q♠', 'K♦')
    assert table.tick(15) == [
        '[dealer] (BLACKJACK, 21) A♣ K♦.',
        '[Pat] (LOSE, 19) 10♠ 9♥. [Bob] (PUSH, 21) A♦ Q♠.',
    ]
    assert table.state == blackjack.IDLE


def test_a_big_table_wraps_the_players_line():
    names = [f'player_with_a_long_name_{i}' for i in range(10)]
    table = table_with(*names)
    lines = table.tick(15)
    assert lines[0].startswith('[dealer] (')
    assert len(lines) > 2
    assert all(len(line) <= blackjack.LINE_LIMIT for line in lines)


def test_round_in_progress_turns_away_newcomers():
    table = table_with('Pat')
    stack(table, 'K♠', '7♣', '4♥', '10♦')
    table.tick(15)
    message = 'Blackjack round in progress. Type !blackjack after it ends.'
    assert table.open('Bob', 'all', 16) == message
    assert table.join('Bob', 16) == message


def test_stale_table_closes_without_a_word():
    table = table_with('Pat')
    assert table.tick(15 + blackjack.STALE_SECONDS + 1) is None
    assert table.state == blackjack.IDLE


# ---------------------------------------------------------------------- shoe

def test_shoe_reshuffles_past_the_cut_card():
    table = table_with('Pat')
    table.shoe.cards = table.shoe.cards[:50]     # well under a quarter of 312
    table.tick(15)
    assert len(table.shoe.cards) == 6 * 52 - 4


def test_deck_count_change_applies_at_next_deal():
    table = table_with('Pat')
    table.decks = 2
    table.tick(15)
    assert table.shoe.decks == 2
    assert len(table.shoe.cards) == 2 * 52 - 4


# ---------------------------------------------------------------------- double

def test_double_draws_one_card_and_marks_the_hand():
    table = table_with('Pat', 'Bob')
    # Pat 5+6 doubles onto a K. Bob hits a 2. Dealer 7 + 10 = 17.
    stack(table, '5♠', '9♣', '7♣', '6♦', '9♠', '10♦', 'K♣', '2♣')
    table.tick(15)
    table.double('Pat', 16)
    assert table.hit('Bob', 17) == [
        '[dealer] (7) 7♣ --.',
        '[Pat] (x2, 21) 5♠ 6♦ K♣. [Bob] >>(20) 9♣ 9♠ 2♣. !hit/!stand',
    ]
    assert table.stand('Bob', 18) == [
        '[dealer] (17) 7♣ 10♦.',
        '[Pat] (WIN x2, 21) 5♠ 6♦ K♣. [Bob] (WIN, 20) 9♣ 9♠ 2♣.',
    ]


def test_double_needs_two_cards():
    table = table_with('Pat')
    stack(table, '2♠', '7♣', '3♦', '10♦', '4♣')
    table.tick(15)
    table.hit('Pat', 16)
    assert table.double('Pat', 17) == REFUSAL.format('Pat')


def test_double_bust_shows_bust_x2():
    table = table_with('Pat')
    stack(table, '9♠', '7♣', '3♦', '10♦', 'K♣')
    table.tick(15)
    assert table.double('Pat', 16) == ['[dealer] (17) 7♣ 10♦.', '[Pat] (BUST x2, 22) 9♠ 3♦ K♣.']


# ---------------------------------------------------------------------- split

def test_split_numbers_the_hands_and_marks_both():
    table = table_with('Pat')
    stack(table, '8♠', '7♣', '8♥', '10♦', '3♦', '10♣')
    table.tick(15)
    assert table.split('Pat', 16) == [
        '[dealer] (7) 7♣ --.',
        '[Pat] #1 >>(11) 8♠ 3♦ | #2 >>(18) 8♥ 10♣. !hit/!stand/!double [#]',
    ]
    assert table.deadline == 31


def test_every_split_hand_moves_each_round():
    table = table_with('Pat')
    stack(table, '8♠', '7♣', '8♥', '10♦', '3♦', '10♣', 'K♠')
    table.tick(15)
    table.split('Pat', 16)
    assert table.stand('Pat', 17) is None          # hand #1; #2 still needs a move
    assert table.hit('Pat', 18) == [               # hand #2
        '[dealer] (17) 7♣ 10♦.',
        '[Pat] (LOSE, 11) 8♠ 3♦ | (BUST, 28) 8♥ 10♣ K♠.',
    ]


def test_a_hand_number_picks_the_hand():
    table = table_with('Pat')
    stack(table, '8♠', '7♣', '8♥', '10♦', '3♦', '10♣', 'K♠')
    table.tick(15)
    table.split('Pat', 16)
    assert table.hit('Pat', 17, '2') is None
    assert table.moves == {(0, 1): blackjack.HIT}
    table.stand('Pat', 18)                         # no number: the first open hand, #1
    assert table.moves == {}                       # the round resolved


def test_a_bad_hand_number_is_refused():
    table = table_with('Pat')
    stack(table, '8♠', '7♣', '8♥', '10♦', '3♦', '10♣')
    table.tick(15)
    table.split('Pat', 16)
    assert table.hit('Pat', 17, '3') == REFUSAL.format('Pat')
    assert table.hit('Pat', 17, 'x') == REFUSAL.format('Pat')
    table.stand('Pat', 17, '#1')
    assert table.hit('Pat', 18, '1') == REFUSAL.format('Pat')    # #1 already moved


def test_split_results_list_each_hand():
    table = table_with('Pat', 'Bob')
    # Pat splits 8s into 8+3 (hits a K: 21) and 8+10 (18). Dealer 7 + 10 = 17.
    stack(table, '8♠', '10♥', '7♣', '8♥', '7♠', '10♦', '3♦', '10♣', 'K♠')
    table.tick(15)
    table.split('Pat', 16)
    assert table.stand('Bob', 17) == [
        '[dealer] (7) 7♣ --.',
        '[Pat] #1 >>(11) 8♠ 3♦ | #2 >>(18) 8♥ 10♣. [Bob] (17) 10♥ 7♠. !hit/!stand/!double [#]',
    ]
    table.hit('Pat', 18, '1')
    assert table.stand('Pat', 19, '2') == [
        '[dealer] (17) 7♣ 10♦.',
        '[Pat] (WIN, 21) 8♠ 3♦ K♠ | (WIN, 18) 8♥ 10♣. [Bob] (PUSH, 17) 10♥ 7♠.',
    ]


def test_split_has_no_limit():
    table = table_with('Pat')
    stack(table, '8♠', '7♣', '8♥', '10♦', '8♦', '2♣', '3♣', '4♣')
    table.tick(15)
    table.split('Pat', 16)              # 8+8 | 8+2
    table.split('Pat', 17, '1')         # 8+3 | 8+4 | 8+2 (stands)
    lines = table.stand('Pat', 17, '2')
    assert [h.cards for h in table.seats[0].hands] == [
        ['8♠', '3♣'], ['8♦', '4♣'], ['8♥', '2♣']]
    assert lines[1].startswith('[Pat] #1 >>(11) 8♠ 3♣ | #2 >>(12) 8♦ 4♣ | #3 (10) 8♥ 2♣.')


def test_split_any_two_ten_value_cards():
    table = table_with('Pat')
    stack(table, 'K♠', '7♣', '10♥', '10♦', '9♦', '9♣')
    table.tick(15)
    assert table.split('Pat', 16)[1].startswith('[Pat] #1 >>(19) K♠ 9♦ | #2 >>(19) 10♥ 9♣.')


def test_split_needs_a_pair():
    table = table_with('Pat')
    stack(table, 'K♠', '7♣', '9♥', '10♦')
    table.tick(15)
    assert table.split('Pat', 16) == REFUSAL.format('Pat')


def test_21_on_a_split_hand_is_not_blackjack():
    table = table_with('Pat')
    # 10s split into 10+A (21, closes by itself) and 10+7.
    stack(table, '10♠', '7♣', '10♥', 'K♦', 'A♦', '7♠')
    table.tick(15)
    assert table.split('Pat', 16) == [
        '[dealer] (7) 7♣ --.',
        '[Pat] #1 (21) 10♠ A♦ | #2 >>(17) 10♥ 7♠. !hit/!stand/!double [#]',
    ]
    assert table.stand('Pat', 17) == [
        '[dealer] (17) 7♣ K♦.',
        '[Pat] (WIN, 21) 10♠ A♦ | (PUSH, 17) 10♥ 7♠.',
    ]


def test_split_aces_get_one_card_each():
    table = table_with('Pat', 'Bob')
    stack(table, 'A♠', '9♣', '7♣', 'A♥', '9♠', '10♦', 'K♦', '5♣', '2♦')
    table.tick(15)
    table.split('Pat', 16)
    assert table.hit('Bob', 17) == [
        '[dealer] (7) 7♣ --.',
        '[Pat] #1 (21) A♠ K♦ | #2 (16) A♥ 5♣. [Bob] >>(20) 9♣ 9♠ 2♦. !hit/!stand [#]',
    ]


def test_split_aces_may_split_again_but_not_hit():
    table = table_with('Pat')
    stack(table, 'A♠', '7♣', 'A♥', '10♦', 'A♦', '5♣')
    table.tick(15)
    assert table.split('Pat', 16) == [
        '[dealer] (7) 7♣ --.',
        '[Pat] #1 >>(2/12) A♠ A♦ | #2 (16) A♥ 5♣. !stand/!split [#]',
    ]
    assert table.hit('Pat', 17) == REFUSAL.format('Pat')
    assert table.double('Pat', 17) == REFUSAL.format('Pat')


def test_timeout_stands_only_the_split_hands_without_a_move():
    table = table_with('Pat')
    stack(table, '8♠', '7♣', '8♥', '10♦', '3♦', '10♣', '5♠')
    table.tick(15)
    table.split('Pat', 16)
    table.hit('Pat', 20, '1')
    assert table.tick(31)[1] == '[Pat] #1 >>(16) 8♠ 3♦ 5♠ | #2 (18) 8♥ 10♣. !hit/!stand [#]'
    assert table.deadline == 46
