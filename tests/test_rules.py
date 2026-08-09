"""Tests for the command-label rules engine: matching, substitution, silencing.

Run with:  venv\\Scripts\\python -m pytest tests/test_rules.py
(or plain `python tests/test_rules.py` to run them without pytest).
"""
import os
import sys

# Make the application package layout (src/) importable when run from anywhere.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import rules

SILENT = {'label': 'SILENT', 'action': 'silent', 'text': ''}
TAUNT = {'label': 'TAUNT', 'action': 'say', 'text': 'get good'}


# ---------------------------------------------------------------- normalization

def test_normalize_strips_every_wrapper_form():
    assert rules.normalize_label('TAUNT') == 'TAUNT'
    assert rules.normalize_label('[TAUNT]') == 'TAUNT'
    assert rules.normalize_label('([TAUNT])') == 'TAUNT'
    assert rules.normalize_label('  ( [ taunt ] )  ') == 'TAUNT'


def test_normalize_handles_empty_and_none():
    assert rules.normalize_label('') == ''
    assert rules.normalize_label(None) == ''
    assert rules.normalize_label('   ') == ''
    assert rules.normalize_label('([])') == ''


def test_index_skips_blank_labels_and_keeps_first_duplicate():
    first = {'label': 'DUP', 'action': 'say', 'text': 'one'}
    second = {'label': 'dup', 'action': 'say', 'text': 'two'}
    index = rules.index_rules([{'label': '  '}, first, second, 'not a dict'])
    assert list(index) == ['DUP']
    assert index['DUP'] is first


# ---------------------------------------------------------------- substitution

def test_bare_label_becomes_the_rule_text():
    assert rules.apply_rules('([TAUNT])', [TAUNT]) == 'get good'


def test_label_is_substituted_in_place():
    assert rules.apply_rules('nice try ([TAUNT]) loser', [TAUNT]) == 'nice try get good loser'


def test_multiple_labels_all_substitute():
    other = {'label': 'GG', 'action': 'say', 'text': 'gg'}
    assert rules.apply_rules('([GG]) and ([TAUNT])', [TAUNT, other]) == 'gg and get good'


def test_matching_is_case_insensitive():
    assert rules.apply_rules('([taunt])', [TAUNT]) == 'get good'
    assert rules.apply_rules('([TaUnT])', [TAUNT]) == 'get good'


def test_rule_label_may_be_written_with_brackets():
    written_out = {'label': '([TAUNT])', 'action': 'say', 'text': 'get good'}
    assert rules.apply_rules('([TAUNT])', [written_out]) == 'get good'


def test_inner_whitespace_in_the_label_still_matches():
    assert rules.apply_rules('([ TAUNT ])', [TAUNT]) == 'get good'


def test_blank_say_text_removes_the_label_without_double_spaces():
    blank = {'label': 'META', 'action': 'say', 'text': ''}
    assert rules.apply_rules('nice ([META]) shot', [blank]) == 'nice shot'


def test_reply_that_is_only_a_blank_label_goes_silent():
    blank = {'label': 'META', 'action': 'say', 'text': ''}
    assert rules.apply_rules('([META])', [blank]) is None


# ---------------------------------------------------------------- silencing

def test_silent_label_drops_the_whole_reply():
    assert rules.apply_rules('whatever ([SILENT]) man', [SILENT]) is None


def test_silent_wins_over_another_matching_rule():
    assert rules.apply_rules('([TAUNT]) ([SILENT])', [TAUNT, SILENT]) is None


def test_silent_on_any_line_drops_every_line():
    reply = ['first line', 'second ([SILENT])', 'third line']
    assert rules.apply_rules(reply, [SILENT]) is None


# ---------------------------------------------------------------- passthrough

def test_unknown_label_is_sent_as_is():
    assert rules.apply_rules('what ([MYSTERY]) now', [TAUNT]) == 'what ([MYSTERY]) now'


def test_unknown_label_alongside_a_known_one_survives():
    assert rules.apply_rules('([MYSTERY]) ([TAUNT])', [TAUNT]) == '([MYSTERY]) get good'


def test_reply_without_labels_is_untouched():
    text = 'just a normal   reply'
    assert rules.apply_rules(text, [TAUNT, SILENT]) == text


def test_malformed_markers_are_not_labels():
    for text in ('([FOO)', '[FOO]', '(FOO)', '([FOO]', 'FOO])'):
        assert rules.apply_rules(text, [{'label': 'FOO', 'action': 'silent', 'text': ''}]) == text


def test_empty_rule_list_is_a_no_op():
    assert rules.apply_rules('([SILENT]) ([TAUNT])', []) == '([SILENT]) ([TAUNT])'
    assert rules.apply_rules('([SILENT])', None) == '([SILENT])'


def test_empty_reply_passes_through():
    assert rules.apply_rules('', [TAUNT]) == ''
    assert rules.apply_rules(None, [TAUNT]) is None


def test_malformed_rules_are_ignored():
    junk = ['nonsense', 42, None, {'action': 'say', 'text': 'no label'}]
    assert rules.apply_rules('([TAUNT])', junk) == '([TAUNT])'


# ---------------------------------------------------------------- list replies

def test_list_reply_substitutes_each_line():
    reply = ['=-=-=', 'say ([TAUNT])', '=-=-=']
    assert rules.apply_rules(reply, [TAUNT]) == ['=-=-=', 'say get good', '=-=-=']


def test_list_reply_drops_lines_emptied_by_substitution():
    blank = {'label': 'META', 'action': 'say', 'text': ''}
    assert rules.apply_rules(['keep me', '([META])'], [blank]) == ['keep me']


def test_list_reply_returns_none_when_every_line_empties():
    blank = {'label': 'META', 'action': 'say', 'text': ''}
    assert rules.apply_rules(['([META])', '([META])'], [blank]) is None


# ---------------------------------------------------------------- prompt snippet

def test_snippet_is_empty_without_rules():
    assert rules.prompt_snippet([]) == ''
    assert rules.prompt_snippet(None) == ''
    assert rules.prompt_snippet([{'label': '  '}]) == ''


def test_snippet_describes_each_action():
    snippet = rules.prompt_snippet([SILENT, TAUNT])
    assert '([SILENT])' in snippet and '([TAUNT])' in snippet
    assert 'get good' in snippet
    # One header line plus one line per rule.
    assert len(snippet.splitlines()) == len(rules.SNIPPET_HEADER.splitlines()) + 2


def test_snippet_uses_the_normalized_label():
    snippet = rules.prompt_snippet([{'label': '([shout])', 'action': 'silent', 'text': ''}])
    assert '([SHOUT])' in snippet


# ---------------------------------------------------------------- descriptions

def test_describe_covers_each_action():
    assert rules.describe_rule(SILENT) == 'stay silent'
    assert rules.describe_rule(TAUNT) == 'say "get good"'
    assert rules.describe_rule({'label': 'M', 'action': 'say', 'text': ''}) == 'remove the label'


def test_describe_ignores_junk():
    assert rules.describe_rule(None) == ''
    assert rules.describe_rule('nonsense') == ''


# ---------------------------------------------------------------- actions table

def test_actions_table_covers_the_supported_actions():
    assert set(rules.ACTIONS) == {rules.ACTION_SILENT, rules.ACTION_SAY}


def test_unknown_action_is_treated_as_say():
    # A rule carrying an action this version doesn't know must not silence the
    # bot: it substitutes its text, the conservative fallback.
    future = {'label': 'HTTP', 'action': 'http', 'text': 'placeholder'}
    assert rules.apply_rules('x ([HTTP]) y', [future]) == 'x placeholder y'


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
