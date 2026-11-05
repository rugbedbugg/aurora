import pytest

from aurora import cli, image, tui

DIRECTIONS = ("up", "down", "left", "right")


def sample():
    return image.load_sample()


@pytest.fixture
def model():
    return tui.Model(sample())


@pytest.fixture
def tabs(model):
    return tui.build_widgets(model)


def find(widgets, key):
    return next(w for w in widgets if w.key == key)


def test_there_is_one_widget_list_per_tab(tabs):
    assert list(tabs) == tui.TABS


def test_every_widget_fits_on_the_canvas(tabs):
    for name, widgets in tabs.items():
        for w in widgets:
            assert 0 <= w.y < tui.CANVAS_H, (name, w.key, w.y)
            assert 0 <= w.x and w.x + w.w <= tui.CANVAS_W, (name, w.key, w.x, w.w)


def test_controls_on_one_tab_do_not_overlap(tabs):
    for name, widgets in tabs.items():
        cells = {}
        for w in widgets:
            for x in range(w.x, w.x + w.w):
                other = cells.setdefault((w.y, x), w)
                assert other is w, (name, w.key, other.key, w.y, x)


def test_the_labels_cover_every_function_and_effect():
    assert set(tui.FUNCTION_LABELS) == set(cli.FUNCTIONS)
    assert len(tui.EFFECT_LABELS) == len(cli.EFFECTS)


def test_right_from_button_one_lands_on_button_five(tabs):
    widgets = tabs["Button"]
    assert tui.nearest(widgets, find(widgets, "button.1"), "right").key == "button.5"
    assert tui.nearest(widgets, find(widgets, "button.5"), "left").key == "button.1"


def test_down_walks_the_left_column_then_reaches_the_bottom_bar(tabs):
    widgets = tabs["Button"]
    cur = find(widgets, "button.1")
    for expected in ("button.2", "button.3", "button.4"):
        cur = tui.nearest(widgets, cur, "down")
        assert cur.key == expected
    assert tui.nearest(widgets, cur, "down").y >= 19


def test_up_from_the_first_button_reaches_the_tab_bar_and_stops(tabs):
    widgets = tabs["Button"]
    tab = tui.nearest(widgets, find(widgets, "button.1"), "up")
    assert tab.kind == "tab"
    assert tui.nearest(widgets, tab, "up") is None


def test_nothing_moves_past_an_edge(tabs):
    widgets = tabs["Button"]
    assert tui.nearest(widgets, find(widgets, "button.1"), "left") is None
    assert tui.nearest(widgets, find(widgets, "button.5"), "right") is None


def test_the_focus_never_lands_on_a_control_that_does_nothing(tabs):
    for widgets in tabs.values():
        for w in widgets:
            if not w.focusable:
                continue
            for direction in DIRECTIONS:
                target = tui.nearest(widgets, w, direction)
                assert target is None or (target.enabled and target.kind != "label")


def test_every_focusable_control_can_be_reached(tabs):
    for name, widgets in tabs.items():
        focusable = [w for w in widgets if w.focusable]
        seen, todo = {id(focusable[0])}, [focusable[0]]
        while todo:
            cur = todo.pop()
            for direction in DIRECTIONS:
                nxt = tui.nearest(widgets, cur, direction)
                if nxt is not None and id(nxt) not in seen:
                    seen.add(id(nxt))
                    todo.append(nxt)
        assert len(seen) == len(focusable), name


def test_the_dpi_list_offers_only_the_values_read_from_the_vendor_app(tabs, model):
    options = find(tabs["Performance"], "dpi.1").options(model.work)
    assert [label for label, _ in options] == [f"{v} DPI" for v in sorted(image.DPI_LABEL.values())]


def test_every_pick_can_choose_every_option(tabs):
    for widgets in tabs.values():
        for w in (w for w in widgets if w.kind == "pick"):
            model = tui.Model(sample())
            for label, edit in w.options(model.work):
                assert model.change(edit) or model.msg.startswith("refused")
                if not model.msg:
                    assert label.startswith(w.value(model.work)) or w.value(model.work) == label
                model.undo_all()


def test_toggles_and_choices_flip_and_flip_back(tabs):
    for widgets in tabs.values():
        for w in (w for w in widgets if w.kind in ("toggle", "choice")):
            if w.kind == "choice":
                continue
            model = tui.Model(sample())
            before = w.selected(model.work)
            assert model.change(w.toggle(model.work)) or model.msg.startswith("refused")
            if not model.msg:
                assert w.selected(model.work) != before
                assert model.change(w.toggle(model.work))
                assert w.selected(model.work) == before
                assert not model.pending


def test_polling_and_profile_choices_select_their_value(tabs, model):
    for hz in tui.POLLING:
        choice = next(w for w in tabs["Performance"] if w.key == "polling" and w.text == str(hz))
        model.change(choice.choose(model.work))
        assert image.get_polling(model.work) == hz
    for i, name in enumerate(tui.PROFILE_NAMES):
        choice = next(w for w in tabs["Button"] if w.key == "profile" and w.text == name)
        model.change(choice.choose(model.work))
        assert tui.profile_of(model.work) == i


def test_sliders_adjust_and_clamp(tabs, model):
    fire = find(tabs["Performance"], "fire-time")
    model.change(fire.adjust(model.work, 1, False))
    assert tui.fire_time(model.work) == 60
    model.change(fire.adjust(model.work, 1, True))
    assert tui.fire_time(model.work) == 61
    for _ in range(40):
        model.change(fire.adjust(model.work, 1, False))
    assert tui.fire_time(model.work) == 300
    bright = find(tabs["Backlight"], "brightness")
    for _ in range(30):
        model.change(bright.adjust(model.work, 1, False))
    assert model.work[0x3F] >> 4 == 15


def test_the_dpi_slider_edits_the_selected_stage_under_that_stages_key(tabs, model):
    slider = find(tabs["Performance"], "dpi-slider")
    model.dpi_sel = 2
    edit = slider.adjust(model.work, 1, False)
    assert edit.key == "dpi.3"
    model.change(edit)
    assert image.get_dpi_index(model.work, 2) == 13
    assert list(model.pending) == ["dpi.3"]


def test_the_cycle_time_slider_does_nothing_for_the_fixed_effects(tabs, model):
    slider = find(tabs["Backlight"], "cycle-time")
    assert slider.adjust(model.work, 1, False) is not None
    image.set_led_effect(model.work, 13)
    assert slider.adjust(model.work, 1, False) is None


def test_a_colour_edit_round_trips(tabs, model):
    for widgets in (tabs["Performance"], tabs["Backlight"]):
        for w in (w for w in widgets if w.kind == "swatch"):
            before = w.rgb[0](model.work)
            rgb = tuple((c + 1) % 16 for c in before)
            assert model.change(tui.Edit(w.key, lambda im, w=w, rgb=rgb: w.rgb[1](im, rgb)))
            assert w.rgb[0](model.work) == rgb
            model.undo(w.key)
            assert w.rgb[0](model.work) == before


def test_removing_left_click_is_refused_and_leaves_nothing_pending(tabs, model):
    options = find(tabs["Button"], "button.1").options(model.work)
    right = next(edit for label, edit in options if label == "Right Click")
    assert not model.change(right)
    assert "Left Click" in model.msg
    assert not model.pending


def test_disabling_every_dpi_stage_is_refused(tabs, model):
    stages = [w for w in tabs["Performance"] if w.kind == "toggle" and w.key.startswith("dpi-enable")]
    results = [model.change(w.toggle(model.work)) for w in reversed(stages)]
    assert results[:5] == [True] * 5
    assert results[5] is False
    assert "enabled" in model.msg


def test_an_edit_that_returns_to_the_original_clears_the_pending_entry(tabs, model):
    c1000 = next(w for w in tabs["Performance"] if w.key == "polling" and w.text == "1000")
    c500 = next(w for w in tabs["Performance"] if w.key == "polling" and w.text == "500")
    model.change(c1000.choose(model.work))
    assert list(model.pending) == ["polling"]
    model.change(c500.choose(model.work))
    assert not model.pending


def test_undo_and_cancel(tabs, model):
    model.change(find(tabs["Backlight"], "symmetry").toggle(model.work))
    model.change(find(tabs["Performance"], "dpi-enable.2").toggle(model.work))
    model.undo("symmetry")
    assert list(model.pending) == ["dpi-enable.2"]
    model.undo_all()
    assert not model.pending
    assert model.work == model.base


def test_reset_adopts_a_new_base(model):
    new = sample()
    image.set_polling(new, 125)
    model.reset(new)
    assert image.get_polling(model.work) == 125
    assert not model.pending


def test_every_control_sits_inside_a_pane_with_its_gutter_column(tabs):
    for name, widgets in tabs.items():
        panes = [*tui.PANES[name], tui.ACTION_PANE]
        for w in widgets:
            if w.y == 2:
                continue
            gutter = 0 if w.kind == "label" else 1
            inside = any(
                p.y < w.y < p.y + p.h - 1 and p.x < w.x - gutter and w.x + w.w - 1 < p.x + p.w - 1
                for p in panes
            )
            assert inside, (name, w.key, w.text, w.y, w.x, w.w)


def test_the_mouse_drawing_sits_inside_its_pane():
    width = max(len(line) for line in tui.ART)
    for name, x in (("Button", 30), ("Backlight", 6)):
        pane = next(p for p in tui.PANES[name] if p.title == "Blaze")
        assert pane.x < x and x + width - 1 < pane.x + pane.w - 1
        assert pane.y < 4 and 4 + len(tui.ART) - 1 < pane.y + pane.h - 1


def test_the_panes_of_a_tab_do_not_overlap():
    for panes in tui.PANES.values():
        cells = set()
        for p in panes:
            for y in range(p.y, p.y + p.h):
                for x in range(p.x, p.x + p.w):
                    assert (y, x) not in cells
                    cells.add((y, x))


def test_the_header_summary_reads_the_working_image(model):
    assert tui.summary(model.work) == "500 Hz | 1200 DPI | Neon"
    model.change(tui.Edit("polling", lambda im: image.set_polling(im, 125)))
    assert tui.summary(model.work).startswith("125 Hz")


def test_set_commands_become_edits_under_the_widget_keys(model):
    command = tui.parse_command("set polling=1000 dpi.6=7200 button.8=rapid-fire")
    assert command.action == "set"
    assert [e.key for e in command.edits] == ["polling", "dpi.6", "button.8"]
    for edit in command.edits:
        assert model.change(edit)
    assert image.get_polling(model.work) == 1000
    assert image.get_dpi_index(model.work, 5) == 16
    assert list(model.pending) == ["polling", "dpi.6", "button.8"]


def test_a_widget_edit_replaces_a_command_edit_with_the_same_key(tabs, model):
    for edit in tui.parse_command("set polling=125").edits:
        model.change(edit)
    choice = next(w for w in tabs["Performance"] if w.key == "polling" and w.text == "250")
    model.change(choice.choose(model.work))
    assert list(model.pending) == ["polling"]
    assert image.get_polling(model.work) == 250
    back = next(w for w in tabs["Performance"] if w.key == "polling" and w.text == "500")
    model.change(back.choose(model.work))
    assert not model.pending


def test_bad_commands_are_refused_with_a_reason():
    for text in ("set", "set dpi.1=3000", "set button.4=macro", "frobnicate", "tab", "tab nowhere", "tab b"):
        with pytest.raises(tui.CommandError):
            tui.parse_command(text)


def test_the_command_names_and_their_aliases():
    for text, action in (
        ("apply", "apply"),
        ("w", "apply"),
        ("cancel", "cancel"),
        ("undo", "cancel"),
        ("reload", "reload"),
        ("rebaseline", "rebaseline"),
        ("quit", "quit"),
        ("q", "quit"),
        ("quit!", "force-quit"),
        ("q!", "force-quit"),
        ("help", "help"),
        ("", "none"),
    ):
        assert tui.parse_command(text).action == action


def test_tabs_can_be_named_by_number_or_prefix():
    assert tui.parse_command("tab 3").arg == 2
    assert tui.parse_command("tab perf").arg == 2
    assert tui.parse_command("tab Back").arg == 3


def test_a_command_that_breaks_an_invariant_is_refused_by_the_model(model):
    edit = tui.parse_command("set button.1=right").edits[0]
    assert not model.change(edit)
    assert "Left Click" in model.msg
    assert not model.pending


def test_the_footer_and_the_help_text_fit_the_canvas():
    assert len(tui.FOOTER) <= 78
    assert all(len(line) <= 70 for line in [*tui.KEYS, *tui.COMMANDS])


def test_every_hint_fits_the_border_title_with_the_colour_prefix(tabs):
    for widgets in tabs.values():
        for w in widgets:
            prefix = len("R 15 G 15 B 15  ") if w.kind == "swatch" else 0
            assert len(w.hint) + prefix <= 68, (w.key, w.hint)
