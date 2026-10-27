"""Trivia for the C2 command bot: one question, four answers, one clock.

Pure game logic, no NiceGUI and no chat I/O, like blackjack.py. The area
fetches the question and hands it to ``ask()``. Every call takes ``now`` (a
``time.monotonic()`` value) instead of reading the clock, so a test can step
past the answer time without sleeping.

A game runs in two states:
  * idle   -- no question. ``!trivia`` asks one.
  * asking -- the question is open. Each player locks one answer with ``!a``
              to ``!d``, with no reply. A second answer is refused. When the
              clock runs out, ``tick()`` gives the right answer and who chose
              it, and the game goes back to idle.

The question and its answers go out as two chat lines::

    [TRIVIA] (Science) Which planet has the most moons?
    [TRIVIA] Ⓐ Mars  Ⓑ Saturn  Ⓒ Venus  Ⓓ Earth | !a !b !c !d, 20s

The answer clock starts when those lines show in chat (``shown()``), not when
the game builds them, like the blackjack round clock. Then::

    [TRIVIA] Answer: Ⓑ Saturn. Right: bob, schwagger.
"""
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional

TAG = '[TRIVIA]'
LETTERS = ('a', 'b', 'c', 'd')
MARKS = ('Ⓐ', 'Ⓑ', 'Ⓒ', 'Ⓓ')       # circled letters show in CS2 chat

DEFAULT_ANSWER_SECONDS = 20

# A question whose clock is this many seconds overdue closes with no message.
# This happens when the bot was off or another tab was open.
STALE_SECONDS = 120

REFUSED_MARK = '✘'
BUSY = 'Trivia question in progress. Type !trivia after it ends.'


@dataclass
class Question:
    category: str
    text: str
    correct: str
    incorrect: List[str] = field(default_factory=list)

    @classmethod
    def from_trivia_api(cls, item) -> 'Question':
        """One item of a The Trivia API (v2) response. ValueError when the
        item is not a question with one right and three wrong answers."""
        try:
            text = (item['question']['text'] or '').strip()
            correct = (item['correctAnswer'] or '').strip()
            incorrect = [(a or '').strip() for a in item['incorrectAnswers']]
        except (KeyError, TypeError) as e:
            raise ValueError(f'not a trivia question: {e}') from e
        if not text or not correct or len(incorrect) != 3 or not all(incorrect):
            raise ValueError('a trivia question needs a text, 1 right and 3 wrong answers')
        # 'food_and_drink' -> 'Food and drink'
        category = (item.get('category') or '').replace('_', ' ').strip().capitalize()
        return cls(category, text, correct, incorrect)


class Trivia:
    def __init__(self, answer_seconds=DEFAULT_ANSWER_SECONDS, rng=None):
        self.answer_seconds = answer_seconds
        self.rng = rng or random.Random()
        self._reset()

    def _reset(self) -> None:
        self.question: Optional[Question] = None
        self.choices: List[str] = []          # the four answers, in A-D order
        self.answers: Dict[str, int] = {}     # name -> choice index, in answer order
        self.channel = 'all'
        self.deadline: Optional[float] = None
        self.view: Optional[List[str]] = None  # the lines that start the clock

    @property
    def asking(self) -> bool:
        return self.question is not None

    def ask(self, question: Question, channel: str, now: float):
        """!trivia: open the question. Returns its two chat lines."""
        if self.asking:
            return BUSY
        choices = [question.correct, *question.incorrect]
        self.rng.shuffle(choices)
        self.question = question
        self.choices = choices
        self.channel = channel
        self.deadline = now + self.answer_seconds
        heading = f'({question.category}) ' if question.category else ''
        options = '  '.join(f'{mark} {choice}' for mark, choice in zip(MARKS, choices))
        moves = ' '.join(f'!{letter}' for letter in LETTERS)
        self.view = [f'{TAG} {heading}{question.text}',
                     f'{TAG} {options} | {moves}, {self.answer_seconds}s']
        return self.view

    def answer(self, name: str, letter: str, now: float):
        """!a to !d: lock this player's answer, with no reply."""
        if not self.asking or name in self.answers or letter not in LETTERS:
            return f'{name}: {REFUSED_MARK}'
        self.answers[name] = LETTERS.index(letter)
        return None

    def tick(self, now: float):
        """The right answer and who chose it, once the clock runs out."""
        if not self.asking or now < self.deadline:
            return None
        if now - self.deadline > STALE_SECONDS:
            self._reset()
            return None
        right_index = self.choices.index(self.question.correct)
        right = [name for name, index in self.answers.items() if index == right_index]
        result = f'Right: {", ".join(right)}.' if right else 'Nobody got it.'
        line = f'{TAG} Answer: {MARKS[right_index]} {self.question.correct}. {result}'
        self._reset()
        return line

    def shown(self, reply, now: float) -> Optional[float]:
        """A reply reached chat. When it is the open question, the answer
        clock starts again from ``now``. Returns the seconds the question took
        to show, or None for any other reply."""
        if self.view is None or reply != self.view:
            return None
        self.view = None
        lag = now - (self.deadline - self.answer_seconds)
        self.deadline = now + self.answer_seconds
        return lag
