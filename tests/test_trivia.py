"""Tests for the trivia game logic (areas/trivia.py).

Run with:  venv\\Scripts\\python -m pytest tests/test_trivia.py
(or plain `python tests/test_trivia.py` to run them without pytest).
"""
import os
import random
import sys

# Make the application package layout (src/) importable when run from anywhere.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from areas import trivia
from areas.trivia import Question, Trivia

PLANETS = Question('Science', 'Which planet has the most moons?',
                   'Saturn', ['Mars', 'Venus', 'Earth'])


def unshuffled(answer_seconds=20):
    """A game whose shuffle keeps the order: the right answer is A."""
    game = Trivia(answer_seconds=answer_seconds)
    game.rng.shuffle = lambda items: None
    return game


def test_ask_shows_the_question_and_four_marked_answers():
    game = unshuffled()
    lines = game.ask(PLANETS, 'all', 0.0)
    assert lines == [
        '[TRIVIA] (Science) Which planet has the most moons?',
        '[TRIVIA] Ⓐ Saturn  Ⓑ Mars  Ⓒ Venus  Ⓓ Earth | !a !b !c !d, 20s',
    ]
    assert game.asking


def test_ask_shuffles_the_answers():
    game = Trivia(rng=random.Random(7))
    game.ask(PLANETS, 'all', 0.0)
    assert sorted(game.choices) == ['Earth', 'Mars', 'Saturn', 'Venus']
    seen = {tuple(Trivia(rng=random.Random(seed)).ask(PLANETS, 'all', 0.0))
            for seed in range(20)}
    assert len(seen) > 1


def test_ask_during_a_question_is_refused():
    game = unshuffled()
    game.ask(PLANETS, 'all', 0.0)
    assert game.ask(PLANETS, 'all', 1.0) == trivia.BUSY


def test_an_answer_locks_with_no_reply():
    game = unshuffled()
    game.ask(PLANETS, 'all', 0.0)
    assert game.answer('bob', 'a', 1.0) is None
    assert game.answers == {'bob': 0}


def test_a_second_answer_is_refused():
    game = unshuffled()
    game.ask(PLANETS, 'all', 0.0)
    game.answer('bob', 'b', 1.0)
    assert game.answer('bob', 'a', 2.0) == 'bob: ' + trivia.REFUSED_MARK
    assert game.answers == {'bob': 1}


def test_an_answer_with_no_question_is_refused():
    assert Trivia().answer('bob', 'a', 0.0) == 'bob: ' + trivia.REFUSED_MARK


def test_tick_waits_for_the_clock():
    game = unshuffled()
    game.ask(PLANETS, 'all', 0.0)
    assert game.tick(19.9) is None
    assert game.asking


def test_tick_gives_the_answer_and_who_was_right():
    game = unshuffled()
    game.ask(PLANETS, 'all', 0.0)
    game.answer('schwagger', 'a', 1.0)
    game.answer('pat', 'c', 2.0)
    game.answer('bob', 'a', 3.0)
    assert game.tick(20.0) == '[TRIVIA] Answer: Ⓐ Saturn. Right: schwagger, bob.'
    assert not game.asking


def test_tick_says_when_nobody_got_it():
    game = unshuffled()
    game.ask(PLANETS, 'all', 0.0)
    game.answer('pat', 'd', 1.0)
    assert game.tick(20.0) == '[TRIVIA] Answer: Ⓐ Saturn. Nobody got it.'


def test_the_game_is_ready_again_after_the_answer():
    game = unshuffled()
    game.ask(PLANETS, 'team', 0.0)
    game.tick(20.0)
    assert game.answer('bob', 'a', 21.0) == 'bob: ' + trivia.REFUSED_MARK
    assert game.ask(PLANETS, 'all', 22.0) != trivia.BUSY
    assert game.channel == 'all'


def test_shown_starts_the_clock_when_the_question_reaches_chat():
    game = unshuffled()
    lines = game.ask(PLANETS, 'all', 0.0)
    assert game.shown(['something else'], 2.0) is None
    assert game.shown(lines, 3.0) == 3.0           # the lag, in seconds
    assert game.tick(22.9) is None
    assert game.tick(23.0).startswith('[TRIVIA] Answer:')


def test_shown_only_counts_once():
    game = unshuffled()
    lines = game.ask(PLANETS, 'all', 0.0)
    game.shown(lines, 3.0)
    assert game.shown(lines, 10.0) is None
    assert game.deadline == 23.0


def test_a_stale_question_closes_with_no_message():
    game = unshuffled()
    game.ask(PLANETS, 'all', 0.0)
    assert game.tick(20.0 + trivia.STALE_SECONDS + 1) is None
    assert not game.asking


def test_question_from_the_trivia_api():
    item = {'category': 'food_and_drink', 'correctAnswer': 'Chicken Machboos',
            'incorrectAnswers': ['Ambuyat', 'Pepperpot', 'Pho'],
            'question': {'text': 'Which of these dishes is most associated with Bahrain?'}}
    assert Question.from_trivia_api(item) == Question(
        'Food and drink', 'Which of these dishes is most associated with Bahrain?',
        'Chicken Machboos', ['Ambuyat', 'Pepperpot', 'Pho'])


def test_question_from_the_trivia_api_rejects_a_bad_item():
    for item in ({}, {'correctAnswer': 'x', 'incorrectAnswers': ['y'],
                      'question': {'text': 'q'}}):
        try:
            Question.from_trivia_api(item)
        except ValueError:
            continue
        raise AssertionError(f'accepted {item!r}')


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
