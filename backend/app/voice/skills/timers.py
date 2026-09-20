"""Voice commands for timers, alarms and the stopwatch.

Every function takes the already-normalized utterance (see text.normalize) and
returns a Reply, or None if the utterance isn't about these things. Actions go
through app.timers.service — the same functions the touch UI uses — so a
spoken timer and a tapped one are the same object.
"""

import re
from typing import Optional

from ...models import Timer
from ...timers import service
from ..core import Context, Reply
from ..text import (
    ClockTime,
    numbers_to_digits,
    parse_clock_time,
    parse_duration,
    parse_repeat,
    resolve_clock_time,
    spoken_clock,
    spoken_duration,
    strip_duration,
)

_CANCEL = r"\b(cancel|delete|remove|clear|kill|get rid of|turn off|switch off|disable)\b"
_ALL = r"\b(all|every|both|everything)\b"
_STRICT_STOP = r"\b(stop|dismiss|silence|quiet|enough|shut up|turn (it )?off)\b"
_ACK = r"\b(stop|dismiss|silence|quiet|enough|shut up|turn (it )?off|okay|ok|got it|thanks|thank you|that will do)\b"

# Words that are part of *asking* for a timer rather than naming it.
_FILLER = set(
    "set start create make new a an the timer timers for of please me called named and on my up add put hey can "
    "you could i want to need lets let s go it that this another one another minute minutes second seconds hour "
    "hours in".split()
)  # fmt: skip


def _has(t: str, pattern: str) -> bool:
    return re.search(pattern, t) is not None


def handle(t: str, ctx: Context) -> Optional[Reply]:
    items = service.list_all(ctx.session)
    ringing = [item for item in items if item.state == "ringing"]

    # Something is going off and the person says "stop" / "snooze": that's the
    # only thing they can mean — unless they name the stopwatch or say "all".
    if ringing and not _has(t, r"\bstopwatch\b") and not _has(t, _ALL):
        reply = _ringing(t, ctx, ringing)
        if reply:
            return reply

    if _has(t, r"\bstopwatch\b"):
        return _stopwatch(t, ctx, [i for i in items if i.kind == "stopwatch"])
    if _has(t, r"\balarms?\b") or _has(t, r"\bwake me\b"):
        return _alarm(t, ctx, [i for i in items if i.kind == "alarm"])
    if _has(t, r"\btimers?\b") or _has(t, r"\bremind me in\b"):
        return _timer(t, ctx, [i for i in items if i.kind == "timer"])
    # "how much time is left?" doesn't say "timer", but nothing else it could mean.
    if _has(t, r"\b(how much time|how long|time) (is )?(left|remaining)\b|\bhow much longer\b"):
        return _timer_status(ctx, [i for i in items if i.kind == "timer"])
    return None


# --- something is ringing ---------------------------------------------------


def _ringing(t: str, ctx: Context, ringing: list[Timer], strict: bool = False) -> Optional[Reply]:
    """`strict` is for hands-free use, where nobody said the wake word first: only
    the explicit words count, so a passing "okay" or "thanks" can't dismiss anything."""
    if _has(t, r"\bsnooze\b"):
        minutes = max(1, round((parse_duration(t) or 300) / 60))
        for item in ringing:
            service.snooze(ctx.session, item, minutes, now=ctx.now)
        return Reply(f"Snoozed for {spoken_duration(minutes * 60)}.")
    if _has(t, _STRICT_STOP) or (not strict and (_has(t, _ACK) or _has(t, _CANCEL))):
        for item in ringing:
            service.dismiss(ctx.session, item, now=ctx.now)
        return Reply("Okay.")
    return None


# A hands-free dismissal is a short, deliberate word or two ("stop", "snooze for
# ten minutes"). Anything longer is people talking, and is left alone.
MAX_RING_COMMAND_WORDS = 6


def handle_while_ringing(t: str, ctx: Context) -> Optional[Reply]:
    ringing = [item for item in service.list_all(ctx.session) if item.state == "ringing"]
    if not ringing or len(t.split()) > MAX_RING_COMMAND_WORDS:
        return None
    return _ringing(t, ctx, ringing, strict=True)


# --- picking which one the person means ------------------------------------


def _select(t: str, items: list[Timer]) -> Optional[list[Timer]]:
    """All of them if "all" was said; the ones whose name was said; the only
    one if there is only one; None if it's genuinely ambiguous."""
    if _has(t, _ALL):
        return items
    named = [i for i in items if i.label and all(word in t.split() for word in i.label.lower().split())]
    if named:
        return named
    return items if len(items) == 1 else None


def _which(items: list[Timer], noun: str) -> str:
    names = [_name(i) for i in items[:4]]
    return f"You have {len(items)} {noun}s: {', '.join(names)}. Which one do you mean?"


def _name(item: Timer) -> str:
    if item.label:
        return item.label
    if item.kind == "alarm":
        hour, minute = (int(x) for x in item.alarm_time.split(":"))
        return f"the {spoken_clock(hour, minute)} alarm"
    return "the stopwatch" if item.kind == "stopwatch" else "an unnamed timer"


# --- countdown timers -------------------------------------------------------


def _timer(t: str, ctx: Context, timers: list[Timer]) -> Reply:
    if _has(t, _CANCEL) or _has(t, r"\bstop\b"):
        if not timers:
            return Reply("You don't have any timers running.")
        chosen = _select(t, timers)
        if chosen is None:
            return Reply(_which(timers, "timer"))
        for item in chosen:
            service.delete(ctx.session, item)
        return Reply("Timer cancelled." if len(chosen) == 1 else f"Cancelled {len(chosen)} timers.")

    if _has(t, r"\bpause\b"):
        running = [i for i in timers if i.state == "running"]
        chosen = _select(t, running) if running else []
        if not running:
            return Reply("There's no running timer to pause.")
        if chosen is None:
            return Reply(_which(running, "running timer"))
        for item in chosen:
            service.pause(ctx.session, item, now=ctx.now)
        return Reply("Timer paused.")

    if _has(t, r"\b(resume|continue|unpause)\b"):
        paused = [i for i in timers if i.state == "paused"]
        if not paused:
            return Reply("There's no paused timer to resume.")
        chosen = _select(t, paused)
        if chosen is None:
            return Reply(_which(paused, "paused timer"))
        for item in chosen:
            service.resume(ctx.session, item, now=ctx.now)
        return Reply("Timer resumed.")

    if _has(t, r"\b(how (much|long)|time left|left on|what timers|which timers|any timers|check|status|how many)\b"):
        return _timer_status(ctx, timers)

    duration = parse_duration(t)
    if duration is None:
        return Reply("How long should the timer be? Try saying, set a timer for ten minutes.", understood=False)
    label = _label_for(t)
    timer = service.create_timer(ctx.session, duration, label, now=ctx.now)
    length = spoken_duration(duration)
    if _has(t, r"\bremind me in\b") and label:
        return Reply(f"Okay, timer set for {length}: {timer.label}.")
    prefix = f"{timer.label} timer" if timer.label else "Timer"
    return Reply(f"{prefix} set for {length}.")


def _timer_status(ctx: Context, timers: list[Timer]) -> Reply:
    if not timers:
        return Reply("You don't have any timers running.")
    lines = []
    for item in timers[:3]:
        info = service.describe(item, ctx.now)
        name = item.label or "Timer"
        if item.state == "ringing":
            lines.append(f"{name} is done")
        elif item.state == "paused":
            lines.append(f"{name} is paused with {spoken_duration(info['remaining_seconds'])} left")
        else:
            lines.append(f"{name} has {spoken_duration(info['remaining_seconds'])} left")
    more = len(timers) - 3
    return Reply(". ".join(lines) + ("." if lines else "") + (f" And {more} more." if more > 0 else ""))


def _label_for(t: str) -> str:
    """What's left of "set a 10 minute pasta timer" / "remind me in 20 minutes
    to take out the trash" once the asking-for-a-timer words are removed."""
    remind = re.search(r"\bremind me in\b.*?\b(?:to|about)\b (.+)$", t)
    if remind:
        return remind.group(1).strip().capitalize()[:60]
    leftover = [w for w in strip_duration(t).split() if w not in _FILLER and not w.isdigit()]
    return " ".join(leftover[:3]).capitalize()


# --- alarms -----------------------------------------------------------------


def _alarm(t: str, ctx: Context, alarms: list[Timer]) -> Reply:
    if _has(t, _CANCEL):
        if not alarms:
            return Reply("You don't have any alarms set.")
        chosen = _select_alarm(t, alarms)
        if chosen is None:
            return Reply(_which(alarms, "alarm"))
        for item in chosen:
            service.delete(ctx.session, item)
        return Reply("Alarm cancelled." if len(chosen) == 1 else f"Cancelled {len(chosen)} alarms.")

    if _has(t, r"\b(what alarms|which alarms|any alarms|when is|what time is|how many|check|list)\b"):
        return _alarm_status(ctx, alarms)

    spoken = parse_clock_time(t)
    if spoken is None:
        # "set an alarm for 10 minutes" is really a timer.
        duration = parse_duration(t)
        if duration:
            timer = service.create_timer(ctx.session, duration, "", now=ctx.now)
            return Reply(f"Timer set for {spoken_duration(duration)}.")
        return Reply("What time should I set the alarm for?", understood=False)

    repeat = parse_repeat(t)
    # "Wake me up at 6:30", or a repeating alarm at 7, is a morning alarm; only a
    # one-off "alarm at 6:30" is left to whichever 6:30 comes round next.
    morning = _has(t, r"\bwake me\b") or repeat != "none"
    if morning and spoken.meridiem is None and 1 <= spoken.hour <= 11:
        spoken = ClockTime(spoken.hour, spoken.minute, "am")
    hour, minute = resolve_clock_time(spoken, ctx.now_local)
    alarm = service.create_alarm(ctx.session, f"{hour:02d}:{minute:02d}", repeat, "", now=ctx.now)
    return Reply(f"Alarm set for {_when(alarm, ctx)}{_repeat_words(repeat)}.")


def _select_alarm(t: str, alarms: list[Timer]) -> Optional[list[Timer]]:
    if _has(t, _ALL):
        return alarms
    spoken = parse_clock_time(t)
    if spoken is not None:
        # Match on the clock face; if am/pm wasn't said, either reading counts.
        matches = [
            a
            for a in alarms
            if _same_time(spoken, *(int(x) for x in a.alarm_time.split(":")))
        ]
        if matches:
            return matches
    return alarms if len(alarms) == 1 else None


def _same_time(spoken: ClockTime, hour24: int, minute: int) -> bool:
    if spoken.minute != minute:
        return False
    if spoken.hour > 12 or spoken.hour == 0:
        return spoken.hour == hour24
    if spoken.meridiem == "am":
        return hour24 == spoken.hour % 12
    if spoken.meridiem == "pm":
        return hour24 == spoken.hour % 12 + 12
    return hour24 % 12 == spoken.hour % 12


def _when(alarm: Timer, ctx: Context) -> str:
    """"7 AM", or "7 AM tomorrow" when it is not the same local day."""
    from datetime import timezone

    hour, minute = (int(x) for x in alarm.alarm_time.split(":"))
    due_local = alarm.due_at.replace(tzinfo=timezone.utc).astimezone(ctx.tz)
    text = spoken_clock(hour, minute)
    if due_local.date() != ctx.now_local.date():
        days = (due_local.date() - ctx.now_local.date()).days
        text += " tomorrow" if days == 1 else f" on {due_local.strftime('%A')}"
    return text


def _repeat_words(repeat: str) -> str:
    return {"daily": ", every day", "weekdays": ", on weekdays"}.get(repeat, "")


def _alarm_status(ctx: Context, alarms: list[Timer]) -> Reply:
    if not alarms:
        return Reply("You don't have any alarms set.")
    parts = [f"{_when(a, ctx)}{_repeat_words(a.repeat)}" for a in alarms[:3]]
    if len(alarms) == 1:
        return Reply(f"Your alarm is set for {parts[0]}.")
    return Reply(f"You have {len(alarms)} alarms: {'; '.join(parts)}.")


# --- stopwatch --------------------------------------------------------------


def _stopwatch(t: str, ctx: Context, watches: list[Timer]) -> Reply:
    watch = watches[0] if watches else None

    def elapsed_words() -> str:
        return spoken_duration(service.describe(watch, ctx.now)["elapsed_seconds"]) if watch else "no time"

    if _has(t, r"\b(reset|zero)\b"):
        if not watch:
            return Reply("There's no stopwatch to reset.")
        service.reset_stopwatch(ctx.session, watch)
        return Reply("Stopwatch reset.")
    if _has(t, _CANCEL):
        if not watch:
            return Reply("There's no stopwatch running.")
        service.delete(ctx.session, watch)
        return Reply("Stopwatch removed.")
    if _has(t, r"\b(stop|pause|freeze|hold)\b"):
        if not watch or watch.state != "running":
            return Reply("The stopwatch isn't running.")
        service.pause(ctx.session, watch, now=ctx.now)
        return Reply(f"Stopwatch stopped at {elapsed_words()}.")
    if _has(t, r"\b(resume|continue|unpause)\b"):
        if not watch or watch.state != "paused":
            return Reply("There's no paused stopwatch to resume.")
        service.resume(ctx.session, watch, now=ctx.now)
        return Reply("Stopwatch resumed.")
    if _has(t, r"\b(how (long|much)|what|check|read|status|time)\b") and not _has(t, r"\b(start|begin|run)\b"):
        if not watch:
            return Reply("There's no stopwatch running.")
        return Reply(f"The stopwatch is at {elapsed_words()}.")

    # Start.
    if watch is None:
        service.create_stopwatch(ctx.session, "", now=ctx.now)
        return Reply("Stopwatch started.")
    if watch.state == "paused":
        service.resume(ctx.session, watch, now=ctx.now)
        return Reply("Stopwatch resumed.")
    return Reply(f"The stopwatch is already running, at {elapsed_words()}.")



