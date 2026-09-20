import asyncio

import pytest

from app.voice import ringing
from app.voice.core import Reply
from app.voice.mic import mic_lock
from app.voice.recorder import MicUnavailable, Recording
from app.voice.ringing import RingListener

HALF_SECOND = b"\x01\x00" * 8000


class FakeRecorder:
    def __init__(self, recording=None, error=None):
        self.recording = recording or Recording(HALF_SECOND, "done")
        self.error = error
        self.calls = []
        self.lock_held_while_recording = None

    async def record(self, stop, on_level, *, start_timeout=None, max_seconds=None):
        self.calls.append({"start_timeout": start_timeout, "max_seconds": max_seconds})
        self.lock_held_while_recording = mic_lock.locked()
        if self.error:
            raise self.error
        return self.recording


class FakeTranscriber:
    def __init__(self, text="stop", ready=True, error=None):
        self.text = text
        self.ready = ready
        self.error = error
        self.heard = []

    def status(self):
        return (self.ready, "ready" if self.ready else "no model")

    def transcribe(self, pcm):
        self.heard.append(pcm)
        if self.error:
            raise self.error
        return self.text


class FakeWake:
    def __init__(self):
        self.log = []

    async def pause(self):
        self.log.append("pause")

    def resume(self):
        self.log.append("resume")


class FakeSpeaker:
    name = "fake"

    def __init__(self, fail=False):
        self.said = []
        self.fail = fail

    async def speak(self, text):
        if self.fail:
            raise RuntimeError("no voice")
        self.said.append(text)


def make(*, recorder=None, transcriber=None, apply=None, speaker=None, wake=None, history=None):
    applied = []

    def apply_fn(text):
        applied.append(text)
        return apply(text) if apply else Reply("Okay.")

    listener = RingListener(
        recorder=recorder or FakeRecorder(),
        transcriber=transcriber or FakeTranscriber(),
        apply_fn=apply_fn,
        speaker_factory=lambda: speaker,
        wake_getter=lambda: wake,
        history=history,
    )
    listener.applied = applied
    return listener


@pytest.fixture(autouse=True)
def enabled(monkeypatch):
    monkeypatch.setattr(ringing.settings, "voice_ring_listen", True)
    monkeypatch.setattr(ringing.settings, "voice_ring_window_seconds", 3.0)
    monkeypatch.setattr(ringing.settings, "voice_ring_max_utterance_seconds", 5.0)


@pytest.mark.anyio
async def test_a_heard_command_is_recognized_applied_and_answered():
    speaker = FakeSpeaker()
    transcriber = FakeTranscriber(text="Stop.")
    listener = make(transcriber=transcriber, speaker=speaker)

    assert await listener.listen_once() is True

    assert transcriber.heard == [HALF_SECOND]
    assert listener.applied == ["Stop."]
    assert speaker.said == ["Okay."]


@pytest.mark.anyio
async def test_the_listening_window_is_short_and_configured():
    recorder = FakeRecorder()
    listener = make(recorder=recorder)

    await listener.listen_once()

    assert recorder.calls == [{"start_timeout": 3.0, "max_seconds": 5.0}]


@pytest.mark.anyio
async def test_nothing_said_means_no_command_and_no_recognition():
    transcriber = FakeTranscriber()
    listener = make(recorder=FakeRecorder(Recording(b"", "no_speech")), transcriber=transcriber)

    assert await listener.listen_once() is False
    assert transcriber.heard == []  # doesn't spend a second recognizing silence


@pytest.mark.anyio
async def test_speech_that_is_not_a_command_is_left_alone_and_logged():
    history = []
    speaker = FakeSpeaker()
    listener = make(
        transcriber=FakeTranscriber(text="We should pick up eggs"),
        apply=lambda text: None,  # the strict matcher declines
        speaker=speaker,
        history=history,
    )

    assert await listener.listen_once() is False

    assert speaker.said == []  # says nothing back to overheard conversation
    (entry,) = history
    assert entry["via"] == "ringing" and entry["ignored"] is True
    assert entry["transcript"] == "We should pick up eggs" and entry["reply"] is None


@pytest.mark.anyio
async def test_a_handled_command_is_logged_too():
    history = []
    listener = make(history=history)

    await listener.listen_once()

    assert history[0]["reply"] == "Okay." and history[0]["ignored"] is False


@pytest.mark.anyio
async def test_the_wake_word_listener_is_paused_and_always_resumed():
    wake = FakeWake()
    recorder = FakeRecorder()
    listener = make(recorder=recorder, wake=wake)

    await listener.listen_once()

    assert wake.log == ["pause", "resume"]
    assert recorder.lock_held_while_recording is True  # the microphone lock is held while recording


@pytest.mark.anyio
async def test_the_wake_word_listener_resumes_even_if_the_microphone_fails():
    wake = FakeWake()
    listener = make(recorder=FakeRecorder(error=MicUnavailable("gone")), wake=wake)

    assert await listener.listen_once() is False

    assert wake.log == ["pause", "resume"]
    assert not mic_lock.locked()  # and the lock is released


@pytest.mark.anyio
async def test_a_missing_microphone_is_reported_once_not_every_chime(caplog):
    listener = make(recorder=FakeRecorder(error=MicUnavailable("gone")))

    with caplog.at_level("WARNING"):
        for _ in range(3):
            await listener.listen_once()

    assert sum("Can't listen" in r.message for r in caplog.records) == 1


@pytest.mark.anyio
async def test_it_never_takes_the_microphone_from_a_conversation():
    recorder = FakeRecorder()
    listener = make(recorder=recorder)

    async with mic_lock:  # a tap-to-talk or wake-word conversation is recording
        assert await listener.listen_once() is False

    assert recorder.calls == []


@pytest.mark.anyio
async def test_it_is_off_when_disabled_or_speech_recognition_is_missing(monkeypatch):
    recorder = FakeRecorder()

    monkeypatch.setattr(ringing.settings, "voice_ring_listen", False)
    listener = make(recorder=recorder)
    assert listener.available() is False and await listener.listen_once() is False

    monkeypatch.setattr(ringing.settings, "voice_ring_listen", True)
    listener = make(recorder=recorder, transcriber=FakeTranscriber(ready=False))
    assert listener.available() is False and await listener.listen_once() is False

    assert recorder.calls == []  # never opened the microphone


@pytest.mark.anyio
async def test_a_recognizer_failure_is_contained(caplog):
    listener = make(transcriber=FakeTranscriber(error=RuntimeError("boom")))

    with caplog.at_level("ERROR"):
        assert await listener.listen_once() is False

    assert any("Couldn't handle speech" in r.message for r in caplog.records)


@pytest.mark.anyio
async def test_a_broken_speaker_does_not_undo_the_dismissal():
    listener = make(speaker=FakeSpeaker(fail=True))

    assert await listener.listen_once() is True  # the command was still handled


@pytest.mark.anyio
async def test_with_no_speaker_the_command_still_works():
    assert await make(speaker=None).listen_once() is True


@pytest.mark.anyio
async def test_the_lock_is_free_again_afterwards():
    await make().listen_once()

    assert not mic_lock.locked()
    await asyncio.wait_for(mic_lock.acquire(), timeout=1)
    mic_lock.release()
