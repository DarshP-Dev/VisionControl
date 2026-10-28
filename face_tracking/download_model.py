"""Explicit setup only: Google's Apache-2.0 BlazeFace short-range float16 v1."""

import argparse
import hashlib
from pathlib import Path
import urllib.request


MODEL_PATH = Path(__file__).resolve().parent / "models" / "blaze_face_short_range.tflite"
MODEL_URL = "https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/1/blaze_face_short_range.tflite"
MODEL_SHA256 = "b4578f35940bf5a1a655214a1cce5cab13eba73c1297cd78e1a04c2380b0152f"


def verify_model(data):
    if hashlib.sha256(data).hexdigest() != MODEL_SHA256:
        raise ValueError("Face model checksum mismatch: expected official BlazeFace short-range float16 v1")


def download_model(destination=MODEL_PATH):
    destination = Path(destination)
    if destination.is_file():
        verify_model(destination.read_bytes())
    else:
        with urllib.request.urlopen(MODEL_URL, timeout=30) as response:
            data = response.read(2_000_001)
        verify_model(data)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb") as output:
            output.write(data)
    print(f"Verified BlazeFace short-range float16 v1: {destination}")
    print(f"SHA256: {MODEL_SHA256}")
    return destination


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, default=MODEL_PATH)
    args = parser.parse_args(argv)
    try:
        download_model(args.destination)
    except (OSError, ValueError) as exc:
        print(f"Face model setup failed: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
