# Lead-DBS headless MCP server (proof of concept)

This folder lets a chat client (Claude Desktop, Claude Code, or any MCP
client, including one backed by a local Ollama model) run ONE validated
Lead-DBS pipeline on this machine. The pipeline has no GUI.

The LLM does not write analysis code. It can only call three whitelisted tools
with schema-checked inputs. All methods and parameters are fixed in
`ea_headless_options.m`.

```
headless/
├── ea_headless_options.m          GUI-free options builder (the validated recipe)
├── matlab/hl_run_preprocessing.m  `matlab -batch` entry point
├── server/leaddbs_mcp.py          MCP server (stdio, 3 tools)
├── server/runner.py               detached job runner (one MATLAB call per job)
├── server/hl_common.py            config, pseudonyms, PHI scrubber, provenance
├── tests/smoke_test.py            end-to-end test over real MCP stdio
└── BLOCKERS.md                    every GUI call on the path, with file:line
```

## The recipe (`preprocessing_v2`)

`v1` used Refined TRAC/CORE. `v2` uses PaCER, the Lead-DBS default for CT. Only `v2`
has matched the expert reference, on one patient (see "Real-data runs").

| step | method |
|---|---|
| Pre-op MR coregistration | SPM (Friston 2007) |
| Post-op CT coregistration | ANTs (Avants 2008) |
| Normalization | ANTs (Avants 2008), default settings |
| Brainshift correction | Coarse mask (Schönecker 2008) |
| Electrode reconstruction | PaCER (Husch 2017), post-op CT only, both sides |
| Manual refinement, checkreg GUI, WarpDrive, 2D/3D export | **off** |

Steps that a human has already approved are never overwritten
(`overwriteapproved=0`).

## Tools

| tool | input | output |
|---|---|---|
| `list_subjects` | none | Pseudonymized IDs (`P-xxxxxxxxxx`), whether post-op imaging exists, last run state, and whether that run was a dry run |
| `run_preprocessing` | `subject_id` (pattern `^P-[0-9a-f]{10}$`), `electrode_model` (enum of the 3 models with a PaCER geometry: Medtronic 3389, Medtronic 3387, Boston Scientific Vercise Directed), `dry_run` | `job_id`. The job runs in the background. `dry_run` only builds and records the options |
| `get_status` | `subject_id` | State, `failure_reason`, timestamps, exit code, step flags (`coreg`, `normalization`, `brainshift`, `reconstruction`), `recon_check`, **dataset-relative paths** to QC PNGs, last 20 log lines after PHI scrubbing. MNI contact coordinates are returned **only** if the electrode check passed |

## Electrode check

Exit code 0 does not mean success. The first full run exited 0 and wrote plausible
MNI coordinates that were not on the electrodes. So `hl_recon_check.m` tests each side:

1. Every contact has CT signal at or above the image's 99th percentile within 2 mm.
2. The first-to-last contact length is within 15% of the electrode model.

If a test fails, or the check cannot run, the job state is `failed`. A person's
manually corrected reconstruction skips the check (`human_approved`).

These thresholds are heuristics and are not validated. A pass does not replace human QC.

## Electrode model check

A wrong model can give wrong coordinates with no error. So `run_preprocessing`, dry
runs included, compares the requested model with `elmodel` in the subject's
`derivatives/leaddbs/sub-XX/prefs/sub-XX_desc-uiprefs.mat`. It refuses before any
job starts, so a refused request does not hide an earlier result.

| Stored model | Result |
|---|---|
| Same as requested, and supported | The run starts |
| Different from requested | `electrode_model_mismatch` |
| Has no PaCER geometry in this recipe | `electrode_model_not_supported` |
| Missing or unreadable | `electrode_model_not_recorded` |

Limits:

- The stored value is the last GUI setting, not a verified implant record. It can
  be wrong, and the check cannot detect a wrong value that the request repeats.
- A new dataset has no stored model until a person sets it in the Lead-DBS GUI, so
  every run is refused until then.
- MATLAB reads the file, because it can be any `.mat` version. This adds about 9 s.
- On Lead-Tutor, 4 of 10 patients are refused as not supported (3 Medtronic B33005,
  1 Abbott 6172).

## Requirements

- MATLAB (tested with R2024b) with SPM12 on the **saved** MATLAB path. The
  runner adds Lead-DBS itself and does not call `savepath`.
- [uv](https://docs.astral.sh/uv/). The server declares its dependency
  (`mcp<2`) inline, so no venv is created in the repo. uv caches it in
  `~/.cache/uv`. (A venv on this exFAT volume took 1.2 GB.)
- A Lead-DBS BIDS dataset (`rawdata/sub-XX/ses-preop/…`, `ses-postop/…`). Its
  path must contain only `A-Z a-z 0-9 _ - /`, or Lead-DBS opens a blocking
  dialog (see BLOCKERS.md).

Environment variables:

| variable | meaning |
|---|---|
| `LEADDBS_DATASET` | **Required.** The only dataset the server may touch. Set by you, never by the LLM |
| `MATLAB_BIN` | Optional. Path to `matlab`. Default: `matlab` on `PATH`, or the newest `/Applications/MATLAB_R*.app/bin/matlab` |

## Connect to Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "leaddbs": {
      "command": "/Users/YOU/.local/bin/uv",
      "args": ["run", "--quiet", "/path/to/leaddbs/headless/server/leaddbs_mcp.py"],
      "env": {
        "LEADDBS_DATASET": "/path/to/your/BIDS_dataset",
        "MATLAB_BIN": "/Applications/MATLAB_R2024b.app/bin/matlab"
      }
    }
  }
}
```

Restart Claude Desktop. Use the absolute path to `uv`, because Desktop does not
read your shell `PATH`.

## Connect to Claude Code

```bash
claude mcp add leaddbs --env LEADDBS_DATASET=/path/to/your/BIDS_dataset --env MATLAB_BIN=/Applications/MATLAB_R2024b.app/bin/matlab -- uv run --quiet /path/to/leaddbs/headless/server/leaddbs_mcp.py
```

Or put the same `mcpServers` block in a project `.mcp.json`. Other MCP clients
(ChatGPT/Codex desktop, Ollama front ends that speak MCP) use the same
command and env.

## PHI rules

Consumer LLM plans have no HIPAA BAA, so everything the tools return is
treated as sent to a third party.

1. **IDs:** the tools only show `P-` + 10 hex characters, an HMAC-SHA256 of the
   BIDS ID. The key is in `derivatives/leaddbs_headless/.pseudonym_key` and
   never leaves the machine. The mapping is computed locally; no lookup table
   is stored.
2. **Derived data only:** step flags, MNI contact coordinates, timestamps of
   the run, and exit codes. No images, voxel data, DICOM headers, names, or
   absolute paths.
3. **QC images stay local:** checkreg PNGs are copied to
   `derivatives/leaddbs_headless/qc/<pseudonym>/` with the subject ID renamed.
   The tool returns only their dataset-relative paths, for a human to open.
4. **Log lines are scrubbed** (`hl_common.scrub`): the dataset path, Lead-DBS
   install path, home folder and other absolute paths are replaced, real subject
   IDs become pseudonyms, and DICOM-style fields, dates, digit runs of 6 or more,
   and e-mail addresses are redacted.
   This is a second line of defence only. It cannot detect free-text names.
   **Do not use BIDS subject IDs that are patient names or MRNs.**
5. **Inputs are closed:** the LLM cannot pass a path, a method, or MATLAB
   code. `subject_id` and `electrode_model` are checked against a pattern and
   an enum before any code runs.
6. **Local files with real IDs:** `jobs/*/job.json`, `jobs/*/matlab.log`,
   `jobs/*/options.json` and `provenance.jsonl` stay in the dataset's
   derivatives folder. No tool returns them in full.

## Provenance

Each run appends two lines (`started`, then `finished` or `failed`) to
`<dataset>/derivatives/leaddbs_headless/provenance.jsonl`:
`job_id`, `pseudonym`, `recipe`, `dry_run`, `leaddbs.commit` and `leaddbs.dirty`
(tracked files only), `inputs_sha256` (SHA-256 of every file in
`rawdata/sub-XX/`, hashed at start and again at end), `options_sha256` (hash of
`options.json`, which includes the user's Lead-DBS prefs), UTC timestamps, and
`exit_code`.

## Human QC (required)

The server never approves a localization. After `get_status` shows
`reconstruction: true` (the electrode check passed), open the subject in the normal Lead-DBS GUI, review
the checkreg images and the electrode localization, and approve or correct
them there. Approved steps are then protected from later runs.

## Smoke test

```bash
uv run headless/tests/smoke_test.py /path/to/dataset
```

```bash
uv run headless/tests/smoke_test.py /path/to/dataset --matlab
```

## Limits of this spike

- One recipe, one subject per job, one configured dataset.
- No queue or cancel tool. Two subjects can run at the same time and compete
  for CPU. Stop a job by killing its `runner.py` / MATLAB process.
- Job state is in JSON files. If the machine reboots mid-run, the job stays
  `running`.
- PaCER needs a post-op CT. PaCER warns about slices thicker than 0.7 mm, and
  it failed on a 2 mm CT (see below). There is no slice-thickness check yet.
- A failed run does not delete the existing `desc-reconstruction.mat`. The GUI
  can still open that old file.
- The PHI scrubber uses patterns, not NLP.
- `mcp` is pinned below 2.0 (the 2.x SDK renamed `FastMCP` to `MCPServer`).

## Verification status (2026-10-26)

Tested on a synthetic BIDS dataset (empty NIfTI placeholders, one subject
with a name-like ID):

- MCP over stdio: exactly 3 tools; `list_subjects` returns pseudonyms only;
  the schema rejects raw IDs and unknown electrode models.
- PHI scrubber: the path, the subject ID, a DICOM `PatientName` field, an MRN
  and a date were redacted, and decimal values were kept.
- `matlab -batch` (R2024b) finds SPM12 and Lead-DBS.
- `run_preprocessing(dry_run=true)` end to end: MCP → detached runner →
  `matlab -batch` → `ea_headless_options` → `options.json` written (about 13 s,
  exit 0). The recipe fields were checked in `options.json`. `get_status`
  returned step flags and a scrubbed log tail with no raw IDs. Two provenance
  lines were written with the git hash, options hash and input hashes.

## Real-data runs (2026-11-06)

Dataset: Lead-Tutor, two patients.

**Worked on both:** coregistration, ANTs normalization, brainshift (no blocking
figure under `-batch -nodisplay`), FSL `slicer` QC PNGs, provenance, and no real
ID or path in `get_status`.

| CT slices | Electrode | Method | Result |
|---|---|---|---|
| 2 mm | Medtronic 3387 | Refined TRAC/CORE (`v1`) | Exit 0, but the contacts were not on metal and spanned about 6.8 mm instead of 9 mm |
| 2 mm | Medtronic 3387 | PaCER (`v2`) | Error: 1 electrode found, 2 expected |
| 0.5 mm | Boston Scientific Vercise Directed | PaCER (`v2`) | 2 electrodes found, electrode check passed, about 10 minutes |

On the 2 mm CT, a threshold of 2000 shows one continuous lead and one lead in
pieces. The probable cause of the PaCER failure is the 2 mm slices. This is not
proven, because the 0.5 mm patient also differs in electrode model and anatomy.

**Electrode check:** it fails the saved TRAC/CORE result on both tests and both
sides, and it passes the 0.5 mm PaCER result. That is one case of each.

Limits of the check on PaCER results:

- PaCER fits the model geometry, so the length test passes almost automatically.
- The shaft is metal, so a contact moved along the shaft can still pass.

**Not verified:** a person's review of the 0.5 mm result in the GUI, the
comparison with a GUI run, and the 1 mm CTs.

### Comparison with the Lead-Tutor expert reference (2026-11-06)

One patient (78754, 0.5 mm CT, recipe `v2`), distance in MNI space from the
average of two experts:

| Electrode marker | Head | Tail | Mean | Page band for this patient | Rotation |
|---|---|---|---|---|---|
| `markers(1)` | 0.17 mm | 0.17 mm | 0.17 mm | Green (up to 0.35 mm) | 33.3° |
| `markers(2)` | 0.49 mm | 0.46 mm | 0.48 mm | Yellow (0.35 to 0.70 mm) | 21.1° |

Mean of both: 0.33 mm. The Lead-Tutor paper reports 0.37 mm between its experts
and 0.66 mm for non-experts against the experts.

Limits of this result:

- It is one patient, with the thinnest CT slices that we tested.
- It is not fully independent. The experts also started from Lead-DBS tools,
  and they could start from PaCER before manual refinement.
- The rotation is not a result of this pipeline, which does not determine
  orientation. The published expert difference is 4.68°. Do not use segment labels.
- The band limits come from the result page's chart code. The server does not
  return a color.

How it ran: `ea_querytutor.m` was not used. It sends every reconstruction in the
dataset, and it labels patients by list position. One POST sent `pt_78754` only.

**Use this server for the public Lead-Tutor data only, never for real patients.**
It stores the markers and a machine ID (a hash of the Mac serial number), and it
uses plain HTTP. For this reason it is not a tool of the MCP server.

**Directional leads:** `ea_runpacer.m` does not pass PaCER's rotation to Lead-DBS,
so segment orientation is not determined. Do not use the segment labels until a
person has set the orientation in the GUI.

### Chat client test (2026-11-06)

Client: Claude Code CLI (`claude -p`, model `haiku`), started from a shell that can
read the user's sign-in. Each request cost about US$0.015 by the CLI's estimate.

| Request | Result |
|---|---|
| List patients and give coordinates for the finished patient | Correct IDs, status and coordinates |
| Give coordinates for the failed patient | Refused, and gave the failure reason. No coordinates |
| Dry-run a subject that has never run | Chose a correct subject and set `dry_run`, but stopped before the job finished. The job finished 25 s after it started |
| Separate real runs from dry runs (after the fix) | Correct |

The test found three defects, all fixed:

- A log line returned the Lead-DBS install path, which contains a person's first name.
- `list_subjects` showed a dry run as `finished`, the same as a real run.
- The server accepted a wrong electrode model. The dry run took Vercise Directed for
  a Medtronic B33005 patient. See "Electrode model check".

After that fix, a request with a wrong model was refused, no job started, and the
client did not retry with the stored model. It asked the user to check the implant
record. That is one request with one model, so it does not prove that every client
will stop.

Open problems:

- **Advice outside the recipe:** the Lead-DBS error text suggests TRAC/CORE, so the
  client offered it. The tools cannot run it, and it gave a wrong result on that patient.
- **Misread field:** the client called `weakest_contact_vs_metal` (a ratio) a distance.
- **Client state:** the client used the user's own settings and notes from earlier
  sessions. So a reply can draw on more than the tools, and the client can store
  tool results on this computer.
