"""Voice commands about the weather, answered from the same cached forecast
the on-screen widget shows (see app/weather.py) — no extra network trip."""

import re
from datetime import datetime, timedelta
from typing import Optional

from ..core import Context, Reply
from ..text import spoken_clock
from . import claude_fallback

_ABOUT_WEATHER = re.compile(
    r"\b(weather|forecast|temperature|how (hot|cold|warm|chilly)|degrees|rain|raining|rainy|snow|snowing"
    r"|umbrella|sunny|cloudy|storm|stormy)\b|\bhow'?s it (looking )?outside\b|\bit outside\b"
)
_RAIN = re.compile(r"\b(rain|raining|rainy|umbrella|shower|showers|storm|stormy|snow|snowing)\b")
_TEMPERATURE_ONLY = re.compile(r"\b(temperature|how (hot|cold|warm|chilly)|degrees)\b")
_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_WET_ICONS = {"rain", "drizzle", "thunderstorm", "snow"}

# "in Tokyo" names a place; "in the afternoon", "for tomorrow" and "at the
# moment" don't. After one of these prepositions, whatever remains once these
# words are dropped is taken to be a place. (Numbers never match, so "at 5 pm"
# and "in 2 hours" are left alone.)
_PLACE_AFTER = re.compile(r"\b(?:in|for|at|near|around)\s+([a-z' ]+)")
_NOT_A_PLACE = {
    "the", "a", "an", "this", "that", "next", "coming", "few", "couple", "of", "rest", "and", "to",
    "today", "tonight", "tomorrow", "morning", "afternoon", "evening", "night", "noon", "midnight",
    "weekend", "week", "now", "right", "moment", "later", "soon", "hour", "hours", "minute", "minutes",
    "day", "days", "while", "am", "pm", "celsius", "fahrenheit", "degrees",
    "here", "outside", "town", "home", "general", *_WEEKDAYS,
}  # fmt: skip
# "for my walk", "for our trip": about us, not somewhere.
_ABOUT_US = {"my", "our", "your"}


def _place_named(t: str, ctx: Context) -> Optional[str]:
    """The place a question names, if it's not here ("weather in Tokyo"); None
    when it names no place, or names the place whose forecast we have."""
    here = (ctx.location_name or "").split(",")[0].strip().lower()
    for match in _PLACE_AFTER.finditer(t):
        words = match.group(1).split()
        if words and words[0] in _ABOUT_US:
            continue
        place = " ".join(w for w in words if w not in _NOT_A_PLACE)
        if place and not (here and place.startswith(here)):
            return place
    return None


def handle(t: str, ctx: Context) -> Optional[Reply]:
    if not _ABOUT_WEATHER.search(t):
        return None
    if _place_named(t, ctx):
        # Only the local forecast is cached. With Claude available, decline so
        # the question falls through to it (it can search the web); otherwise
        # say so rather than read out the wrong city's weather.
        if claude_fallback.available():
            return None
        where = ctx.location_name.split(",")[0] if ctx.location_name else "here"
        return Reply(f"I only have the weather for {where}.", understood=False)
    weather = ctx.weather
    if not weather:
        return Reply("I don't have the weather yet. Try again in a moment.")

    day = _which_day(t, weather, ctx)
    if day is None:
        return Reply("I only have the forecast for the next few days.")

    if _RAIN.search(t):
        return _rain(t, weather, ctx, day)
    if _TEMPERATURE_ONLY.search(t) and day == 0:
        return Reply(f"It's {_temp(weather, weather['current']['temperature'])} right now.")
    return _summary(weather, ctx, day)


def _which_day(t: str, weather: dict, ctx: Context) -> Optional[int]:
    """Index into the daily forecast: 0 = today, 1 = tomorrow, or a weekday
    name. None if a weekday was named that isn't in the forecast."""
    if re.search(r"\btomorrow\b", t):
        return 1 if len(weather["forecast"]) > 1 else None
    for name in _WEEKDAYS:
        if re.search(rf"\b{name}\b", t):
            for i, day in enumerate(weather["forecast"]):
                if datetime.fromisoformat(day["date"]).strftime("%A").lower() == name:
                    return i
            return None
    return 0


def _place(ctx: Context) -> str:
    return f" in {ctx.location_name.split(',')[0]}" if ctx.location_name else ""


def _temp(weather: dict, value: float) -> str:
    unit = "degrees Celsius" if "C" in weather.get("unit", "") else "degrees"
    return f"{round(value)} {unit}"


def _day_name(day: int, weather: dict) -> str:
    if day == 0:
        return "Today"
    if day == 1:
        return "Tomorrow"
    return datetime.fromisoformat(weather["forecast"][day]["date"]).strftime("%A")


def _summary(weather: dict, ctx: Context, day: int) -> Reply:
    forecast = weather["forecast"][day]
    high, low = round(forecast["high"]), round(forecast["low"])
    if day == 0:
        current = weather["current"]
        return Reply(
            f"It's {_temp(weather, current['temperature'])} and {current['description'].lower()}{_place(ctx)}. "
            f"Today's high is {high} and the low is {low}."
        )
    return Reply(
        f"{_day_name(day, weather)}{_place(ctx)}: {forecast['description'].lower()}, "
        f"with a high of {high} and a low of {low}."
    )


def _upcoming_hours(weather: dict, ctx: Context, day: int) -> list[dict]:
    """The hourly entries that matter for "will it rain": for today, the rest
    of the day; for another day, that whole (location-local) day."""
    offset = timedelta(seconds=weather.get("utc_offset_seconds", 0))
    date = weather["forecast"][day]["date"]
    hours = []
    for hour in weather.get("hourly", []):
        if not hour["time"].startswith(date):
            continue
        instant = datetime.fromisoformat(hour["time"]) - offset  # naive UTC, like ctx.now
        if day == 0 and instant <= ctx.now:
            continue
        hours.append(hour)
    return hours


def _rain(t: str, weather: dict, ctx: Context, day: int) -> Reply:
    snow = bool(re.search(r"\bsnow|snowing\b", t))
    word = "snow" if snow else "rain"
    when = "today" if day == 0 else _day_name(day, weather).lower()
    hours = _upcoming_hours(weather, ctx, day)
    chances = [(h["precipitation_probability"], h) for h in hours if h.get("precipitation_probability") is not None]

    if chances:
        best, hour = max(chances, key=lambda pair: pair[0])
        clock = datetime.fromisoformat(hour["time"])
        around = spoken_clock(clock.hour, 0)
        if best >= 50:
            return Reply(f"Yes, there's a {best} percent chance of {word} around {around} {when}.")
        if best >= 20:
            return Reply(f"Maybe. There's up to a {best} percent chance of {word} around {around} {when}.")
        return Reply(f"Not likely. The chance of {word} stays under {best + 1} percent {when}.")

    # No hourly data: fall back to the day's overall conditions.
    if weather["forecast"][day]["icon"] in _WET_ICONS:
        return Reply(f"Yes, {word} is in the forecast {when}.")
    return Reply(f"No {word} in the forecast {when}.")
