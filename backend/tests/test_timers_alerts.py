import pytest

from app.timers import alerts


class Clock:
    """A fake clock plus sleep, so a "cycle" takes no real time."""

    def __init__(self, chime_takes=1.6):
        self.now = 0.0
        self.slept = []
        self.chime_takes = chime_takes

    def __call__(self):
        return self.now

    async def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


def cycle(clock, *, listen=True, ringing=(True, True, True), repeat=2.5, log=None):
    log = log if log is not None else []
    answers = iter(ringing)

    async def play():
        log.append("chime")
        clock.now += clock.chime_takes

    async def do_listen():
        log.append("listen")
        return False

    return alerts.ring_once(
        play=play,
        listen=do_listen if listen else None,
        is_ringing=lambda: next(answers, True),
        repeat_seconds=repeat,
        sleep=clock.sleep,
        clock=clock,
    ), log


@pytest.mark.anyio
async def test_a_cycle_is_chime_then_a_moment_then_a_listening_window():
    clock = Clock()
    run, log = cycle(clock)

    await run

    assert log == ["chime", "listen"]
    assert clock.slept == [alerts._REVERB_SECONDS]  # the chime's echo dies away before listening


@pytest.mark.anyio
async def test_without_voice_dismissal_the_old_cadence_is_kept():
    clock = Clock(chime_takes=1.6)
    run, log = cycle(clock, listen=False, repeat=2.5)

    await run

    assert log == ["chime"]
    assert clock.slept == [pytest.approx(0.9)]  # rest of the 2.5 s interval after a 1.6 s chime


@pytest.mark.anyio
async def test_a_chime_longer_than_the_interval_does_not_sleep_a_negative_time():
    clock = Clock(chime_takes=3.0)
    run, _ = cycle(clock, listen=False, repeat=2.5)

    await run

    assert clock.slept == [0.0]


@pytest.mark.anyio
async def test_it_stops_at_once_if_dismissed_during_the_chime():
    clock = Clock()
    run, log = cycle(clock, ringing=(False,))  # dismissed on screen while the chime played

    await run

    assert log == ["chime"]  # no listening window for something already gone
    assert clock.slept == []


@pytest.mark.anyio
async def test_it_does_not_listen_if_dismissed_during_the_echo_pause():
    clock = Clock()
    run, log = cycle(clock, ringing=(True, False))

    await run

    assert log == ["chime"]
    assert clock.slept == [alerts._REVERB_SECONDS]
