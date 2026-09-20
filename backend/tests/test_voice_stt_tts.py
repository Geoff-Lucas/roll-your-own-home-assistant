import sys
import types

import pytest

from app.voice import setup as voice_setup
from app.voice import stt, tts


@pytest.fixture(autouse=True)
def models_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(stt.settings, "data_dir", tmp_path)
    monkeypatch.setattr(stt.settings, "voice_stt_model", "base.en")
    monkeypatch.setattr(stt.settings, "voice_stt_auto_download", False)
    return tmp_path / "voice" / "models"


def install_model(models_dir, name="base.en"):
    path = models_dir / f"models--Systran--faster-whisper-{name}" / "snapshots" / "abc123" / "model.bin"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"weights")
    return path


class FakeWhisperModel:
    instances = []

    def __init__(self, name, **kwargs):
        self.name = name
        self.kwargs = kwargs
        self.calls = []
        FakeWhisperModel.instances.append(self)

    def transcribe(self, audio, **kwargs):
        self.calls.append((audio, kwargs))
        segments = [types.SimpleNamespace(text=" set a timer "), types.SimpleNamespace(text=" for ten minutes ")]
        return iter(segments), types.SimpleNamespace()


@pytest.fixture
def fake_whisper(monkeypatch):
    FakeWhisperModel.instances = []
    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=FakeWhisperModel))
    return FakeWhisperModel


# --- speech recognition -----------------------------------------------------


def test_a_missing_package_is_reported(monkeypatch):
    monkeypatch.setitem(sys.modules, "faster_whisper", None)  # makes `import faster_whisper` fail

    ready, why = stt.WhisperTranscriber().status()

    assert ready is False
    assert "faster-whisper" in why


def test_a_missing_model_is_reported_with_the_fix_and_never_downloaded(fake_whisper):
    ready, why = stt.WhisperTranscriber().status()

    assert ready is False
    assert "base.en" in why and "python -m app.voice.setup" in why
    assert fake_whisper.instances == []  # checking status loads nothing


def test_an_installed_model_is_ready(fake_whisper, models_dir):
    install_model(models_dir)

    assert stt.WhisperTranscriber().status() == (True, "ready")


def test_a_different_model_size_does_not_satisfy_the_check(fake_whisper, models_dir):
    install_model(models_dir, name="tiny.en")

    assert stt.WhisperTranscriber().status()[0] is False


def test_transcribing_feeds_the_model_normalized_audio_and_joins_the_segments(fake_whisper, models_dir):
    pytest.importorskip("numpy")
    install_model(models_dir)
    transcriber = stt.WhisperTranscriber()
    pcm = (32767).to_bytes(2, "little", signed=True) + (-32768).to_bytes(2, "little", signed=True)

    text = transcriber.transcribe(pcm)

    assert text == "set a timer for ten minutes"
    model = fake_whisper.instances[0]
    audio, options = model.calls[0]
    assert str(audio.dtype) == "float32"
    assert audio[0] == pytest.approx(1.0, abs=1e-3) and audio[1] == pytest.approx(-1.0)
    assert options["language"] == "en"
    assert options["vad_filter"] is True
    assert "timer" in options["initial_prompt"]


def test_the_model_is_loaded_offline_once_and_reused(fake_whisper, models_dir):
    pytest.importorskip("numpy")
    install_model(models_dir)
    transcriber = stt.WhisperTranscriber()

    transcriber.transcribe(b"\x00\x00" * 100)
    transcriber.transcribe(b"\x00\x00" * 100)

    assert len(fake_whisper.instances) == 1
    assert fake_whisper.instances[0].kwargs["local_files_only"] is True
    assert fake_whisper.instances[0].kwargs["compute_type"] == "int8"


def test_transcribing_without_a_model_raises_instead_of_downloading(fake_whisper):
    pytest.importorskip("numpy")

    with pytest.raises(stt.SpeechRecognitionUnavailable, match="python -m app.voice.setup"):
        stt.WhisperTranscriber().transcribe(b"\x00\x00" * 100)
    assert fake_whisper.instances == []


def test_setup_check_reports_without_downloading(fake_whisper, models_dir, capsys):
    assert voice_setup.main(["--check"]) == 1
    assert "not installed" in capsys.readouterr().out

    install_model(models_dir)
    assert voice_setup.main(["--check"]) == 0
    assert "installed" in capsys.readouterr().out


# --- speaking ---------------------------------------------------------------


def test_replies_are_cleaned_for_speech():
    assert tts.clean_for_speech("**Timer** set   for\n10 minutes.") == "Timer set for 10 minutes."
    assert tts.clean_for_speech("a | b > c `d`") == "a b c d"
    assert len(tts.clean_for_speech("x" * 1000)) == tts.MAX_SPOKEN_CHARS


@pytest.fixture
def engines(monkeypatch):
    state = {"piper": False, "espeak": False}
    monkeypatch.setattr(tts, "piper_available", lambda: state["piper"])
    monkeypatch.setattr(tts.shutil, "which", lambda name: "/usr/bin/espeak-ng" if state["espeak"] else None)
    monkeypatch.setattr(tts.settings, "voice_tts", "auto")
    return state


def test_piper_is_preferred_when_it_is_installed(engines):
    engines.update(piper=True, espeak=True)

    assert isinstance(tts.choose_speaker(), tts.PiperSpeaker)


def test_espeak_is_the_fallback(engines):
    engines.update(piper=False, espeak=True)

    assert isinstance(tts.choose_speaker(), tts.EspeakSpeaker)


def test_no_engine_means_no_speaker(engines):
    assert tts.choose_speaker() is None


def test_a_forced_engine_is_respected(engines, monkeypatch):
    engines.update(piper=True, espeak=True)
    monkeypatch.setattr(tts.settings, "voice_tts", "espeak")
    assert isinstance(tts.choose_speaker(), tts.EspeakSpeaker)

    monkeypatch.setattr(tts.settings, "voice_tts", "none")
    assert tts.choose_speaker() is None

    monkeypatch.setattr(tts.settings, "voice_tts", "piper")
    engines.update(piper=False)
    assert tts.choose_speaker() is None  # asked for piper, doesn't fall back silently


@pytest.mark.anyio
async def test_espeak_renders_then_plays_the_file(monkeypatch):
    ran, played = [], []

    async def fake_run(*command, stdin=None):
        ran.append(command)
        # espeak-ng writes the file named after -w
        open(command[command.index("-w") + 1], "wb").write(b"RIFF")
        return 0

    async def fake_play(path):
        played.append(path.read_bytes())
        return True

    monkeypatch.setattr(tts, "_run", fake_run)
    monkeypatch.setattr(tts, "play_and_wait", fake_play)

    await tts.EspeakSpeaker().speak("- Timer set")

    assert ran[0][0] == "espeak-ng"
    assert ran[0][-2:] == ("--", "- Timer set")  # a leading dash can't be read as an option
    assert played == [b"RIFF"]


@pytest.mark.anyio
async def test_a_failed_render_is_an_error_not_silence(monkeypatch):
    async def failing(*command, stdin=None):
        return 1

    monkeypatch.setattr(tts, "_run", failing)

    with pytest.raises(tts.SpeechError):
        await tts.EspeakSpeaker().speak("hello")


@pytest.mark.anyio
async def test_piper_is_given_the_text_on_stdin(monkeypatch):
    monkeypatch.setattr(tts.settings, "voice_piper_binary", "/opt/piper/piper")
    monkeypatch.setattr(tts.settings, "voice_piper_model", "/opt/piper/voice.onnx")
    seen = {}

    async def fake_run(*command, stdin=None):
        seen["command"], seen["stdin"] = command, stdin
        open(command[command.index("--output_file") + 1], "wb").write(b"RIFF")
        return 0

    async def fake_play(path):
        return True

    monkeypatch.setattr(tts, "_run", fake_run)
    monkeypatch.setattr(tts, "play_and_wait", fake_play)

    await tts.PiperSpeaker().speak("Timer set for 10 minutes.")

    assert seen["command"][:3] == ("/opt/piper/piper", "--model", "/opt/piper/voice.onnx")
    assert seen["stdin"] == b"Timer set for 10 minutes."
