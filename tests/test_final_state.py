"""Exit 0 alone must never mark a run as finished.

Usage: python3 -B headless/tests/test_final_state.py
"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))
from runner import final_state  # noqa: E402


def state_with(summary_text, code=0, dry_run=False):
    with tempfile.TemporaryDirectory() as tmp:
        job_dir = Path(tmp)
        if summary_text is not None:
            (job_dir / "summary.json").write_text(summary_text)
        return final_state(code, job_dir, dry_run)


def check(status):
    return json.dumps({"recon_check": {"status": status}})


assert state_with(check("pass")) == ("finished", None)
assert state_with(check("human_approved")) == ("finished", None)
assert state_with(check("fail")) == ("failed", "recon_check_failed")
assert state_with(check("not_run")) == ("failed", "recon_check_failed")
assert state_with(None) == ("failed", "recon_check_missing")
assert state_with("{not json") == ("failed", "recon_check_missing")
assert state_with("{}") == ("failed", "recon_check_missing")
assert state_with(check("pass"), code=1) == ("failed", "matlab_error")
assert state_with(None, dry_run=True) == ("finished", None)
print("final_state: all cases OK")
