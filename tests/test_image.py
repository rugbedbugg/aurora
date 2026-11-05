import json

import pytest
from helpers import DATA, load_json
from ini_map import apply_ini_key, get_ini_view

from aurora import image

REFUSED_PROBES = {
    "ShareData.DPI_SET3=23",
    "ShareData.DPI_SET3=24",
    "ShareData.DPI_SET3=25",
    "Config0.K7=7",
    "Config0.K7=8",
    "Config0.K7=9",
    "Config0.K7=10",
    "Config0.K7=11",
    "ShareData.LED_TYPE=14",
    "ShareData.LED_TYPE=15",
}


def diff(a, b):
    return [[x, a.get(x), b.get(x)] for x in sorted(set(a) | set(b)) if a.get(x) != b.get(x)]


def test_recorded_probes_match_the_encoder():
    ref = image.load_sample()
    seen, matched, mismatched, unmodelled = set(), 0, [], set()
    for line in (DATA / "probes.jsonl").read_text().splitlines():
        probe = json.loads(line)
        label = probe["label"]
        if label.startswith("base") or label in seen:
            continue
        seen.add(label)
        target, value = label.rsplit("=", 1)
        section, key = target.split(".", 1)
        img = dict(ref)
        try:
            apply_ini_key(img, section, key, value)
        except image.Unmapped:
            if probe["diff"]:
                unmodelled.add(label)
            continue
        if diff(ref, img) == probe["diff"]:
            matched += 1
        else:
            mismatched.append(label)
    assert not mismatched
    assert matched >= 150
    assert unmodelled == REFUSED_PROBES


def test_decoding_the_sample_gives_the_vendor_config_values():
    values = load_json("ini-values.json")
    view = get_ini_view(image.load_sample())
    wrong = {k: (view[k], v) for k, v in values.items() if view[k] != v}
    assert not wrong
    assert len(values) >= 70


@pytest.mark.parametrize("hz", [125, 250, 500, 1000])
def test_polling_round_trip(hz):
    img = image.load_sample()
    image.set_polling(img, hz)
    assert image.get_polling(img) == hz


def test_dpi_round_trip_for_every_stage_and_index():
    for stage in range(6):
        for index in range(image.DPI_MAX_INDEX + 1):
            img = image.load_sample()
            image.set_dpi_stage(img, stage, index)
            assert image.get_dpi_index(img, stage) == index


def test_dpi_index_beyond_the_table_is_refused():
    with pytest.raises(image.Unmapped):
        image.set_dpi_stage(image.load_sample(), 0, 23)


def test_led_effect_round_trip():
    for effect in range(14):
        img = image.load_sample()
        image.set_led_effect(img, effect)
        assert image.get_led_effect(img) == effect


def test_literal_effects_need_a_cycle_time_of_one():
    img = image.load_sample()
    image.set_led_cycle_time(img, 3)
    with pytest.raises(image.Unmapped):
        image.set_led_effect(img, 13)
    with pytest.raises(image.Unmapped):
        image.set_led_effect(img, 14)


def test_colours_round_trip():
    for slot in range(7):
        img = image.load_sample()
        image.set_led_colour(img, slot, 15, 1, 7)
        assert image.get_led_colour(img, slot) == (15, 1, 7)
    for stage in range(6):
        img = image.load_sample()
        image.set_dpi_colour(img, stage, 3, 14, 0)
        assert image.get_dpi_colour(img, stage) == (3, 14, 0)


def test_cycle_colour_enables_are_bits_of_one_byte():
    img = image.load_sample()
    assert all(image.get_cycle_colour_enabled(img, n) for n in range(7))
    image.set_cycle_colour_enabled(img, 0, False)
    assert img[0x1D] == 0xFE
    assert not image.get_cycle_colour_enabled(img, 0)
    image.set_cycle_colour_enabled(img, 0, True)
    assert img[0x1D] == 0xFF
    with pytest.raises(ValueError):
        image.set_cycle_colour_enabled(img, 7, True)


def test_colour_values_above_a_nibble_are_refused():
    with pytest.raises(ValueError):
        image.set_dpi_colour(image.load_sample(), 0, 16, 0, 0)


def test_fire_time_spans_two_bytes():
    img = image.load_sample()
    for ms in (0, 50, 255, 256, 300):
        image.set_fire_time(img, ms)
        assert img[0x1A] | img[0x1B] << 8 == ms
    with pytest.raises(ValueError):
        image.set_fire_time(img, 301)


def test_button_functions_round_trip_and_keep_the_reaction_bits():
    for button in range(1, 9):
        for function in image.FUNCTION_CODE:
            img = image.load_sample()
            image.set_button_reaction(img, button, 2)
            image.set_button(img, button, function)
            assert image.get_button(img, button) == (function, 2)


def test_profile_button_tables_are_only_verified_for_button_eight():
    with pytest.raises(image.Unmapped):
        image.set_button(image.load_sample(), 1, 1, profile=1)
    image.set_button(image.load_sample(), 8, 14, profile=1)


def test_profile_round_trip():
    for profile in range(4):
        img = image.load_sample()
        image.set_profile(img, profile)
        assert img[0x01] >> 5 & 3 == profile
        assert img[0x76] & 3 == profile


def test_the_sample_satisfies_the_invariants():
    image.check_invariants(image.load_sample())


def test_left_click_must_stay_on_some_button():
    img = image.load_sample()
    image.set_button(img, 1, 3)
    with pytest.raises(ValueError, match="Left Click"):
        image.check_invariants(img)


def test_one_dpi_stage_must_stay_enabled():
    img = image.load_sample()
    for stage in range(6):
        image.set_dpi_enabled(img, stage, False)
    with pytest.raises(ValueError, match="enabled"):
        image.check_invariants(img)


def test_the_active_dpi_stage_must_be_enabled():
    img = image.load_sample()
    image.set_dpi_enabled(img, 0, False)
    with pytest.raises(ValueError, match="active"):
        image.check_invariants(img)
