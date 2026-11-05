import pytest

from aurora import image, preview


def sample():
    return image.load_sample()


def text_of(lines):
    return "\n".join(line.text for line in lines)


def test_the_file_is_valid_toml_and_holds_every_setting():
    tomllib = pytest.importorskip("tomllib")
    data = tomllib.loads(text_of(preview.render(sample(), 200)))
    assert data["profile"] == 0
    perf = data["performance"]
    assert perf["polling"] == 500 and perf["fire-time"] == 50 and perf["dpi-active"] == 1
    assert sorted(data["dpi"]) == ["1", "2", "3", "4", "5", "6"]
    assert data["dpi"]["1"] == {"value": 1200, "enabled": True, "rgb": [0, 0, 15]}
    light = data["backlight"]
    assert light["effect"] == "neon" and light["brightness"] == 0
    assert len(light["cycle"]) == 7 and sorted(light["colour"]) == [str(n) for n in range(7)]
    assert sorted(data["buttons"], key=int) == [str(n) for n in range(1, 9)]
    assert data["buttons"]["1"] == "left"


def test_every_line_fits_the_narrowest_preview_pane():
    for img in (sample(), image.load_sample()):
        image.set_dpi_stage(img, 0, 22)
        image.set_button(img, 8, 20)
        lines = preview.render(img)
        assert all(len(line.text) <= preview.MIN_WIDTH for line in lines)


def test_long_lines_are_cut_with_an_ellipsis():
    assert preview.fit("abcdefgh", 5) == "abcd…"
    assert preview.fit("abc", 5) == "abc"


def test_the_sections_cover_the_file_in_order():
    sections = [line.section for line in preview.render(sample())]
    assert set(sections) == set(preview.SECTIONS)
    order = [s for i, s in enumerate(sections) if i == 0 or s != sections[i - 1]]
    assert order == list(preview.SECTIONS)


def test_an_unchanged_image_has_no_changed_rows():
    lines = preview.render(sample())
    rows = preview.diff(lines, lines)
    assert [r.text for r in rows] == [x.text for x in lines]
    assert {r.tag for r in rows} == {" "}
    assert preview.first_change(rows) is None


def test_a_changed_value_shows_the_old_line_then_the_new_one_in_place():
    img = sample()
    image.set_polling(img, 1000)
    rows = preview.diff(preview.render(sample()), preview.render(img))
    texts = [(r.tag, r.text) for r in rows]
    at = texts.index(("-", "polling = 500"))
    assert texts[at + 1] == ("+", "polling = 1000")
    assert texts[at - 1][0] == " " and texts[at + 2][0] == " "
    assert sum(1 for r in rows if r.tag != " ") == 2
    assert preview.first_change(rows) == at


def test_two_changes_give_two_separate_pairs():
    img = sample()
    image.set_polling(img, 125)
    image.set_dpi_stage(img, 5, 16)
    rows = preview.diff(preview.render(sample()), preview.render(img))
    changed = [(r.tag, r.text) for r in rows if r.tag != " "]
    assert changed == [
        ("-", "polling = 500"),
        ("+", "polling = 125"),
        ("-", "value = 12800"),
        ("+", "value = 7200"),
    ]


def test_the_diff_keeps_every_line_of_the_file():
    img = sample()
    image.set_led_effect(img, 2)
    old, new = preview.render(sample()), preview.render(img)
    rows = preview.diff(old, new)
    assert [r.text for r in rows if r.tag != "+"] == [x.text for x in old]
    assert [r.text for r in rows if r.tag != "-"] == [x.text for x in new]


@pytest.mark.parametrize("section", preview.SECTIONS)
def test_every_section_has_an_anchor(section):
    rows = preview.diff(preview.render(sample()), preview.render(sample()))
    at = preview.anchor(rows, section)
    assert rows[at].section == section
    assert all(r.section != section for r in rows[:at])


def test_an_unknown_section_anchors_at_the_top():
    assert preview.anchor([], "nowhere") == 0
