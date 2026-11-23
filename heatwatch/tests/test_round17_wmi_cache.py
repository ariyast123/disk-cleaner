"""Round 17: the WMI negative cache in collect_temps."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import heatwatch_core as core


class Counting:
    def __init__(self, web=None, wmi=None, smi=None):
        self.values = {"web": web, "wmi": wmi, "smi": smi}
        self.calls = {"web": 0, "wmi": 0, "smi": 0}

    def readers(self):
        def make(key):
            def read():
                self.calls[key] += 1
                return self.values[key]
            return read
        return {key: make(key) for key in self.values}


def test_miss_is_cached_for_a_minute():
    core._reset_source_caches()
    probe = Counting(web=None, wmi=None, smi=65.0)
    sample = core.collect_temps(readers=probe.readers(), now=1000.0)
    assert sample["gpu"] == 65.0 and probe.calls["wmi"] == 1
    core.collect_temps(readers=probe.readers(), now=1030.0)
    assert probe.calls["wmi"] == 1, probe.calls  # skipped, too soon
    core.collect_temps(readers=probe.readers(), now=1061.0)
    assert probe.calls["wmi"] == 2, probe.calls  # retried after 60s
    print("PASS an empty WMI is not re-spawned for 60 seconds")


def test_hit_clears_the_miss():
    core._reset_source_caches()
    probe = Counting(web=None, wmi=None, smi=None)
    core.collect_temps(readers=probe.readers(), now=2000.0)
    assert probe.calls["wmi"] == 1
    probe.values["wmi"] = {"cpu": 90.0, "gpu": None}
    core.collect_temps(readers=probe.readers(), now=2030.0)
    assert probe.calls["wmi"] == 1  # still inside the miss window
    sample = core.collect_temps(readers=probe.readers(), now=2061.0)
    assert probe.calls["wmi"] == 2 and sample["cpu"] == 90.0
    core.collect_temps(readers=probe.readers(), now=2062.0)
    assert probe.calls["wmi"] == 3  # hit cleared the miss: no skip
    print("PASS a WMI hit clears the miss at once")


def test_complete_web_never_touches_wmi():
    core._reset_source_caches()
    probe = Counting(web={"cpu": 80.0, "gpu": 60.0},
                     wmi={"cpu": 1.0, "gpu": 1.0}, smi=1.0)
    sample = core.collect_temps(readers=probe.readers(), now=3000.0)
    assert sample["source"] == "LHM web"
    assert probe.calls["wmi"] == 0 and probe.calls["smi"] == 0
    print("PASS a complete web feed still short-circuits the rest")


def test_merge_semantics_unchanged():
    core._reset_source_caches()
    probe = Counting(web=None, wmi={"cpu": 88.0, "gpu": None},
                     smi=69.0)
    sample = core.collect_temps(readers=probe.readers(), now=4000.0)
    assert sample == {"cpu": 88.0, "gpu": 69.0,
                      "source": "LHM WMI + nvidia-smi"}, sample
    core._reset_source_caches()
    probe = Counting(web={"cpu": None, "gpu": 71.0},
                     wmi={"cpu": 90.0, "gpu": 40.0}, smi=None)
    sample = core.collect_temps(readers=probe.readers(), now=5000.0)
    assert sample["source"] == "LHM web + LHM WMI", sample
    print("PASS merge results and labels are exactly as before")


def main():
    test_miss_is_cached_for_a_minute()
    test_hit_clears_the_miss()
    test_complete_web_never_touches_wmi()
    test_merge_semantics_unchanged()
    print("ROUND 17 ALL PASS")


if __name__ == "__main__":
    main()
