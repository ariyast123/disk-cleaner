"""Round 5: the sustained-heat warner."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import heatwatch_core as core


def test_sustained_fires_once():
    warner = core.HeatWarner(95, sustain_seconds=15.0)
    assert warner.update(0, 96) is False
    assert warner.update(10, 97) is False
    assert warner.update(15, 96) is True
    assert warner.update(20, 99) is False
    assert warner.update(30, 99) is False
    print("PASS sustained heat fires exactly once")


def test_dip_resets_clock():
    warner = core.HeatWarner(95, sustain_seconds=15.0)
    warner.update(0, 96)
    warner.update(10, 90)
    assert warner.update(20, 96) is False
    assert warner.update(34, 96) is False
    assert warner.update(35, 96) is True
    print("PASS a real cool-down resets the sustain clock")


def test_small_dip_keeps_clock():
    warner = core.HeatWarner(95, sustain_seconds=15.0, hysteresis=2.0)
    warner.update(0, 96)
    warner.update(8, 94)
    assert warner.update(15, 96) is True
    print("PASS a 1-degree dip inside hysteresis does not reset")


def test_rearm_after_cooling():
    warner = core.HeatWarner(95, sustain_seconds=10.0)
    warner.update(0, 97)
    assert warner.update(10, 97) is True
    warner.update(12, 80)
    warner.update(20, 97)
    assert warner.update(30, 97) is True
    print("PASS cooling re-arms the warning for the next climb")


def test_none_is_silent():
    warner = core.HeatWarner(95, sustain_seconds=5.0)
    assert warner.update(0, None) is False
    assert warner.update(100, None) is False
    print("PASS missing readings never warn")


def main():
    test_sustained_fires_once()
    test_dip_resets_clock()
    test_small_dip_keeps_clock()
    test_rearm_after_cooling()
    test_none_is_silent()
    print("ROUND 5 ALL PASS")


if __name__ == "__main__":
    main()
