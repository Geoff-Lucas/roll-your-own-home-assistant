import wave

import pytest

from app.audio import player


@pytest.fixture(autouse=True)
def fresh_player_state(monkeypatch):
    monkeypatch.setattr(player, "_current", None)
    monkeypatch.setattr(player, "_warned_missing", False)
    monkeypatch.setattr(player, "_warned_failed", False)


def test_the_generated_chime_is_a_valid_short_stereo_wav(tmp_path):
    path = tmp_path / "chime.wav"

    player.write_chime(path)

    with wave.open(str(path)) as wav:
        assert wav.getnchannels() == 2
        assert wav.getsampwidth() == 2
        assert wav.getframerate() == 48000
        assert 1.0 < wav.getnframes() / wav.getframerate() < 3.0
        data = wav.readframes(wav.getnframes())
    assert any(byte != 0 for byte in data)  # not silence


def test_chime_is_created_on_first_use_and_then_reused(tmp_path, monkeypatch):
    monkeypatch.setattr(player.settings, "data_dir", tmp_path)

    first = player.chime_path()
    stamp = first.stat().st_mtime_ns
    second = player.chime_path()

    assert first == second == tmp_path / "sounds" / "chime.wav"
    assert second.stat().st_mtime_ns == stamp


class FakeProcess:
    def __init__(self, running=True, status=0):
        self.running = running
        self.status = status

    def poll(self):
        return None if self.running else self.status


def test_playback_uses_the_configured_alsa_device(monkeypatch, tmp_path):
    launched = []
    monkeypatch.setattr(player.settings, "audio_device", "plughw:0,3")
    monkeypatch.setattr(player.subprocess, "Popen", lambda cmd, **kw: launched.append(cmd) or FakeProcess())

    assert player.play_file(tmp_path / "x.wav") is True

    assert launched == [["aplay", "-q", "-D", "plughw:0,3", str(tmp_path / "x.wav")]]


def test_a_new_sound_waits_for_the_previous_one_instead_of_overlapping(monkeypatch, tmp_path):
    launched = []
    process = FakeProcess(running=True)
    monkeypatch.setattr(player.subprocess, "Popen", lambda cmd, **kw: launched.append(cmd) or process)

    assert player.play_file(tmp_path / "x.wav") is True
    assert player.play_file(tmp_path / "x.wav") is False  # still playing
    process.running = False
    assert player.play_file(tmp_path / "x.wav") is True  # finished, so free again

    assert len(launched) == 2


def test_a_missing_aplay_is_not_an_error_and_warns_only_once(monkeypatch, tmp_path, caplog):
    def not_installed(cmd, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(player.subprocess, "Popen", not_installed)

    with caplog.at_level("WARNING"):
        assert player.play_file(tmp_path / "x.wav") is False
        assert player.play_file(tmp_path / "x.wav") is False

    assert sum("aplay not found" in record.message for record in caplog.records) == 1


def test_a_failing_aplay_is_reported_once_with_the_device_name(monkeypatch, tmp_path, caplog):
    monkeypatch.setattr(player.settings, "audio_device", "plughw:0,3")
    monkeypatch.setattr(player.subprocess, "Popen", lambda cmd, **kw: FakeProcess(running=False, status=1))

    with caplog.at_level("WARNING"):
        for _ in range(4):  # each call reaps the previous (failed) aplay and starts another
            assert player.play_file(tmp_path / "x.wav") is True

    warnings = [r.message for r in caplog.records if "aplay exited" in r.message]
    assert len(warnings) == 1
    assert "plughw:0,3" in warnings[0]


def test_the_acknowledgement_tone_is_a_short_valid_wav_created_once(tmp_path, monkeypatch):
    monkeypatch.setattr(player.settings, "data_dir", tmp_path)

    path = player.ack_path()
    stamp = path.stat().st_mtime_ns

    assert path == tmp_path / "sounds" / "ack.wav"
    with wave.open(str(path)) as wav:
        assert (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) == (2, 2, 48000)
        assert 0.2 < wav.getnframes() / wav.getframerate() < 0.6  # brief: this is a cue, not a jingle
        data = wav.readframes(wav.getnframes())
    assert any(byte != 0 for byte in data)
    assert player.ack_path().stat().st_mtime_ns == stamp

