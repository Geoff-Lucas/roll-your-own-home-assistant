from datetime import datetime

import pytest

from app.voice.text import (
    ClockTime,
    normalize,
    numbers_to_digits,
    ordinal,
    parse_clock_time,
    parse_duration,
    parse_repeat,
    resolve_clock_time,
    spoken_clock,
    spoken_duration,
    strip_duration,
)


def test_normalize_lowercases_and_drops_punctuation_but_keeps_what_numbers_need():
    assert normalize("Set a timer for 10 minutes.") == "set a timer for 10 minutes"
    assert normalize("What's the time?") == "what's the time"
    assert normalize("Wake me at 7:30 A.M.!") == "wake me at 7:30 am"
    assert normalize("two and a half-hours") == "two and a half hours"
    assert normalize("it's 2.5 hours") == "it's 2.5 hours"  # decimal point survives
    assert normalize("  lots   of   space  ") == "lots of space"


@pytest.mark.parametrize(
    "spoken, digits",
    [
        ("ten", "10"),
        ("twenty five", "25"),
        ("ninety", "90"),
        ("thirteen", "13"),
        ("one hundred", "100"),
        ("one hundred twenty five", "125"),
        ("seven fifteen", "7 15"),  # two numbers, as a spoken time reads
        ("seven thirty", "7 30"),
        ("set a timer for ten minutes", "set a timer for 10 minutes"),
        ("nothing numeric here", "nothing numeric here"),
    ],
)
def test_number_words_become_digits(spoken, digits):
    assert numbers_to_digits(spoken) == digits


@pytest.mark.parametrize(
    "said, seconds",
    [
        ("set a timer for 10 minutes", 600),
        ("Set a timer for ten minutes.", 600),
        ("a 10-minute timer", 600),
        ("90 seconds", 90),
        ("ninety seconds", 90),
        ("1 hour 20 minutes", 4800),
        ("an hour", 3600),
        ("an hour and a half", 5400),
        ("1 hour and a half", 5400),
        ("two and a half hours", 9000),
        ("a minute and a half", 90),
        ("half an hour", 1800),
        ("a half hour", 1800),
        ("quarter of an hour", 900),
        ("three quarters of an hour", 2700),
        ("twenty five minutes", 1500),
        ("2 hrs 5 mins 30 secs", 7530),
        ("1.5 hours", 5400),
    ],
)
def test_durations(said, seconds):
    assert parse_duration(said) == seconds


@pytest.mark.parametrize("said", ["set a timer", "for a while", "at 7 am", "0 minutes", ""])
def test_no_duration(said):
    assert parse_duration(said) is None


def test_strip_duration_leaves_the_rest_for_naming():
    assert strip_duration("set a 10 minute pasta timer") == "set a pasta timer"
    assert "10" not in strip_duration("timer for ten minutes for the eggs")


@pytest.mark.parametrize(
    "seconds, words",
    [
        (45, "45 seconds"),
        (60, "1 minute"),
        (150, "2 minutes and 30 seconds"),
        (3600, "1 hour"),
        (5430, "1 hour and 30 minutes"),  # seconds dropped once hours are involved
        (7200, "2 hours"),
        (0, "no time"),
        (0.4, "no time"),
    ],
)
def test_spoken_duration(seconds, words):
    assert spoken_duration(seconds) == words


@pytest.mark.parametrize(
    "said, expected",
    [
        ("wake me up at 6:30", ClockTime(6, 30, None)),
        ("set an alarm for 7 am", ClockTime(7, 0, "am")),
        ("alarm for seven thirty pm", ClockTime(7, 30, "pm")),
        ("7:15 PM", ClockTime(7, 15, "pm")),
        ("at 5 30 in the evening", ClockTime(5, 30, "pm")),
        ("6 in the morning", ClockTime(6, 0, "am")),
        ("at 8 tonight", ClockTime(8, 0, "pm")),
        ("seven fifteen", ClockTime(7, 15, None)),
        ("at half past six", ClockTime(6, 30, None)),
        ("wake me at noon", ClockTime(12, 0, "pm")),
        ("alarm at midnight", ClockTime(12, 0, "am")),
        ("alarm for 6 o'clock", ClockTime(6, 0, None)),
        ("alarm at 14:30", ClockTime(14, 30, None)),  # 24-hour
        ("at 6", ClockTime(6, 0, None)),
        # The real recognizer writes "six thirty" as "6.30" (a dot, not a colon).
        ("Wake me up at 6.30 every weekday.", ClockTime(6, 30, None)),
        ("alarm for 7.15 pm", ClockTime(7, 15, "pm")),
        ("at 12.05 am", ClockTime(12, 5, "am")),
    ],
)
def test_clock_times(said, expected):
    assert parse_clock_time(said) == expected


@pytest.mark.parametrize(
    "said",
    [
        "for 10 minutes", "timer for 5 hours", "no times here", "alarm at 15 pm", "at 7:75", "at 30",
        "alarm for 2.5 hours",  # a decimal length of time, not 2:50
        "alarm for 1.25 hours",
    ],
)  # fmt: skip
def test_not_a_clock_time(said):
    assert parse_clock_time(said) is None


def test_ambiguous_times_resolve_to_whichever_comes_round_next():
    afternoon = datetime(2026, 9, 20, 15, 0)  # 3 PM
    late_night = datetime(2026, 9, 20, 22, 0)  # 10 PM

    assert resolve_clock_time(ClockTime(6, 30, None), afternoon) == (18, 30)  # this evening
    assert resolve_clock_time(ClockTime(6, 30, None), late_night) == (6, 30)  # tomorrow morning
    assert resolve_clock_time(ClockTime(4, 0, None), afternoon) == (16, 0)  # in an hour
    assert resolve_clock_time(ClockTime(12, 0, None), late_night) == (0, 0)  # midnight is nearer than noon


def test_stated_times_are_not_second_guessed():
    now = datetime(2026, 9, 20, 15, 0)

    assert resolve_clock_time(ClockTime(7, 0, "am"), now) == (7, 0)
    assert resolve_clock_time(ClockTime(7, 0, "pm"), now) == (19, 0)
    assert resolve_clock_time(ClockTime(12, 0, "am"), now) == (0, 0)
    assert resolve_clock_time(ClockTime(12, 0, "pm"), now) == (12, 0)
    assert resolve_clock_time(ClockTime(14, 30, None), now) == (14, 30)  # 24-hour


def test_spoken_clock():
    assert spoken_clock(7, 0) == "7 AM"
    assert spoken_clock(19, 30) == "7:30 PM"
    assert spoken_clock(0, 5) == "12:05 AM"
    assert spoken_clock(12, 0) == "12 PM"


@pytest.mark.parametrize(
    "said, repeat",
    [
        ("every day", "daily"),
        ("everyday", "daily"),
        ("daily at seven", "daily"),
        ("on weekdays", "weekdays"),
        ("every weekday", "weekdays"),
        ("monday through friday", "weekdays"),
        ("just tomorrow", "none"),
    ],
)
def test_repeat(said, repeat):
    assert parse_repeat(said) == repeat


@pytest.mark.parametrize("n, text", [(1, "1st"), (2, "2nd"), (3, "3rd"), (4, "4th"), (11, "11th"), (12, "12th"), (13, "13th"), (21, "21st"), (22, "22nd"), (30, "30th")])
def test_ordinals(n, text):
    assert ordinal(n) == text
