"""Reproducible synthetic comparison to the starting revision; no camera or input.

Run from the repository root: python -m gestures.tests.benchmark_pointing
The pinned baseline remains the pre-fix classifier after this change is committed.
"""

from collections import Counter
import json
from pathlib import Path
import statistics
import subprocess
import sys
import time
from types import ModuleType

from gestures.features import extract_features
from gestures.static_gestures import classify_hand
from .static_fixtures import SIZE, pose_hand, project_hand
from .test_pointing_reliability import ALL, OTHERS, natural_pointing


BASELINE_REVISION = "a1c02314631cc0e394956aaf99dc14681d591c7d"


def corpus():
    cases = []
    for side in ("Left", "Right"):
        for relaxed in ((OTHERS[0],), (OTHERS[1],), (OTHERS[2],), OTHERS):
            cases.append(("relaxed_curl", natural_pointing(relaxed=relaxed, side=side)))
        for relaxed in ((), OTHERS):
            cases.append(("bent_index", natural_pointing(relaxed=relaxed, bent_index=True, side=side)))
        for scale in (.025, .07, .11):
            for roll in (0, -35, 35, 90, 180):
                for yaw, pitch in ((0, 0), (-30, 0), (30, 0), (0, 30), (150, 0), (180, 0)):
                    hand = project_hand(natural_pointing(side=side, scale=scale, rotation=roll),
                                        yaw=yaw, pitch=pitch)
                    cases.append(("rotated_pointing", hand))
        for yaw in (0, -30, 30, 150, 180):
            for curled, partial, thumb in ((ALL, (), "tucked"), (ALL, (), "relaxed"),
                                           (ALL, (), "extended"), ((), (), "relaxed"),
                                           (OTHERS[1:], (), "relaxed"), ((OTHERS[2],), (), "relaxed"),
                                           (OTHERS[1:], ALL[:2], "relaxed"), (OTHERS, (ALL[0],), "relaxed")):
                cases.append(("non_pointing", project_hand(pose_hand(curled=curled, partial=partial,
                                                                      thumb=thumb, side=side), yaw=yaw)))
    return [(group, extract_features(hand, image_size=SIZE)) for group, hand in cases]


def baseline_classifier():
    root = Path(__file__).resolve().parents[2]
    baseline_path = f"{BASELINE_REVISION}:gestures/static_gestures.py"
    source = subprocess.run(["git", "show", baseline_path], cwd=root,
                            check=True, capture_output=True, text=True).stdout
    module = ModuleType("gestures._pointing_baseline")
    sys.modules[module.__name__] = module
    exec(compile(source, baseline_path, "exec"), module.__dict__)
    return module.classify_hand


def main():
    baseline = baseline_classifier()
    samples = corpus()
    counts = {}
    for name, classify in (("before", baseline), ("after", classify_hand)):
        groups = {}
        for group, features in samples:
            groups.setdefault(group, Counter())[classify(features, 0).gesture.value] += 1
        counts[name] = groups
    # Same cached pair, warmup and alternating execution order reduce host drift.
    pair = (samples[0][1], extract_features(pose_hand(curled=ALL), image_size=SIZE))
    timings = {"before": [], "after": []}
    for iteration in range(2200):
        order = (("before", baseline), ("after", classify_hand))
        for name, classify in (order if iteration % 2 else reversed(order)):
            start = time.perf_counter_ns()
            for features in pair:
                classify(features, iteration)
            elapsed = (time.perf_counter_ns() - start) / 1e6
            if iteration >= 200:
                timings[name].append(elapsed)
    summary = {name: {"mean_ms": statistics.mean(values),
                      "p95_ms": sorted(values)[int(.95 * len(values)) - 1]}
               for name, values in timings.items()}
    limitations = []
    for roll in (35, 90):
        features = extract_features(project_hand(natural_pointing(rotation=roll), yaw=45), image_size=SIZE)
        result = classify_hand(features, 0, diagnostics=True)
        limitations.append({"roll": roll, "yaw": 45, "gesture": result.gesture.value,
                            "failed": [f"{check.finger}.{check.measurement}" for check in result.pointing_checks
                                       if not check.passed]})
    non_pointing_changes = sum(baseline(features, 0).gesture.value != classify_hand(features, 0).gesture.value
                               for group, features in samples if group == "non_pointing")
    print(json.dumps({"corpus_size": len(samples), "classifications": counts,
                      "non_pointing_classifications_changed": non_pointing_changes,
                      "cached_two_hand_rules_2000_samples": summary,
                      "projected_limitations": limitations}, indent=2))


if __name__ == "__main__":
    main()
