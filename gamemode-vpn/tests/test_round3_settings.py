"""Round 3 — settings load / save / normalize."""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import gamemode_core as core

TMP = tempfile.mkdtemp(prefix="gmvpn-settings-")


def path(name):
    return os.path.join(TMP, name)


def test_defaults_when_missing_or_corrupt():
    assert core.load_settings(path("nope.json")) == core.default_settings()
    bad = path("bad.json")
    with open(bad, "w") as fh:
        fh.write("{not json")
    assert core.load_settings(bad) == core.default_settings()
    weird = path("weird.json")
    with open(weird, "w") as fh:
        json.dump(["a", "list"], fh)
    assert core.load_settings(weird) == core.default_settings()
    print("PASS missing / corrupt -> defaults")


def test_partial_merge_and_clamps():
    raw = {"poll_seconds": 99, "gone_debounce_seconds": -5,
           "auto_launch_proton": False, "proton_path": "  D:\\Apps\\ProtonVPN.exe  "}
    s = core.normalize_settings(raw)
    assert s["poll_seconds"] == 10.0          # clamped to max
    assert s["gone_debounce_seconds"] == 0.0  # clamped to min
    assert s["auto_launch_proton"] is False
    assert s["proton_path"] == "D:\\Apps\\ProtonVPN.exe"  # trimmed
    assert s["games"] == core.default_settings()["games"]  # untouched default
    s2 = core.normalize_settings({"poll_seconds": "banana"})
    assert s2["poll_seconds"] == 2.0          # garbage -> fallback
    print("PASS partial merge + clamps")


def test_games_validation():
    raw = {"games": [
        {"name": "Good", "patterns": ["good.exe"], "enabled": True},
        {"name": "good", "patterns": ["dupe.exe"]},            # duplicate name (case)
        {"name": "NoPatterns", "patterns": []},                # dropped
        {"name": "", "patterns": ["x.exe"]},                   # dropped
        "not-a-dict",                                          # dropped
        {"name": "Stringy", "patterns": "oops.exe"},           # dropped (not a list)
        {"name": "Caps", "patterns": ["CAPS.EXE", "  "]},      # kept, cleaned
    ]}
    s = core.normalize_settings(raw)
    names = [g["name"] for g in s["games"]]
    assert names == ["Good", "Caps"], names
    assert s["games"][1]["patterns"] == ["caps.exe"]
    print("PASS games validation")


def test_adapter_keywords():
    s = core.normalize_settings({"adapter_keywords": [" Proton ", "", "WINTUN"]})
    assert s["adapter_keywords"] == ["proton", "wintun"]
    s = core.normalize_settings({"adapter_keywords": []})
    assert s["adapter_keywords"] == ["proton"]  # empty list -> default
    print("PASS adapter keywords")


def test_save_load_roundtrip():
    target = path(os.path.join("nested", "settings.json"))
    s = core.default_settings()
    s["poll_seconds"] = 3.5
    s["games"].append({"name": "Valorant", "patterns": ["valorant.exe"],
                        "enabled": True, "builtin": False})
    core.save_settings(s, target)
    loaded = core.load_settings(target)
    assert loaded["poll_seconds"] == 3.5
    assert any(g["name"] == "Valorant" for g in loaded["games"])
    assert not os.path.exists(target + ".tmp")  # atomic replace cleaned up
    print("PASS save/load roundtrip")


if __name__ == "__main__":
    test_defaults_when_missing_or_corrupt()
    test_partial_merge_and_clamps()
    test_games_validation()
    test_adapter_keywords()
    test_save_load_roundtrip()
    print("ROUND 3: ALL PASS")
