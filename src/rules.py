"""Command labels: let a bot's own reply tell the app what to do.

An area's reply may carry command labels written ``([LABEL])``. A user-editable
rule list -- Settings > Command Rules, persisted with the app settings -- points
each label at an action:

  * ``silent``  say nothing at all this turn (the whole reply is dropped)
  * ``say``     the label is replaced, in place, with a fixed piece of text

Labels with no matching rule are left in the reply exactly as written, so a typo
shows up in chat instead of quietly changing what the bot does.

The chat loop calls ``apply_rules`` between ``area.generate(...)`` and
``send_to_game(...)``, so every area gets the same treatment. This module is
deliberately pure -- it imports no widgets and knows nothing about AppState --
which is what lets core.py call it and the tests exercise it without a GUI.
"""
import re

# ``([LABEL])``, tolerating whitespace just inside the brackets. The character
# class excludes further brackets and parens so a malformed marker can only fail
# to match -- it can never swallow the rest of the line.
LABEL_PATTERN = re.compile(r'\(\[\s*([^\[\]()]*?)\s*\]\)')

ACTION_SILENT = 'silent'
ACTION_SAY = 'say'

# action -> the label shown in the Settings dropdown. Adding an action later
# (e.g. an HTTP call) is an entry here plus a branch in _apply_to_line.
ACTIONS = {
    ACTION_SILENT: 'Stay silent',
    ACTION_SAY: 'Say this',
}

SNIPPET_HEADER = ('You may use these command labels in your replies. Write them '
                  'exactly as shown, brackets included:')


def normalize_label(text) -> str:
    """Reduce whatever was typed to the bare label name, uppercased.

    ``TAUNT``, ``[TAUNT]`` and ``([TAUNT])`` all normalize to ``TAUNT``, so a
    rule matches however much of the wrapper the user typed into the box.
    Uppercase because matching is case-insensitive and the stored form is what
    the prompt snippet advertises to the bot.

    Stripping loops until the value settles: one pass would leave the inner
    spaces of ``( [ taunt ] )`` stranded between the brackets it hasn't reached.
    """
    label = (text or '').strip()
    previous = None
    while label != previous:
        previous = label
        label = label.strip('()[]').strip()
    return label.upper()


def index_rules(rules) -> dict:
    """Map normalized label -> rule for fast lookup while substituting.

    Junk entries (non-dicts, blank labels) are skipped rather than raising, so a
    hand-edited settings file can't break the chat loop. On duplicates the first
    rule wins, matching the order shown in Settings.
    """
    index = {}
    for rule in rules or []:
        if not isinstance(rule, dict):
            continue
        label = normalize_label(rule.get('label'))
        if label and label not in index:
            index[label] = rule
    return index


def apply_rules(reply, rules):
    """Run ``reply`` through the rules; return what should actually be sent.

    ``reply`` is whatever an area returned: a single string, or a list of strings
    (each its own chat line). Returns the same shape with known labels
    substituted, or ``None`` to stay silent -- which the chat loop's existing
    "no reply" path already handles, so nothing is typed and no cooldown starts.
    """
    if not reply or not rules:
        return reply

    index = index_rules(rules)
    if not index:
        return reply

    lines = [reply] if isinstance(reply, str) else list(reply)
    kept = []
    for line in lines:
        result = _apply_to_line(line, index)
        if result is None:
            return None      # a silent label anywhere silences the whole reply
        if result:
            kept.append(result)

    if not kept:
        return None          # everything substituted away to nothing
    return kept[0] if isinstance(reply, str) else kept


def _apply_to_line(line: str, index: dict):
    """Substitute the known labels in one line, or return None to go silent.

    Two passes on purpose: the silent check runs over every label in the line
    before any text is rewritten, so ``([TAUNT]) ([SILENT])`` silences the bot
    regardless of which label the model wrote first.
    """
    matched = [index[label] for label in
               (normalize_label(m) for m in LABEL_PATTERN.findall(line))
               if label in index]
    if not matched:
        return line
    if any(rule.get('action') == ACTION_SILENT for rule in matched):
        return None

    def substitute(match):
        rule = index.get(normalize_label(match.group(1)))
        if rule is None:
            return match.group(0)          # unknown label: leave it as written
        return (rule.get('text') or '').strip()

    # Collapse the whitespace a removed label leaves behind, so a rule with no
    # text deletes its label cleanly instead of leaving "nice  shot".
    return re.sub(r'\s{2,}', ' ', LABEL_PATTERN.sub(substitute, line)).strip()


def describe_rule(rule) -> str:
    """One short phrase for what a rule does, shown beside it in Settings.

    Reads to a person scanning the list ("stay silent", 'say "get good"'), where
    ``prompt_snippet`` writes for the bot -- same data, different audience.
    """
    if not isinstance(rule, dict):
        return ''
    if rule.get('action') == ACTION_SILENT:
        return 'stay silent'
    text = (rule.get('text') or '').strip()
    return f'say "{text}"' if text else 'remove the label'


def prompt_snippet(rules) -> str:
    """Build the copyable block that teaches a bot which labels it may emit.

    Rendered in Settings > Command Rules for pasting into an area's system
    prompt (or a Character.AI persona, where there's no system prompt field to
    append to automatically). Empty when there are no usable rules.
    """
    lines = []
    for rule in rules or []:
        if not isinstance(rule, dict):
            continue
        label = normalize_label(rule.get('label'))
        if not label:
            continue
        if rule.get('action') == ACTION_SILENT:
            desc = 'say nothing at all this turn'
        else:
            text = (rule.get('text') or '').strip()
            desc = f'is replaced with "{text}"' if text else 'is removed from your reply'
        lines.append(f'([{label}]) - {desc}')

    if not lines:
        return ''
    return SNIPPET_HEADER + '\n' + '\n'.join(lines)
