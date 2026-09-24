from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.timers import service
from app.voice.core import Context
from app.voice.router import NOT_UNDERSTOOD, route

NEW_YORK = ZoneInfo("America/New_York")
NOW = datetime(2026, 9, 20, 19, 0)  # Sunday 3:00 PM in New York (EDT)

WEATHER = {
    "current": {"temperature": 84.2, "icon": "cloudy", "description": "Overcast"},
    "unit": "°F",
    "utc_offset_seconds": -14400,
    "forecast": [
        {"date": "2026-09-20", "high": 85.3, "low": 70.1, "icon": "cloudy", "description": "Overcast"},
        {"date": "2026-09-21", "high": 73.4, "low": 60.2, "icon": "rain", "description": "Slight rain"},
        {"date": "2026-09-22", "high": 62.0, "low": 56.0, "icon": "rain", "description": "Slight rain showers"},
    ],
    "hourly": [
        # Location-local times. 16:00 has already passed at 3:00 PM? No — 3 PM is 15:00, so 16:00 is next.
        {"time": "2026-09-20T14:00", "temperature": 84, "icon": "cloudy", "precipitation_probability": 90},  # past
        {"time": "2026-09-20T16:00", "temperature": 85, "icon": "cloudy", "precipitation_probability": 10},
        {"time": "2026-09-20T17:00", "temperature": 83, "icon": "cloudy", "precipitation_probability": 35},
        {"time": "2026-09-21T09:00", "temperature": 70, "icon": "rain", "precipitation_probability": 80},
    ],
}


@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture(autouse=True)
def new_york(monkeypatch):
    monkeypatch.setattr(service.settings, "timezone", "America/New_York")


@pytest.fixture
def say(session):
    def _say(text, weather=WEATHER, now=NOW, location="Fairfax, VA"):
        ctx = Context(session=session, now=now, tz=NEW_YORK, weather=weather, location_name=location)
        return route(text, ctx).text

    return _say


def timers_of(session, kind=None):
    return [t for t in service.list_all(session) if kind is None or t.kind == kind]


# --- timers -----------------------------------------------------------------


def test_setting_a_timer(say, session):
    assert say("Set a timer for ten minutes.") == "Timer set for 10 minutes."

    (timer,) = timers_of(session, "timer")
    assert timer.duration_seconds == 600
    assert timer.due_at == NOW + timedelta(minutes=10)


@pytest.mark.parametrize(
    "said, seconds",
    [
        ("set a timer for 90 seconds", 90),
        ("timer for an hour and a half", 5400),
        ("set a 25 minute timer", 1500),
        ("start a timer for one hour twenty minutes", 4800),
        ("can you set a timer for half an hour please", 1800),
    ],
)
def test_timer_phrasings(say, session, said, seconds):
    say(said)

    assert timers_of(session, "timer")[0].duration_seconds == seconds


def test_a_timer_can_be_named(say, session):
    assert say("set a 10 minute pasta timer") == "Pasta timer set for 10 minutes."
    assert say("set a timer for 5 minutes for the eggs") == "Eggs timer set for 5 minutes."

    assert sorted(t.label for t in timers_of(session, "timer")) == ["Eggs", "Pasta"]


def test_remind_me_in_makes_a_named_timer(say, session):
    assert say("remind me in 20 minutes to take out the trash") == "Okay, timer set for 20 minutes: Take out the trash."

    assert timers_of(session, "timer")[0].label == "Take out the trash"


def test_a_timer_without_a_length_asks_for_one(say, session):
    assert "How long" in say("set a timer")
    assert timers_of(session) == []


def test_asking_how_much_time_is_left(say, session):
    assert say("how much time is left") == "You don't have any timers running."
    say("set a timer for ten minutes")

    later = NOW + timedelta(minutes=3, seconds=30)
    assert say("how much time is left on the timer?", now=later) == "Timer has 6 minutes and 30 seconds left."
    assert say("how much time is left?", now=later) == "Timer has 6 minutes and 30 seconds left."


def test_status_with_several_timers_reads_the_first_few(say, session):
    for name in ("pasta", "eggs", "rice", "bread"):
        say(f"set a 10 minute {name} timer")

    reply = say("what timers do I have")

    assert reply.count("has 10 minutes left") == 3
    assert reply.endswith("And 1 more.")


def test_cancelling_the_only_timer(say, session):
    say("set a timer for ten minutes")

    assert say("cancel the timer") == "Timer cancelled."
    assert timers_of(session) == []


def test_cancelling_by_name_leaves_the_others(say, session):
    say("set a 10 minute pasta timer")
    say("set a 5 minute eggs timer")

    assert say("cancel the pasta timer") == "Timer cancelled."

    assert [t.label for t in timers_of(session, "timer")] == ["Eggs"]


def test_cancelling_when_it_is_ambiguous_asks_which(say, session):
    say("set a 10 minute pasta timer")
    say("set a 5 minute eggs timer")

    reply = say("cancel the timer")

    assert "Which one" in reply
    assert len(timers_of(session, "timer")) == 2  # nothing was cancelled on a guess


def test_cancelling_all(say, session):
    say("set a 10 minute pasta timer")
    say("set a 5 minute eggs timer")

    assert say("cancel all timers") == "Cancelled 2 timers."
    assert timers_of(session) == []


def test_cancelling_with_no_timers(say):
    assert say("cancel the timer") == "You don't have any timers running."


def test_pause_and_resume_a_timer(say, session):
    say("set a timer for ten minutes")

    assert say("pause the timer", now=NOW + timedelta(minutes=4)) == "Timer paused."
    assert timers_of(session)[0].state == "paused"
    assert say("resume the timer", now=NOW + timedelta(hours=1)) == "Timer resumed."
    assert timers_of(session)[0].state == "running"
    assert say("resume the timer") == "There's no paused timer to resume."


def test_stop_dismisses_whatever_is_ringing(say, session):
    say("set a timer for one minute")
    service.tick(session, now=NOW + timedelta(minutes=2))

    assert say("stop", now=NOW + timedelta(minutes=2)) == "Okay."

    assert timers_of(session) == []


def test_snooze_defaults_to_five_minutes_or_takes_a_length(say, session):
    say("set a timer for one minute")
    service.tick(session, now=NOW + timedelta(minutes=2))
    assert say("snooze", now=NOW + timedelta(minutes=2)) == "Snoozed for 5 minutes."
    service.tick(session, now=NOW + timedelta(minutes=8))

    assert say("snooze for ten minutes", now=NOW + timedelta(minutes=8)) == "Snoozed for 10 minutes."
    assert timers_of(session)[0].due_at == NOW + timedelta(minutes=18)


def test_stop_does_nothing_special_when_nothing_is_ringing(say):
    assert say("stop") == NOT_UNDERSTOOD


# --- alarms -----------------------------------------------------------------


def test_setting_an_alarm_for_tomorrow_morning(say, session):
    assert say("set an alarm for 7 am") == "Alarm set for 7 AM tomorrow."

    (alarm,) = timers_of(session, "alarm")
    assert alarm.alarm_time == "07:00"
    assert alarm.due_at == datetime(2026, 9, 21, 11, 0)  # 7:00 EDT


def test_an_alarm_later_today_says_no_day(say):
    assert say("set an alarm for 5:30 pm") == "Alarm set for 5:30 PM."


def test_an_unqualified_alarm_time_goes_to_whichever_comes_next(say, session):
    say("set an alarm for 6:30")  # at 3 PM: this evening

    assert timers_of(session, "alarm")[0].alarm_time == "18:30"


def test_wake_me_up_means_the_morning(say, session):
    assert say("wake me up at 6:30") == "Alarm set for 6:30 AM tomorrow."

    assert timers_of(session, "alarm")[0].alarm_time == "06:30"


def test_alarms_heard_the_way_the_recognizer_actually_writes_them(say, session):
    # Whisper's output for "wake me up at six thirty every weekday".
    assert say("Wake me up at 6.30 every weekday.") == "Alarm set for 6:30 AM tomorrow, on weekdays."

    assert timers_of(session, "alarm")[0].alarm_time == "06:30"


def test_an_alarm_for_a_decimal_length_of_time_is_a_timer(say, session):
    assert say("set an alarm for 2.5 hours") == "Timer set for 2 hours and 30 minutes."


def test_repeating_alarms(say, session):
    assert say("set an alarm for 7 every weekday") == "Alarm set for 7 AM tomorrow, on weekdays."
    assert say("set an alarm for 8 am every day") == "Alarm set for 8 AM tomorrow, every day."

    assert sorted((a.alarm_time, a.repeat) for a in timers_of(session, "alarm")) == [("07:00", "weekdays"), ("08:00", "daily")]


def test_an_alarm_over_the_weekend_names_the_day(say, session):
    friday_evening = datetime(2026, 9, 25, 22, 0)  # Fri 6 PM EDT

    assert say("wake me up at 7 on weekdays", now=friday_evening) == "Alarm set for 7 AM on Monday, on weekdays."


def test_an_alarm_without_a_time_asks_for_one(say, session):
    assert say("set an alarm") == "What time should I set the alarm for?"
    assert timers_of(session) == []


def test_an_alarm_for_a_length_of_time_is_really_a_timer(say, session):
    assert say("set an alarm for 10 minutes") == "Timer set for 10 minutes."

    assert timers_of(session, "alarm") == []
    assert timers_of(session, "timer")[0].duration_seconds == 600


def test_listing_alarms(say):
    assert say("what alarms do I have") == "You don't have any alarms set."
    say("set an alarm for 7 am")
    assert say("what alarms do I have") == "Your alarm is set for 7 AM tomorrow."
    say("set an alarm for 8 am every day")
    assert say("what alarms do I have") == "You have 2 alarms: 7 AM tomorrow; 8 AM tomorrow, every day."


def test_cancelling_alarms(say, session):
    say("set an alarm for 7 am")
    say("set an alarm for 8 am")

    assert "Which one" in say("cancel the alarm")
    assert say("cancel the 7 am alarm") == "Alarm cancelled."
    assert [a.alarm_time for a in timers_of(session, "alarm")] == ["08:00"]
    assert say("cancel all alarms") == "Alarm cancelled."
    assert timers_of(session, "alarm") == []


def test_dismissing_a_ringing_repeating_alarm_keeps_it(say, session):
    say("set an alarm for 7 am every day")
    (alarm,) = timers_of(session, "alarm")
    service.tick(session, now=alarm.due_at)

    assert say("stop", now=alarm.due_at) == "Okay."

    assert timers_of(session, "alarm")[0].state == "running"  # back to waiting for tomorrow


# --- stopwatch --------------------------------------------------------------


def test_stopwatch_lifecycle(say, session):
    assert say("start a stopwatch") == "Stopwatch started."
    assert say("start a stopwatch", now=NOW + timedelta(seconds=5)) == "The stopwatch is already running, at 5 seconds."

    assert say("how long on the stopwatch", now=NOW + timedelta(minutes=2, seconds=5)) == "The stopwatch is at 2 minutes and 5 seconds."
    assert say("stop the stopwatch", now=NOW + timedelta(minutes=3)) == "Stopwatch stopped at 3 minutes."
    assert say("resume the stopwatch", now=NOW + timedelta(minutes=10)) == "Stopwatch resumed."
    assert say("reset the stopwatch") == "Stopwatch reset."
    assert say("remove the stopwatch") == "Stopwatch removed."
    assert timers_of(session) == []


def test_stopwatch_commands_with_no_stopwatch(say):
    assert say("stop the stopwatch") == "The stopwatch isn't running."
    assert say("reset the stopwatch") == "There's no stopwatch to reset."
    assert say("how long on the stopwatch") == "There's no stopwatch running."


# --- clock ------------------------------------------------------------------


@pytest.mark.parametrize("said", ["what time is it", "What's the time?", "what is the time", "tell me the time"])
def test_the_time(say, said):
    assert say(said) == "It's 3 PM."


@pytest.mark.parametrize("said", ["what's the date", "what day is it", "what's today", "What is the date today?"])
def test_the_date(say, said):
    assert say(said) == "Today is Sunday, September 20th."


def test_the_time_uses_the_local_zone_not_utc(say):
    assert say("what time is it", now=datetime(2026, 12, 25, 3, 5)) == "It's 10:05 PM."  # 03:05 UTC = 10:05 PM EST, the 24th


# --- weather ----------------------------------------------------------------


def test_weather_summary(say):
    assert say("what's the weather?") == (
        "It's 84 degrees and overcast in Fairfax. Today's high is 85 and the low is 70."
    )


def test_temperature_only(say):
    assert say("what's the temperature outside") == "It's 84 degrees right now."
    assert say("how cold is it") == "It's 84 degrees right now."


def test_celsius_is_spoken_as_such(say):
    celsius = {**WEATHER, "unit": "°C"}

    assert say("what's the temperature", weather=celsius) == "It's 84 degrees Celsius right now."


def test_tomorrows_weather(say):
    assert say("what's the weather tomorrow") == "Tomorrow in Fairfax: slight rain, with a high of 73 and a low of 60."


def test_a_weekday_in_the_forecast(say):
    assert say("what's the weather on Tuesday") == "Tuesday in Fairfax: slight rain showers, with a high of 62 and a low of 56."


def test_a_day_beyond_the_forecast(say):
    assert say("what's the weather on Saturday") == "I only have the forecast for the next few days."


def test_will_it_rain_uses_only_the_hours_still_to_come(say):
    # The 90% hour at 2 PM is already past; the best of what's left is 35% at 5 PM.
    assert say("will it rain today") == "Maybe. There's up to a 35 percent chance of rain around 5 PM today."


def test_rain_thresholds(say):
    def at(prob):
        weather = {**WEATHER, "hourly": [{"time": "2026-09-20T17:00", "precipitation_probability": prob}]}
        return say("will it rain today", weather=weather)

    assert at(70) == "Yes, there's a 70 percent chance of rain around 5 PM today."
    assert at(50).startswith("Yes")
    assert at(49).startswith("Maybe")
    assert at(20).startswith("Maybe")
    assert at(19) == "Not likely. The chance of rain stays under 20 percent today."


def test_rain_tomorrow(say):
    assert say("is it going to rain tomorrow") == "Yes, there's a 80 percent chance of rain around 9 AM tomorrow."


def test_snow_is_asked_about_as_snow(say):
    assert "snow" in say("will it snow today")


def test_rain_falls_back_to_the_day_when_there_is_no_hourly_data(say):
    no_hours = {**WEATHER, "hourly": []}

    assert say("will it rain tomorrow", weather=no_hours) == "Yes, rain is in the forecast tomorrow."
    assert say("will it rain today", weather=no_hours) == "No rain in the forecast today."


def test_weather_before_it_has_loaded(say):
    assert say("what's the weather", weather=None) == "I don't have the weather yet. Try again in a moment."


def test_weather_without_a_known_place(say):
    assert say("what's the weather", location=None).startswith("It's 84 degrees and overcast. Today's")


# Only the local forecast is cached, so a question about somewhere else must
# not be answered with it (it used to read out Fairfax's weather for Tokyo).
SOMEWHERE_ELSE = [
    "what's the weather forecast in tokyo this weekend",
    "how hot is it in phoenix",
    "is it raining in london",
    "what's the forecast for chicago",
    "what's the weather like in new york city tomorrow",
]


@pytest.mark.parametrize("said", SOMEWHERE_ELSE)
def test_weather_somewhere_else_goes_to_claude(say, monkeypatch, said):
    from app.voice.skills import claude_fallback

    asked = []
    monkeypatch.setattr(claude_fallback.settings, "voice_claude_enabled", True)
    monkeypatch.setattr(claude_fallback.settings, "voice_claude_api_key", "sk-test-key")
    monkeypatch.setattr(claude_fallback, "_call_claude", lambda system, text: asked.append(text) or "It's 70 there.")

    assert say(said) == "It's 70 there."
    assert len(asked) == 1


@pytest.mark.parametrize("said", SOMEWHERE_ELSE)
def test_weather_somewhere_else_is_declined_honestly_without_claude(say, said):
    assert say(said) == "I only have the weather for Fairfax."


def test_weather_somewhere_else_without_a_known_place(say):
    assert say("what's the weather in tokyo", location=None) == "I only have the weather for here."


@pytest.mark.parametrize(
    "said, starts",
    [
        ("what's the weather in fairfax", "It's 84 degrees and overcast in Fairfax"),
        ("what's the weather here", "It's 84 degrees and overcast in Fairfax"),
        ("what's the weather for tomorrow", "Tomorrow in Fairfax"),
        ("what's the weather for today", "It's 84 degrees and overcast in Fairfax"),
        ("what's the weather for the rest of the day", "It's 84 degrees and overcast in Fairfax"),
        ("is it going to rain in the afternoon", "Maybe"),
        ("will it rain at 5 pm", "Maybe"),
        ("is it going to rain in an hour", "Maybe"),
        ("what's the temperature in celsius", "It's 84 degrees"),
        ("what's the temperature at the moment", "It's 84 degrees"),
    ],
)
def test_times_and_here_are_not_mistaken_for_other_places(say, said, starts):
    assert say(said).startswith(starts)


# --- routing ----------------------------------------------------------------


@pytest.mark.parametrize("said", ["tell me a joke", "play some music", "what is the capital of france", "", "   "])
def test_unrecognized_requests_are_not_guessed_at(say, said):
    reply = say(said)

    assert reply in (NOT_UNDERSTOOD, "I didn't catch that.")


def test_what_time_is_my_alarm_is_an_alarm_question_not_the_clock(say):
    say("set an alarm for 7 am")

    assert say("what time is my alarm") == "Your alarm is set for 7 AM tomorrow."


# --- hands-free dismissal (no wake word) -----------------------------------


from app.voice.router import route_while_ringing  # noqa: E402


@pytest.fixture
def ring(session):
    """Say something with no wake word, while `n` timers are ringing."""

    def _ring(text, ringing=1, now=NOW):
        for i in range(ringing):
            service.create_timer(session, 1, f"t{i}", now=NOW)
        service.tick(session, now=NOW + timedelta(seconds=5))
        ctx = Context(session=session, now=now, tz=NEW_YORK, weather=WEATHER, location_name="Fairfax, VA")
        reply = route_while_ringing(text, ctx)
        return reply.text if reply else None

    return _ring


@pytest.mark.parametrize("said", ["stop", "Stop.", "dismiss", "silence", "quiet", "enough", "shut up", "turn it off", "turn off"])
def test_an_explicit_stop_word_dismisses_whatever_is_ringing(ring, session, said):
    assert ring(said) == "Okay."

    assert timers_of(session) == []


def test_stop_dismisses_everything_that_is_ringing(ring, session):
    assert ring("stop", ringing=3) == "Okay."

    assert timers_of(session) == []


def test_snooze_by_voice_defaults_to_five_minutes_or_takes_a_length(ring, session):
    later = NOW + timedelta(seconds=5)
    assert ring("snooze", now=later) == "Snoozed for 5 minutes."
    assert timers_of(session)[0].state == "running"


def test_snooze_with_a_length(ring, session):
    assert ring("snooze for ten minutes", now=NOW + timedelta(seconds=5)) == "Snoozed for 10 minutes."


@pytest.mark.parametrize(
    "said",
    ["okay", "ok", "thanks", "thank you", "got it", "that will do", "cancel", "yes", "hello"],
)
def test_everyday_words_never_dismiss_anything_without_the_wake_word(ring, session, said):
    # "okay" and "thanks" come up constantly in a kitchen; they must not silence a timer.
    assert ring(said) is None

    assert timers_of(session)[0].state == "ringing"


def test_a_long_utterance_is_conversation_not_a_command(ring, session):
    assert ring("we should stop by the store on the way home and pick up eggs") is None
    assert timers_of(session)[0].state == "ringing"


def test_the_length_limit_is_six_words(ring, session):
    assert ring("please stop that noise right now") == "Okay."  # six words: allowed


def test_seven_words_is_too_many(ring, session):
    assert ring("please stop that noise right now thanks") is None


@pytest.mark.parametrize("said", ["set a timer for ten minutes", "cancel all timers", "what time is it", "set an alarm for 7 am"])
def test_other_commands_are_ignored_without_the_wake_word(ring, session, said):
    # Overheard chatter must not be able to change your timers or alarms.
    assert ring(said) is None

    assert [(t.label, t.state) for t in timers_of(session)] == [("t0", "ringing")]  # nothing created or removed


def test_nothing_happens_if_nothing_is_ringing(session):
    ctx = Context(session=session, now=NOW, tz=NEW_YORK, weather=WEATHER, location_name=None)
    service.create_timer(session, 600, "still running", now=NOW)

    assert route_while_ringing("stop", ctx) is None
    assert timers_of(session)[0].state == "running"


def test_the_normal_route_keeps_its_more_forgiving_words(say, session):
    # With the wake word said first ("Hey Jarvis, okay"), the lenient set still applies.
    service.create_timer(session, 1, "t", now=NOW)
    service.tick(session, now=NOW + timedelta(seconds=5))

    assert say("okay", now=NOW + timedelta(seconds=5)) == "Okay."


# --- the Claude fallback, reached only for what nothing above understands ---


def test_something_no_skill_understands_reaches_claude_when_its_turned_on(say, monkeypatch):
    from app.voice.skills import claude_fallback

    monkeypatch.setattr(claude_fallback.settings, "voice_claude_enabled", True)
    monkeypatch.setattr(claude_fallback.settings, "voice_claude_api_key", "sk-test-key")
    monkeypatch.setattr(claude_fallback, "_call_claude", lambda system, text: "Plain yogurt works well.")

    assert say("what's a good buttermilk substitute") == "Plain yogurt works well."


def test_a_command_a_skill_already_handles_never_reaches_claude(say, session, monkeypatch):
    from app.voice.skills import claude_fallback

    monkeypatch.setattr(claude_fallback.settings, "voice_claude_enabled", True)
    monkeypatch.setattr(claude_fallback.settings, "voice_claude_api_key", "sk-test-key")
    monkeypatch.setattr(claude_fallback, "_call_claude", lambda system, text: pytest.fail("should not be called"))

    assert say("what time is it") != "Plain yogurt works well."


def test_left_off_by_default_nothing_about_routing_changes():
    # Off unless both HOME_ORGANIZER_VOICE_CLAUDE_ENABLED and an API key are set —
    # the same NOT_UNDERSTOOD as before anything about Claude existed.
    from app.voice.skills import claude_fallback

    assert claude_fallback.settings.voice_claude_enabled is False
