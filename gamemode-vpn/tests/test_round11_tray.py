"""Round 11 — tray image + tray availability degradation (no display)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import gamemode_vpn_app as gui


def test_tray_image():
    if not gui.TRAY_AVAILABLE:
        # pystray needs a display backend this env lacks; Pillow is
        # present, so inject it and exercise the drawing itself.
        from PIL import Image, ImageDraw
        gui.Image, gui.ImageDraw = Image, ImageDraw
    image = gui._tray_image()
    assert image.size == (64, 64)
    assert image.mode == "RGBA"
    # the cyan core pixel at the centre and a transparent corner
    assert image.getpixel((32, 32)) == (34, 211, 238, 255)
    assert image.getpixel((0, 0))[3] == 0
    print("PASS tray image drawn (64x64, cyan core, transparent corner)")


def test_tray_flag_is_bool():
    assert isinstance(gui.TRAY_AVAILABLE, bool)
    print(f"PASS TRAY_AVAILABLE is a bool ({gui.TRAY_AVAILABLE})")


if __name__ == "__main__":
    test_tray_image()
    test_tray_flag_is_bool()
    print("ROUND 11: ALL PASS")
