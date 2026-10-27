"""The common float optimization must keep the original validation contract."""

from fractions import Fraction
import math
from numbers import Real
import unittest

import numpy as np

from gestures.models import finite_number


def reference(value, name):
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(name)
    try:
        number = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError(name) from exc
    if not math.isfinite(number):
        raise ValueError(name)
    return number


class NumericFastpathTest(unittest.TestCase):
    def test_accepted_values_match_reference_exactly(self):
        for value in (0, -7, 0., -0., 1e-300, 1e300, Fraction(2, 3), np.float32(.1), np.float64(.3), np.int64(42)):
            self.assertEqual(finite_number(value, "test"), reference(value, "test"))

    def test_rejected_values_match_reference(self):
        for value in (True, False, None, "1", 1j, [], float("inf"), float("nan"), 10**1000, np.bool_(True)):
            with self.subTest(kind=type(value).__name__):
                with self.assertRaises(ValueError):
                    reference(value, "test")
                with self.assertRaises(ValueError):
                    finite_number(value, "test")


if __name__ == "__main__":
    unittest.main()
