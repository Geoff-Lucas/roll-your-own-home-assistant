import sys
import types
import wave

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
async def test_the_configured_espeak_voice_and_speed_are_used(monkeypatch):
    monkeypatch.setattr(tts.settings, "voice_espeak_voice", "en-us+f3")
    monkeypatch.setattr(tts.settings, "voice_espeak_speed", 175)
    ran = []

    async def fake_run(*command, stdin=None):
        ran.append(command)
        open(command[command.index("-w") + 1], "wb").write(b"RIFF")
        return 0

    async def fake_play(path):
        return True

    monkeypatch.setattr(tts, "_run", fake_run)
    monkeypatch.setattr(tts, "play_and_wait", fake_play)

    await tts.EspeakSpeaker().speak("Hello")

    command = ran[0]
    assert command[command.index("-v") + 1] == "en-us+f3"
    assert command[command.index("-s") + 1] == "175"


@pytest.mark.anyio
async def test_a_failed_render_is_an_error_not_silence(monkeypatch):
    async def failing(*command, stdin=None):
        return 1

    monkeypatch.setattr(tts, "_run", failing)

    with pytest.raises(tts.SpeechError):
        await tts.EspeakSpeaker().speak("hello")


class FakePiperVoice:
    """Stands in for piper.PiperVoice: counts loads and writes a tiny real WAV."""

    loads = []

    @classmethod
    def load(cls, model):
        cls.loads.append(model)
        return cls()

    def synthesize_wav(self, text, wav_file):
        self.spoken = text
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(22050)
        wav_file.writeframes(b"\x00\x00" * 2205)


@pytest.fixture
def piper(tmp_path, monkeypatch):
    """A voice file on disk, a fake piper package installed, and nothing loaded yet."""
    voices = tmp_path / "voices"
    voices.mkdir()
    (voices / "en_US-amy-medium.onnx").write_bytes(b"")
    (voices / "en_US-lessac-medium.onnx").write_bytes(b"")
    monkeypatch.setattr(tts.settings, "voice_piper_model", "en_US-amy-medium")
    monkeypatch.setattr(tts.settings, "voice_tts", "auto")
    monkeypatch.setattr(type(tts.settings), "voice_piper_dir", property(lambda self: voices))
    FakePiperVoice.loads = []
    package = types.ModuleType("piper")
    package.PiperVoice = FakePiperVoice
    monkeypatch.setitem(sys.modules, "piper", package)
    monkeypatch.setattr(tts, "piper_installed", lambda: True)
    monkeypatch.setattr(tts, "_piper_loaded", None)
    return voices


def test_a_voice_is_found_by_name_in_the_piper_folder(piper):
    assert tts.piper_model() == piper / "en_US-amy-medium.onnx"
    assert tts.piper_available() is True


def test_a_voice_can_be_a_path_instead(piper, tmp_path, monkeypatch):
    elsewhere = tmp_path / "other.onnx"
    elsewhere.write_bytes(b"")
    monkeypatch.setattr(tts.settings, "voice_piper_model", str(elsewhere))

    assert tts.piper_model() == elsewhere


def test_piper_is_unavailable_without_a_chosen_or_present_voice(piper, monkeypatch):
    monkeypatch.setattr(tts.settings, "voice_piper_model", "")
    assert tts.piper_model() is None and tts.piper_available() is False

    monkeypatch.setattr(tts.settings, "voice_piper_model", "en_GB-not-downloaded")
    assert tts.piper_model() is None and tts.piper_available() is False


def test_piper_is_unavailable_when_the_package_is_not_installed(piper, monkeypatch):
    monkeypatch.setattr(tts, "piper_installed", lambda: False)

    assert tts.piper_available() is False


def test_the_voice_is_loaded_once_and_kept_for_every_reply(piper):
    model = piper / "en_US-amy-medium.onnx"

    first = tts._load_piper(model)
    second = tts._load_piper(model)

    assert first is second
    assert FakePiperVoice.loads == [model]  # a fresh load costs over a second, every reply


def test_choosing_a_different_voice_loads_that_one(piper):
    amy, lessac = piper / "en_US-amy-medium.onnx", piper / "en_US-lessac-medium.onnx"

    tts._load_piper(amy)
    tts._load_piper(lessac)

    assert FakePiperVoice.loads == [amy, lessac]


def test_rendering_writes_a_playable_wav(piper, tmp_path):
    wav = tmp_path / "out.wav"

    tts._render_piper(piper / "en_US-amy-medium.onnx", "Hello there", wav)

    with wave.open(str(wav)) as written:
        assert written.getnframes() == 2205 and written.getframerate() == 22050


@pytest.mark.anyio
async def test_warming_up_loads_the_voice_before_anyone_asks_for_a_reply(piper):
    await tts.warm_up()

    assert FakePiperVoice.loads == [piper / "en_US-amy-medium.onnx"]


@pytest.mark.anyio
async def test_warming_up_does_nothing_when_piper_is_not_wanted_or_not_ready(piper, monkeypatch):
    monkeypatch.setattr(tts.settings, "voice_tts", "espeak")
    await tts.warm_up()

    monkeypatch.setattr(tts.settings, "voice_tts", "auto")
    monkeypatch.setattr(tts.settings, "voice_piper_model", "")
    await tts.warm_up()

    assert FakePiperVoice.loads == []


@pytest.mark.anyio
async def test_a_voice_that_fails_to_load_at_startup_is_logged_not_fatal(piper, monkeypatch, caplog):
    def broken(model):
        raise RuntimeError("corrupt model")

    monkeypatch.setattr(FakePiperVoice, "load", classmethod(lambda cls, model: broken(model)))

    with caplog.at_level("ERROR"):
        await tts.warm_up()  # must not raise: the app starts, and replies fall back to failing softly

    assert any("Couldn't load the Piper voice" in r.message for r in caplog.records)


@pytest.mark.anyio
async def test_speaking_with_piper_but_no_voice_is_an_error(piper, monkeypatch):
    monkeypatch.setattr(tts.settings, "voice_piper_model", "en_GB-not-downloaded")

    with pytest.raises(tts.SpeechError, match="voice file is missing"):
        await tts.PiperSpeaker().speak("hello")


@pytest.mark.anyio
async def test_piper_renders_the_reply_then_plays_it(piper, monkeypatch):
    played = []

    async def fake_play(path):
        with wave.open(str(path)) as rendered:  # the file exists and is a real WAV at this point
            played.append(rendered.getnframes())
        return True

    monkeypatch.setattr(tts, "play_and_wait", fake_play)

    await tts.PiperSpeaker().speak("Timer set for 10 minutes.")

    assert played == [2205]
    assert FakePiperVoice.loads == [piper / "en_US-amy-medium.onnx"]


@pytest.mark.anyio
async def test_a_reply_with_nothing_to_say_is_not_rendered_or_played(piper, monkeypatch):
    async def fake_play(path):
        pytest.fail("nothing to play")

    monkeypatch.setattr(tts, "play_and_wait", fake_play)

    await tts.PiperSpeaker().speak("   ")

    assert FakePiperVoice.loads == []


@pytest.mark.anyio
async def test_a_render_failure_is_a_speech_error(piper, monkeypatch):
    def broken(model, text, wav):
        raise RuntimeError("onnx exploded")

    monkeypatch.setattr(tts, "_render_piper", broken)

    with pytest.raises(tts.SpeechError, match="onnx exploded"):
        await tts.PiperSpeaker().speak("hello")


def test_setup_downloads_a_named_piper_voice(monkeypatch, tmp_path, capsys):
    from app.voice import setup

    monkeypatch.setattr(type(setup.settings), "voice_piper_dir", property(lambda self: tmp_path / "piper"))
    calls = []

    class Done:
        returncode = 0

    monkeypatch.setattr(setup.subprocess, "run", lambda command: calls.append(command) or Done())

    assert setup.main(["--piper", "en_US-amy-medium"]) == 0

    (command,) = calls
    assert command[1:4] == ["-m", "piper.download_voices", "en_US-amy-medium"]
    assert command[-1] == str(tmp_path / "piper")
    assert "HOME_ORGANIZER_VOICE_PIPER_MODEL=en_US-amy-medium" in capsys.readouterr().out


def test_setup_does_not_download_a_voice_it_already_has(monkeypatch, tmp_path):
    from app.voice import setup

    (tmp_path / "piper").mkdir()
    (tmp_path / "piper" / "en_US-amy-medium.onnx").write_bytes(b"")
    monkeypatch.setattr(type(setup.settings), "voice_piper_dir", property(lambda self: tmp_path / "piper"))
    monkeypatch.setattr(setup.subprocess, "run", lambda command: pytest.fail("should not download"))

    assert setup.main(["--piper", "en_US-amy-medium"]) == 0
