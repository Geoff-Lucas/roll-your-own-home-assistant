import asyncio
import sys
import types

import pytest

from app.voice import wakeword
from app.voice.recorder import MicUnavailable
from app.voice.wakeword import FRAME_BYTES, OpenWakeWordDetector, WakeWordListener

FRAME = b"\x00\x00" * (FRAME_BYTES // 2)


async def until(condition, timeout=3.0):
    """Wait for something to become true. The detector runs in a worker thread,
    so "yield a few times" isn't enough — poll, with a limit."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not condition():
        if loop.time() > deadline:
            raise AssertionError("condition was never met")
        await asyncio.sleep(0.005)


async def stays(condition, seconds=0.08):
    """Assert something stays true for a little while."""
    loop = asyncio.get_running_loop()
    end = loop.time() + seconds
    while loop.time() < end:
        assert condition()
        await asyncio.sleep(0.005)


class FakeStream:
    """A microphone that yields frames of silence forever (or fails)."""

    def __init__(self, error=None):
        self.error = error
        self.closed = False
        self.read_sizes = set()

    async def readexactly(self, n):
        self.read_sizes.add(n)
        await asyncio.sleep(0.001)  # real audio takes time to arrive
        if self.error:
            raise self.error
        return FRAME

    async def close(self):
        self.closed = True


class FakeDetector:
    def __init__(self, scores):
        self.scores = list(scores)
        self.calls = 0
        self.resets = 0

    def score(self, frame):
        self.calls += 1
        return self.scores.pop(0) if self.scores else 0.0

    def reset(self):
        self.resets += 1


class Harness:
    """A listener with a fake microphone. By default the wake handler behaves like
    the real one (VoiceSession): it pauses the listener, i.e. takes over the mic."""

    def __init__(self, scores, *, threshold=0.5, cooldown=2.0, streams=None, take_over_mic=True):
        self.woken = 0
        self.opened = 0
        self.streams = streams if streams is not None else []
        self.detector = FakeDetector(scores)
        self.last_stream = None
        self.task = None

        async def open_stream():
            self.opened += 1
            self.last_stream = self.streams.pop(0) if self.streams else FakeStream()
            return self.last_stream

        async def on_wake():
            self.woken += 1
            if take_over_mic:
                await self.listener.pause()

        self.listener = WakeWordListener(
            detector=self.detector, on_wake=on_wake, open_stream=open_stream, threshold=threshold, cooldown=cooldown
        )

    def start(self):
        self.task = asyncio.create_task(self.listener.run())

    async def stop(self):
        self.task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await self.task


# --- the listener -----------------------------------------------------------


@pytest.mark.anyio
async def test_the_phrase_wakes_the_assistant_after_the_microphone_is_released():
    h = Harness(scores=[0.0, 0.1, 0.9])
    first_stream = []

    original_open = h.listener._open_stream

    async def remember():
        stream = await original_open()
        first_stream.append(stream)
        return stream

    h.listener._open_stream = remember
    h.start()
    await until(lambda: h.woken == 1)

    assert first_stream[0].closed  # let go of before the handler ran
    assert h.listener.listening is False
    await h.stop()


@pytest.mark.anyio
async def test_scores_below_the_threshold_never_wake_it():
    h = Harness(scores=[0.1, 0.4, 0.49, 0.2], threshold=0.5)
    h.start()
    await until(lambda: h.detector.calls >= 6)

    assert h.woken == 0
    assert h.listener.listening is True
    await h.stop()


@pytest.mark.anyio
async def test_a_score_exactly_at_the_threshold_counts():
    h = Harness(scores=[0.5], threshold=0.5)
    h.start()
    await until(lambda: h.woken == 1)
    await h.stop()


@pytest.mark.anyio
async def test_frames_are_the_size_the_model_expects_and_the_model_starts_fresh():
    h = Harness(scores=[])
    h.start()
    await until(lambda: h.detector.calls >= 2)

    assert h.last_stream.read_sizes == {FRAME_BYTES}
    assert FRAME_BYTES == 2560  # 80 ms of 16 kHz 16-bit audio
    assert h.detector.resets == 1
    await h.stop()


@pytest.mark.anyio
async def test_it_stays_off_while_paused_and_listens_again_on_resume():
    h = Harness(scores=[])
    h.start()
    await until(lambda: h.listener.listening)

    await h.listener.pause()
    assert h.listener.listening is False
    assert h.last_stream.closed
    opened = h.opened
    await stays(lambda: h.opened == opened and not h.listener.listening)  # doesn't reopen behind our back

    h.listener.resume()
    await until(lambda: h.opened == opened + 1 and h.listener.listening)
    await h.stop()


@pytest.mark.anyio
async def test_after_the_phrase_it_waits_for_resume_before_listening_again():
    h = Harness(scores=[0.9])
    h.start()
    await until(lambda: h.woken == 1)
    opened = h.opened

    # The handler (a conversation) has the microphone now.
    await stays(lambda: h.opened == opened and not h.listener.listening)

    h.listener.resume()
    await until(lambda: h.opened == opened + 1)
    await h.stop()


@pytest.mark.anyio
async def test_the_cooldown_stops_one_utterance_triggering_twice(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(wakeword, "_now", lambda: clock[0])
    h = Harness(scores=[0.9, 0.95], cooldown=2.0)
    h.start()
    await until(lambda: h.woken == 1)

    h.listener.resume()
    await until(lambda: h.detector.calls >= 2)  # the second high score was heard...
    await stays(lambda: h.woken == 1)  # ...and ignored: it's inside the cooldown

    clock[0] += 3.0
    h.detector.scores.append(0.9)
    await until(lambda: h.woken == 2)  # after the cooldown the phrase counts again
    await h.stop()


@pytest.mark.anyio
async def test_a_missing_microphone_is_retried_and_reported_only_once(monkeypatch, caplog):
    monkeypatch.setattr(wakeword, "_RETRY_SECONDS", 0.005)
    h = Harness(scores=[], streams=[FakeStream(error=MicUnavailable("no device")) for _ in range(4)])

    with caplog.at_level("WARNING"):
        h.start()
        await until(lambda: h.opened >= 5)  # the four failures, then one that works

    assert sum("Wake word paused" in r.message for r in caplog.records) == 1
    await until(lambda: h.listener.listening)  # recovered
    await h.stop()


@pytest.mark.anyio
async def test_a_failure_in_the_handler_does_not_end_listening(caplog):
    h = Harness(scores=[0.9])

    async def broken():
        raise RuntimeError("couldn't start")

    h.listener._on_wake = broken
    with caplog.at_level("ERROR"):
        h.start()
        await until(lambda: any("Couldn't start listening" in r.message for r in caplog.records))
        await until(lambda: h.listener.listening)  # went straight back to listening

    assert not h.task.done()
    await h.stop()


@pytest.mark.anyio
async def test_the_microphone_is_always_closed_when_the_task_is_cancelled():
    h = Harness(scores=[])
    h.start()
    await until(lambda: h.listener.listening)
    stream = h.last_stream

    await h.stop()

    assert stream.closed
    assert h.listener.listening is False


@pytest.mark.anyio
async def test_it_reports_the_best_score_and_loudest_level_it_has_recently_heard():
    class LoudStream(FakeStream):
        async def readexactly(self, n):
            await super().readexactly(n)
            return (1000).to_bytes(2, "little", signed=True) * (n // 2)

    h = Harness(scores=[0.1, 0.42, 0.2], streams=[LoudStream()])
    assert (h.listener.recent_peak_score, h.listener.recent_peak_level) == (0.0, 0.0)  # nothing heard yet
    h.start()
    await until(lambda: h.detector.calls >= 6)

    assert h.listener.recent_peak_score == pytest.approx(0.42)
    assert h.listener.recent_peak_level == pytest.approx(1000)
    await h.stop()


@pytest.mark.anyio
async def test_pausing_when_it_is_already_idle_returns_at_once():
    h = Harness(scores=[])

    await h.listener.pause()  # never started: nothing to release

    assert h.listener.listening is False


# --- the model wrapper ------------------------------------------------------


class FakeModel:
    instances = []

    def __init__(self, wakeword_model_paths):
        self.paths = wakeword_model_paths
        self.resets = 0
        FakeModel.instances.append(self)

    def predict(self, audio):
        self.audio = audio
        return {"hey_jarvis_v0.1": 0.25, "other": 0.75}

    def reset(self):
        self.resets += 1


@pytest.fixture
def fake_openwakeword(tmp_path, monkeypatch):
    package = tmp_path / "openwakeword"
    (package / "resources" / "models").mkdir(parents=True)
    (package / "resources" / "models" / "hey_jarvis_v0.1.onnx").write_bytes(b"model")
    module = types.ModuleType("openwakeword")
    module.__file__ = str(package / "__init__.py")
    model_module = types.ModuleType("openwakeword.model")
    model_module.Model = FakeModel
    FakeModel.instances = []
    monkeypatch.setitem(sys.modules, "openwakeword", module)
    monkeypatch.setitem(sys.modules, "openwakeword.model", model_module)
    return package


def test_the_detector_reports_a_missing_package(monkeypatch):
    monkeypatch.setitem(sys.modules, "openwakeword", None)

    ready, why = OpenWakeWordDetector().status()

    assert ready is False and "openwakeword" in why


def test_the_detector_reports_a_missing_model_file(fake_openwakeword):
    (fake_openwakeword / "resources" / "models" / "hey_jarvis_v0.1.onnx").unlink()

    ready, why = OpenWakeWordDetector().status()

    assert ready is False and "hey_jarvis" in why


def test_the_detector_is_ready_when_the_model_is_bundled(fake_openwakeword):
    assert OpenWakeWordDetector().status() == (True, "ready")


def test_scoring_feeds_the_model_int16_audio_and_takes_the_best_score(fake_openwakeword):
    pytest.importorskip("numpy")
    detector = OpenWakeWordDetector()

    score = detector.score(b"\x01\x00\xff\xff")

    assert score == 0.75
    model = FakeModel.instances[0]
    assert str(model.audio.dtype) == "int16"
    assert list(model.audio) == [1, -1]
    assert model.paths[0].endswith("hey_jarvis_v0.1.onnx")


def test_the_model_is_loaded_lazily_once_and_can_be_reset(fake_openwakeword):
    pytest.importorskip("numpy")
    detector = OpenWakeWordDetector()
    detector.reset()  # before anything is loaded: harmless
    assert FakeModel.instances == []

    detector.score(b"\x00\x00")
    detector.score(b"\x00\x00")
    detector.reset()

    assert len(FakeModel.instances) == 1
    assert FakeModel.instances[0].resets == 1
