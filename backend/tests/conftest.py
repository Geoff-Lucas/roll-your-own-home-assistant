import pytest

from app import system


@pytest.fixture(autouse=True)
def never_really_reboot(monkeypatch):
    """No test may restart the machine it runs on: anything that reaches the
    real reboot fails instead. Tests of the restart path replace it themselves."""

    def refuse():
        raise AssertionError("a test tried to reboot the computer")

    monkeypatch.setattr(system, "reboot", refuse)
