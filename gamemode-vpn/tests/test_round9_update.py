"""Round 9 — self-update helpers: versions, validation, What's New."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import gamemode_core as core

TMP = tempfile.mkdtemp(prefix="gmvpn-update-")

GOOD = {
    "gamemode_vpn_app.py": b"print('app')\n",
    "gamemode_core.py": b"print('core')\n",
    "build.bat": b"@echo off\n",
}


def test_parse_version():
    p = core.parse_version
    assert p("1.1") == p("1.1.0")
    assert p("1.2.0") > p("1.1.9")
    assert p("1.10.0") > p("1.9.9")
    assert p("2") > p("1.99.99")
    assert p("") == (0,)
    assert p("banana") == (0,)
    assert p("1.2.3-beta") == (1, 2, 3)
    assert p(" 1.0.1 ") == (1, 0, 1)
    print("PASS parse_version")


def test_validate_update_files():
    v = core.validate_update_files
    assert v(dict(GOOD)) is True
    assert v(None) is False
    assert v({}) is False
    missing = dict(GOOD)
    del missing["build.bat"]
    assert v(missing) is False
    empty = dict(GOOD)
    empty["gamemode_core.py"] = b""
    assert v(empty) is False
    broken = dict(GOOD)
    broken["gamemode_vpn_app.py"] = b"def broken(:\n"
    assert v(broken) is False
    print("PASS validate_update_files")


def test_whats_new_flow():
    info = {"version": "1.2.0", "patch_notes": "Line one\nLine two"}
    core.save_whats_new(info, directory=TMP)
    # running an older version: stale file is consumed, nothing shown
    assert core.pop_whats_new("1.1.0", directory=TMP) is None
    assert not os.path.exists(core.whats_new_path(TMP))
    # matching version: shown exactly once
    core.save_whats_new(info, directory=TMP)
    data = core.pop_whats_new("1.2.0", directory=TMP)
    assert data is not None
    assert data["version"] == "1.2.0"
    assert data["patch_notes"] == "Line one\nLine two"
    assert core.pop_whats_new("1.2.0", directory=TMP) is None
    print("PASS whats_new shown exactly once, only on match")


def test_whats_new_list_notes():
    info = {"version": "1.3.0", "patch_notes": ["alpha", "beta"]}
    core.save_whats_new(info, directory=TMP)
    data = core.pop_whats_new("1.3.0", directory=TMP)
    assert data["patch_notes"] == "alpha\nbeta"
    # no file at all -> None, no crash
    assert core.pop_whats_new("1.3.0", directory=TMP) is None
    print("PASS whats_new list notes normalized")


if __name__ == "__main__":
    test_parse_version()
    test_validate_update_files()
    test_whats_new_flow()
    test_whats_new_list_notes()
    print("ROUND 9: ALL PASS")
