"""Shared helpers for the Lead-DBS headless MCP server.

Everything here runs locally. Nothing in this module sends data anywhere.
"""

from __future__ import annotations

import gzip
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import struct
import subprocess
import tempfile
import zlib
from datetime import datetime, timezone
from pathlib import Path

HEADLESS_DIR = Path(__file__).resolve().parent.parent
# Lead-DBS install. Set LEADDBS_ROOT when this folder is not inside Lead-DBS.
LEADDBS_ROOT = Path(os.path.abspath(Path(os.environ.get("LEADDBS_ROOT") or HEADLESS_DIR.parent).expanduser()))
MATLAB_DIR = HEADLESS_DIR / "matlab"

PSEUDONYM_RE = re.compile(r"^P-[0-9a-f]{10}$")
SUBJ_RE = re.compile(r"^[A-Za-z0-9]+$")


# ---------------------------------------------------------------- config

def dataset_dir() -> Path:
    """The ONE dataset this server may touch. Set by the user, never by the LLM."""
    value = os.environ.get("LEADDBS_DATASET")
    if not value:
        raise RuntimeError("LEADDBS_DATASET is not set (path to a Lead-DBS BIDS dataset).")
    # abspath, not resolve: keep a symlink that gives a space-free path to Lead-DBS
    path = Path(os.path.abspath(Path(value).expanduser()))
    if not (path / "rawdata").is_dir():
        raise RuntimeError("LEADDBS_DATASET has no rawdata/ folder.")
    return path


def state_dir() -> Path:
    """Server-owned folder inside the dataset derivatives."""
    path = dataset_dir() / "derivatives" / "leaddbs_headless"
    path.mkdir(parents=True, exist_ok=True)
    return path


def matlab_bin() -> str:
    value = os.environ.get("MATLAB_BIN")
    if value:
        return value
    found = shutil.which("matlab")
    if found:
        return found
    apps = sorted(Path("/Applications").glob("MATLAB_R*.app/bin/matlab"), reverse=True)
    if apps:
        return str(apps[0])
    raise RuntimeError("MATLAB not found. Set MATLAB_BIN.")


def mstr(value) -> str:
    """Quote a value as a MATLAB char literal."""
    return "'" + str(value).replace("'", "''") + "'"


# ------------------------------------------------------- electrode model check

def stored_electrode_model(subj: str) -> str | None:
    """The model saved for this patient in Lead-DBS, or None if it cannot be read.
    It is the last GUI setting, not a verified implant record."""
    name = f"sub-{subj}"
    prefs = dataset_dir() / "derivatives" / "leaddbs" / name / "prefs" / f"{name}_desc-uiprefs.mat"
    if not prefs.is_file():
        return None
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "elmodel.txt"
        cmd = f"addpath({mstr(MATLAB_DIR)}); hl_stored_elmodel({mstr(prefs)}, {mstr(out)});"
        try:
            subprocess.run([matlab_bin(), "-nodisplay", "-batch", cmd], cwd=tmp, check=True,
                           stdin=subprocess.DEVNULL, capture_output=True, timeout=300)
            return out.read_text().strip() or None
        except (OSError, RuntimeError, subprocess.SubprocessError):
            return None


def electrode_refusal(requested: str, stored: str | None, supported: tuple) -> dict | None:
    """Why a run must not start, or None if the model matches. Fails closed."""
    ask = "Ask the user to check the implant record. Do not choose a model for the user."
    if stored is None:
        return {"accepted": False, "reason": "electrode_model_not_recorded",
                "message": "No stored electrode model could be read for this subject. "
                           "The user must set it in Lead-DBS first. " + ask}
    if stored not in supported:
        return {"accepted": False, "reason": "electrode_model_not_supported",
                "stored_model": stored,
                "message": "This recipe has no validated PaCER geometry for the stored model. "
                           "This subject cannot run with this recipe. " + ask}
    if stored != requested:
        return {"accepted": False, "reason": "electrode_model_mismatch",
                "stored_model": stored, "requested_model": requested,
                "message": "The requested model differs from the stored model. No job started. " + ask}
    return None


# ------------------------------------------------------------- post-op CT check

# Upper end of the tested range. PaCER failed at 2 mm. No supported patient lies
# between 1 and 2 mm. This limit comes from 6 patients and is not a validated value.
MAX_CT_SLICE_MM = 1.0


def _nifti_slice_mm(path: Path) -> float | None:
    """Largest voxel size from a NIfTI-1 header, or None if the header is not usable."""
    try:
        with (gzip.open(path, "rb") if path.suffix == ".gz" else path.open("rb")) as f:
            header = f.read(348)
        for order in "<>":
            if len(header) == 348 and struct.unpack(order + "i", header[:4])[0] == 348:
                pixdim = struct.unpack(order + "3f", header[80:92])
                return max(pixdim) if min(pixdim) > 0 else None
    except (OSError, EOFError, zlib.error, struct.error):
        pass
    return None


def ct_slice_mm(subj: str) -> float | None:
    """Thickest slice of the post-op CT files, or None if any file cannot be read."""
    raw = dataset_dir() / "rawdata" / f"sub-{subj}"
    files = [p for p in raw.glob("ses-postop*/anat/*CT*.nii*") if not p.name.startswith("._")]
    sizes = [_nifti_slice_mm(p) for p in files]
    return max(sizes) if sizes and None not in sizes else None


def ct_refusal(slice_mm: float | None) -> dict | None:
    """Why the CT must not go to PaCER, or None if it may. Fails closed."""
    if slice_mm is None:
        return {"accepted": False, "reason": "ct_not_readable",
                "message": "No readable post-op CT was found for this subject. No job started."}
    if round(slice_mm, 2) > MAX_CT_SLICE_MM:
        return {"accepted": False, "reason": "ct_slices_too_thick",
                "ct_slice_mm": round(slice_mm, 2), "max_slice_mm": MAX_CT_SLICE_MM,
                "message": "The post-op CT slices are thicker than this recipe was tested on. "
                           "No job started. This subject cannot run with this recipe."}
    return None


# ------------------------------------------------------- text for the chat client

FAILED_RUN_NOTE = ("This server runs one fixed recipe. It cannot run another method. "
                   "Report the failure to the user. Do not recommend another method, "
                   "and do not offer to run one.")

RECON_CHECK_NOTES = {
    "side": "Side 1 and side1 are the right hemisphere (positive x in MNI space). "
            "Side 2 and side2 are the left hemisphere (negative x).",
    "weakest_contact_vs_metal": "A ratio with no unit, not a distance. It is the CT signal near "
                                "the weakest contact, divided by the metal threshold. "
                                "Values of 1 or more pass.",
    "length_mm": "Distance from the first contact to the last contact, in mm.",
    "expected_length_mm": "The same distance in the electrode model, in mm.",
    "pass": "A pass does not validate the localization. A person must still review it.",
}

_METHOD_ADVICE = re.compile(r"Potentially\s+try\s+running\s+the\s+TRAC/CORE.*?pre-reconstruction\.?",
                            re.DOTALL)


def failure_detail(log: str) -> str | None:
    """Fixed text for a known failure. The cause can be above the log lines that we return."""
    if "PaCER returned a different number of electrodes" in log:
        return ("PaCER found a different number of electrodes than expected. PaCER says that "
                "the usual cause is its brain mask estimate on an unusual CT. "
                "This cause is not confirmed for this run.")
    return None


def strip_method_advice(text: str) -> str:
    """Remove the Lead-DBS advice to use a method that this server cannot run."""
    return _METHOD_ADVICE.sub("[advice removed: method outside the recipe]", text)


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ------------------------------------------------------------ pseudonyms

def _key() -> bytes:
    """Per-dataset secret. Stays on disk next to the data, never returned."""
    key_file = state_dir() / ".pseudonym_key"
    if not key_file.exists():
        key_file.write_text(secrets.token_hex(32))
        try:
            key_file.chmod(0o600)
        except OSError:  # exFAT and similar have no POSIX modes
            pass
    return bytes.fromhex(key_file.read_text().strip())


def pseudonym(subj_id: str) -> str:
    digest = hmac.new(_key(), subj_id.encode(), hashlib.sha256).hexdigest()
    return "P-" + digest[:10]


def real_subjects() -> list[str]:
    raw = dataset_dir() / "rawdata"
    ids = [p.name[4:] for p in raw.glob("sub-*") if p.is_dir()]
    return sorted(i for i in ids if SUBJ_RE.match(i))


def resolve_pseudonym(pid: str) -> str:
    """Map a pseudonym back to the real BIDS ID, locally only."""
    if not PSEUDONYM_RE.match(pid):
        raise ValueError("Invalid pseudonymized ID.")
    for subj in real_subjects():
        if hmac.compare_digest(pseudonym(subj), pid):
            return subj
    raise ValueError("Unknown pseudonymized ID.")


# ----------------------------------------------------------- PHI scrubber

_PATTERNS = [
    # DICOM-style header fields with their values
    (re.compile(r"(?i)\b(patient'?s?\s*(name|id|birth\s*date|sex|age|address)|"
                r"referring\s*physician|institution\s*name|accession\s*number|"
                r"study\s*date|series\s*date|acquisition\s*date)\b\s*[:=]?\s*[^\n,;]*"),
     "[PHI-FIELD]"),
    # Dates: 2024-01-31, 2024/01/31, 31.01.2024, 01/31/2024, 20240131
    (re.compile(r"\b\d{4}[-/.]\d{1,2}[-/.]\d{1,2}\b"), "[DATE]"),
    (re.compile(r"\b\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}\b"), "[DATE]"),
    (re.compile(r"(?<![\d.])(19|20)\d{2}(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])(?![\d.])"), "[DATE]"),
    # Long digit runs (MRN, accession, phone) but not decimals
    (re.compile(r"(?<![\d.])\d{6,}(?![\d.])"), "[NUM]"),
    # E-mail
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "[EMAIL]"),
    # Any other absolute path. A folder name can hold a person's name.
    (re.compile(r"(?<![\w.~<>-])/(?:Volumes|Users|home|mnt|media|private|tmp|opt|var|Applications)"
                r"/[^\s\"':,;]+"), "<path>"),
]


def scrub(text: str) -> str:
    """Best-effort PHI filter for MATLAB output. Second line of defence only:
    tools return structured fields we generate, not raw logs."""
    try:
        root = str(dataset_dir())
        text = text.replace(root, "<dataset>")
    except RuntimeError:
        pass
    # The server folder first: it can be inside the Lead-DBS folder.
    text = text.replace(str(HEADLESS_DIR), "<headless>")
    text = text.replace(str(LEADDBS_ROOT), "<leaddbs>")
    text = text.replace(str(Path.home()), "~")
    try:
        # Longest first so 'sub-10' does not clobber 'sub-101'
        for subj in sorted(real_subjects(), key=len, reverse=True):
            text = re.sub(rf"(?<![A-Za-z0-9]){re.escape(subj)}(?![A-Za-z0-9])", pseudonym(subj), text)
    except RuntimeError:
        pass
    for pattern, repl in _PATTERNS:
        text = pattern.sub(repl, text)
    return text


# ------------------------------------------------------------ provenance

def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()


def leaddbs_git(root: Path = LEADDBS_ROOT) -> dict:
    """Commit and changed-file flag of a git checkout (Lead-DBS by default)."""
    def git(*args: str) -> str:
        return subprocess.run(["git", "-C", str(root), *args],
                              capture_output=True, text=True, timeout=30).stdout.strip()
    try:
        return {"commit": git("rev-parse", "HEAD"),
                # tracked files only; untracked macOS ._ files are noise
                "dirty": bool(git("status", "--porcelain", "--untracked-files=no"))}
    except (OSError, subprocess.SubprocessError):
        return {"commit": None, "dirty": None}


def input_hashes(subj_id: str) -> dict[str, str]:
    """SHA-256 of every raw input file, keyed by path relative to rawdata/."""
    raw = dataset_dir() / "rawdata"
    out = {}
    for f in sorted((raw / f"sub-{subj_id}").rglob("*")):
        if f.is_file() and not f.name.startswith("._"):
            out[str(f.relative_to(raw))] = sha256_file(f)
    return out


def append_provenance(record: dict) -> None:
    """Append one JSON line. Local file; never returned to the LLM."""
    with (state_dir() / "provenance.jsonl").open("a") as f:
        f.write(json.dumps(record, sort_keys=True) + "\n")
