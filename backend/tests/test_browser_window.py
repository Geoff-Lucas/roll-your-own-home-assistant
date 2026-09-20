import pytest

from app.browser import window


@pytest.fixture
def commands(monkeypatch):
    """Record every command instead of running it, and skip the settle delays."""
    recorded = []
    monkeypatch.setattr(window, "_run", lambda command: recorded.append(command) or "")
    monkeypatch.setattr(window.time, "sleep", lambda _seconds: None)
    return recorded


def test_place_shows_the_window_frameless_at_the_exact_rectangle_above_the_app(commands):
    window.place("123", 0, 330, 1440, 1500)

    assert commands == [
        ["xdotool", "windowmap", "123"],
        # Out of fullscreen (kiosk mode draws no frame, so this leaves a frameless window)...
        ["wmctrl", "-i", "-r", "123", "-b", "remove,fullscreen"],
        # ...sized exactly...
        ["wmctrl", "-i", "-r", "123", "-e", "0,0,330,1440,1500"],
        # ...and always on top of the app's own window.
        ["wmctrl", "-i", "-r", "123", "-b", "add,above"],
    ]


def test_hide_unmaps_the_window_without_closing_it(commands):
    window.hide("123")

    assert commands == [["xdotool", "windowunmap", "123"]]


def test_find_window_picks_the_largest_id_and_handles_no_match(monkeypatch):
    monkeypatch.setattr(window, "_run", lambda command: "111 222 333\n")
    assert window.find_window(42) == "333"

    def no_match(command):
        raise window.WindowError("xdotool exits non-zero when nothing matches")

    monkeypatch.setattr(window, "_run", no_match)
    assert window.find_window(42) is None


def test_exists_reflects_whether_the_window_can_be_queried(monkeypatch):
    monkeypatch.setattr(window, "_run", lambda command: "Some Title")
    assert window.exists("123") is True

    def gone(command):
        raise window.WindowError("no such window")

    monkeypatch.setattr(window, "_run", gone)
    assert window.exists("123") is False


def test_a_missing_tool_reports_where_to_fix_it(monkeypatch):
    def not_installed(*args, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(window.subprocess, "run", not_installed)

    with pytest.raises(window.WindowError, match="not installed"):
        window._run(["wmctrl", "-l"])


def test_commands_run_against_the_configured_display(monkeypatch):
    seen = {}

    class Result:
        returncode = 0
        stdout = "ok"
        stderr = ""

    def fake_run(command, **kwargs):
        seen["display"] = kwargs["env"]["DISPLAY"]
        return Result()

    monkeypatch.setattr(window.subprocess, "run", fake_run)
    monkeypatch.setattr(window.settings, "browser_display", ":7")

    window._run(["xdotool", "version"])

    assert seen["display"] == ":7"
