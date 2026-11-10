"""Detached job runner: one `matlab -batch` call for one subject.

Started by the MCP server in its own session, so a long run (hours)
survives if the chat client closes. Usage: python runner.py <job_dir>
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hl_common as hc  # noqa: E402


mstr = hc.mstr


def collect_qc(subj: str, pid: str) -> list[str]:
    """Copy checkreg PNGs to a pseudonymized folder; return dataset-relative paths."""
    ds = hc.dataset_dir()
    src_root = ds / "derivatives" / "leaddbs" / f"sub-{subj}"
    dst = hc.state_dir() / "qc" / pid
    dst.mkdir(parents=True, exist_ok=True)
    out = []
    for png in sorted(src_root.rglob("checkreg/*.png")):
        if png.name.startswith("._"):
            continue
        name = png.name.replace(f"sub-{subj}", pid)
        target = dst / f"{png.parent.parent.name}_{name}"
        shutil.copy2(png, target)
        out.append(str(target.relative_to(ds)))
    return out


def final_state(code: int, job_dir: Path, dry_run: bool) -> tuple[str, str | None]:
    """Exit 0 is not success. A real run must also pass the electrode check,
    so a missing or unreadable result fails too (fail closed)."""
    if code != 0:
        return "failed", "matlab_error"
    if dry_run:
        return "finished", None
    try:
        check = json.loads((job_dir / "summary.json").read_text())["recon_check"]
        status = check["status"]
    except (OSError, ValueError, KeyError, TypeError):
        return "failed", "recon_check_missing"
    if status in ("pass", "human_approved"):
        return "finished", None
    return "failed", "recon_check_failed"


def main(job_dir: Path) -> int:
    job_file = job_dir / "job.json"
    job = json.loads(job_file.read_text())
    subj, pid = job["subj"], job["pseudonym"]

    job.update(state="running", started=hc.now())
    job_file.write_text(json.dumps(job, indent=2))
    base = {"job_id": job["job_id"], "pseudonym": pid, "recipe": job["recipe"],
            "dry_run": job["dry_run"], "leaddbs": hc.leaddbs_git(),
            "headless": hc.leaddbs_git(hc.HEADLESS_DIR)}
    hc.append_provenance({**base, "event": "started", "time": job["started"],
                          "inputs_sha256": hc.input_hashes(subj)})

    cmd = (f"addpath({mstr(hc.MATLAB_DIR)}); addpath({mstr(hc.HEADLESS_DIR)}); "
           f"hl_run_preprocessing({mstr(hc.dataset_dir())}, {mstr(subj)}, "
           f"{mstr(job_dir)}, {'true' if job['dry_run'] else 'false'}, "
           f"{mstr(job['electrode_model'])});")
    with (job_dir / "matlab.log").open("w") as log:
        try:
            # stdin=/dev/null: a stray `keyboard` in Lead-DBS ends instead of hanging
            proc = subprocess.run([hc.matlab_bin(), "-nodisplay", "-batch", cmd],
                                  stdin=subprocess.DEVNULL, stdout=log,
                                  stderr=subprocess.STDOUT, cwd=job_dir)
            code = proc.returncode
        except OSError as exc:
            log.write(f"Failed to start MATLAB: {exc}\n")
            code = -1

    options_json = job_dir / "options.json"
    state, reason = final_state(code, job_dir, job["dry_run"])
    job.update(state=state, failure_reason=reason, exit_code=code,
               finished=hc.now(), qc_images=collect_qc(subj, pid))
    job_file.write_text(json.dumps(job, indent=2))
    hc.append_provenance({
        **base, "event": job["state"], "time": job["finished"], "exit_code": code,
        "options_sha256": hc.sha256_file(options_json) if options_json.exists() else None,
        # Re-hash: shows whether inputs changed during the run
        "inputs_sha256": hc.input_hashes(subj),
    })
    return code


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1])))
