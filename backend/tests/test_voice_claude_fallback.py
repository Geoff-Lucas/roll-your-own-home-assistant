from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.voice import core
from app.voice.skills import claude_fallback as fallback

NEW_YORK = ZoneInfo("America/New_York")
NOW = datetime(2026, 9, 22, 19, 30)  # 3:30 PM local (EDT)

WEATHER = {
    "current": {"temperature": 68.4, "description": "Partly cloudy"},
    "unit": "°F",
}


def context(**overrides):
    fields = dict(session=None, now=NOW, tz=NEW_YORK, weather=WEATHER, location_name="Fairfax, VA")
    fields.update(overrides)
    return core.Context(**fields)


@pytest.fixture(autouse=True)
def configured(monkeypatch):
    """On, with a (fake) key — most tests want the happy path; a few turn it
    back off to check that route stays untouched."""
    monkeypatch.setattr(fallback.settings, "voice_claude_enabled", True)
    monkeypatch.setattr(fallback.settings, "voice_claude_api_key", "sk-test-key")
    monkeypatch.setattr(fallback.settings, "voice_claude_model", "claude-test-model")
    monkeypatch.setattr(fallback.settings, "voice_claude_timeout_seconds", 5.0)


# --- when it's not turned on -------------------------------------------------


def test_it_is_unavailable_without_being_enabled(monkeypatch):
    monkeypatch.setattr(fallback.settings, "voice_claude_enabled", False)
    assert fallback.available() is False


def test_it_is_unavailable_without_an_api_key(monkeypatch):
    monkeypatch.setattr(fallback.settings, "voice_claude_api_key", "")
    assert fallback.available() is False


def test_disabled_it_declines_exactly_like_any_other_skill(monkeypatch):
    monkeypatch.setattr(fallback.settings, "voice_claude_enabled", False)

    assert fallback.handle("what's a good buttermilk substitute", context()) is None


# --- grounding: what gets sent alongside the question ------------------------


def test_the_question_and_a_grounded_system_prompt_are_sent(monkeypatch):
    seen = {}

    def fake_call(system, text):
        seen["system"] = system
        seen["text"] = text
        return "Plain yogurt works well."

    monkeypatch.setattr(fallback, "_call_claude", fake_call)

    fallback.handle("what's a good buttermilk substitute", context())

    assert seen["text"] == "what's a good buttermilk substitute"
    assert "Tuesday, September 22, 2026" in seen["system"]
    assert "3:30 PM" in seen["system"]
    assert "Fairfax, VA" in seen["system"]
    assert "Partly cloudy" in seen["system"] and "68°F" in seen["system"]
    assert "one or two short" in seen["system"]  # the reply-aloud instruction is always there


def test_missing_weather_or_location_are_just_left_out(monkeypatch):
    seen = {}
    monkeypatch.setattr(fallback, "_call_claude", lambda system, text: seen.setdefault("system", system) or "ok")

    fallback.handle("hello", context(weather=None, location_name=None))

    assert "near" not in seen["system"]
    assert "weather" not in seen["system"].lower()


# --- the reply ----------------------------------------------------------------


def test_a_good_answer_is_understood(monkeypatch):
    monkeypatch.setattr(fallback, "_call_claude", lambda system, text: "Plain yogurt works well.")

    reply = fallback.handle("what's a good buttermilk substitute", context())

    assert reply == core.Reply("Plain yogurt works well.")
    assert reply.understood is True


def test_an_empty_answer_is_treated_as_unavailable(monkeypatch):
    monkeypatch.setattr(fallback, "_call_claude", lambda system, text: "   ")

    reply = fallback.handle("hello", context())

    assert reply == core.Reply(fallback.UNAVAILABLE, understood=False)


def test_a_network_or_api_failure_is_reported_not_raised(monkeypatch, caplog):
    def broken(system, text):
        raise RuntimeError("connection reset")

    monkeypatch.setattr(fallback, "_call_claude", broken)

    with caplog.at_level("ERROR"):
        reply = fallback.handle("hello", context())

    assert reply == core.Reply(fallback.UNAVAILABLE, understood=False)
    assert any("Claude fallback failed" in r.message for r in caplog.records)


# --- the actual network call, isolated from the rest of the above ------------


def test_the_api_is_called_with_the_configured_model_key_and_timeout(monkeypatch):
    seen = {}

    class FakeMessages:
        def create(self, **kwargs):
            seen["kwargs"] = kwargs

            class Block:
                type = "text"
                text = "Sure, here's an answer."

            class Response:
                content = [Block()]

            return Response()

    class FakeClient:
        def __init__(self, **kwargs):
            seen["client_kwargs"] = kwargs
            self.messages = FakeMessages()

    fake_anthropic = type("module", (), {"Anthropic": FakeClient})
    monkeypatch.setitem(__import__("sys").modules, "anthropic", fake_anthropic)

    answer = fallback._call_claude("system prompt", "a question")

    assert answer == "Sure, here's an answer."
    assert seen["client_kwargs"] == {"api_key": "sk-test-key", "timeout": 5.0}
    assert seen["kwargs"]["model"] == "claude-test-model"
    assert seen["kwargs"]["system"] == "system prompt"
    assert seen["kwargs"]["messages"] == [{"role": "user", "content": "a question"}]
    assert seen["kwargs"]["max_tokens"] == fallback.MAX_TOKENS
    assert seen["kwargs"]["tools"] == []  # off unless explicitly turned on


def test_web_search_is_off_by_default():
    assert fallback._tools() == []


def test_web_search_is_added_when_turned_on(monkeypatch):
    monkeypatch.setattr(fallback.settings, "voice_claude_web_search", True)
    monkeypatch.setattr(fallback.settings, "voice_claude_web_search_max_uses", 5)

    assert fallback._tools() == [{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}]


def test_the_search_tool_is_included_in_the_actual_request_when_on(monkeypatch):
    monkeypatch.setattr(fallback.settings, "voice_claude_web_search", True)
    seen = {}

    class FakeMessages:
        def create(self, **kwargs):
            seen["kwargs"] = kwargs

            class Block:
                type = "text"
                text = "It's 72 today."

            class Response:
                content = [Block()]

            return Response()

    class FakeClient:
        def __init__(self, **kwargs):
            self.messages = FakeMessages()

    fake_anthropic = type("module", (), {"Anthropic": FakeClient})
    monkeypatch.setitem(__import__("sys").modules, "anthropic", fake_anthropic)

    fallback._call_claude("system", "what's the weather in Tokyo")

    assert seen["kwargs"]["tools"] == [{"type": "web_search_20250305", "name": "web_search", "max_uses": 3}]


def test_only_text_blocks_are_read_and_multiple_are_joined(monkeypatch):
    class Block:
        def __init__(self, type_, text=""):
            self.type = type_
            self.text = text

    class FakeMessages:
        def create(self, **kwargs):
            class Response:
                content = [Block("text", "Part one. "), Block("tool_use"), Block("text", "Part two.")]

            return Response()

    class FakeClient:
        def __init__(self, **kwargs):
            self.messages = FakeMessages()

    fake_anthropic = type("module", (), {"Anthropic": FakeClient})
    monkeypatch.setitem(__import__("sys").modules, "anthropic", fake_anthropic)

    assert fallback._call_claude("system", "text") == "Part one. Part two."


def test_a_reply_cut_off_before_any_answer_is_logged_with_why(monkeypatch, caplog):
    # The shape seen live: reasoning and searching used up the token budget.
    class Block:
        def __init__(self, type_):
            self.type = type_

    class FakeMessages:
        def create(self, **kwargs):
            class Response:
                stop_reason = "max_tokens"
                content = [Block("thinking"), Block("server_tool_use"), Block("web_search_tool_result")]

            return Response()

    class FakeClient:
        def __init__(self, **kwargs):
            self.messages = FakeMessages()

    fake_anthropic = type("module", (), {"Anthropic": FakeClient})
    monkeypatch.setitem(__import__("sys").modules, "anthropic", fake_anthropic)

    with caplog.at_level("WARNING"):
        assert fallback._call_claude("system", "what was the score") == ""

    (record,) = [r for r in caplog.records if "no answer" in r.message]
    assert "max_tokens" in record.message and "web_search_tool_result" in record.message


def test_the_token_cap_leaves_room_for_reasoning_and_searching():
    assert fallback.MAX_TOKENS >= 1024


def test_search_result_blocks_are_skipped_the_same_way(monkeypatch):
    # The block types a search actually adds, not just a generic stand-in.
    class Block:
        def __init__(self, type_, text=""):
            self.type = type_
            self.text = text

    class FakeMessages:
        def create(self, **kwargs):
            class Response:
                content = [
                    Block("server_tool_use"),
                    Block("web_search_tool_result"),
                    Block("text", "It's 72 and sunny today."),
                ]

            return Response()

    class FakeClient:
        def __init__(self, **kwargs):
            self.messages = FakeMessages()

    fake_anthropic = type("module", (), {"Anthropic": FakeClient})
    monkeypatch.setitem(__import__("sys").modules, "anthropic", fake_anthropic)

    assert fallback._call_claude("system", "what's the weather") == "It's 72 and sunny today."
