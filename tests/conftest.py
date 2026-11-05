import pytest

from aurora import burst, device


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    """Skip the pauses between reports so a replayed burst takes no real time."""
    monkeypatch.setattr(burst.time, "sleep", lambda _: None)
    monkeypatch.setattr(device.time, "sleep", lambda _: None)
