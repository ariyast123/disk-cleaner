"""Round 14: UI polish helpers — buffer, scaling, gauge math."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import heatwatch_core as core

import heatwatch_app as gui


def test_buffer():
    buf = core.SampleBuffer(capacity=5)
    for i in range(8):
        buf.push(i, 50.0 + i, 40.0 + i)
    assert len(buf) == 5
    assert buf.cpu_series() == [53.0, 54.0, 55.0, 56.0, 57.0]
    assert buf.gpu_series() == [43.0, 44.0, 45.0, 46.0, 47.0]
    buf2 = core.SampleBuffer()
    buf2.push(0, None, 60.0)
    buf2.push(1, 70.0, None)
    assert buf2.cpu_series() == [70.0] and buf2.gpu_series() == [60.0]
    print("PASS sample buffer: newest N kept, missing skipped per line")


def test_scale_series():
    assert core.scale_series([], 100, 50, 30, 110) == []
    assert core.scale_series([70.0], 100, 50, 30, 110) == []
    points = core.scale_series([30.0, 70.0, 110.0], 100, 80, 30, 110)
    assert points[0] == (0.0, 80.0)
    assert points[1] == (50.0, 40.0)
    assert points[2] == (100.0, 0.0)
    clamped = core.scale_series([10.0, 200.0], 100, 80, 30, 110)
    assert clamped[0][1] == 80.0 and clamped[1][1] == 0.0
    print("PASS sparkline scaling: cold bottom, hot top, clamped")


def test_gauge_fraction():
    assert gui.gauge_fraction(None) == 0.0
    assert gui.gauge_fraction(0) == 0.0
    assert gui.gauge_fraction(55) == 0.5
    assert gui.gauge_fraction(110) == 1.0
    assert gui.gauge_fraction(220) == 1.0
    assert gui.gauge_fraction(-5) == 0.0
    print("PASS gauge fraction clamps to 0..1, None is empty")


def main():
    test_buffer()
    test_scale_series()
    test_gauge_fraction()
    print("ROUND 14 ALL PASS")


if __name__ == "__main__":
    main()
