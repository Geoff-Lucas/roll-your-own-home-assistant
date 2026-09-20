import asyncio

import pytest

from app.voice.core import Reply
from app.voice.recorder import MicUnavailable, Recording
from app.voice.session import VoiceBusy, VoiceSession
from app.voice.stt import SpeechRecognitionUnavailable

HALF_SECOND = b"\x01\x00" * 8000


class FakeRecorder:
    def __init__(self, recording=None, error=None):
        self.recording = recording or Recording(HALF_SECOND, "done")
        self.error = error
        self.calls = 0
        self.stop_seen = None
        self.states = []
        self.session = None

    async def record(self, stop, on_level):
        self.calls += 1
        self.stop_seen = stop
        if self.session:
            self.states.append(self.session.state)
        on_level(1500.0)
        if self.error:
            raise self.error
        return self.recording


class FakeTranscriber:
    def __init__(self, text="set a timer for ten minutes", ready=(True, "ready"), error=None):
        self.text = text
        self._ready = ready
        self.error = error
        self.heard = None

    def status(self):
        return self._ready

    def transcribe(self, pcm):
        self.heard = pcm
        if self.error:
            raise self.error
        return self.text


class FakeSpeaker:
    name = "fake"

    def __init__(self, fail=False):
        self.said = []
        self.fail = fail
        self.session = None
        self.state_when_spoken = None

    async def speak(self, text):
        self.state_when_spoken = self.session.state if self.session else None
        if self.fail:
            raise RuntimeError("speaker on fire")
        self.said.append(text)


class FakeWake:
    phrase = "Hey Jarvis"
    listening = True
    threshold = 0.5
    recent_peak_score = 0.25
    recent_peak_level = 1200.4

    def __init__(self, log=None):
        self.log = log if log is not None else []

    async def pause(self):
        self.log.append("pause")

    def resume(self):
        self.log.append("resume")


def make(recorder=None, transcriber=None, speaker=None, reply=Reply("Timer set for 10 minutes."), understood=None, ack=None, wake=None):
    heard = []

    def understand(text):
        heard.append(text)
        return understood(text) if understood else reply

    session = VoiceSession(
        recorder=recorder or FakeRecorder(),
        transcriber=transcriber or FakeTranscriber(),
        speaker_factory=lambda: speaker,
        understand_fn=understand,
        **({"ack_fn": ack} if ack else {}),
    )
    if wake is not None:
        session.attach_wake(wake)
        session.resume_delay = 0  # don't make the tests wait out the real settling time
    for part in (session.recorder, speaker):
        if part is not None:
            part.session = session
    session.heard = heard
    return session


async def run(session):
    await session.start()
    await session._task
    return session.snapshot()


@pytest.mark.anyio
async def test_a_spoken_command_is_recorded_understood_and_answered_aloud():
    speaker = FakeSpeaker()
    session = make(speaker=speaker)

    result = await run(session)

    assert result["state"] == "done"
    assert result["transcript"] == "set a timer for ten minutes"
    assert result["reply"] == "Timer set for 10 minutes."
    assert result["understood"] is True
    assert result["error"] is None
    assert session.heard == ["set a timer for ten minutes"]
    assert speaker.said == ["Timer set for 10 minutes."]
    assert speaker.state_when_spoken == "speaking"
    assert session.recorder.states == ["listening"]


@pytest.mark.anyio
async def test_the_recording_goes_to_the_transcriber_untouched():
    transcriber = FakeTranscriber()
    session = make(transcriber=transcriber)

    await run(session)

    assert transcriber.heard == HALF_SECOND


@pytest.mark.anyio
async def test_the_level_meter_follows_the_microphone_then_resets():
    session = make()
    levels = []
    original = session._on_level
    session._on_level = lambda value: (original(value), levels.append(session.level))

    await run(session)

    assert levels == [0.5]  # 1500 of 3000 full-scale
    assert session.level == 0.0


@pytest.mark.anyio
async def test_hearing_nothing_is_reported_and_nothing_is_transcribed():
    transcriber = FakeTranscriber()
    session = make(recorder=FakeRecorder(Recording(b"", "no_speech")), transcriber=transcriber)

    result = await run(session)

    assert result["error"] == "I didn't hear anything."
    assert transcriber.heard is None
    assert result["reply"] is None


@pytest.mark.anyio
async def test_a_tap_that_stops_the_recording_at_once_counts_as_hearing_nothing():
    session = make(recorder=FakeRecorder(Recording(b"\x01\x00" * 50, "stopped")))

    assert (await run(session))["error"] == "I didn't hear anything."


@pytest.mark.anyio
async def test_unintelligible_audio_is_reported():
    session = make(transcriber=FakeTranscriber(text=""))

    result = await run(session)

    assert result["error"] == "I couldn't make that out."
    assert session.heard == []


@pytest.mark.anyio
async def test_a_missing_speech_model_is_explained_before_any_recording():
    recorder = FakeRecorder()
    session = make(
        recorder=recorder,
        transcriber=FakeTranscriber(ready=(False, "The speech model 'base.en' isn't installed yet. Run: python -m app.voice.setup")),
    )

    result = await run(session)

    assert "isn't installed yet" in result["error"]
    assert recorder.calls == 0  # doesn't make someone speak into a dead microphone


@pytest.mark.anyio
async def test_a_broken_microphone_surfaces_its_message():
    session = make(recorder=FakeRecorder(error=MicUnavailable("The microphone isn't sending any audio")))

    assert (await run(session))["error"] == "The microphone isn't sending any audio"


@pytest.mark.anyio
async def test_a_recognizer_that_fails_at_load_time_is_reported():
    session = make(transcriber=FakeTranscriber(error=SpeechRecognitionUnavailable("model files are corrupt")))

    assert (await run(session))["error"] == "model files are corrupt"


@pytest.mark.anyio
async def test_an_unexpected_failure_is_contained_and_the_session_recovers():
    session = make(transcriber=FakeTranscriber(error=RuntimeError("boom")))

    assert (await run(session))["error"] == "Something went wrong."

    session.transcriber.error = None
    assert (await run(session))["error"] is None  # usable again


@pytest.mark.anyio
async def test_a_second_start_while_listening_is_refused():
    gate = asyncio.Event()

    class SlowRecorder(FakeRecorder):
        async def record(self, stop, on_level):
            await gate.wait()
            return await super().record(stop, on_level)

    session = make(recorder=SlowRecorder())
    await session.start()

    assert session.state == "listening" and session.busy
    with pytest.raises(VoiceBusy):
        await session.start()
    with pytest.raises(VoiceBusy):
        await session.say_text("what time is it")

    gate.set()
    await session._task
    assert not session.busy


@pytest.mark.anyio
async def test_stop_signals_the_recorder():
    session = make()
    await session.start()

    session.stop()
    await session._task

    assert session.recorder.stop_seen.is_set()  # the recorder was handed the event that stop() sets


@pytest.mark.anyio
async def test_a_reply_survives_a_broken_speaker():
    session = make(speaker=FakeSpeaker(fail=True))

    result = await run(session)

    assert result["reply"] == "Timer set for 10 minutes."  # still on screen
    assert result["error"] is None
    assert result["state"] == "done"


@pytest.mark.anyio
async def test_with_no_speaker_the_reply_is_still_shown():
    session = make(speaker=None)

    result = await run(session)

    assert result["reply"] == "Timer set for 10 minutes."
    assert result["state"] == "done"


@pytest.mark.anyio
async def test_replies_are_cleaned_up_for_the_speaker():
    speaker = FakeSpeaker()
    session = make(speaker=speaker, reply=Reply("**Timer** set   for\n10 minutes."))

    await run(session)

    assert speaker.said == ["Timer set for 10 minutes."]


@pytest.mark.anyio
async def test_an_unrecognized_command_is_marked_as_not_understood():
    session = make(reply=Reply("Sorry, I don't know how to help with that yet.", understood=False))

    assert (await run(session))["understood"] is False


@pytest.mark.anyio
async def test_typed_commands_use_the_same_path_without_the_microphone():
    speaker = FakeSpeaker()
    session = make(speaker=speaker)

    reply = await session.say_text("what time is it")

    assert reply.text == "Timer set for 10 minutes."
    assert session.recorder.calls == 0
    assert session.transcript == "what time is it"
    assert speaker.said == ["Timer set for 10 minutes."]
    assert session.state == "done"


@pytest.mark.anyio
async def test_typed_commands_can_skip_speaking():
    speaker = FakeSpeaker()
    session = make(speaker=speaker)

    await session.say_text("what time is it", speak=False)

    assert speaker.said == []


@pytest.mark.anyio
async def test_starting_again_clears_the_previous_result():
    session = make()
    await run(session)
    assert session.reply

    await session.start()
    assert session.reply is None and session.transcript is None
    await session._task


@pytest.mark.anyio
async def test_each_interaction_is_kept_in_a_short_history_with_timings():
    session = make(speaker=FakeSpeaker())

    await run(session)

    (entry,) = session.history
    assert entry["transcript"] == "set a timer for ten minutes"
    assert entry["reply"] == "Timer set for 10 minutes."
    assert entry["understood"] is True and entry["error"] is None
    assert entry["recorded_seconds"] == 0.5  # HALF_SECOND of audio
    assert entry["recognized_in_seconds"] >= 0
    assert entry["at"]


@pytest.mark.anyio
async def test_failures_are_in_the_history_too():
    session = make(recorder=FakeRecorder(Recording(b"", "no_speech")))

    await run(session)

    assert session.history[-1]["error"] == "I didn't hear anything."
    assert session.history[-1]["transcript"] is None


@pytest.mark.anyio
async def test_typed_commands_are_recorded_without_timings():
    session = make()

    await session.say_text("what time is it")

    entry = session.history[-1]
    assert entry["transcript"] == "what time is it"
    assert "recorded_seconds" not in entry


@pytest.mark.anyio
async def test_the_history_is_capped_and_a_new_interaction_does_not_inherit_old_timings():
    session = make()
    for _ in range(30):
        await session.say_text("hi", speak=False)
    await run(session)  # a real recording, so it has timings
    await session.say_text("hi again", speak=False)  # ...and this one must not carry them over

    assert len(session.history) == 25
    assert "recorded_seconds" not in session.history[-1]


# --- hands-free: sharing the microphone with the wake-word listener ----------


@pytest.mark.anyio
async def test_the_wake_listener_is_paused_before_recording_and_resumed_after_the_reply():
    log = []
    wake = FakeWake(log)

    class LoggingRecorder(FakeRecorder):
        async def record(self, stop, on_level):
            log.append("record")
            return await super().record(stop, on_level)

    speaker = FakeSpeaker()
    speaker_speak = speaker.speak

    async def logged_speak(text):
        log.append("speak")
        await speaker_speak(text)

    speaker.speak = logged_speak
    session = make(recorder=LoggingRecorder(), speaker=speaker, wake=wake)

    await run(session)
    await asyncio.sleep(0.01)

    # The microphone is released first, and only handed back once the reply is done.
    assert log == ["pause", "record", "speak", "resume"]


@pytest.mark.anyio
async def test_the_wake_listener_is_resumed_even_when_the_interaction_fails():
    for session_kwargs in (
        {"recorder": FakeRecorder(error=MicUnavailable("gone"))},
        {"recorder": FakeRecorder(Recording(b"", "no_speech"))},
        {"transcriber": FakeTranscriber(ready=(False, "model missing"))},
        {"transcriber": FakeTranscriber(error=RuntimeError("boom"))},
    ):
        wake = FakeWake()
        session = make(wake=wake, **session_kwargs)

        await run(session)
        await asyncio.sleep(0.01)

        assert wake.log == ["pause", "resume"], session_kwargs  # never left deaf


@pytest.mark.anyio
async def test_the_acknowledgement_tone_plays_before_the_microphone_opens():
    order = []

    async def ack():
        order.append("ack")

    class OrderedRecorder(FakeRecorder):
        async def record(self, stop, on_level):
            order.append("record")
            return await super().record(stop, on_level)

    session = make(recorder=OrderedRecorder(), ack=ack)

    await session.start(ack=True)
    await session._task

    assert order == ["ack", "record"]  # not the other way: the mic would hear the tone


@pytest.mark.anyio
async def test_a_plain_tap_has_no_acknowledgement_tone():
    played = []

    async def ack():
        played.append(1)

    session = make(ack=ack)

    await session.start()
    await session._task

    assert played == []


@pytest.mark.anyio
async def test_the_interface_shows_listening_immediately_even_while_the_tone_plays():
    seen = []
    session = make()

    async def slow_ack():
        seen.append(session.state)

    session._ack = slow_ack

    await session.start(ack=True)
    assert session.state == "listening"  # the panel can open before the tone has finished
    await session._task

    assert seen == ["listening"]


def test_wake_status_reflects_whether_a_listener_is_attached():
    plain = make()
    assert plain.wake_status() == {"enabled": False, "listening": False, "phrase": None}

    plain.attach_wake(FakeWake())
    assert plain.wake_status() == {
        "enabled": True,
        "listening": True,
        "phrase": "Hey Jarvis",
        "threshold": 0.5,
        "recent_peak_score": 0.25,
        "recent_peak_level": 1200,
    }

