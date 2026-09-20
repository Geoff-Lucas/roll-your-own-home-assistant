from datetime import datetime, timedelta

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.config import settings
from app.timers import service

# Naive UTC, like everything stored in the database.
T0 = datetime(2026, 9, 20, 12, 0, 0)  # 08:00 in New York (EDT)


@pytest.fixture(autouse=True)
def new_york(monkeypatch):
    monkeypatch.setattr(settings, "timezone", "America/New_York")


@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


# --- countdown timers -------------------------------------------------------


def test_a_timer_goes_off_after_its_duration(session):
    timer = service.create_timer(session, 600, "pasta", now=T0)

    assert timer.due_at == T0 + timedelta(minutes=10)
    assert (timer.kind, timer.state, timer.label, timer.duration_seconds) == ("timer", "running", "pasta", 600)


@pytest.mark.parametrize("seconds", [0, -5, service.MAX_TIMER_SECONDS + 1])
def test_timer_length_is_bounded(session, seconds):
    with pytest.raises(ValueError):
        service.create_timer(session, seconds, now=T0)


def test_pausing_freezes_the_time_left_and_resuming_continues_from_it(session):
    timer = service.create_timer(session, 600, now=T0)

    service.pause(session, timer, now=T0 + timedelta(seconds=150))
    assert timer.state == "paused"
    assert timer.due_at is None
    assert timer.paused_remaining_seconds == 450

    # Time passes while paused; none of it counts.
    service.resume(session, timer, now=T0 + timedelta(hours=1))
    assert timer.state == "running"
    assert timer.due_at == T0 + timedelta(hours=1, seconds=450)
    assert timer.paused_remaining_seconds is None


def test_tick_rings_only_what_has_come_due(session):
    soon = service.create_timer(session, 60, "soon", now=T0)
    later = service.create_timer(session, 600, "later", now=T0)

    assert service.tick(session, now=T0 + timedelta(seconds=59)) == []

    rang = service.tick(session, now=T0 + timedelta(seconds=60))
    assert [t.id for t in rang] == [soon.id]
    assert soon.state == "ringing"
    assert soon.ring_started_at == T0 + timedelta(seconds=60)
    assert later.state == "running"


def test_tick_does_not_ring_the_same_timer_twice(session):
    service.create_timer(session, 5, now=T0)

    assert len(service.tick(session, now=T0 + timedelta(seconds=6))) == 1
    assert service.tick(session, now=T0 + timedelta(seconds=7)) == []


def test_a_timer_that_came_due_while_the_backend_was_down_rings_on_the_next_tick(session):
    timer = service.create_timer(session, 60, now=T0)

    service.tick(session, now=T0 + timedelta(hours=3))

    assert timer.state == "ringing"


def test_paused_timers_never_ring(session):
    timer = service.create_timer(session, 60, now=T0)
    service.pause(session, timer, now=T0 + timedelta(seconds=10))

    assert service.tick(session, now=T0 + timedelta(days=1)) == []


def test_snoozing_sends_a_ringing_timer_back_to_running(session):
    timer = service.create_timer(session, 60, now=T0)
    service.tick(session, now=T0 + timedelta(seconds=60))

    service.snooze(session, timer, 5, now=T0 + timedelta(seconds=70))

    assert timer.state == "running"
    assert timer.due_at == T0 + timedelta(seconds=70 + 300)
    assert timer.ring_started_at is None


def test_snooze_is_bounded_and_only_for_ringing_things(session):
    timer = service.create_timer(session, 600, now=T0)
    with pytest.raises(ValueError, match="ringing"):
        service.snooze(session, timer, 5, now=T0)

    service.tick(session, now=T0 + timedelta(hours=1))
    for minutes in (0, 121):
        with pytest.raises(ValueError, match="between"):
            service.snooze(session, timer, minutes, now=T0)


def test_dismissing_a_finished_timer_removes_it(session):
    timer = service.create_timer(session, 60, now=T0)
    service.tick(session, now=T0 + timedelta(seconds=60))

    assert service.dismiss(session, timer, now=T0 + timedelta(seconds=61)) is None
    assert service.list_all(session) == []


def test_only_ringing_things_can_be_dismissed(session):
    timer = service.create_timer(session, 600, now=T0)

    with pytest.raises(ValueError, match="ringing"):
        service.dismiss(session, timer, now=T0)


def test_pause_and_resume_reject_the_wrong_state(session):
    timer = service.create_timer(session, 600, now=T0)
    with pytest.raises(ValueError):
        service.resume(session, timer, now=T0)  # not paused
    service.pause(session, timer, now=T0)
    with pytest.raises(ValueError):
        service.pause(session, timer, now=T0)  # already paused


# --- alarms -----------------------------------------------------------------


def test_an_alarm_later_today_rings_today(session):
    alarm = service.create_alarm(session, "17:30", now=T0)  # it's 08:00 locally

    # 17:30 EDT is 21:30 UTC.
    assert alarm.due_at == datetime(2026, 9, 20, 21, 30)


def test_an_alarm_whose_time_has_passed_rings_tomorrow(session):
    alarm = service.create_alarm(session, "07:00", now=T0)  # 07:00 already went by at 08:00

    assert alarm.due_at == datetime(2026, 9, 21, 11, 0)  # 07:00 EDT tomorrow


def test_an_alarm_set_for_exactly_now_waits_for_tomorrow(session):
    alarm = service.create_alarm(session, "08:00", now=T0)

    assert alarm.due_at == datetime(2026, 9, 21, 12, 0)


def test_weekday_alarms_skip_the_weekend():
    friday_evening = datetime(2026, 9, 25, 22, 0)  # Fri 18:00 EDT
    monday_7am_utc = datetime(2026, 9, 28, 11, 0)

    assert service.next_alarm_due("07:00", "weekdays", friday_evening) == monday_7am_utc
    assert service.next_alarm_due("07:00", "daily", friday_evening) == datetime(2026, 9, 26, 11, 0)  # Saturday


def test_an_alarm_still_rings_at_its_wall_clock_time_across_daylight_saving():
    # US clocks spring forward on 2026-03-08. From Saturday evening, a daily
    # 07:00 alarm must ring at 07:00 *local* on Sunday (11:00 UTC, now EDT) —
    # not 24h later in UTC terms, which would be 08:00 local.
    saturday_evening = datetime(2026, 3, 8, 0, 0)  # Sat 19:00 EST

    assert service.next_alarm_due("07:00", "daily", saturday_evening) == datetime(2026, 3, 8, 11, 0)


@pytest.mark.parametrize("bad", ["7:00", "24:00", "07:60", "seven", "", "07-00"])
def test_alarm_times_must_be_24h_hh_mm(session, bad):
    with pytest.raises(ValueError):
        service.create_alarm(session, bad, now=T0)


def test_an_unknown_repeat_is_rejected(session):
    with pytest.raises(ValueError, match="repeat"):
        service.create_alarm(session, "07:00", repeat="sometimes", now=T0)


def test_dismissing_a_one_off_alarm_removes_it(session):
    alarm = service.create_alarm(session, "09:00", now=T0)
    service.tick(session, now=alarm.due_at)

    assert service.dismiss(session, alarm, now=alarm.due_at) is None
    assert service.list_all(session) == []


def test_dismissing_a_repeating_alarm_reschedules_it(session):
    alarm = service.create_alarm(session, "09:00", repeat="daily", now=T0)
    first_due = alarm.due_at
    service.tick(session, now=first_due)

    kept = service.dismiss(session, alarm, now=first_due + timedelta(seconds=30))

    assert kept is not None
    assert kept.state == "running"
    assert kept.due_at == first_due + timedelta(days=1)
    assert kept.ring_started_at is None


def test_alarms_cannot_be_paused(session):
    alarm = service.create_alarm(session, "09:00", now=T0)

    with pytest.raises(ValueError):
        service.pause(session, alarm, now=T0)


# --- stopwatch --------------------------------------------------------------


def test_a_stopwatch_accumulates_across_pauses(session):
    watch = service.create_stopwatch(session, now=T0)

    service.pause(session, watch, now=T0 + timedelta(seconds=30))
    assert watch.elapsed_seconds == 30
    assert watch.started_at is None

    service.resume(session, watch, now=T0 + timedelta(minutes=10))
    service.pause(session, watch, now=T0 + timedelta(minutes=10, seconds=15))
    assert watch.elapsed_seconds == 45


def test_a_stopwatch_never_rings(session):
    service.create_stopwatch(session, now=T0)

    assert service.tick(session, now=T0 + timedelta(days=30)) == []


def test_resetting_a_stopwatch_zeroes_and_stops_it(session):
    watch = service.create_stopwatch(session, now=T0)

    service.reset_stopwatch(session, watch)

    assert (watch.elapsed_seconds, watch.state, watch.started_at) == (0.0, "paused", None)


def test_only_stopwatches_can_be_reset(session):
    timer = service.create_timer(session, 60, now=T0)

    with pytest.raises(ValueError):
        service.reset_stopwatch(session, timer)


# --- describing and ordering -----------------------------------------------


def test_describe_reports_seconds_left_or_elapsed(session):
    timer = service.create_timer(session, 600, now=T0)
    watch = service.create_stopwatch(session, now=T0)

    assert service.describe(timer, now=T0 + timedelta(seconds=100))["remaining_seconds"] == 500
    assert service.describe(timer, now=T0 + timedelta(hours=1))["remaining_seconds"] == 0  # never negative
    assert service.describe(watch, now=T0 + timedelta(seconds=42))["elapsed_seconds"] == 42
    assert service.describe(watch, now=T0)["remaining_seconds"] is None

    service.pause(session, timer, now=T0 + timedelta(seconds=100))
    assert service.describe(timer, now=T0 + timedelta(days=1))["remaining_seconds"] == 500


def test_the_list_puts_ringing_first_then_soonest_then_stopwatches_last(session):
    watch = service.create_stopwatch(session, now=T0)
    slow = service.create_timer(session, 3600, "slow", now=T0)
    fast = service.create_timer(session, 60, "fast", now=T0)
    done = service.create_timer(session, 5, "done", now=T0)
    service.tick(session, now=T0 + timedelta(seconds=5))

    assert [t.id for t in service.list_all(session)] == [done.id, fast.id, slow.id, watch.id]


def test_the_chime_gives_up_after_the_configured_time(session, monkeypatch):
    monkeypatch.setattr(settings, "timer_ring_max_seconds", 300)
    timer = service.create_timer(session, 5, now=T0)
    service.tick(session, now=T0 + timedelta(seconds=5))

    ringing_at = T0 + timedelta(seconds=5)
    assert service.ringing_audibly([timer], ringing_at + timedelta(seconds=299)) is True
    assert service.ringing_audibly([timer], ringing_at + timedelta(seconds=301)) is False
    # ...but it is still ringing on screen until someone deals with it.
    assert timer.state == "ringing"


def test_nothing_ringing_means_no_chime(session):
    timer = service.create_timer(session, 600, now=T0)

    assert service.ringing_audibly([timer], T0) is False
