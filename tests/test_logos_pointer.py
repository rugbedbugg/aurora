import json

import pytest

from aurora import logos, pointer


def write(tmp_path, text):
    path = tmp_path / "os-release"
    path.write_text(text)
    return str(path)


def test_the_os_is_found_by_id_then_by_id_like(tmp_path):
    assert logos.detect(write(tmp_path, 'ID=nixos\nNAME="NixOS"\n')) == ("nixos", "NixOS")
    assert logos.detect(write(tmp_path, 'ID=manjaro\nID_LIKE=arch\nNAME="Manjaro Linux"\n')) == (
        "arch",
        "Manjaro Linux",
    )
    assert logos.detect(write(tmp_path, 'ID=pop\nID_LIKE="ubuntu debian"\nNAME="Pop!_OS"\n'))[0] == "ubuntu"


def test_an_unknown_or_missing_os_gets_the_generic_logo(tmp_path):
    assert logos.detect(write(tmp_path, "ID=plan9\nNAME=Plan9\n")) == ("linux", "Plan9")
    assert logos.detect(str(tmp_path / "absent"))[0] == "linux"


def test_every_logo_splits_into_tones_without_losing_text():
    for key, lines in [*logos.LOGOS.items(), *logos.SMALL.items()]:
        rows = logos.tones(lines)
        assert len(rows) == len(lines), key
        for line, row in zip(lines, rows, strict=True):
            plain = line.replace("{1}", "").replace("{2}", "")
            assert "".join(text for _, text in row) == plain
            assert all(tone in (1, 2) for tone, _ in row)


def test_the_nixos_logo_uses_both_tones_and_fits_a_tall_terminal():
    tones = {tone for row in logos.tones(logos.LOGOS["nixos"]) for tone, _ in row}
    assert tones == {1, 2}
    height, width = logos.size(logos.LOGOS["nixos"])
    assert (height, width) == (20, 43)


def test_only_the_ascii_logos_are_safe_without_unicode():
    plain = [k for k, v in logos.LOGOS.items() if all(ord(c) < 128 for line in v for c in line)]
    assert "nixos" not in plain
    assert {"arch", "debian", "ubuntu", "fedora", "linux"} <= set(plain)


def test_every_distribution_has_a_small_logo_made_of_ascii():
    assert set(logos.SMALL) == set(logos.LOGOS)
    for key, lines in logos.SMALL.items():
        assert all(ord(c) < 128 for line in lines for c in line), key
        assert logos.size(lines)[0] <= 11 and logos.size(lines)[0] < logos.size(logos.LOGOS[key])[0]


def test_the_largest_logo_that_fits_is_picked():
    assert logos.pick("nixos", 30) is logos.LOGOS["nixos"]
    assert logos.pick("nixos", 20) is logos.LOGOS["nixos"]
    assert logos.pick("nixos", 19) is logos.SMALL["nixos"]
    assert logos.pick("nixos", 7) is logos.SMALL["nixos"]
    assert logos.pick("nixos", 6) is None


def test_a_terminal_without_unicode_gets_an_ascii_logo_or_none():
    assert logos.pick("nixos", 30, unicode=False) is logos.SMALL["nixos"]
    assert logos.pick("arch", 30, unicode=False) is logos.LOGOS["arch"]
    assert logos.pick("nixos", 5, unicode=False) is None


def make_sysfs(tmp_path, nodes):
    for i, (vendor, product, name) in enumerate(nodes):
        node = tmp_path / f"input{i}"
        (node / "id").mkdir(parents=True)
        (node / "id" / "vendor").write_text(vendor + "\n")
        (node / "id" / "product").write_text(product + "\n")
        (node / "name").write_text(name + "\n")
    return str(tmp_path)


def test_hyprland_names_are_lowercase_with_dashes():
    assert pointer.internal_name("Instant USB Gaming Mouse ") == "instant-usb-gaming-mouse-"


def test_only_the_input_nodes_of_this_mouse_are_found(tmp_path):
    sysfs = make_sysfs(
        tmp_path,
        [("30fa", "1440", "Instant USB Gaming Mouse "), ("093a", "200b", "ASUP1411:00 093A:200B Mouse")],
    )
    assert pointer.input_names(sysfs) == ["instant-usb-gaming-mouse-"]


class Hypr:
    def __init__(self, mice=("instant-usb-gaming-mouse-",), fail=False):
        self.calls, self.mice, self.fail = [], mice, fail

    def __call__(self, args):
        self.calls.append(args)
        if self.fail and args[0] == "eval":
            raise pointer.PointerError("hyprctl failed: no")
        if args[0] == "devices":
            return json.dumps({"mice": [{"name": m} for m in self.mice]})
        if args[0] == "getoption":
            return json.dumps({"float": 0.0 if args[1].endswith("sensitivity") else 1.0})
        return "ok\n"


def test_detect_needs_a_hyprland_session_and_the_mouse_in_it(tmp_path, monkeypatch):
    sysfs = make_sysfs(tmp_path, [("30fa", "1440", "Instant USB Gaming Mouse ")])
    monkeypatch.delenv("HYPRLAND_INSTANCE_SIGNATURE", raising=False)
    assert pointer.Pointer.detect(Hypr(), sysfs) is None
    monkeypatch.setenv("HYPRLAND_INSTANCE_SIGNATURE", "x")
    monkeypatch.setattr(pointer.shutil, "which", lambda name: "/bin/hyprctl")
    found = pointer.Pointer.detect(Hypr(), sysfs)
    assert found.devices == ["instant-usb-gaming-mouse-"]
    assert (found.sensitivity, found.scroll) == (0.0, 1.0)
    assert pointer.Pointer.detect(Hypr(mice=("other",)), sysfs) is None


def test_a_step_moves_one_value_and_sends_both_to_hyprland():
    run = Hypr()
    live = pointer.Pointer(["instant-usb-gaming-mouse-"], 0.0, 1.0, run)
    text = live.step("sensitivity", 1)
    assert live.sensitivity == 0.1
    assert "sensitivity 0.1" in text and "resets when Hyprland reloads" in text
    assert run.calls == [
        [
            "eval",
            "hl.device({ name = 'instant-usb-gaming-mouse-', sensitivity = 0.10, scroll_factor = 1.00 })",
        ]
    ]


def test_values_stop_at_the_ends_of_their_ranges():
    live = pointer.Pointer(["m"], 1.0, 4.0, Hypr())
    assert live.step("sensitivity", 1) == ""
    assert live.step("scroll", 1) == ""
    assert (live.sensitivity, live.scroll) == (1.0, 4.0)
    low = pointer.Pointer(["m"], -1.0, 0.25, Hypr())
    assert low.step("sensitivity", -1) == "" and low.step("scroll", -1) == ""


def test_a_failed_command_leaves_the_value_unchanged():
    live = pointer.Pointer(["m"], 0.0, 1.0, Hypr(fail=True))
    assert "hyprctl failed" in live.step("scroll", 1)
    assert live.scroll == 1.0


def test_a_device_name_that_could_break_the_command_is_refused():
    live = pointer.Pointer(["bad'name"], 0.0, 1.0, Hypr())
    with pytest.raises(pointer.PointerError):
        live.push()
