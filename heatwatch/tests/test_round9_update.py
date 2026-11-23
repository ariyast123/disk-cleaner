"""Round 9: self-update helpers (versions, validation, What's New)."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import heatwatch_core as core

TMP = tempfile.mkdtemp(prefix="hw-upd-")
core.data_dir = lambda: TMP

import heatwatch_app as gui

GOOD = {
    "heatwatch_app.py": b"# app\nVALUE = 1\n",
    "heatwatch_core.py": b"# core\nVALUE = 2\n",
    "build.bat": b"@echo off\n",
    "heatwatch_icon.ico": b"\x00\x01fake",
}


def test_parse_version():
    assert gui.parse_version("1.0.0") == gui.parse_version("1.0")
    assert gui.parse_version("1.2.9") > gui.parse_version("1.2.8")
    assert gui.parse_version("v2.0") > gui.parse_version("1.9.9")
    assert gui.parse_version("1.0.1") > gui.parse_version("1.0.0")
    print("PASS version comparison, trailing zeros ignored")


def test_validate():
    assert gui.validate_update_files(GOOD) is True
    missing = dict(GOOD)
    del missing["heatwatch_icon.ico"]
    assert gui.validate_update_files(missing) is False
    broken = dict(GOOD)
    broken["heatwatch_core.py"] = b"def broken(:\n"
    assert gui.validate_update_files(broken) is False
    empty = dict(GOOD)
    empty["build.bat"] = b""
    assert gui.validate_update_files(empty) is False
    assert gui.validate_update_files(None) is False
    assert gui.validate_update_files("junk") is False
    print("PASS update validation: complete set + compilable sources")


def test_whats_new_once():
    gui.save_whats_new({"version": "1.0.0",
                        "patch_notes": "First line\nSecond line"})
    assert gui.pop_whats_new("1.0.0") == "First line\nSecond line"
    assert gui.pop_whats_new("1.0.0") is None  # consumed
    gui.save_whats_new({"version": "9.9.9", "patch_notes": "future"})
    assert gui.pop_whats_new("1.0.0") is None  # stale version dropped
    gui.save_whats_new({"version": "1.0.1",
                        "patch_notes": ["a", "b"]})
    assert gui.pop_whats_new("1.0.1") == "a\nb"  # list notes join
    print("PASS What's New: shown once, only for its own version")


def test_raw_url_bust():
    plain = gui._raw_url("heatwatch/version.json")
    assert plain == ("https://raw.githubusercontent.com/ariyast123/"
                     "disk-cleaner/main/heatwatch/version.json")
    busted = gui._raw_url("heatwatch/version.json", cache_bust=True)
    assert busted.startswith(plain + "?t=")
    assert busted.rsplit("=", 1)[1].isdigit()
    print("PASS raw URLs, with and without the cache buster")


def main():
    test_parse_version()
    test_validate()
    test_whats_new_once()
    test_raw_url_bust()
    print("ROUND 9 ALL PASS")


if __name__ == "__main__":
    main()
