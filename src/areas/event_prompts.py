"""Turn a GSI TiltEvent into a one-line instruction for an AI brain.

Shared by the Tilt Bot area (when its taunt/clapback source is an AI provider)
and by the AI areas themselves (when they opt into reacting to game events).
Kept separate from system/gsi.py -- gsi owns event *detection*; this owns the
human-language *phrasing* -- and free of any provider/UI import so both sides
can use it without an import cycle.
"""

# Per-kind instruction templates. {kills}/{hp} are filled from event.data. Each
# asks for one short, in-character all-chat brag aimed at the enemy team.
EVENT_PROMPTS = {
    'MULTI_KILL': "I just got a {kills}-kill in this Counter-Strike 2 round. "
                  "Brag about it to the enemy team in all chat, one short line.",
    'MVP': "I just earned the round MVP in Counter-Strike 2. Gloat about it to "
           "the enemy in all chat, one short line.",
    'ROUND_WIN': "My team just won the round in Counter-Strike 2. Talk trash to "
                 "the enemy in all chat, one short line.",
    'LOW_HP_SURVIVAL': "I just clutched and survived a Counter-Strike 2 round on "
                       "{hp} HP. Talk trash about it in all chat, one short line.",
    'MATCH_POINT': "My team just reached match point in Counter-Strike 2. Rub it "
                   "in to the enemy in all chat, one short line.",
    'MATCH_WIN': "My team just won the Counter-Strike 2 match. Gloat to the enemy "
                 "in all chat, one short line.",
}

# Used for unknown kinds or when a template's data token is missing, so a new or
# data-less event never crashes a reply -- it just produces a generic brag.
FALLBACK_PROMPT = ("I just had a great moment in this Counter-Strike 2 round. "
                   "Talk trash to the enemy in all chat, one short line.")


def event_to_prompt(event) -> str:
    """Return a one-line AI instruction for a system.gsi.TiltEvent.

    Unknown kinds and missing {tokens} degrade to FALLBACK_PROMPT rather than
    raising.
    """
    template = EVENT_PROMPTS.get(event.kind, FALLBACK_PROMPT)
    try:
        return template.format(**(event.data or {}))
    except (KeyError, IndexError, ValueError):
        return FALLBACK_PROMPT
