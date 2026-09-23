import pytest

from app import system


@pytest.fixture
def commands(monkeypatch):
    """Record every command instead of running it."""
    recorded = []
    monkeypatch.setattr(system, "_run", lambda command: recorded.append(command))
    return recorded


def test_minimize_to_desktop_minimizes_whatever_window_is_focused(commands):
    system.minimize_to_desktop()

    # Not a specific window id: the click that reached this came from inside
    # this app's own page, so the focused window always is this app's window.
    assert commands == [["xdotool", "getactivewindow", "windowminimize"]]


def test_a_missing_tool_reports_where_to_fix_it(monkeypatch):
    def not_installed(*args, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(system.subprocess, "run", not_installed)

    with pytest.raises(system.SystemControlError, match="not installed"):
        system._run(["xdotool", "getactivewindow", "windowminimize"])


def test_a_hung_command_times_out_rather_than_blocking(monkeypatch):
    def hangs(*args, **kwargs):
        raise system.subprocess.TimeoutExpired(cmd="xdotool", timeout=5)

    monkeypatch.setattr(system.subprocess, "run", hangs)

    with pytest.raises(system.SystemControlError, match="timed out"):
        system._run(["xdotool", "getactivewindow", "windowminimize"])


def test_a_failing_command_reports_its_stderr(monkeypatch):
    class Result:
        returncode = 1
        stdout = ""
        stderr = "no active window"

    monkeypatch.setattr(system.subprocess, "run", lambda *a, **k: Result())

    with pytest.raises(system.SystemControlError, match="no active window"):
        system._run(["xdotool", "getactivewindow", "windowminimize"])


def test_commands_run_against_the_configured_display(monkeypatch):
    seen = {}

    class Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(command, **kwargs):
        seen["display"] = kwargs["env"]["DISPLAY"]
        return Result()

    monkeypatch.setattr(system.subprocess, "run", fake_run)
    monkeypatch.setattr(system.settings, "browser_display", ":7")

    system._run(["xdotool", "version"])

    assert seen["display"] == ":7"
