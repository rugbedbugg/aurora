import pytest

from aurora import cli, image, logos, tui

DIRECTIONS = ("up", "down", "left", "right")
SIZES = [(24, 80), (29, 99), (40, 90), (30, 100), (38, 160), (40, 120), (45, 170), (50, 200), (60, 300)]


def sample():
    return image.load_sample()


@pytest.fixture
def model():
    return tui.Model(sample())


@pytest.fixture(params=SIZES, ids=lambda size: "x".join(map(str, reversed(size))))
def layout(request):
    return tui.make_layout(*request.param)


@pytest.fixture
def tabs(model, layout):
    return tui.build_widgets(model, layout)


def find(widgets, key):
    return next(w for w in widgets if w.key == key)


def test_there_is_one_widget_list_per_tab(tabs):
    assert list(tabs) == tui.TABS


def test_every_widget_fits_on_the_screen(tabs, layout):
    for name, widgets in tabs.items():
        for w in widgets:
            assert 0 <= w.y and w.y + w.h <= layout.h, (name, w.key, w.y, w.h)
            assert 0 <= w.x and w.x + w.w <= layout.w, (name, w.key, w.x, w.w)


def test_controls_on_one_tab_do_not_overlap(tabs):
    for name, widgets in tabs.items():
        cells = {}
        for w in widgets:
            for y in range(w.y, w.y + w.h):
                for x in range(w.x, w.x + w.w):
                    other = cells.setdefault((y, x), w)
                    assert other is w, (name, w.key, other.key, y, x)


def test_the_labels_cover_every_function_and_effect():
    assert set(tui.FUNCTION_LABELS) == set(cli.FUNCTIONS)
    assert len(tui.EFFECT_LABELS) == len(cli.EFFECTS)


def test_the_eight_buttons_sit_in_one_column(tabs):
    widgets = tabs["Button"]
    picks = [find(widgets, f"button.{n}") for n in range(1, 9)]
    assert len({w.x for w in picks}) == 1
    assert [w.y for w in picks] == sorted(w.y for w in picks)
    assert len({w.y for w in picks}) == 8
    assert all(w.w <= 36 for w in picks)


def test_down_walks_the_button_column_then_reaches_the_bottom_bar(tabs, layout):
    widgets = tabs["Button"]
    cur = find(widgets, "button.1")
    for n in range(2, 9):
        cur = tui.nearest(widgets, cur, "down")
        assert cur.key == f"button.{n}"
    assert tui.nearest(widgets, cur, "down").y >= layout.action_y


def test_up_from_the_first_button_reaches_the_tab_bar_and_stops(tabs):
    widgets = tabs["Button"]
    tab = tui.nearest(widgets, find(widgets, "button.1"), "up")
    assert tab.kind == "tab"
    assert tui.nearest(widgets, tab, "up") is None


def test_nothing_moves_past_an_edge(tabs):
    widgets = tabs["Button"]
    assert tui.nearest(widgets, find(widgets, "button.1"), "left") is None
    assert tui.nearest(widgets, find(widgets, "button.8"), "right") is None


def test_the_focus_never_lands_on_a_control_that_does_nothing(pointer_tabs):
    for widgets in pointer_tabs.values():
        for w in widgets:
            if not w.focusable:
                continue
            for direction in DIRECTIONS:
                target = tui.nearest(widgets, w, direction)
                assert target is None or (target.enabled and target.kind != "label")


@pytest.fixture(params=[None, "fake"], ids=["no-pointer", "pointer"])
def pointer_tabs(request, layout):
    fake = FakePointer() if request.param else None
    return tui.build_widgets(tui.Model(sample(), pointer=fake), layout)


def test_every_focusable_control_can_be_reached(pointer_tabs):
    for name, widgets in pointer_tabs.items():
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


def test_every_control_sits_inside_a_pane_with_its_gutter_column(tabs, layout):
    panes, action = tui.make_panes(layout)
    for name, widgets in tabs.items():
        for w in widgets:
            if w.area == "tabs":
                continue
            gutter = 0 if w.kind == "label" else 1
            inside = any(
                p.y < w.y
                and w.y + w.h - 1 < p.y + p.h - 1
                and p.x < w.x - gutter
                and w.x + w.w - 1 < p.x + p.w - 1
                for p in [*panes[name], action]
            )
            assert inside, (name, w.key, w.text, w.y, w.x, w.w)


@pytest.mark.parametrize("name,reserve", [("Button", 3), ("Backlight", 2)])
def test_the_mouse_drawing_sits_inside_its_pane(layout, name, reserve):
    pane = tui.pane_titled(tui.make_panes(layout)[0][name], "Blaze")
    if pane is None:
        pytest.skip("this layout has no mouse pane on that tab")
    ix, iy, iw, ih = tui.inner(pane)
    width, height = tui.diagram_size(iw, ih, reserve)
    x0 = ix + 2 + (iw - width - 2) // 2
    y0 = iy + 1 + max(0, ih - reserve - height) // 2
    assert pane.x < x0 - 2 and x0 + width - 1 < pane.x + pane.w - 1
    assert pane.y < y0 and y0 + height - 1 < pane.y + pane.h - 1


@pytest.mark.parametrize("unicode", [True, False])
@pytest.mark.parametrize("size", [(11, 9), (15, 10), (27, 18), (43, 29), (75, 50)])
def test_the_mouse_shape_keeps_every_number_on_a_blank_cell(size, unicode):
    width, height = size
    rows, marks = tui.mouse_shape(width, height, unicode)
    assert len(rows) == height and {len(r) for r in rows} == {width}
    assert sorted(marks) == [1, 2, 3, 4, 5, 6, 7, 8]
    for n, (y, x) in marks.items():
        assert 0 <= y < height
        if x < 0:
            assert n in (4, 5) and x == -2
        else:
            assert x < width and rows[y][x] == " ", (n, y, x)
    assert (not unicode) <= all(ord(c) < 128 for row in rows for c in row)


def test_the_mouse_is_about_one_and_a_half_times_as_wide_as_it_is_tall():
    width, height = tui.diagram_size(10**6, 40, 3)
    assert height == 37 and width % 2 == 1
    assert abs(width / height - tui.DIAGRAM_ASPECT) < 0.05


def test_the_smallest_screen_still_gets_a_mouse():
    layout = tui.make_layout(24, 80)
    pane = tui.make_panes(layout)[0]["Button"][1]
    ix, iy, iw, ih = tui.inner(pane)
    width, height = tui.diagram_size(iw, ih, 3)
    assert width >= tui.MIN_DIAGRAM_W and height >= tui.MIN_DIAGRAM_H


def test_the_not_office_note_fits_the_pane_it_is_drawn_on(layout):
    panes = tui.make_panes(layout)[0]["Button"]
    pane = tui.pane_titled(panes, "Buttons" if layout.split else "Blaze")
    assert len(tui.NOT_OFFICE) <= pane.w - 4


def test_the_panes_of_a_tab_do_not_overlap_and_fill_the_width(layout):
    panes, action = tui.make_panes(layout)
    for tab in panes.values():
        cells = set()
        for p in tab:
            for y in range(p.y, p.y + p.h):
                for x in range(p.x, p.x + p.w):
                    assert (y, x) not in cells
                    cells.add((y, x))
        assert max(p.x + p.w for p in tab) == layout.w - 1
        assert max(p.y + p.h for p in tab) == action.y
    assert action.y + action.h == layout.status_y


def test_the_rows_of_the_screen_do_not_overlap(layout):
    assert layout.body_y + layout.body_h == layout.action_y
    assert layout.action_y + layout.action_h == layout.status_y
    assert layout.footer_y == layout.h - 1


def test_the_smallest_screen_keeps_the_original_rows():
    layout = tui.make_layout(24, 80)
    assert (layout.body_h, layout.action_y, layout.status_y, layout.footer_y) == (15, 18, 22, 23)


def test_the_colour_swatches_grow_with_the_terminal():
    sizes = {}
    for size in SIZES:
        swatches = [
            w
            for w in tui.build_widgets(tui.Model(sample()), tui.make_layout(*size))["Backlight"]
            if w.kind == "swatch"
        ]
        sizes[size] = (swatches[0].w, swatches[0].h)
    assert sizes[(24, 80)][0] >= 4 and sizes[(24, 80)][1] >= 2
    assert sizes[(60, 300)][0] >= 12 and sizes[(60, 300)][1] >= 5
    assert sizes[(60, 300)][0] <= tui.MAX_SWATCH_W and sizes[(60, 300)][1] <= tui.MAX_SWATCH_H


def test_sliders_stop_growing_on_a_wide_terminal(tabs):
    for widgets in tabs.values():
        for w in widgets:
            if w.kind == "slider" and w.key != "dpi-slider":
                assert w.w <= tui.MAX_BAR, w.key
    dpi = find(tabs["Performance"], "dpi-slider")
    assert dpi.w <= 6 * tui.MAX_SWATCH_W + 5 * 2


def test_the_body_holds_every_control_between_the_bars(tabs):
    for widgets in tabs.values():
        areas = {w.area for w in widgets}
        assert areas <= {"tabs", "foot", "body"}
        assert all(w.area != "body" for w in widgets if w.kind == "tab")


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


def test_the_footer_and_the_help_text_fit_the_smallest_screen():
    assert len(tui.FOOTER) <= tui.MIN_W - 2
    assert all(len(line) <= 70 for line in [*tui.KEYS, *tui.COMMANDS])


def test_every_hint_fits_the_border_title_with_the_colour_prefix(tabs):
    for widgets in tabs.values():
        for w in widgets:
            prefix = len("R 15 G 15 B 15  ") if w.kind == "swatch" else 0
            assert len(w.hint) + prefix <= 68, (w.key, w.hint)


def test_the_colour_modal_text_fits_inside_its_border():
    assert len(tui.COLOUR_HINT) <= tui.COLOUR_MODAL_MIN_W - 4
    assert tui.COLOUR_MODAL_MIN_W <= tui.COLOUR_MODAL_MAX_W < tui.MIN_W


def test_down_from_a_dpi_swatch_reaches_the_dpi_slider(tabs):
    widgets = tabs["Performance"]
    for n in range(1, 7):
        swatch = find(widgets, f"dpi-colour.{n}")
        assert tui.nearest(widgets, swatch, "down").key == "dpi-slider", n


def test_down_walks_the_lighting_pane_in_order(tabs):
    widgets = tabs["Backlight"]
    cur = find(widgets, "effect")
    for expected in ("led-colour", "cycle-colour", "brightness", "cycle-time", "symmetry"):
        cur = tui.nearest(widgets, cur, "down")
        assert cur.key.startswith(expected), (expected, cur.key)
    assert tui.nearest(widgets, cur, "down").area == "foot"


def test_the_dpi_stages_share_a_row_when_there_is_room_and_stack_when_there_is_not():
    model = tui.Model(sample())
    wide = tui.build_widgets(model, tui.make_layout(50, 200))["Performance"]
    toggle, pick = find(wide, "dpi-enable.1"), find(wide, "dpi.1")
    assert pick.y == toggle.y and pick.x > toggle.x + toggle.w and pick.w >= 9
    narrow = tui.build_widgets(model, tui.make_layout(24, 80))["Performance"]
    toggle, pick = find(narrow, "dpi-enable.1"), find(narrow, "dpi.1")
    assert pick.y == toggle.y + 1


def test_the_dpi_group_has_the_same_margin_on_both_sides(tabs, layout):
    first, last = find(tabs["Performance"], "dpi-enable.1"), find(tabs["Performance"], "dpi-colour.6")
    panes = tui.make_panes(layout)[0]["Performance"]
    pane = next(p for p in panes if p.x <= first.x < p.x + p.w)
    x0, _, iw, _ = tui.inner(pane)
    left_margin, right_margin = first.x - x0, x0 + iw - (last.x + last.w)
    assert abs(left_margin - right_margin) <= 1


def test_the_dpi_column_is_one_block(tabs):
    widgets = tabs["Performance"]
    for n in range(1, 7):
        toggle, swatch = find(widgets, f"dpi-enable.{n}"), find(widgets, f"dpi-colour.{n}")
        pick = find(widgets, f"dpi.{n}")
        assert toggle.x == swatch.x
        assert pick.x + pick.w <= swatch.x + swatch.w


def test_the_first_row_of_a_pane_is_padded_when_there_is_room(tabs, layout):
    if layout.body_h < 20:
        pytest.skip("the smallest screens have no spare row")
    panes, _ = tui.make_panes(layout)
    for name, widgets in tabs.items():
        for w in widgets:
            if w.area != "body":
                continue
            pane = next(p for p in panes[name] if p.x <= w.x < p.x + p.w)
            assert w.y >= pane.y + 2, (name, w.key, w.y, pane.y)


def test_the_header_does_not_name_the_vendor():
    import inspect

    assert "EvoFox" not in inspect.getsource(tui)


def test_toggles_are_drawn_with_a_star():
    import inspect

    assert "'*' if on" in inspect.getsource(tui.Screen.draw_widget)


class FakePointer:
    def __init__(self):
        self.sensitivity, self.scroll, self.calls = 0.0, 1.0, []

    def step(self, which, direction):
        self.calls.append((which, direction))
        return "moved"


def test_the_pointer_sliders_apply_at_once_when_hyprland_is_there():
    fake = FakePointer()
    model = tui.Model(sample(), pointer=fake)
    widgets = tui.build_widgets(model, tui.make_layout(40, 120))["Performance"]
    sens, scroll = find(widgets, "pointer.sensitivity"), find(widgets, "pointer.scroll")
    assert sens.kind == scroll.kind == "slider" and sens.live and scroll.live
    assert sens.live(1, False) == "moved"
    assert scroll.live(-1, False) == "moved"
    assert fake.calls == [("sensitivity", 1), ("scroll", -1)]
    assert sens.bar(model.work)[3] == "+0.0"
    assert scroll.bar(model.work)[3] == "1.00x"


def test_the_pointer_sliders_are_placeholders_without_hyprland(tabs):
    keys = {w.key for widgets in tabs.values() for w in widgets}
    assert "pointer.sensitivity" not in keys
    assert any("set by OS" in w.text for w in tabs["Performance"] if w.kind == "label")


@pytest.mark.parametrize(
    "size,split",
    [
        ((24, 80), False),
        ((29, 100), False),
        ((30, 99), False),
        ((60, 99), False),
        ((30, 100), True),
        ((60, 300), True),
    ],
)
def test_the_split_layout_starts_at_one_hundred_by_thirty(size, split):
    assert tui.make_layout(*size).split is split


def test_the_split_rows_at_the_smallest_split_size():
    layout = tui.make_layout(30, 100)
    assert (layout.body_y, layout.body_h, layout.action_y, layout.status_y, layout.footer_y) == (
        7,
        17,
        24,
        28,
        29,
    )
    assert layout.action_h == 4


def test_the_banner_leaves_room_for_the_tab_bar_and_the_body():
    for h in (30, 39, 40, 60):
        layout = tui.make_layout(h, 120)
        assert layout.body_y == tui.BANNER_ROWS + 1
        assert layout.action_h == (4 if h < 40 else 6)


def split_layouts():
    return [tui.make_layout(h, w) for h, w in [(30, 100), (36, 120), (45, 170), (50, 200), (60, 300)]]


def test_settings_take_sixty_percent_and_the_preview_forty():
    for layout in split_layouts():
        panes, _ = tui.make_panes(layout)
        for name in ("Macro", "Performance", "Backlight", "Button"):
            left = tui.pane_titled(panes[name], {"Macro": "Macros", "Button": "Buttons"}.get(name, name))
            if name == "Backlight":
                left = tui.pane_titled(panes[name], "Lighting")
            preview = tui.pane_titled(panes[name], tui.PREVIEW_TITLE)
            span = layout.w - 2
            assert abs(left.w / span - 0.60) < 0.02, (layout.w, name)
            assert left.w + preview.w == span


def test_every_tab_has_the_preview_in_the_split_layout_and_never_in_the_compact_one():
    for layout in split_layouts():
        for panes in tui.make_panes(layout)[0].values():
            assert tui.pane_titled(panes, tui.PREVIEW_TITLE) is not None
    for size in ((24, 80), (29, 99), (60, 99)):
        for panes in tui.make_panes(tui.make_layout(*size))[0].values():
            assert tui.pane_titled(panes, tui.PREVIEW_TITLE) is None


def test_the_preview_text_fits_the_narrowest_preview_pane():
    from aurora import preview

    panes = tui.make_panes(tui.make_layout(30, 100))[0]
    pane = tui.pane_titled(panes["Performance"], tui.PREVIEW_TITLE)
    assert tui.inner(pane)[2] - 2 >= preview.MIN_WIDTH


def test_no_control_sits_in_the_preview(tabs, layout):
    if not layout.split:
        pytest.skip("only the split layout has a preview")
    panes, _ = tui.make_panes(layout)
    for name, widgets in tabs.items():
        pane = tui.pane_titled(panes[name], tui.PREVIEW_TITLE)
        for w in widgets:
            inside = pane.x <= w.x < pane.x + pane.w and pane.y <= w.y < pane.y + pane.h
            assert not inside, (name, w.key)


def first_height(predicate, width=120):
    return next(h for h in range(30, 90) if predicate(tui.make_layout(h, width)))


def button_panes(height, width=120):
    return tui.make_panes(tui.make_layout(height, width))[0]["Button"]


@pytest.mark.parametrize(
    "height,system,mouse",
    [(35, False, False), (36, False, True), (37, True, True), (45, True, True), (60, True, True)],
)
def test_the_system_section_and_the_mouse_pane_appear_only_when_there_is_room(height, system, mouse):
    panes = button_panes(height)
    assert (tui.pane_titled(panes, "System") is not None) is system
    assert (tui.pane_titled(panes, "Blaze") is not None) is mouse
    assert tui.pane_titled(panes, "Buttons").h >= tui.BUTTONS_PANE_H
    assert tui.pane_titled(panes, tui.PREVIEW_TITLE).h >= tui.PREVIEW_MIN_H


def test_the_system_section_takes_what_its_content_needs_and_gives_the_rest_to_the_buttons():
    for height in (37, 45, 50, 51, 60, 80):
        layout = tui.make_layout(height, 120)
        panes = button_panes(height)
        system, buttons = tui.pane_titled(panes, "System"), tui.pane_titled(panes, "Buttons")
        assert system.h in (tui.SYSTEM_SMALL_H, tui.SYSTEM_FULL_H)
        assert system.h + buttons.h == layout.body_h


def test_the_full_logo_fits_the_system_section_from_the_first_tall_size():
    height = first_height(
        lambda lay: (
            tui.pane_titled(tui.make_panes(lay)[0]["Button"], "System").h == tui.SYSTEM_FULL_H
            if tui.pane_titled(tui.make_panes(lay)[0]["Button"], "System")
            else False
        )
    )
    section = tui.pane_titled(button_panes(height), "System")
    assert logos.pick("nixos", tui.inner(section)[3]) is logos.LOGOS["nixos"]
    assert tui.pane_titled(button_panes(height), "Buttons").h >= tui.BUTTONS_PANE_H
    below = tui.pane_titled(button_panes(height - 1), "System")
    assert below.h == tui.SYSTEM_SMALL_H


def test_the_small_logo_and_the_stats_fit_the_small_system_section():
    section = tui.pane_titled(button_panes(45), "System")
    ih = tui.inner(section)[3]
    assert logos.pick("nixos", ih) is logos.SMALL["nixos"]
    assert ih >= 8


def test_the_buttons_get_their_rows_back_when_the_logo_is_small():
    panes = button_panes(45)
    buttons = tui.pane_titled(panes, "Buttons")
    assert buttons.h == tui.make_layout(45, 120).body_h - tui.SYSTEM_SMALL_H
    assert buttons.h >= tui.BUTTONS_PANE_H


def test_the_system_section_sits_above_the_buttons():
    panes = tui.make_panes(tui.make_layout(45, 170))[0]["Button"]
    system, buttons = tui.pane_titled(panes, "System"), tui.pane_titled(panes, "Buttons")
    assert system.y + system.h == buttons.y and system.x == buttons.x and system.w == buttons.w
    mouse = tui.pane_titled(panes, "Blaze")
    preview = tui.pane_titled(panes, tui.PREVIEW_TITLE)
    assert mouse.y + mouse.h == preview.y


def test_the_banner_and_the_profile_fit_beside_each_other_at_the_smallest_split_width():
    from aurora import banner

    beside = 2 + banner.render().width + 2
    assert beside + len("[offline] [read only]") < 100


def test_the_summary_fits_beside_the_tab_bar_at_the_smallest_split_width():
    longest = "1000 Hz | 12800 DPI | Cycle Breathing Effect"
    tabs_end = 33 + len("Backlight") + 2
    assert tabs_end + 2 < 100 - 3 - len(longest)


def test_the_preview_scrolls_by_pages_and_stops_at_both_ends():
    screen = object.__new__(tui.Screen)
    screen.preview_len, screen.preview_page, screen.preview_top = 60, 10, 0
    screen.scroll_preview(1)
    assert screen.preview_top == 10
    screen.scroll_preview(0.5)
    assert screen.preview_top == 15
    for _ in range(20):
        screen.scroll_preview(1)
    assert screen.preview_top == 49
    for _ in range(20):
        screen.scroll_preview(-1)
    assert screen.preview_top == 0
    screen.scroll_preview(-0.5)
    assert screen.preview_top == 0


def test_the_preview_keys_are_in_the_help():
    text = "\n".join(tui.KEYS)
    assert "PgUp / PgDn" in text and "Ctrl-U / Ctrl-D" in text
