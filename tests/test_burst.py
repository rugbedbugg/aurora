import pytest
from helpers import FakeDevice, full_image, install_fake, load_json

from blazectl import burst, image

template = burst.load_template()


def patch_polling(hz):
    return lambda img: image.set_polling(img, hz)


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    return tmp_path


def test_the_template_and_sample_rebuild_the_recorded_apply_burst():
    golden = load_json("final-burst.json")
    built = [
        None if report is None else report.hex() for _, report in burst.build(template, image.load_sample())
    ]
    assert built == golden


def test_the_template_is_one_get_then_reports_ending_in_the_final_commit():
    assert template[0]["op"] == "get"
    assert all(e["op"] != "get" for e in template[1:])
    assert bytes.fromhex(template[-2]["raw"]).hex() == "0718100000000000"
    assert all(0 <= e["addr"] < burst.IMAGE_SIZE for e in template if e["op"] == "data")


def test_a_good_read_passes_for_every_profile():
    for profile in range(4):
        img = full_image()
        img[0x01] = 0x03 | profile << 5
        assert burst.validate_read(img, None) == []


def test_a_repeated_page_zero_is_rejected():
    garbage = {a: burst.MAGIC_PAGE0[a % 8] for a in range(burst.IMAGE_SIZE)}
    assert burst.validate_read(garbage, None)


def test_a_wrong_header_byte_is_rejected():
    for addr in (0, 2):
        img = full_image()
        img[addr] = 0
        assert burst.validate_read(img, None) == ["page 0 does not hold the expected header"]


def test_drift_from_the_last_good_dump_is_reported():
    good = full_image()
    drifted = dict(good)
    drifted[0x1E] = 0
    assert "0x1e" in burst.validate_read(drifted, good)[0]


def test_state_lives_under_xdg_state_home(state):
    assert burst.state_dir() == str(state / "blazectl")
    assert burst.load_last_good() is None
    burst.save_last_good({1: 2, 3: 4})
    assert burst.load_last_good() == {1: 2, 3: 4}
    assert list((state / "blazectl").iterdir()) == [state / "blazectl" / "last-good.json"]


def test_apply_writes_one_burst_and_verifies_it(state, monkeypatch):
    mem = full_image()
    opened = install_fake(monkeypatch, mem)
    assert burst.apply([patch_polling(1000)])
    assert image.get_polling(mem) == 1000
    assert opened[0].sent == len(template) - 1
    assert burst.load_last_good() == mem


def test_apply_sends_nothing_when_nothing_changes(state, monkeypatch, capsys):
    mem = full_image()
    opened = install_fake(monkeypatch, mem)
    assert burst.apply([patch_polling(500)])
    assert opened[0].sent == 0
    assert "no burst sent" in capsys.readouterr().out


def test_rewrite_sends_the_burst_even_when_nothing_changes(state, monkeypatch):
    mem = full_image()
    opened = install_fake(monkeypatch, mem)
    assert burst.apply([], rewrite=True)
    assert opened[0].sent == len(template) - 1


def test_an_invariant_violation_raises_before_any_write(state, monkeypatch):
    mem = full_image()
    opened = install_fake(monkeypatch, mem)
    with pytest.raises(ValueError, match="Left Click"):
        burst.apply([lambda img: image.set_button(img, 1, 3)])
    assert opened[0].sent == 0
    assert opened[0].closed


def test_a_device_that_differs_from_the_last_good_dump_is_refused(state, monkeypatch, capsys):
    mem = full_image()
    burst.save_last_good(mem)
    mem[0x1E] = 0x00
    opened = install_fake(monkeypatch, mem)
    assert not burst.apply([patch_polling(250)])
    assert opened[0].sent == 0
    assert "refusing to write" in capsys.readouterr().out
    assert burst.apply([patch_polling(250)], force=True)
    assert image.get_polling(mem) == 250


def test_a_failed_burst_is_recovered_by_replaying_the_previous_settings(state, monkeypatch, capsys):
    mem = full_image()
    before = dict(mem)
    opened = install_fake(monkeypatch, mem, fail_first=300)
    assert not burst.apply([patch_polling(1000), lambda img: image.set_fire_time(img, 120)])
    assert len(opened) == 2
    assert mem == before
    assert "restored the previous settings" in capsys.readouterr().out


def test_recovery_reports_a_missing_device(state, monkeypatch, capsys):
    mem = full_image()
    monkeypatch.setattr(burst.device, "Device", lambda: FakeDevice(mem, fail_after=10))
    assert not burst.apply([patch_polling(1000)])
    assert "blazectl rewrite --force" in capsys.readouterr().out


def test_rebaseline_saves_a_sane_read_and_refuses_a_bad_one(state, monkeypatch, capsys):
    mem = full_image()
    install_fake(monkeypatch, mem)
    assert burst.rebaseline()
    assert burst.load_last_good() == mem
    mem[0] = 0
    assert not burst.rebaseline()
    assert "refusing" in capsys.readouterr().out
