"""Camera-only sync/latest delivery benchmark. No model, GUI, image files or input.

Measures host BGR deliveries, not verified unique sensor frames or exposure age.
"""

import argparse
from pathlib import Path
import time

import cv2

from .camera_diagnostics import BACKENDS, capture_snapshot, configure_capture, read_frame
from .latest_capture import CaptureError, LatestCapture, ensure_camera_available
from hand_tracking.diagnostics import process_memory
from hand_tracking.performance import Profile, process_cpu_usage, write_report


def measure(args):
    cap = source = None
    report = {"kind": "camera_only_host_delivery", "capture_pipeline_mode": args.capture_pipeline,
              "requested_capture": {key: getattr(args, key) for key in
                                    ("camera_index", "backend", "width", "height", "fps", "fourcc")},
              "sensor_fps": None, "sensor_exposure_age_ms": None,
              "limitations": "No inference/GUI/controls; BGR read completions are not verified unique sensor frames."}
    def configure_owned(camera):
        if not camera.isOpened():
            raise CaptureError("Cannot open requested camera")
        accepted = configure_capture(camera, args)
        return {"driver_readback": capture_snapshot(camera, args, "Camera-only configuration"),
                "configuration_accepted": accepted}
    profile = Profile(enabled=False)
    first = start = cpu_start = last = None
    frames = 0
    try:
        if args.capture_pipeline == "latest-thread":
            source = LatestCapture(lambda: cv2.VideoCapture(args.camera_index, BACKENDS[args.backend]),
                                   configure_owned, device_key=(args.backend, args.camera_index),
                                   profile=True, measuring=False).start()
        else:
            ensure_camera_available((args.backend, args.camera_index))
            cap = cv2.VideoCapture(args.camera_index, BACKENDS[args.backend])
            report.update(configure_owned(cap))
        while True:
            before = time.perf_counter()
            if source is not None:
                packet = source.take(.01)
                source.check_deadline()
                if packet is None:
                    continue
                read_at, duration = packet.read_completed_at, packet.read_seconds
                dimensions = packet.dimensions
            else:
                image = read_frame(cap)
                read_at = time.perf_counter()
                duration = read_at-before
                dimensions = (image.shape[1], image.shape[0])
            now = time.perf_counter()
            if first is None:
                first = now
            if start is None:
                if now-first < args.warmup:
                    continue
                start, cpu_start = now, time.process_time()
                profile.enabled = True
                if source is not None:
                    source.begin_measurement()
                continue  # First fully measured delivery begins after this boundary.
            profile.add("camera_read", duration)
            profile.add("host_age_at_consumption", now-read_at)
            if last is not None:
                profile.add("consumer_delivery_interval", now-last)
            last = now
            frames += 1
            report["actual_dimensions"] = list(dimensions)
            if now-start >= args.duration:
                report["status"] = "completed"
                break
    except (OSError, RuntimeError, ValueError, cv2.error) as exc:
        report.update(status="error", error=str(exc))
    except KeyboardInterrupt:
        report["status"] = "interrupted"
    finally:
        end, cpu_end = time.perf_counter(), time.process_time()
        if source is not None:
            try:
                source.close()
            except CaptureError as exc:
                report.update(status="error", shutdown_error=str(exc))
            report["capture_pipeline"] = source.snapshot()
            report.update(report["capture_pipeline"]["metadata"])
        elif cap is not None:
            cap.release()
        elapsed = max(0., end-start) if start is not None else 0.
        report.update(frames=frames, measurement_seconds=elapsed,
                      warmup_seconds_requested=args.warmup, measurement_seconds_requested=args.duration,
                      capture_only_consumer_fps=frames/elapsed if elapsed else None,
                      timings=profile.summary(), memory=process_memory(),
                      resources=process_cpu_usage(cpu_end-cpu_start if cpu_start is not None else 0., elapsed, frames))
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture-pipeline", choices=("sync", "latest-thread"), default="sync")
    parser.add_argument("--camera-index", type=int, default=0)
    parser.add_argument("--backend", choices=BACKENDS, default="msmf")
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--fps", type=float, default=60.)
    parser.add_argument("--fourcc", choices=("MJPG", "YUY2"), default="MJPG")
    parser.add_argument("--warmup", type=float, default=3.)
    parser.add_argument("--duration", type=float, default=30.)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    import math
    if (args.camera_index < 0 or min(args.width, args.height) <= 0 or args.warmup < 0
            or not all(math.isfinite(v) for v in (args.warmup, args.duration, args.fps))
            or min(args.duration, args.fps) <= 0 or args.report.exists()):
        parser.error("Use valid camera dimensions/rates, nonnegative warmup, positive duration and a fresh report path")
    report = measure(args)
    write_report(args.report, report)
    print(f"{report['status']}: {report['capture_only_consumer_fps']} host BGR deliveries/s; report: {args.report}")
    if report.get("error"):
        print(report["error"])
    return 0 if report["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
