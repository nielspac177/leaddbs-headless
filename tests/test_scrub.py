"""Log text must not carry absolute paths to the LLM.

Usage: python3 -B headless/tests/test_scrub.py
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))
import hl_common as hc  # noqa: E402

os.environ.pop("LEADDBS_DATASET", None)

# The install path, which is the case that leaked in the chat test.
out = hc.scrub(f"In: {hc.LEADDBS_ROOT}/ea_runpacer.m")
assert out == "In: <leaddbs>/ea_runpacer.m", out

# The server's own folder, which can sit outside Lead-DBS.
out = hc.scrub(f"Error in {hc.HEADLESS_DIR}/matlab/hl_run_preprocessing.m")
assert out == "Error in <headless>/matlab/hl_run_preprocessing.m", out

# Paths outside the install, the dataset and the home folder.
for path in ("/Volumes/Jane_Doe/x.nii", "/Users/janedoe/a.m", "/private/tmp/b.mat",
             "/Applications/MATLAB_R2024b.app/toolbox/c.m"):
    out = hc.scrub(f"Error in {path} at line 3")
    assert path not in out and "<path>" in out, out

# Text that only looks similar stays.
for text in ("voxel 1.0/2.0 mm", "<leaddbs>/ea_run.m", "~/a.m", "and/or", "derivatives/qc/a.png"):
    assert hc.scrub(text) == text, text

# Lead-DBS advice to use a method outside the recipe. MATLAB can wrap the text.
wrapped = ("PaCER failed. Potentially try running the TRAC/CORE Algorithm or a fully manual\n"
           "pre-reconstruction.\n\nError in ea_autocoord (line 338)")
out = hc.strip_method_advice(wrapped)
assert "TRAC/CORE" not in out and "manual" not in out, out
assert out.startswith("PaCER failed.") and "Error in ea_autocoord (line 338)" in out, out
assert hc.strip_method_advice("Max off-model: 0.07") == "Max off-model: 0.07"

# A known failure gives fixed text. An unknown failure gives nothing.
known = "Message: PaCER returned a different number of electrodes than expected by LeadDBS!"
assert "different number of electrodes" in hc.failure_detail(known)
assert hc.failure_detail("Error in ea_run (line 113)") is None

# The hemisphere note must stay in the output, because a client guessed it wrong.
assert "right hemisphere" in hc.RECON_CHECK_NOTES["side"]

print("test_scrub passed")
