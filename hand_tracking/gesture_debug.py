"""Sample numeric rule diagnostics, never camera frames or raw landmark coordinates."""

import logging

from gestures.static_gestures import GestureResult


LOGGER = logging.getLogger("hand_tracking")


class GestureDebug:
    """Log scheduling only; never retain or debounce gesture classifications."""

    def __init__(self, interval_ms: int = 2000):
        if not isinstance(interval_ms, int) or isinstance(interval_ms, bool) or interval_ms <= 0:
            raise ValueError("Debug interval must be a positive integer number of milliseconds")
        self.interval_ms = interval_ms
        self.next_ms = 0

    def due(self, timestamp_ms: int) -> bool:
        if timestamp_ms < self.next_ms:
            return False
        self.next_ms = timestamp_ms + self.interval_ms
        return True

    def log(self, results: tuple[GestureResult, ...], timestamp_ms: int) -> None:
        if not results:
            LOGGER.info("Gesture debug t=%d ms: no hand observations", timestamp_ms)
        for slot, result in enumerate(results):
            labels = "/".join(prediction.category_name or "Unknown" for prediction in result.handedness) or "Unknown"
            matches = "/".join(rule.value for rule in result.matched_rules) or "none"
            LOGGER.info("Gesture debug t=%d ms | frame slot=%d (not an ID) | side=%s | %s | matches=%s | reason=%s",
                        timestamp_ms, slot, labels, result.gesture.value, matches, result.reason)
            for finger in (None,) + tuple(dict.fromkeys(check.finger for check in result.pointing_checks
                                                        if check.finger is not None)):
                checks = [check for check in result.pointing_checks if check.finger == finger]
                if not checks:
                    continue
                details = "; ".join(
                    f"{check.measurement}={'INVALID' if check.value is None else f'{check.value:.3f}'} "
                    f"{check.comparison}{check.threshold:g} {'PASS' if check.passed else 'FAIL'}"
                    for check in checks)
                LOGGER.info("  %s: %s", finger.value if finger is not None else "input", details)
            blockers = [f"{check.finger.value if check.finger else 'input'}.{check.measurement}"
                        for check in result.pointing_checks if not check.passed]
            LOGGER.info("  POINTING blockers: %s", ", ".join(blockers) if blockers else "none")
