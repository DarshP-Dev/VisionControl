"""Download the versioned official Google Hand Landmarker bundle locally."""

import hashlib
from pathlib import Path
import urllib.error
import urllib.request


MODEL_PATH = Path(__file__).resolve().parent / "models" / "hand_landmarker.task"
MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
    "hand_landmarker/float16/1/hand_landmarker.task"
)
MODEL_SHA256 = "fbc2a30080c3c557093b5ddfc334698132eb341044ccee322ccf8bcf3607cde1"


def verify_model(data):
    if hashlib.sha256(data).hexdigest() != MODEL_SHA256:
        raise ValueError("Model checksum mismatch; expected the official float16 v1 bundle")


def download_model(destination=MODEL_PATH):
    destination = Path(destination)
    if destination.is_file():
        verify_model(destination.read_bytes())
        print(f"Verified existing model: {destination}")
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(MODEL_URL, timeout=60) as response:
        data = response.read()
    verify_model(data)
    # Exclusive creation preserves any model placed here during the download.
    with destination.open("xb") as output:
        output.write(data)
    print(f"Saved official Hand Landmarker v1: {destination}")
    print(f"SHA256: {hashlib.sha256(data).hexdigest()}")
    return destination


def main():
    try:
        download_model()
    except (OSError, ValueError, urllib.error.URLError) as exc:
        print(f"Model setup failed: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
