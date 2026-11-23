"""Round 3: nvidia-smi parsing + merged source priority."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import heatwatch_core as core


def readers(web=None, wmi=None, smi=None):
    return {"web": lambda: web, "wmi": lambda: wmi, "smi": lambda: smi}


def test_smi_parse():
    assert core.parse_nvidia_smi("72\n") == 72.0
    assert core.parse_nvidia_smi("  65 \n") == 65.0
    assert core.parse_nvidia_smi("") is None
    assert core.parse_nvidia_smi("N/A") is None
    assert core.parse_nvidia_smi(None) is None
    print("PASS nvidia-smi output parsing")


def test_web_wins():
    sample = core.collect_temps(readers=readers(
        web={"cpu": 91.0, "gpu": 70.0},
        wmi={"cpu": 50.0, "gpu": 40.0}, smi=30.0))
    assert sample == {"cpu": 91.0, "gpu": 70.0, "source": "LHM web"}, sample
    print("PASS web feed beats WMI and smi when complete")


def test_wmi_fills_cpu_smi_fills_gpu():
    sample = core.collect_temps(readers=readers(
        web=None, wmi={"cpu": 88.0, "gpu": None}, smi=69.0))
    assert sample == {"cpu": 88.0, "gpu": 69.0,
                      "source": "LHM WMI + nvidia-smi"}, sample
    print("PASS WMI fills the CPU, smi fills the GPU")


def test_partial_web_plus_wmi():
    sample = core.collect_temps(readers=readers(
        web={"cpu": None, "gpu": 71.0},
        wmi={"cpu": 90.0, "gpu": 40.0}, smi=None))
    assert sample["cpu"] == 90.0 and sample["gpu"] == 71.0, sample
    assert sample["source"] == "LHM web + LHM WMI", sample
    print("PASS partial web result merges with WMI, labels honest")


def test_nothing_anywhere():
    sample = core.collect_temps(readers=readers())
    assert sample == {"cpu": None, "gpu": None, "source": "none"}, sample
    print("PASS no sources -> a clean 'none' sample")


def main():
    test_smi_parse()
    test_web_wins()
    test_wmi_fills_cpu_smi_fills_gpu()
    test_partial_web_plus_wmi()
    test_nothing_anywhere()
    print("ROUND 3 ALL PASS")


if __name__ == "__main__":
    main()
