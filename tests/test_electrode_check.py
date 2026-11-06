"""A run starts only if the requested model matches the stored one.

Usage: python3 -B headless/tests/test_electrode_check.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))
import hl_common as hc  # noqa: E402

SUPPORTED = ("Medtronic 3389", "Medtronic 3387", "Boston Scientific Vercise Directed")


def reason(requested, stored):
    refusal = hc.electrode_refusal(requested, stored, SUPPORTED)
    if refusal:
        assert refusal["accepted"] is False
    return refusal["reason"] if refusal else None


assert reason("Medtronic 3387", "Medtronic 3387") is None
assert reason("Medtronic 3389", "Medtronic 3387") == "electrode_model_mismatch"
assert reason("Medtronic 3389", None) == "electrode_model_not_recorded"
assert reason("Medtronic 3389", "Medtronic B33005") == "electrode_model_not_supported"
# A match with an unsupported model still fails. The schema blocks this, but the check must too.
assert reason("Medtronic B33005", "Medtronic B33005") == "electrode_model_not_supported"
print("electrode_refusal: all cases OK")
