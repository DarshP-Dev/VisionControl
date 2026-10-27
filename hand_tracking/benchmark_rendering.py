"""Offline preview-policy comparison, with synthetic pixels. No HighGUI or input.

Replays Phase 3.8's unconditional drawing and Phase 3.9's visibility decision.
State names describe a policy input, not measured OS focus or scheduling states.
"""

import argparse
from pathlib import Path
import platform
import time

import numpy as np

from .benchmark_synthetic import observations
from .performance import Profile, write_report
from .preview_window import PreviewWindow
from .tracking_utils import PreviewRenderer, make_preview


def measure(hands, state, policy, frames=200, warmup=20):
    if hands not in (1, 2, 3, 4) or state not in ("focused", "unfocused", "minimized", "restored"):
        raise ValueError("Use 1–4 hands and a defined synthetic preview state")
    if policy not in ("phase3_8", "phase3_9") or frames <= 0 or warmup < 0:
        raise ValueError("Invalid benchmark policy or frame counts")
    frame = np.zeros((1080, 1920, 3), np.uint8)
    result = observations(hands, tracked=True)[0]
    renderer, timings = PreviewRenderer(), Profile(enabled=False)
    rendered = 0
    for index in range(warmup+frames):
        timings.enabled = index >= warmup
        before = time.perf_counter()
        if policy == "phase3_8" or PreviewWindow.should_render(state):
            make_preview(frame, result, 30., False, renderer=renderer, timings=timings, max_hands=hands)
            if timings.enabled:
                rendered += 1
        timings.add("preview_policy_total", time.perf_counter()-before)
    return {"hands": hands, "synthetic_state": state, "policy": policy,
            "frames": frames, "warmup_frames": warmup, "rendered": rendered,
            "timings": timings.summary()}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frames", type=int, default=200)
    parser.add_argument("--warmup", type=int, default=20)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.frames <= 0 or args.warmup < 0 or args.repeats <= 0 or args.report.exists():
        parser.error("Positive frames/repeats, nonnegative warmup and a fresh report path required")
    runs = [dict(measure(hands, state, policy, args.frames, args.warmup), repeat=repeat)
            for repeat in range(1, args.repeats+1) for hands in (1, 2, 3, 4)
            for state in ("focused", "unfocused", "minimized", "restored")
            for policy in ("phase3_8", "phase3_9")]
    write_report(args.report, {"kind": "synthetic_render_policy_only", "python": platform.python_version(),
                              "runs": runs, "excluded": "camera, inference, HighGUI, actual focus/minimize, scheduling, Windows input"})
    print(f"Saved {len(runs)} synthetic policy runs to {args.report}; NOT OS focus-state measurements.")


if __name__ == "__main__":
    main()
