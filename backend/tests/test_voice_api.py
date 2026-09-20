import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import voice as voice_module
from app.voice.core import Reply
from app.voice.session import VoiceBusy


class FakeVoice:
    """Stands in for the shared session: these are wiring tests for the HTTP layer."""

    def __init__(self):
        self.started = 0
        self.stopped = 0
        self.busy_on_start = False
        self.typed = []
        self.snap = {"state": "idle", "transcript": None, "reply": None, "understood": None, "error": None, "level": 0.0}

        class Transcriber:
            def status(inner):
                return (False, "The speech model 'base.en' isn't installed yet. Run: python -m app.voice.setup")

        self.transcriber = Transcriber()

    def wake_status(self):
        return {"enabled": True, "listening": True, "phrase": "Hey Jarvis"}

    async def start(self):
        if self.busy_on_start:
            raise VoiceBusy("Already listening")
        self.started += 1
        self.snap = {**self.snap, "state": "listening"}

    def stop(self):
        self.stopped += 1

    def snapshot(self):
        return self.snap

    async def say_text(self, text, speak=True):
        if self.busy_on_start:
            raise VoiceBusy("Already busy")
        self.typed.append((text, speak))
        return Reply("It's 3 PM.")


@pytest.fixture
def setup(monkeypatch):
    fake = FakeVoice()
    monkeypatch.setattr(voice_module, "voice", fake)
    app = FastAPI()
    app.include_router(voice_module.router)
    return TestClient(app), fake


def test_start_begins_listening_and_returns_the_state(setup):
    client, fake = setup

    res = client.post("/voice/start")

    assert res.status_code == 202
    assert res.json()["state"] == "listening"
    assert fake.started == 1


def test_start_while_busy_is_a_409(setup):
    client, fake = setup
    fake.busy_on_start = True

    assert client.post("/voice/start").status_code == 409


def test_stop(setup):
    client, fake = setup

    assert client.post("/voice/stop").status_code == 204
    assert fake.stopped == 1


def test_state_is_what_the_session_reports(setup):
    client, fake = setup
    fake.snap = {**fake.snap, "state": "done", "reply": "Timer set for 10 minutes."}

    assert client.get("/voice/state").json()["reply"] == "Timer set for 10 minutes."


def test_a_typed_command_runs_through_the_same_path(setup):
    client, fake = setup

    res = client.post("/voice/text", json={"text": "what time is it"})

    assert res.json() == {"reply": "It's 3 PM.", "understood": True}
    assert fake.typed == [("what time is it", True)]


def test_a_typed_command_can_skip_speaking(setup):
    client, fake = setup

    client.post("/voice/text", json={"text": "what time is it", "speak": False})

    assert fake.typed == [("what time is it", False)]


@pytest.mark.parametrize("body", [{}, {"text": ""}, {"text": "x" * 301}])
def test_typed_commands_are_validated(setup, body):
    client, fake = setup

    assert client.post("/voice/text", json=body).status_code == 422
    assert fake.typed == []


def test_a_typed_command_while_busy_is_a_409(setup):
    client, fake = setup
    fake.busy_on_start = True

    assert client.post("/voice/text", json={"text": "hi"}).status_code == 409


def test_status_explains_what_is_missing(setup, monkeypatch):
    client, _ = setup
    monkeypatch.setattr(voice_module.shutil, "which", lambda name: "/usr/bin/arecord")
    monkeypatch.setattr(voice_module, "choose_speaker", lambda: None)

    body = client.get("/voice/status").json()

    assert body["microphone"] is True
    assert body["speech_recognition"]["ready"] is False
    assert "python -m app.voice.setup" in body["speech_recognition"]["detail"]
    assert body["speaker"] is None
    assert body["wake_word"] == {"enabled": True, "listening": True, "phrase": "Hey Jarvis"}
