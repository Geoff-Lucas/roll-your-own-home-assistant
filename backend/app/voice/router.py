"""Deciding what a spoken command means, and doing it.

Rule-based on purpose: for the everyday commands (timers, the time, the
weather) matching is instant, free and predictable. Anything the rules don't
recognize is where a language-model fallback will plug in later — see the
"Voice assistant" section of PLAN.md.
"""

from typing import Callable, Optional

from .core import Context, Reply
from .skills import clock, timers, weather
from .text import normalize, numbers_to_digits

Skill = Callable[[str, Context], Optional[Reply]]

# Order matters where phrasings overlap: "what time is my alarm" belongs to
# timers, not the clock, so timers are asked first.
SKILLS: tuple[Skill, ...] = (timers.handle, clock.handle, weather.handle)

NOT_UNDERSTOOD = "Sorry, I don't know how to help with that yet."


def route(utterance: str, ctx: Context) -> Reply:
    text = numbers_to_digits(normalize(utterance))
    if not text:
        return Reply("I didn't catch that.", understood=False)
    for skill in SKILLS:
        reply = skill(text, ctx)
        if reply is not None:
            return reply
    return Reply(NOT_UNDERSTOOD, understood=False)
