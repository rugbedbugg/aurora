import pytest

from aurora import banner, sysinfo


def cells(result):
    """Return {(y, x): (char, layer, zone)} for every drawn cell."""
    out = {}
    for run in result.runs:
        for i, ch in enumerate(run.text):
            assert (run.y, run.x + i) not in out
            out[(run.y, run.x + i)] = (ch, run.layer, run.zone)
    return out


@pytest.mark.parametrize("unicode", [True, False])
def test_the_banner_is_six_rows_and_seventy_two_columns(unicode):
    result = banner.render(unicode)
    assert (result.height, result.width) == (6, 72)
    drawn = cells(result)
    assert all(0 <= y < result.height and 0 <= x < result.width for y, x in drawn)


def test_the_banner_uses_block_characters_or_plain_ones():
    assert {c for c, _, _ in cells(banner.render(True)).values()} == {"█", "░"}
    assert {c for c, _, _ in cells(banner.render(False)).values()} == {"#", "."}


def test_the_shadow_sits_one_row_down_and_two_cells_right_and_never_covers_a_letter():
    drawn = cells(banner.render())
    faces = {pos for pos, (_, layer, _) in drawn.items() if layer == "face"}
    shades = {pos for pos, (_, layer, _) in drawn.items() if layer == "shadow"}
    assert shades and not faces & shades
    for y, x in shades:
        assert (y - 1, x - 2) in faces


def test_the_letters_are_square_pixels_two_cells_wide():
    drawn = cells(banner.render())
    top = sorted(x for (y, x), (_, layer, _) in drawn.items() if y == 0 and layer == "face")
    assert top[:6] == [2, 3, 4, 5, 6, 7]


def test_every_zone_is_used_and_grows_from_left_to_right():
    result = banner.render()
    zones = sorted({run.zone for run in result.runs})
    assert zones == list(range(banner.ZONES))
    left = [run.zone for run in result.runs if run.x < 10]
    right = [run.zone for run in result.runs if run.x > 60]
    assert max(left) < min(right)


def test_a_run_never_crosses_a_zone():
    for run in banner.render().runs:
        first = min(banner.ZONES - 1, run.x * banner.ZONES // 72)
        last = min(banner.ZONES - 1, (run.x + len(run.text) - 1) * banner.ZONES // 72)
        assert first == last == run.zone


def tree(tmp_path):
    def put(path, text):
        file = tmp_path / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(text)

    put("etc/os-release", 'NAME="NixOS"\nPRETTY_NAME="NixOS 26.05 (Yarara)"\n')
    put("proc/sys/kernel/osrelease", "7.2.10\n")
    put("sys/devices/virtual/dmi/id/sys_vendor", "ASUSTeK COMPUTER INC.\n")
    put("sys/devices/virtual/dmi/id/product_name", "Vivobook\n")
    put("proc/cpuinfo", "processor\t: 0\nmodel name\t: AMD  Ryzen 7   7735HS\nmodel name\t: other\n")
    put("proc/meminfo", "MemTotal:       16777216 kB\nMemFree: 1 kB\nMemAvailable:    8388608 kB\n")
    put("proc/uptime", "11520.5 99.0\n")
    return str(tmp_path)


def test_the_rows_describe_the_machine(tmp_path):
    env = {"XDG_CURRENT_DESKTOP": "Hyprland", "XDG_SESSION_TYPE": "wayland"}
    rows = dict(sysinfo.gather(tree(tmp_path), env, mouse=lambda: "/dev/hidraw2"))
    assert rows == {
        "OS": "NixOS 26.05 (Yarara)",
        "Kernel": "7.2.10",
        "Host": "ASUSTeK COMPUTER INC. Vivobook",
        "CPU": "AMD Ryzen 7 7735HS",
        "Memory": "8.0 / 16.0 GiB",
        "Uptime": "3h 12m",
        "Session": "Hyprland wayland",
        "Mouse": "Blaze on /dev/hidraw2",
    }


def test_rows_without_a_value_are_left_out(tmp_path):
    rows = sysinfo.gather(str(tmp_path), {}, mouse=lambda: "")
    assert rows == []


def test_the_labels_keep_their_order(tmp_path):
    labels = [label for label, _ in sysinfo.gather(tree(tmp_path), {"XDG_SESSION_TYPE": "tty"}, lambda: "x")]
    assert labels == ["OS", "Kernel", "Host", "CPU", "Memory", "Uptime", "Session", "Mouse"]


@pytest.mark.parametrize(
    "seconds,text",
    [(30, "0m"), (59 * 60, "59m"), (3600, "1h 0m"), (3 * 3600 + 720, "3h 12m"), (90000, "1d 1h")],
)
def test_uptime_is_short(seconds, text):
    assert sysinfo.uptime(seconds) == text


def test_memory_needs_both_numbers():
    assert sysinfo.memory("MemTotal: 1024 kB\n") == ""
    assert sysinfo.memory("MemTotal: nope kB\nMemAvailable: 1 kB\n") == ""
