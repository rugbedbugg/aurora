from blazectl import device


def test_ioctl_numbers_match_the_kernel_values_for_eight_byte_reports():
    assert device.HIDIOCSFEATURE == 0xC0084806
    assert device.HIDIOCGFEATURE == 0xC0084807


def test_hexs_formats_bytes():
    assert device.hexs(bytes([7, 0x18, 0xFF])) == "07 18 ff"


def test_the_vendor_app_check_reads_the_process_list():
    assert device.vendor_app_running() in (True, False)
