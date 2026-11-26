"""Round 23: impossible sensor values are dropped, never trusted.

LHM sometimes publishes 255 °C (or -55 °C) for a missing probe,
and a stray fan RPM in the hundreds of thousands. Those values
must read as "no reading" — never as a peak, a verdict input,
or a warning — and dropping one must still let the fallback
sources fill the gap.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import heatwatch_core as core


def tree(cpu_sensors, gpu_sensors, cpu_fans=None):
    def hw(name, sensors, fans=None):
        children = [{"Text": "Temperatures", "Children": [
            {"Text": n, "Value": v} for n, v in sensors]}]
        if fans:
            children.append({"Text": "Fans", "Children": [
                {"Text": n, "Value": v} for n, v in fans]})
        return {"Text": name, "Children": children}

    return {"Text": "Sensor", "Children": [
        {"Text": "DESKTOP-ARIYA", "Children": [
            hw("Intel Core i7-11800H", cpu_sensors, cpu_fans),
            hw("NVIDIA GeForce RTX 3060 Laptop GPU", gpu_sensors),
        ]}]}


def test_web_garbage_temps_dropped():
    # A 255 °C "package" is a dead probe: the hottest real core
    # speaks instead, and the garbage never becomes a peak.
    result = core.parse_lhm_web_tree(tree(
        [("CPU Package", "255.0 °C"), ("CPU Core #1", "91.0 °C")],
        [("GPU Core", "71.0 °C")]))
    assert result["cpu"] == 91.0, result
    result = core.parse_lhm_web_tree(tree(
        [("CPU Package", "-55.0 °C"), ("CPU Core #1", "88.0 °C")],
        [("GPU Core", "71.0 °C")]))
    assert result["cpu"] == 88.0, result
    # A lone impossible GPU reading leaves the GPU as "none".
    result = core.parse_lhm_web_tree(tree(
        [("CPU Package", "90.0 °C")], [("GPU Core", "999 °C")]))
    assert result == {"cpu": 90.0, "gpu": None, "fan": None}, result
    # Boundaries: -40 and 130 are kept, a tenth past either is not.
    result = core.parse_lhm_web_tree(tree(
        [("CPU Core #1", "130.0 °C"), ("CPU Core #2", "90.0 °C")], []))
    assert result["cpu"] == 130.0, result
    result = core.parse_lhm_web_tree(tree([("CPU Core #1", "130.1 °C")], []))
    assert result["cpu"] is None, result
    result = core.parse_lhm_web_tree(tree([("CPU Core #1", "-40.0 °C")], []))
    assert result["cpu"] == -40.0, result
    result = core.parse_lhm_web_tree(tree([("CPU Core #1", "-40.1 °C")], []))
    assert result["cpu"] is None, result
    print("PASS web feed: 255/-55/999 °C dropped, bounds kept")


def test_web_garbage_fans_dropped():
    result = core.parse_lhm_web_tree(tree(
        [("CPU Package", "90.0 °C")], [("GPU Core", "70.0 °C")],
        cpu_fans=[("Fan #1", "-100 RPM")]))
    assert result["fan"] is None, result
    result = core.parse_lhm_web_tree(tree(
        [("CPU Package", "90.0 °C")], [("GPU Core", "70.0 °C")],
        cpu_fans=[("Fan #1", "999999 RPM")]))
    assert result["fan"] is None, result
    # A stopped fan (0 RPM) is real and kept; the 100k bound is kept.
    result = core.parse_lhm_web_tree(tree(
        [("CPU Package", "90.0 °C")], [("GPU Core", "70.0 °C")],
        cpu_fans=[("Fan #1", "0 RPM")]))
    assert result["fan"] == 0.0, result
    result = core.parse_lhm_web_tree(tree(
        [("CPU Package", "90.0 °C")], [("GPU Core", "70.0 °C")],
        cpu_fans=[("Fan #1", "100000 RPM")]))
    assert result["fan"] == 100000.0, result
    result = core.parse_lhm_web_tree(tree(
        [("CPU Package", "90.0 °C")], [("GPU Core", "70.0 °C")],
        cpu_fans=[("Fan #1", "100001 RPM")]))
    assert result["fan"] is None, result
    # One garbage fan does not hide the good one.
    result = core.parse_lhm_web_tree(tree(
        [("CPU Package", "90.0 °C")], [("GPU Core", "70.0 °C")],
        cpu_fans=[("Fan #1", "-100 RPM"), ("Fan #2", "2100 RPM")]))
    assert result["fan"] == 2100.0, result
    print("PASS web feed: impossible fan RPM dropped, 0 kept")


def test_wmi_garbage_dropped():
    def sensor(name, value, identifier, stype="Temperature"):
        return {"Name": name, "SensorType": stype, "Value": value,
                "Identifier": identifier}

    payload = json.dumps([
        sensor("CPU Package", 255.0, "/intelcpu/0/temperature/9"),
        sensor("CPU Core #1", 91.0, "/intelcpu/0/temperature/0"),
        sensor("GPU Core", 999.0, "/gpu-nvidia/0/temperature/0"),
        sensor("GPU Fan", -50.0, "/gpu-nvidia/0/fan/0", "Fan"),
        sensor("CPU Fan", 2200.0, "/intelcpu/0/fan/0", "Fan"),
    ])
    result = core.parse_wmi_sensors(payload)
    assert result == {"cpu": 91.0, "gpu": None, "fan": 2200.0}, result
    payload = json.dumps(
        sensor("CPU Package", 255.0, "/intelcpu/0/temperature/9"))
    assert core.parse_wmi_sensors(payload) == {"cpu": None, "gpu": None,
                                               "fan": None}
    print("PASS WMI: impossible temps and fan RPM dropped")


def test_smi_garbage_dropped():
    assert core.parse_nvidia_smi("255\n") is None
    assert core.parse_nvidia_smi("131\n") is None
    assert core.parse_nvidia_smi("-50\n") is None
    assert core.parse_nvidia_smi("72\n") == 72.0
    assert core.parse_nvidia_smi("130\n") == 130.0
    print("PASS nvidia-smi: impossible GPU temps dropped")


def test_dropped_reading_still_falls_back():
    # The web feed's CPU is garbage (dropped to None) but its GPU
    # is fine; WMI must still get its chance to fill the CPU.
    garbage_tree = tree(
        [("CPU Package", "255.0 °C")], [("GPU Core", "71.0 °C")])
    readers = {
        "web": lambda: core.parse_lhm_web_tree(garbage_tree),
        "wmi": lambda: {"cpu": 90.0, "gpu": None, "fan": None},
        "smi": lambda: None,
    }
    sample = core.collect_temps(readers=readers)
    assert sample == {"cpu": 90.0, "gpu": 71.0, "fan": None,
                      "source": "LHM web + LHM WMI"}, sample
    print("PASS a dropped reading behaves like a missing one: "
          "fallback still fills it")


def main():
    test_web_garbage_temps_dropped()
    test_web_garbage_fans_dropped()
    test_wmi_garbage_dropped()
    test_smi_garbage_dropped()
    test_dropped_reading_still_falls_back()
    print("ROUND 23 ALL PASS")


if __name__ == "__main__":
    main()
