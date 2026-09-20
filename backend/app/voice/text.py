"""Turning what someone said into numbers, durations and clock times.

Speech-to-text output is untidy: "Set a timer for ten minutes." one moment,
"set a 10 minute timer" the next, "an hour and a half" or "seven thirty" after
that. Everything here works on that untidiness, and is pure (no clock, no I/O
except where a `now` is passed in) so it can be tested exhaustively.
"""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

_UNITS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
}  # fmt: skip
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}


def normalize(text: str) -> str:
    """Lowercase, and strip punctuation except what carries meaning in numbers
    and times (digits, ':' in 7:30, '.' in 2.5, apostrophes in o'clock)."""
    t = text.lower().replace("’", "'")
    t = re.sub(r"\b([ap])\.\s?m\b\.?", r"\1m", t)  # "a.m." / "p.m." -> "am" / "pm"
    t = t.replace("-", " ")
    t = re.sub(r"[^a-z0-9:.' ]", " ", t)
    t = re.sub(r"(?<!\d)\.|\.(?!\d)", " ", t)  # a dot that isn't a decimal point
    return re.sub(r"\s+", " ", t).strip()


def numbers_to_digits(text: str) -> str:
    """"twenty five" -> "25". Numbers that don't add up stay separate, as a
    spoken time needs: "seven fifteen" -> "7 15"."""
    tokens = text.split()
    out: list[str] = []
    i = 0
    while i < len(tokens):
        if tokens[i] in _UNITS or tokens[i] in _TENS:
            value, i = _read_number(tokens, i)
            out.append(str(value))
        else:
            out.append(tokens[i])
            i += 1
    return " ".join(out)


def _read_number(tokens: list[str], i: int) -> tuple[int, int]:
    value = 0
    last = None  # what kind of word we just consumed: unit | teen | tens | hundred | ones
    while i < len(tokens):
        tok = tokens[i]
        if tok in _TENS and last in (None, "hundred"):
            value += _TENS[tok]
            last = "tens"
        elif tok in _UNITS:
            n = _UNITS[tok]
            if n >= 10 and last in (None, "hundred"):
                value += n
                last = "teen"
            elif n < 10 and last is None:
                value += n
                last = "unit"
            elif 0 < n < 10 and last in ("tens", "hundred"):
                value += n
                last = "ones"
            else:
                break
        elif tok == "hundred" and last == "unit":
            value *= 100
            last = "hundred"
        else:
            break
        i += 1
    return value, i


# --- durations --------------------------------------------------------------

_UNIT = r"(hours?|hrs?|minutes?|mins?|seconds?|secs?)"
_DURATION = re.compile(rf"(\d+(?:\.\d+)?) ?{_UNIT}\b")


def _prepare_duration(text: str) -> str:
    t = numbers_to_digits(normalize(text))
    # Fractions of an hour first: they contain "an hour", which is rewritten below.
    t = re.sub(r"\b(\d+) quarters? of an hour\b", lambda m: f"{int(m.group(1)) * 0.25} hour", t)
    t = re.sub(r"\b(?:a )?quarter (?:of an |of a )?hour\b", "0.25 hour", t)
    t = re.sub(r"\b(?:half an hour|an? half hour|half hour)\b", "0.5 hour", t)
    t = re.sub(r"\ban? (hour|minute|second)\b", r"1 \1", t)
    # "2 and a half hours" / "1 and a half minutes"
    t = re.sub(rf"\b(\d+) and a half {_UNIT}\b", lambda m: f"{int(m.group(1)) + 0.5:g} {m.group(2)}", t)
    # "1 hour and a half" / "2 minutes and a half"
    t = re.sub(
        rf"\b(\d+(?:\.\d+)?) {_UNIT} and a half\b",
        lambda m: f"{float(m.group(1)) + 0.5:g} {m.group(2)}",
        t,
    )
    return t


def parse_duration(text: str) -> Optional[int]:
    """Total seconds for phrases like "10 minutes", "an hour and a half",
    "1 hour 20 minutes", "ninety seconds"; None if there's no duration in it."""
    total = 0.0
    found = False
    for amount, unit in _DURATION.findall(_prepare_duration(text)):
        found = True
        value = float(amount)
        total += value * (3600 if unit.startswith("h") else 60 if unit.startswith("m") else 1)
    return round(total) if found and total > 0 else None


def strip_duration(text: str) -> str:
    """The text with any duration phrase cut out (used to find what's left over,
    e.g. the name of a timer: "10 minute pasta timer" -> "set a pasta timer")."""
    t = _DURATION.sub(" ", _prepare_duration(text))
    return re.sub(r"\s+", " ", t).strip()


def spoken_duration(seconds: float) -> str:
    total = max(0, round(seconds))
    if total == 0:
        return "no time"
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    parts = []
    if hours:
        parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
    if minutes:
        parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
    if secs and not hours:  # "1 hour and 30 minutes", not "... and 12 seconds"
        parts.append(f"{secs} second{'s' if secs != 1 else ''}")
    return " and ".join(parts)


# --- clock times ------------------------------------------------------------


@dataclass(frozen=True)
class ClockTime:
    hour: int  # 1-12 when spoken on a 12-hour clock, or 0-23 when clearly 24-hour
    minute: int
    meridiem: Optional[str]  # "am", "pm", or None when not said


# What a bare number must NOT be followed by to count as a time: a duration unit
# ("for 10 minutes"), an am/pm that a stricter pattern already rejected ("15 pm"),
# or the start of minutes that don't exist ("7:75").
_LATER_UNITS = r"(?!:\d|\.\d| ?(?:am|pm|hours?|hrs?|minutes?|mins?|seconds?|secs?)\b)"


def parse_clock_time(text: str) -> Optional[ClockTime]:
    t = numbers_to_digits(normalize(text))
    # Speech-to-text writes "six thirty" as "6.30" as often as "6:30" (found the
    # hard way, from the real recognizer). Read a two-digit "decimal" as a time
    # unless it is really a length of time ("1.25 hours").
    t = re.sub(r"\b(\d{1,2})\.(\d{2})\b(?! ?(?:hours?|hrs?|minutes?|mins?|seconds?|secs?))", r"\1:\2", t)

    if re.search(r"\bnoon\b", t):
        return ClockTime(12, 0, "pm")
    if re.search(r"\bmidnight\b", t):
        return ClockTime(12, 0, "am")

    period = None
    if re.search(r"\bmorning\b", t):
        period = "am"
    elif re.search(r"\b(afternoon|evening|tonight|night)\b", t):
        period = "pm"

    # Most explicit first. A match that isn't a real time (e.g. "30 pm" from
    # "7 30 pm") is skipped, and the next pattern gets a go.
    for pattern, build in (
        (r"\b(\d{1,2}):(\d{2}) ?(am|pm)?\b", lambda m: (m[1], m[2], m[3])),
        (r"\b(\d{1,2}) (\d{2}) ?(am|pm)\b", lambda m: (m[1], m[2], m[3])),
        (r"\b(\d{1,2}) ?(am|pm)\b", lambda m: (m[1], 0, m[2])),
        (r"\bhalf past (\d{1,2})\b", lambda m: (m[1], 30, None)),
        (r"\b(\d{1,2}) o'?clock\b", lambda m: (m[1], 0, None)),
        (r"\b(\d{1,2}) (?:in the|at) (?:morning|afternoon|evening|night)\b", lambda m: (m[1], 0, None)),
        (r"\b(?:at|for) (\d{1,2}) (\d{2})\b" + _LATER_UNITS, lambda m: (m[1], m[2], None)),
        (r"\b(?:at|for) (\d{1,2})\b" + _LATER_UNITS, lambda m: (m[1], 0, None)),
        (r"\b(\d{1,2}) ([0-5]\d)\b" + _LATER_UNITS, lambda m: (m[1], m[2], None)),  # "seven fifteen"
    ):
        for match in re.finditer(pattern, t):
            hour, minute, meridiem = build(match)
            hour, minute = int(hour), int(minute)
            if hour == 24:
                hour = 0
            if not (0 <= hour <= 23 and 0 <= minute < 60):
                continue
            if meridiem is None and hour <= 12:
                meridiem = period
            if meridiem is not None and not 1 <= hour <= 12:
                continue  # "15 pm"
            return ClockTime(hour, minute, meridiem)
    return None


def resolve_clock_time(spoken: ClockTime, now_local: datetime) -> tuple[int, int]:
    """(hour24, minute). When am/pm wasn't said ("wake me at 6:30"), pick
    whichever reading comes round next — at 3pm "6:30" means this evening, at
    10pm it means tomorrow morning."""
    hour, minute = spoken.hour, spoken.minute
    if hour > 12 or hour == 0:
        return hour, minute
    if spoken.meridiem == "am":
        return hour % 12, minute
    if spoken.meridiem == "pm":
        return hour % 12 + 12, minute
    candidates = [(hour % 12, minute), (hour % 12 + 12, minute)]

    def wait(candidate: tuple[int, int]) -> timedelta:
        ahead = now_local.replace(hour=candidate[0], minute=candidate[1], second=0, microsecond=0)
        if ahead <= now_local:
            ahead += timedelta(days=1)
        return ahead - now_local

    return min(candidates, key=wait)


def spoken_clock(hour24: int, minute: int) -> str:
    """"7 AM", "7:30 PM", "12 PM"."""
    suffix = "AM" if hour24 < 12 else "PM"
    hour = hour24 % 12 or 12
    return f"{hour} {suffix}" if minute == 0 else f"{hour}:{minute:02d} {suffix}"


def parse_repeat(text: str) -> str:
    t = normalize(text)
    if re.search(r"\b(weekdays?|every weekday|monday through friday|work ?days?)\b", t):
        return "weekdays"
    if re.search(r"\b(every ?day|daily|each day|all week)\b", t):
        return "daily"
    return "none"


def ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"
