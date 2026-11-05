from blazectl import image, tui


def sample():
    return image.load_sample()


def test_dpi_steps_move_along_the_known_values_only():
    img = sample()
    step = tui.dpi_step(0)
    step(img, 1, False)(img)
    assert image.get_dpi_index(img, 0) == 8
    for _ in range(10):
        step(img, 1, False)(img)
    assert image.get_dpi_index(img, 0) == 22
    for _ in range(10):
        step(img, -1, False)(img)
    assert image.get_dpi_index(img, 0) == 2


def test_an_unknown_dpi_index_steps_to_the_nearest_known_value():
    img = sample()
    image.set_dpi_stage(img, 0, 6)
    tui.dpi_step(0)(img, 1, False)(img)
    assert image.get_dpi_index(img, 0) == 8
    image.set_dpi_stage(img, 0, 6)
    tui.dpi_step(0)(img, -1, False)(img)
    assert image.get_dpi_index(img, 0) == 5


def test_number_steps_clamp_and_honour_the_fine_step():
    img = sample()
    row = next(r for r in tui.build_rows()["Performance"] if r.key == "fire-time")
    row.step(img, 1, False)(img)
    assert img[0x1A] == 60
    row.step(img, 1, True)(img)
    assert img[0x1A] == 61
    for _ in range(40):
        row.step(img, 1, False)(img)
    assert img[0x1A] | img[0x1B] << 8 == 300


def test_every_row_shows_a_value_for_the_sample():
    for rows in tui.build_rows().values():
        for row in rows:
            value = row.rgb[0](sample()) if row.rgb else row.show(sample())
            assert value is not None


def test_there_is_one_tab_per_name():
    assert list(tui.build_rows()) == tui.TABS
