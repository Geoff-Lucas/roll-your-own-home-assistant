import pytest

from app.browser import cdp
from app.browser.controller import BrowserController, BrowserUnavailable


@pytest.fixture
def controller(monkeypatch):
    """A controller that believes its browser is already running, with the
    DevTools layer replaced by a recorder."""
    instance = BrowserController()

    async def always_ready():
        return True

    async def nothing():
        return None

    monkeypatch.setattr(instance, "_ready", always_ready)
    monkeypatch.setattr(instance, "ensure_running", nothing)
    return instance


@pytest.fixture
def devtools(monkeypatch):
    calls = {"navigated": [], "sent": [], "reloaded": 0, "stepped": []}
    page = {"id": "P1", "url": "https://example.com/soup", "title": "Soup", "webSocketDebuggerUrl": "ws://x"}

    async def fake_navigate(url):
        calls["navigated"].append(url)

    async def fake_reload():
        calls["reloaded"] += 1

    async def fake_step(delta):
        calls["stepped"].append(delta)
        return True

    async def fake_first_page():
        return page

    async def fake_send(page_, method, params=None):
        calls["sent"].append(method)
        return {"currentIndex": 1, "entries": [{"id": 1}, {"id": 2}, {"id": 3}]}

    monkeypatch.setattr(cdp, "navigate", fake_navigate)
    monkeypatch.setattr(cdp, "reload", fake_reload)
    monkeypatch.setattr(cdp, "step_history", fake_step)
    monkeypatch.setattr(cdp, "first_page", fake_first_page)
    monkeypatch.setattr(cdp, "send", fake_send)
    return calls


@pytest.mark.anyio
async def test_navigate_normalizes_what_was_typed(controller, devtools):
    await controller.navigate("easy chicken soup")
    await controller.navigate("example.com")

    assert devtools["navigated"] == [
        "https://www.google.com/search?q=easy+chicken+soup",
        "https://example.com",
    ]


@pytest.mark.anyio
async def test_navigate_refuses_dangerous_schemes_before_touching_the_browser(controller, devtools):
    with pytest.raises(ValueError):
        await controller.navigate("javascript:alert(1)")

    assert devtools["navigated"] == []


@pytest.mark.anyio
async def test_back_forward_and_reload_are_passed_through(controller, devtools):
    await controller.back()
    await controller.forward()
    await controller.reload()

    assert devtools["stepped"] == [-1, +1]
    assert devtools["reloaded"] == 1


@pytest.mark.anyio
async def test_state_reports_the_page_and_which_history_buttons_work(controller, devtools):
    state = await controller.state()

    assert state == {
        "running": True,
        "url": "https://example.com/soup",
        "title": "Soup",
        "can_go_back": True,  # index 1 of 3 entries: something behind...
        "can_go_forward": True,  # ...and something ahead
    }


@pytest.mark.anyio
async def test_state_at_the_ends_of_history(controller, monkeypatch, devtools):
    async def at_start(page_, method, params=None):
        return {"currentIndex": 0, "entries": [{"id": 1}]}

    monkeypatch.setattr(cdp, "send", at_start)

    state = await controller.state()

    assert state["can_go_back"] is False
    assert state["can_go_forward"] is False


@pytest.mark.anyio
async def test_state_when_no_browser_is_running_does_not_launch_one(monkeypatch):
    instance = BrowserController()

    async def not_ready():
        return False

    async def must_not_launch():
        raise AssertionError("polling state must never start the browser")

    monkeypatch.setattr(instance, "_ready", not_ready)
    monkeypatch.setattr(instance, "ensure_running", must_not_launch)

    assert (await instance.state())["running"] is False
    assert await instance.current_url() is None
    await instance.hide()  # nothing to hide, and no error


@pytest.mark.anyio
async def test_launch_reports_a_missing_tool_clearly(monkeypatch):
    monkeypatch.setattr("app.browser.controller.shutil.which", lambda tool: None if tool == "wmctrl" else "/usr/bin/x")
    instance = BrowserController()

    with pytest.raises(BrowserUnavailable, match="wmctrl"):
        await instance._launch()


@pytest.mark.anyio
async def test_history_step_stops_at_the_ends(monkeypatch):
    sent = []

    async def fake_first_page():
        return {"webSocketDebuggerUrl": "ws://x"}

    async def fake_send(page, method, params=None):
        sent.append((method, params))
        return {"currentIndex": 0, "entries": [{"id": 10}, {"id": 11}]}

    monkeypatch.setattr(cdp, "first_page", fake_first_page)
    monkeypatch.setattr(cdp, "send", fake_send)

    assert await cdp.step_history(-1) is False  # already at the first entry
    assert [m for m, _ in sent] == ["Page.getNavigationHistory"]

    sent.clear()
    assert await cdp.step_history(+1) is True
    assert sent[-1] == ("Page.navigateToHistoryEntry", {"entryId": 11})
