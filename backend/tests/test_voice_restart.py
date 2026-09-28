from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app import system
from app.voice.core import Context, Reply
from app.voice.router import route
from app.voice.session import VoiceSession, run_action
from app.voice.skills import restart

NOW = datetime(2026, 9, 27, 19, 0)
REAL_CAN_REBOOT = system.can_reboot  # before the fixture below stands in for it


@pytest.fixture(autouse=True)
def allowed(monkeypatch):
    monkeypatch.setattr(restart, "_pending_until", None)
    monkeypatch.setattr(restart.host, "can_reboot", lambda: True)
    monkeypatch.setattr(restart.settings, "voice_restart_enabled", True)
    monkeypatch.setattr(restart.settings, "voice_restart_confirm_seconds", 30)


@pytest.fixture(autouse=True)
def session():
    # The timer commands are asked first and look in the database.
    global _session
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as _session:
        yield _session


def say(text, now=NOW):
    return route(text, Context(session=_session, now=now, tz=ZoneInfo("America/New_York")))


@pytest.mark.parametrize(
    "said",
    ["Hey Jarvis, restart the kiosk", "reboot the computer", "restart yourself", "Please restart the system.", "Restart."],
)
def test_asking_to_restart_asks_for_confirmation_first(said):
    reply = say(said)

    assert reply.text == "To restart the kiosk, say restart now within 30 seconds."
    assert reply.then is None  # nothing happens yet


def test_restart_now_within_the_window_restarts():
    say("restart the kiosk")

    reply = say("Restart now.", now=NOW + timedelta(seconds=25))

    assert reply.then == "reboot"
    assert reply.text.startswith("Restarting now")


def test_confirming_too_late_only_asks_again():
    say("restart the kiosk")

    reply = say("restart now", now=NOW + timedelta(seconds=31))

    assert reply.then is None and "say restart now" in reply.text


def test_restart_now_on_its_own_still_needs_a_second_one():
    # Heard once out of the blue (the TV, a misheard phrase), it only arms it.
    assert say("restart now").then is None
    assert say("restart now", now=NOW + timedelta(seconds=5)).then == "reboot"


def test_one_confirmation_is_used_up():
    say("restart the kiosk")
    assert say("restart now", now=NOW + timedelta(seconds=5)).then == "reboot"

    assert say("restart now", now=NOW + timedelta(seconds=6)).then is None


@pytest.mark.parametrize("said", ["restart the timer", "restart the stopwatch", "reboot my alarm"])
def test_restarting_a_timer_is_not_restarting_the_computer(said):
    assert say(said).then is None
    assert "restart now" not in say(said).text


def test_a_machine_that_does_not_allow_it_says_so(monkeypatch):
    monkeypatch.setattr(restart.host, "can_reboot", lambda: False)

    reply = say("restart the kiosk")

    assert reply == Reply("I'm not allowed to restart this computer. The setup notes say how to allow it.", understood=False)


def test_it_can_be_turned_off(monkeypatch):
    monkeypatch.setattr(restart.settings, "voice_restart_enabled", False)

    assert say("restart the kiosk").text == "Restarting by voice is turned off."


# --- the reboot happens after the reply has been said -------------------------


class Speaker:
    name = "fake"

    def __init__(self, log):
        self.log = log

    async def speak(self, text):
        self.log.append(f"said: {text}")


@pytest.mark.anyio
async def test_the_restart_happens_after_saying_so():
    log = []

    async def action(name):
        log.append(f"did: {name}")

    session = VoiceSession(
        speaker_factory=lambda: Speaker(log),
        understand_fn=lambda text: Reply("Restarting now.", then="reboot"),
        action_fn=action,
    )

    await session.say_text("restart now")

    assert log == ["said: Restarting now.", "did: reboot"]
    assert session.history[-1]["reply"] == "Restarting now."  # recorded before the machine goes


@pytest.mark.anyio
async def test_a_failed_restart_is_logged_not_raised(caplog):
    async def broken(name):
        raise RuntimeError("sudo said no")

    session = VoiceSession(speaker_factory=lambda: None, understand_fn=lambda t: Reply("Restarting now.", then="reboot"),
                           action_fn=broken)  # fmt: skip

    with caplog.at_level("ERROR"):
        await session.say_text("restart now")

    assert any("Couldn't reboot" in r.message for r in caplog.records)


@pytest.mark.anyio
async def test_run_action_reboots_through_sudo_without_a_password_prompt(monkeypatch):
    ran = []
    monkeypatch.setattr(system, "reboot", lambda: ran.append(system._REBOOT))

    await run_action("reboot")

    assert ran == [["sudo", "-n", "systemctl", "reboot"]]  # -n: fail at once, never wait for a password


def test_can_reboot_only_asks_sudo_and_changes_nothing(monkeypatch):
    seen = {}

    class Result:
        returncode = 0

    def fake_run(command, **kwargs):
        seen["command"] = command
        return Result()

    monkeypatch.setattr(system.subprocess, "run", fake_run)

    assert REAL_CAN_REBOOT() is True
    assert seen["command"] == ["sudo", "-n", "-l", "systemctl", "reboot"]  # -l: list permission only


def test_can_reboot_is_false_without_sudo(monkeypatch):
    def missing(*args, **kwargs):
        raise FileNotFoundError("sudo")

    monkeypatch.setattr(system.subprocess, "run", missing)

    assert REAL_CAN_REBOOT() is False


def test_the_safety_net_stops_any_test_from_rebooting():
    with pytest.raises(AssertionError, match="tried to reboot"):
        system.reboot()
