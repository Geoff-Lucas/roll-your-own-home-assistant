import asyncio
import struct

import pytest

from app.voice import recorder
from app.voice.recorder import CHUNK_BYTES, CHUNK_SECONDS, EndpointDetector, MicUnavailable, Recording, rms


def pcm_at(level: int) -> bytes:
    """A chunk of audio whose loudness (rms) is `level`."""
    return struct.pack("<h", level) * (CHUNK_BYTES // 2)


def detector(**overrides):
    settings = dict(silence_seconds=1.1, start_timeout=6.0, max_seconds=15.0)
    settings.update(overrides)
    return EndpointDetector(**settings)


def feed(det, levels):
    """Feed levels until the detector stops; returns (verdict, chunks used)."""
    for used, level in enumerate(levels, start=1):
        verdict = det.feed(level)
        if verdict:
            return verdict, used
    return None, len(levels)


QUIET, SPEECH = 40, 1500


def chunks(seconds):
    return int(round(seconds / CHUNK_SECONDS))


# --- loudness ---------------------------------------------------------------


def test_rms_of_silence_a_tone_and_nothing():
    assert rms(pcm_at(0)) == 0
    assert rms(pcm_at(1000)) == pytest.approx(1000)
    assert rms(pcm_at(-1000)) == pytest.approx(1000)
    assert rms(b"") == 0.0
    assert rms(b"\x01") == 0.0  # half a sample is ignored, not an error


# --- knowing when someone has finished --------------------------------------


def test_speech_then_silence_ends_the_recording():
    verdict, used = feed(detector(), [QUIET] * 5 + [SPEECH] * 12 + [QUIET] * 20)

    assert verdict == "done"
    # It waited out the silence (1.1s) rather than cutting off at the first quiet chunk.
    assert used >= 5 + 12 + chunks(1.1) - 1
    assert used <= 5 + 12 + chunks(1.1) + 1


def test_nothing_said_gives_up_at_the_start_timeout():
    verdict, used = feed(detector(start_timeout=6.0), [QUIET] * 100)

    assert verdict == "no_speech"
    assert chunks(6.0) - 1 <= used <= chunks(6.0) + 1


def test_a_single_click_is_not_speech():
    # One loud chunk (a tap on the desk, a cupboard) must not start a recording.
    det = detector()
    feed(det, [QUIET] * 5 + [SPEECH] + [QUIET] * 5)

    assert det.speaking is False


def test_two_loud_chunks_in_a_row_are_speech():
    det = detector()
    feed(det, [QUIET] * 3 + [SPEECH, SPEECH])

    assert det.speaking is True


def test_a_short_pause_mid_sentence_does_not_end_it():
    pause = [QUIET] * chunks(0.6)  # well under the 1.1s of silence that ends it

    verdict, _ = feed(detector(), [QUIET] * 3 + [SPEECH] * 8 + pause + [SPEECH] * 8 + [QUIET] * 3)

    assert verdict is None  # still going


def test_a_noisy_kitchen_raises_the_bar_so_the_fan_is_not_speech():
    fan = 350  # steady background: 3x this is above ordinary murmuring
    det = detector()

    verdict, _ = feed(det, [fan] * 60)

    assert det.speaking is False
    assert verdict == "no_speech"


def test_speech_over_a_noisy_room_is_still_heard():
    det = detector()

    verdict, _ = feed(det, [350] * 5 + [2500] * 10 + [350] * 20)

    assert verdict == "done"
    assert det.speaking is True


def test_softly_trailing_speech_is_not_cut_off():
    # Loud start, then quieter — but still well above the room — keeps going.
    verdict, _ = feed(detector(), [QUIET] * 4 + [2000] * 6 + [700] * 20)

    assert verdict is None


def test_talking_forever_is_cut_at_the_maximum():
    verdict, used = feed(detector(max_seconds=5.0), [QUIET] * 3 + [SPEECH] * 500)

    assert verdict == "max"
    assert used <= chunks(5.0) + 1


def test_a_recording_reports_whether_it_is_worth_transcribing():
    half_second = b"\x01\x00" * 8000
    assert Recording(half_second, "done").usable is True
    assert Recording(half_second, "no_speech").usable is False
    assert Recording(b"\x01\x00" * 100, "stopped").usable is False  # 6ms: a tap, not a command
    assert Recording(half_second, "stopped").seconds == pytest.approx(0.5)


# --- the recorder, against a simulated arecord ------------------------------


class FakeStdout:
    def __init__(self, chunks_):
        self.queue = list(chunks_)
        self.hang = False

    async def readexactly(self, n):
        if self.hang:
            await asyncio.sleep(10)
        if not self.queue:
            raise asyncio.IncompleteReadError(b"", n)
        return self.queue.pop(0)


class FakeStderr:
    def __init__(self, text=b""):
        self.text = text

    async def read(self):
        return self.text


class FakeProcess:
    def __init__(self, chunks_, stderr=b""):
        self.stdout = FakeStdout(chunks_)
        self.stderr = FakeStderr(stderr)
        self.returncode = None
        self.killed = False

    def kill(self):
        self.killed = True
        self.returncode = -9

    async def wait(self):
        return self.returncode


@pytest.fixture
def arecord(monkeypatch):
    holder = {}

    def install(process):
        async def fake_exec(*command, **kwargs):
            holder["command"] = command
            return process

        monkeypatch.setattr(recorder.asyncio, "create_subprocess_exec", fake_exec)
        return holder

    return install


@pytest.mark.anyio
async def test_recording_captures_speech_until_the_person_stops(arecord, monkeypatch):
    monkeypatch.setattr(recorder.settings, "mic_device", "plughw:CARD=Microphone,DEV=0")
    stream = [pcm_at(QUIET)] * 3 + [pcm_at(SPEECH)] * 8 + [pcm_at(QUIET)] * 30
    process = FakeProcess(stream)
    seen = arecord(process)
    levels = []

    recording = await recorder.Recorder().record(asyncio.Event(), levels.append)

    assert recording.reason == "done"
    assert recording.usable
    assert len(recording.pcm) < len(stream) * CHUNK_BYTES  # stopped early, didn't drain the mic
    assert len(levels) == len(recording.pcm) // CHUNK_BYTES
    assert max(levels) == pytest.approx(SPEECH)
    assert process.killed  # never leaves arecord running
    assert seen["command"][:5] == ("arecord", "-q", "-D", "plughw:CARD=Microphone,DEV=0", "-f")
    assert "16000" in seen["command"]


@pytest.mark.anyio
async def test_stopping_early_returns_what_was_heard(arecord):
    stop = asyncio.Event()
    process = FakeProcess([pcm_at(SPEECH)] * 200)
    arecord(process)
    count = 0

    def on_level(_level):
        nonlocal count
        count += 1
        if count == 6:
            stop.set()  # the person taps Stop

    recording = await recorder.Recorder().record(stop, on_level)

    assert recording.reason == "stopped"
    assert len(recording.pcm) == 6 * CHUNK_BYTES
    assert process.killed


@pytest.mark.anyio
async def test_a_missing_arecord_is_reported_clearly(monkeypatch):
    async def missing(*command, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(recorder.asyncio, "create_subprocess_exec", missing)

    with pytest.raises(MicUnavailable, match="arecord"):
        await recorder.Recorder().record(asyncio.Event(), lambda _l: None)


@pytest.mark.anyio
async def test_a_microphone_that_errors_surfaces_arecords_message(arecord):
    process = FakeProcess([], stderr=b"arecord: main:850: audio open error: No such file or directory")
    arecord(process)

    with pytest.raises(MicUnavailable, match="No such file"):
        await recorder.Recorder().record(asyncio.Event(), lambda _l: None)
    assert process.killed


@pytest.mark.anyio
async def test_a_microphone_that_goes_silent_is_an_error_not_a_hang(arecord, monkeypatch):
    process = FakeProcess([])
    process.stdout.hang = True
    arecord(process)
    real_wait_for = asyncio.wait_for

    async def quick(awaitable, timeout):
        return await real_wait_for(awaitable, timeout=0.01)

    monkeypatch.setattr(recorder.asyncio, "wait_for", quick)

    with pytest.raises(MicUnavailable, match="isn't sending"):
        await recorder.Recorder().record(asyncio.Event(), lambda _l: None)


@pytest.mark.anyio
async def test_a_short_listening_window_gives_up_sooner_than_the_default(arecord):
    # While an alarm rings, only a few seconds are spent listening for "stop".
    process = FakeProcess([pcm_at(QUIET)] * 200)
    arecord(process)

    recording = await recorder.Recorder().record(asyncio.Event(), lambda _l: None, start_timeout=1.0)

    assert recording.reason == "no_speech"
    assert len(recording.pcm) <= chunks(1.0) * CHUNK_BYTES + CHUNK_BYTES  # ~1 second, not the default 6


@pytest.mark.anyio
async def test_the_utterance_limit_can_be_overridden_too(arecord):
    process = FakeProcess([pcm_at(SPEECH)] * 400)
    arecord(process)

    recording = await recorder.Recorder().record(asyncio.Event(), lambda _l: None, max_seconds=2.0)

    assert recording.reason == "max"
    assert recording.seconds <= 2.3
