"""Round 2: LibreHardwareMonitor WMI (PowerShell JSON) parsing."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import heatwatch_core as core


def sensor(name, value, identifier, stype="Temperature"):
    return {"Name": name, "SensorType": stype, "Value": value,
            "Identifier": identifier}


def test_full_list():
    payload = json.dumps([
        sensor("CPU Core #1", 88.0, "/intelcpu/0/temperature/0"),
        sensor("CPU Package", 94.0, "/intelcpu/0/temperature/9"),
        sensor("GPU Core", 72.0, "/gpu-nvidia/0/temperature/0"),
        sensor("GPU Fan", 2100.0, "/gpu-nvidia/0/fan/0", "Fan"),
        sensor("CPU Total", 55.0, "/intelcpu/0/load/0", "Load"),
    ])
    result = core.parse_wmi_sensors(payload)
    assert result == {"cpu": 94.0, "gpu": 72.0, "fan": 2100.0}, result
    print("PASS WMI list: package + GPU core, non-temps filtered")


def test_single_object_not_array():
    payload = json.dumps(
        sensor("CPU Package", 90.0, "/amdcpu/0/temperature/3"))
    assert core.parse_wmi_sensors(payload) == {"cpu": 90.0,
                                               "gpu": None,
                                               "fan": None}
    print("PASS a lone sensor arrives as an object, not an array")


def test_garbage():
    empty = {"cpu": None, "gpu": None, "fan": None}
    assert core.parse_wmi_sensors("") == empty
    assert core.parse_wmi_sensors("not json") == empty
    assert core.parse_wmi_sensors("42") == empty
    assert core.parse_wmi_sensors(None) == empty
    print("PASS garbage WMI output yields Nones, never raises")


def main():
    test_full_list()
    test_single_object_not_array()
    test_garbage()
    print("ROUND 2 ALL PASS")


if __name__ == "__main__":
    main()
