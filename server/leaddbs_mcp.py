# /// script
# requires-python = ">=3.10"
# dependencies = ["mcp>=1.2,<2"]
# ///
"""Lead-DBS headless MCP server (proof of concept, validated mode).

Exposes exactly three whitelisted tools over stdio. The LLM can only pick
a pseudonymized subject and an electrode model from a fixed list; all
methods and parameters are fixed in ea_headless_options.m.

Run:  LEADDBS_DATASET=/path/to/dataset uv run headless/server/leaddbs_mcp.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Annotated, Literal, get_args

from mcp.server.fastmcp import FastMCP
from pydantic import Field

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hl_common as hc  # noqa: E402

RECIPE = "preprocessing_v2"

# Models with a PaCER geometry (see ea_mod2pacermod in ea_runpacer.m). For any
# other model PaCER estimates the type, "which might be wrong" (refitElec.m).
ElectrodeModel = Literal[
    "Medtronic 3389",
    "Medtronic 3387",
    "Boston Scientific Vercise Directed",
]
SubjectId = Annotated[str, Field(pattern=r"^P-[0-9a-f]{10}$",
                                 description="Pseudonymized ID from list_subjects")]

mcp = FastMCP("leaddbs-headless")


def _jobs_dir() -> Path:
    path = hc.state_dir() / "jobs"
    path.mkdir(exist_ok=True)
    return path


def _latest_job(pid: str) -> dict | None:
    jobs = []
    for f in _jobs_dir().glob("*/job.json"):
        job = json.loads(f.read_text())
        if job.get("pseudonym") == pid:
            job["_dir"] = f.parent
            jobs.append(job)
    return max(jobs, key=lambda j: j["created"]) if jobs else None


def _has_postop(subj: str) -> bool:
    raw = hc.dataset_dir() / "rawdata" / f"sub-{subj}"
    return any(p.is_dir() for p in raw.glob("ses-postop*"))


@mcp.tool()
def list_subjects() -> dict:
    """List subjects in the configured dataset by pseudonymized ID only."""
    out = []
    for subj in hc.real_subjects():
        pid = hc.pseudonym(subj)
        job = _latest_job(pid)
        out.append({"id": pid, "has_postop_imaging": _has_postop(subj),
                    "last_run_state": job["state"] if job else None,
                    "last_run_dry_run": bool(job.get("dry_run")) if job else None})
    return {"subjects": out, "count": len(out)}


@mcp.tool()
def run_preprocessing(subject_id: SubjectId,
                      electrode_model: ElectrodeModel = "Medtronic 3389",
                      dry_run: bool = False) -> dict:
    """Start the validated recipe (coregistration, ANTs normalization,
    brainshift correction, PaCER reconstruction from post-op CT) in the
    background. Methods are fixed. Approved steps are never overwritten.
    Use dry_run=true to only build and record the options.
    electrode_model must match the model stored for this subject, or the run
    is refused and no job starts. Do not guess the model.
    A post-op CT with slices thicker than 1 mm is refused.
    Poll get_status for progress. A full run took about 10 minutes on the test
    machine. It can take longer on other machines or data."""
    subj = hc.resolve_pseudonym(subject_id)
    if not _has_postop(subj):
        return {"accepted": False, "reason": "No post-op imaging for this subject."}
    last = _latest_job(subject_id)
    if last and last["state"] in ("queued", "running"):
        return {"accepted": False, "reason": "A run is already active for this subject.",
                "job_id": last["job_id"]}
    # The CT check reads one header. The electrode check starts MATLAB, so it is second.
    refusal = hc.ct_refusal(hc.ct_slice_mm(subj)) or hc.electrode_refusal(
        electrode_model, hc.stored_electrode_model(subj), get_args(ElectrodeModel))
    if refusal:
        return refusal

    job_id = uuid.uuid4().hex[:12]
    job_dir = _jobs_dir() / job_id
    job_dir.mkdir()
    job = {"job_id": job_id, "pseudonym": subject_id, "subj": subj, "recipe": RECIPE,
           "electrode_model": electrode_model, "dry_run": dry_run,
           "state": "queued", "created": hc.now()}
    (job_dir / "job.json").write_text(json.dumps(job, indent=2))
    subprocess.Popen([sys.executable, str(Path(__file__).with_name("runner.py")), str(job_dir)],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)
    return {"accepted": True, "job_id": job_id, "recipe": RECIPE, "dry_run": dry_run}


@mcp.tool()
def get_status(subject_id: SubjectId) -> dict:
    """Status and derived results of the latest run for one subject.
    Returns step flags, the electrode check, MNI contact coordinates, and
    dataset-relative paths to QC images for local human review. Never image
    content or headers. A failed run returns no coordinates: tell the user
    that the run failed, and do not report a localization. Do not recommend
    a method outside the fixed recipe. recon_check_notes defines the fields
    of recon_check."""
    hc.resolve_pseudonym(subject_id)  # validates that the ID exists
    job = _latest_job(subject_id)
    if not job:
        return {"subject_id": subject_id, "state": "never_run"}
    job_dir = job.pop("_dir")
    result = {k: job.get(k) for k in ("job_id", "recipe", "electrode_model", "dry_run",
                                      "state", "failure_reason", "created", "started",
                                      "finished", "exit_code", "qc_images")}
    result["subject_id"] = subject_id
    summary = job_dir / "summary.json"
    if summary.exists():
        s = json.loads(summary.read_text())
        result["steps"] = s.get("steps")
        result["recon_check"] = s.get("recon_check")
        result["recon_check_notes"] = hc.RECON_CHECK_NOTES
        # Plausible-looking wrong coordinates must not reach the chat.
        # The state is not enough: a dry run finishes, and it can read old files.
        check_status = (s.get("recon_check") or {}).get("status")
        if job["state"] == "finished" and check_status in ("pass", "human_approved"):
            result["contacts_mni"] = s.get("contacts_mni")
    log = job_dir / "matlab.log"
    if log.exists():
        text = log.read_text(errors="replace")
        result["log_tail"] = hc.strip_method_advice(hc.scrub("\n".join(text.splitlines()[-20:])))
        if job["state"] == "failed":
            result["failure_detail"] = hc.failure_detail(text)
    if job["state"] == "failed":
        result["failure_note"] = hc.FAILED_RUN_NOTE
    if result.get("qc_images"):
        result["qc_note"] = ("Open these images locally and approve the "
                             "localization in Lead-DBS before any analysis.")
    return result


if __name__ == "__main__":
    mcp.run()  # stdio transport
