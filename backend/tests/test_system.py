import pytest

from app import system


@pytest.fixture
def commands(monkeypatch):
    """Record every command instead of running it; xdotool says window 4242 has focus."""
    recorded = []

    def fake_run(command):
        recorded.append(command)
        return "4242\n" if command[:2] == ["xdotool", "getactivewindow"] else ""

    monkeypatch.setattr(system, "_run", fake_run)
    return recorded


@pytest.fixture
def panel(monkeypatch):
    """Record what happens to the desktop panel and to the watcher that hides it again."""
    events = []
    monkeypatch.setattr(system, "show_panel", lambda: events.append("show"))
    monkeypatch.setattr(system, "_start_watching", lambda window: events.append(f"watch {window}"))
    return events


def test_minimize_to_desktop_minimizes_the_focused_window(commands, panel):
    system.minimize_to_desktop()

    # The focused window, because the click that reached this came from inside
    # this app's own page, so that always is this app's window.
    assert commands == [["xdotool", "getactivewindow"], ["xdotool", "windowminimize", "4242"]]


def test_minimizing_brings_the_panel_back_and_watches_for_the_return(commands, panel):
    system.minimize_to_desktop()

    assert panel == ["show", "watch 4242"]


def test_nothing_is_minimized_or_shown_when_no_window_has_focus(monkeypatch, panel):
    monkeypatch.setattr(system, "_run", lambda command: "\n")

    with pytest.raises(system.SystemControlError, match="no window has focus"):
        system.minimize_to_desktop()

    assert panel == []


def test_a_failed_minimize_leaves_the_panel_hidden(monkeypatch, panel):
    def fails(command):
        if command[1] == "windowminimize":
            raise system.SystemControlError("windowminimize failed")
        return "4242"

    monkeypatch.setattr(system, "_run", fails)

    with pytest.raises(system.SystemControlError):
        system.minimize_to_desktop()

    assert panel == []


@pytest.fixture
def watch(monkeypatch):
    """Run the watcher's loop instantly, feeding it one window state per poll,
    and record when the panel is hidden."""

    def run(states, monkeypatch=monkeypatch):
        remaining = iter(states)
        hidden = []
        clock = {"now": 0.0}

        def sleep(seconds):
            clock["now"] += seconds

        monkeypatch.setattr(system.time, "sleep", sleep)
        monkeypatch.setattr(system.time, "monotonic", lambda: clock["now"])
        monkeypatch.setattr(system, "_window_state", lambda window: next(remaining))
        monkeypatch.setattr(system, "hide_panel", lambda: hidden.append(clock["now"]))
        system._hide_panel_once_restored("4242")
        return hidden

    return run


def test_the_panel_stays_while_the_app_is_minimized_and_goes_when_it_is_back(watch):
    hidden = watch(["Normal", "Iconic", "Iconic", "Iconic", "Normal"])

    assert hidden == [5.0]  # the fifth look, not before


def test_the_panel_goes_when_the_window_disappears(watch):
    assert watch(["Iconic", None]) == [2.0]


def test_the_panel_goes_if_the_window_never_gets_minimized(watch):
    # The minimize didn't take: give up after the grace period rather than watching forever.
    assert watch(["Normal"] * 10) == [5.0]


def test_only_one_watcher_runs_at_a_time(monkeypatch):
    started = []

    class FakeThread:
        def __init__(self, target, args, daemon):
            started.append(args)

        def start(self):
            pass

        def is_alive(self):
            return True

    monkeypatch.setattr(system.threading, "Thread", FakeThread)
    monkeypatch.setattr(system, "_watcher", None)

    system._start_watching("1")
    system._start_watching("2")

    assert started == [("1",)]


def test_a_window_reads_as_minimized_or_normal_or_gone(monkeypatch):
    outputs = {
        "min": "WM_STATE(WM_STATE):\n\t\twindow state: Iconic\n\t\ticon window: 0x0\n",
        "up": "WM_STATE(WM_STATE):\n\t\twindow state: Normal\n",
    }

    def fake_run(command):
        if command[-2] == "gone":
            raise system.SystemControlError("BadWindow")
        return outputs[command[-2]]

    monkeypatch.setattr(system, "_run", fake_run)

    assert [system._window_state(w) for w in ("min", "up", "gone")] == ["Iconic", "Normal", None]


def test_the_panel_is_started_detached_unless_it_is_already_running(monkeypatch):
    started = []
    monkeypatch.setattr(system.subprocess, "Popen", lambda command, **kwargs: started.append((command, kwargs)))
    monkeypatch.setattr(system, "_panel_is_running", lambda: False)

    system.show_panel()

    [(command, kwargs)] = started
    assert command == ["xfce4-panel"]
    assert kwargs["start_new_session"] is True
    assert kwargs["env"]["DISPLAY"] == system.settings.browser_display

    started.clear()
    monkeypatch.setattr(system, "_panel_is_running", lambda: True)
    system.show_panel()
    assert started == []


def test_a_panel_that_wont_start_doesnt_break_minimizing(monkeypatch):
    def cant(*args, **kwargs):
        raise FileNotFoundError("xfce4-panel")

    monkeypatch.setattr(system.subprocess, "Popen", cant)
    monkeypatch.setattr(system, "_panel_is_running", lambda: False)

    system.show_panel()  # logs, does not raise


def test_hiding_the_panel_quits_it(monkeypatch):
    seen = []

    class Result:
        returncode = 0

    monkeypatch.setattr(system.subprocess, "run", lambda command, **kwargs: seen.append(command) or Result())

    system.hide_panel()

    assert seen == [["xfce4-panel", "--quit"]]


def test_the_session_bus_is_found_from_the_runtime_directory(monkeypatch):
    monkeypatch.delenv("DBUS_SESSION_BUS_ADDRESS", raising=False)
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1000")

    assert system._env()["DBUS_SESSION_BUS_ADDRESS"] == "unix:path=/run/user/1000/bus"

    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:path=/elsewhere")
    assert system._env()["DBUS_SESSION_BUS_ADDRESS"] == "unix:path=/elsewhere"


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
