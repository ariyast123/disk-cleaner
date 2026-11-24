"""Round 10 — exe icon: generation, ICO validity, build wiring."""
import hashlib
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import gamemode_core as core

TMP = tempfile.mkdtemp(prefix="gmvpn-icon-")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _sha(path):
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def test_write_app_icon():
    out = os.path.join(TMP, "gamemode_icon.ico")
    assert core.write_app_icon(out) == out
    assert os.path.isfile(out)
    assert os.path.getsize(out) > 1000
    from PIL import Image

    img = Image.open(out)
    assert img.format == "ICO"
    assert img.size == (256, 256)
    assert set(img.info.get("sizes", [])) == set(core.ICON_SIZES)
    # The bolt stays cyan and the corners stay transparent at 256px.
    px = img.convert("RGBA")
    assert px.getpixel((128, 128))[0] < 100  # inside the bolt: cyan, low red
    assert px.getpixel((128, 128))[2] > 200
    assert px.getpixel((4, 4))[3] == 0  # rounded corner: transparent
    print("PASS write_app_icon produces a valid multi-size ICO")


def test_write_app_icon_deterministic():
    first = os.path.join(TMP, "first.ico")
    second = os.path.join(TMP, "second.ico")
    core.write_app_icon(first)
    core.write_app_icon(second)
    assert _sha(first) == _sha(second)
    print("PASS write_app_icon is deterministic")


def test_build_bat_wiring():
    with open(os.path.join(ROOT, "build.bat"), encoding="utf-8") as handle:
        build = handle.read()
    assert "--icon gamemode_icon.ico" in build
    assert "write_app_icon" in build  # regenerates the icon when missing
    assert "pillow" in build  # the icon generator needs Pillow
    assert "gamemode_icon.ico" in core.UPDATE_FILES
    print("PASS build.bat embeds the icon and regenerates it when missing")


def test_shipped_icon_valid():
    shipped = os.path.join(ROOT, "gamemode_icon.ico")
    assert os.path.isfile(shipped), "gamemode_icon.ico must ship in the repo"
    from PIL import Image

    img = Image.open(shipped)
    assert img.format == "ICO"
    assert set(img.info.get("sizes", [])) == set(core.ICON_SIZES)
    print("PASS shipped gamemode_icon.ico is a valid multi-size ICO")


if __name__ == "__main__":
    test_write_app_icon()
    test_write_app_icon_deterministic()
    test_build_bat_wiring()
    test_shipped_icon_valid()
    print("ROUND 10: ALL PASS")
