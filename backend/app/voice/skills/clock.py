"""Voice commands for the time and date."""

import re
from typing import Optional

from ..core import Context, Reply
from ..text import ordinal, spoken_clock

_TIME = re.compile(
    r"\bwhat'?s? (is )?the (current )?time\b|\bwhat time is it\b|\bcurrent time\b|\btell me the time\b|\btime is it\b"
)
_DATE = re.compile(
    r"\bwhat'?s? (is )?(the |today'?s )?(date|day)\b|\bwhat day (is it|is today)\b|\btoday'?s date\b"
    r"|\bwhat is today\b|\bwhat'?s today\b|\bday of the week\b"
)


def handle(t: str, ctx: Context) -> Optional[Reply]:
    now = ctx.now_local
    if _TIME.search(t):
        return Reply(f"It's {spoken_clock(now.hour, now.minute)}.")
    if _DATE.search(t):
        return Reply(f"Today is {now.strftime('%A, %B')} {ordinal(now.day)}.")
    return None
