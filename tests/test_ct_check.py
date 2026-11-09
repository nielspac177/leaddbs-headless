"""A run starts only if the post-op CT header shows slices within the tested range.

Usage: python3 -B headless/tests/test_ct_check.py
"""

import gzip
import os
import struct
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))
import hl_common as hc  # noqa: E402


def header(voxel, order="<"):
    """A 348-byte NIfTI-1 header. Only sizeof_hdr and pixdim hold values."""
    data = bytearray(348)
    data[:4] = struct.pack(order + "i", 348)
    data[80:92] = struct.pack(order + "3f", *voxel)
    return bytes(data)


def reason(slice_mm):
    refusal = hc.ct_refusal(slice_mm)
    if refusal:
        assert refusal["accepted"] is False
    return refusal["reason"] if refusal else None


assert reason(0.5) is None
assert reason(1.0) is None
assert reason(1.0000001) is None  # float noise from the header
assert reason(1.26) == "ct_slices_too_thick"
assert reason(2.0) == "ct_slices_too_thick"
assert reason(None) == "ct_not_readable"

with tempfile.TemporaryDirectory() as tmp:
    os.environ["LEADDBS_DATASET"] = tmp

    def add(subj, name, content, zipped=True):
        folder = Path(tmp, "rawdata", f"sub-{subj}", "ses-postop", "anat")
        folder.mkdir(parents=True, exist_ok=True)
        (folder / name).write_bytes(gzip.compress(content) if zipped else content)

    add("a", "sub-a_CT.nii.gz", header((0.4, 0.4, 1.0)))
    assert round(hc.ct_slice_mm("a"), 2) == 1.0
    add("a", "._sub-a_CT.nii.gz", b"macOS metadata", zipped=False)  # must be ignored
    assert round(hc.ct_slice_mm("a"), 2) == 1.0

    add("b", "sub-b_CT.nii", header((0.5, 0.5, 2.0), ">"), zipped=False)  # big-endian
    assert round(hc.ct_slice_mm("b"), 2) == 2.0

    add("c", "sub-c_CT.nii.gz", b"not a header")  # short file
    assert hc.ct_slice_mm("c") is None

    add("d", "sub-d_CT.nii.gz", header((0.5, 0.5, 0.0)))  # invalid voxel size
    assert hc.ct_slice_mm("d") is None

    add("e", "sub-e_CT.nii.gz", b"\x00" * 348, zipped=False)  # corrupt gzip
    assert hc.ct_slice_mm("e") is None

    add("f", "sub-f_T1w.nii.gz", header((1.0, 1.0, 1.0)))  # post-op MR only, no CT
    assert hc.ct_slice_mm("f") is None

    add("g", "sub-g_acq-a_CT.nii.gz", header((0.5, 0.5, 0.5)))  # any bad file fails closed
    add("g", "sub-g_acq-b_CT.nii.gz", b"not a header")
    assert hc.ct_slice_mm("g") is None

print("ct check: all cases OK")
