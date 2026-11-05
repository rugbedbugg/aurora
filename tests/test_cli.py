import pytest
from helpers import full_image, install_fake

from blazectl import cli, image


@pytest.fixture
def mouse(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    mem = full_image()
    install_fake(monkeypatch, mem)
    return mem


def patched(arg):
    img = image.load_sample()
    cli.parse_setting(arg)(img)
    return img


def test_known_dpi_values_are_accepted_by_value():
    assert image.get_dpi_index(patched("dpi.6=7200"), 5) == 16


def test_an_unknown_dpi_value_is_refused_but_an_index_is_accepted():
    with pytest.raises(ValueError, match="unknown DPI value"):
        cli.parse_setting("dpi.1=3000")
    assert image.get_dpi_index(patched("dpi.1=idx:3"), 0) == 3


def test_effects_and_functions_are_accepted_by_name():
    assert image.get_led_effect(patched("effect=ripple")) == 10
    assert image.get_button(patched("button.2=middle"), 2)[0] == 2


def test_bad_settings_are_refused():
    for arg in ("polling", "dpi.7=600", "button.4=macro", "polling=3", "colour=1"):
        with pytest.raises(ValueError):
            cli.parse_setting(arg)(image.load_sample())


def test_describe_reports_the_sample_the_way_the_vendor_app_shows_it():
    lines = dict(cli.describe(image.load_sample()))
    assert lines["polling"] == "500 Hz"
    assert lines["dpi.1"].startswith("1200")
    assert lines["dpi.6"].startswith("12800")
    assert lines["effect"] == "neon"
    assert lines["button.8"].startswith("double-click")


def test_get_prints_the_settings_read_from_the_device(mouse, capsys):
    assert cli.main(["get", "polling", "dpi.1"]) == 0
    assert capsys.readouterr().out.splitlines() == ["polling = 500 Hz", "dpi.1 = 1200, on, colour 0,0,15"]


def test_set_changes_the_device(mouse):
    assert cli.main(["set", "polling=125", "dpi.6=7200"]) == 0
    assert image.get_polling(mouse) == 125
    assert image.get_dpi_index(mouse, 5) == 16


def test_dry_run_writes_nothing(mouse, capsys):
    before = dict(mouse)
    assert cli.main(["set", "dpi.6=7200", "--dry-run"]) == 0
    assert mouse == before
    assert "12800" in capsys.readouterr().out


def test_set_refuses_to_remove_left_click(mouse, capsys):
    assert cli.main(["set", "button.1=right"]) == 2
    assert "Left Click" in capsys.readouterr().err


def test_dry_run_applies_the_same_refusals(mouse, capsys):
    assert cli.main(["set", "button.1=right", "--dry-run"]) == 2
    assert "Left Click" in capsys.readouterr().err
