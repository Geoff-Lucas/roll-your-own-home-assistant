import pytest

from app import display

ASLEEP_SINK = "auto_null"
AWAKE_SINK = "alsa_output.pci-0000_04_00.1.hdmi-stereo"


class Commands:
    """Stands in for running pactl/xset; records what was run."""

    def __init__(self, sink=AWAKE_SINK):
        self.sink = sink
        self.ran = []
        self.missing = set()
        self.failing = set()
        self.dpms_enabled = False  # the kiosk's setting: sleep is the screen saver's job

    async def __call__(self, *command):
        self.ran.append(command)
        if command[0] in self.missing:
            raise FileNotFoundError(command[0])
        if command[0] in self.failing:
            raise OSError("boom")
        if command[:2] == ("pactl", "get-default-sink"):
            return 0, self.sink
        if command == ("xset", "q"):
            return 0, f"DPMS (Display Power Management Signaling):\n  DPMS is {'Enabled' if self.dpms_enabled else 'Disabled'}"
        if command == ("xset", "dpms", "force", "on"):
            self.dpms_enabled = True  # as the real xset does, verified on the kiosk
        return 0, ""


@pytest.fixture
def commands(monkeypatch):
    fake = Commands()
    monkeypatch.setattr(display, "_run", fake)
    monkeypatch.setattr(display.settings, "display_wake_settle_seconds", 1.5)
    monkeypatch.setattr(display, "_warned", False)
    return fake


class Sleeps:
    def __init__(self):
        self.seconds = []

    async def __call__(self, seconds):
        self.seconds.append(seconds)


@pytest.mark.anyio
async def test_a_null_default_output_means_the_screen_is_asleep(commands):
    commands.sink = ASLEEP_SINK
    assert await display.speakers_asleep() is True

    commands.sink = AWAKE_SINK
    assert await display.speakers_asleep() is False


@pytest.mark.anyio
async def test_without_pulseaudio_the_screen_is_assumed_awake(commands):
    commands.missing.add("pactl")

    assert await display.speakers_asleep() is False


@pytest.mark.anyio
async def test_a_sleeping_screen_is_woken_and_given_time_to_come_back(commands):
    commands.sink = ASLEEP_SINK
    sleeps = Sleeps()

    assert await display.wake_display(sleep=sleeps) is True

    assert ("xset", "s", "reset") in commands.ran
    assert sleeps.seconds == [1.5]  # the monitor needs a moment before it can show or play anything


@pytest.mark.anyio
async def test_waking_does_not_switch_dpms_back_on(commands):
    # `xset dpms force on` quietly enables DPMS, with X's 10-minute default. Run
    # on every "Hey Jarvis" and alarm chime, it undid the kiosk's own sleep setting.
    commands.sink = ASLEEP_SINK

    await display.wake_display(sleep=Sleeps())

    assert commands.dpms_enabled is False
    assert ("xset", "dpms", "force", "on") not in commands.ran


@pytest.mark.anyio
async def test_a_screen_asleep_under_dpms_is_forced_back_on(commands):
    # If DPMS is what's in use (someone set it up that way), waking has to end it.
    commands.sink = ASLEEP_SINK
    commands.dpms_enabled = True

    await display.wake_display(sleep=Sleeps())

    assert ("xset", "dpms", "force", "on") in commands.ran


@pytest.mark.anyio
async def test_an_awake_screen_is_left_alone_without_waiting(commands):
    sleeps = Sleeps()

    assert await display.wake_display(sleep=sleeps) is False

    assert sleeps.seconds == []  # no delay when there was nothing to wake


@pytest.mark.anyio
async def test_a_machine_without_xset_carries_on_and_says_so_once(commands, caplog):
    commands.missing.add("xset")

    with caplog.at_level("INFO"):
        assert await display.wake_display(sleep=Sleeps()) is False
        assert await display.wake_display(sleep=Sleeps()) is False

    assert sum("xset isn't installed" in r.message for r in caplog.records) == 1


@pytest.mark.anyio
async def test_a_failure_to_wake_never_propagates(commands, caplog):
    commands.failing.add("xset")

    with caplog.at_level("ERROR"):
        assert await display.wake_display(sleep=Sleeps()) is False

    assert any("Couldn't wake the screen" in r.message for r in caplog.records)
