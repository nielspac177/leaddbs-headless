# Lead-DBS headless MCP server

This repository runs one fixed Lead-DBS preprocessing pipeline without the Lead-DBS
graphical user interface (GUI). A chat client starts the pipeline and reads its
results through the Model Context Protocol (MCP). The client can be Claude Desktop,
Claude Code, or another MCP client, including one that runs a local model.

The chat client cannot write analysis code. It can call three tools, and each tool
accepts only a pseudonymized patient ID, an electrode model from a fixed list, and a
dry-run flag. The file `ea_headless_options.m` fixes every method and parameter.

> **Status: proof of concept, research use only.** No person has reviewed a
> localization from this pipeline yet. It is not a medical device, and you must not
> use it for clinical decisions. The evaluation is in [`PHASE0_REPORT.md`](PHASE0_REPORT.md).

## Contents

```
.
├── ea_headless_options.m           Builds the Lead-DBS options with no GUI (the recipe)
├── matlab/hl_run_preprocessing.m   Entry point for `matlab -batch`
├── matlab/hl_recon_check.m         Electrode check on the post-op CT
├── matlab/hl_stored_elmodel.m      Reads the stored electrode model of a patient
├── server/leaddbs_mcp.py           MCP server (stdio, three tools)
├── server/runner.py                Runs one MATLAB job in the background
├── server/hl_common.py             Configuration, pseudonyms, log scrubber, checks, provenance
├── tests/                          Unit tests and an end-to-end smoke test
├── BLOCKERS.md                     Each GUI call on the pipeline path, with file and line
├── PHASE0_REPORT.md                Evaluation on the Lead-Tutor dataset
├── CITATION.cff                    How to cite this software
└── LICENSE                         GNU General Public License version 3
```

## The recipe (`preprocessing_v2`)

| Step | Method |
|---|---|
| Pre-op MRI coregistration | SPM (Friston 2007) |
| Post-op CT coregistration | ANTs (Avants 2008) |
| Normalization | ANTs (Avants 2008), default settings |
| Brainshift correction | Coarse mask (Schönecker 2008) |
| Electrode reconstruction | PaCER (Husch 2017), post-op CT only, both hemispheres |
| Manual refinement, checkreg GUI, WarpDrive, 2D and 3D export | Off |

The first recipe (`v1`) used Refined TRAC/CORE. On a 2 mm CT it exited without an
error but placed the contacts off the metal, so `v2` replaced it with PaCER, which
is the Lead-DBS default for CT. A run never overwrites a step that a person has
already approved (`overwriteapproved=0`).

## Tools

| Tool | Input | Output |
|---|---|---|
| `list_subjects` | None | Pseudonymized IDs (`P-` and 10 hex characters), whether post-op imaging exists, the state of the last run, and whether that run was a dry run |
| `run_preprocessing` | `subject_id`, `electrode_model` (Medtronic 3389, Medtronic 3387, or Boston Scientific Vercise Directed), `dry_run` | A `job_id`, or a refusal with a reason. The job runs in the background. A dry run only builds and records the options |
| `get_status` | `subject_id` | State, failure reason and detail, times, exit code, step flags, the electrode check with notes on each field, paths to the local QC images, and the last 20 log lines after scrubbing. It returns MNI contact coordinates only when the electrode check passed |

The three electrode models are the models for which PaCER has a geometry in
`ea_runpacer.m`. For other models, PaCER guesses the type.

## Checks before and after a run

A run can finish with exit code 0 and still give wrong coordinates. The first full
run on real data did this. For that reason the server checks the request before a
job starts, and it checks the result before it returns coordinates.

**Before a run**, `run_preprocessing` refuses the request and starts no job in
three cases. The first case is a post-op CT that it cannot read or that has slices
thicker than 1 mm. The second case is a requested electrode model that differs from
the model stored in the patient's `uiprefs.mat`. The third case is a stored model
that is missing or that the recipe does not support. The refusal comes before the
job, so a refused request cannot hide an earlier result.

| Refusal reason | Cause |
|---|---|
| `ct_not_readable` | No post-op CT, or its NIfTI-1 header cannot be read |
| `ct_slices_too_thick` | The thickest voxel side of the post-op CT is above 1 mm |
| `electrode_model_mismatch` | The requested model differs from the stored model |
| `electrode_model_not_supported` | The stored model has no PaCER geometry in this recipe |
| `electrode_model_not_recorded` | No stored model could be read |

The 1 mm limit is the upper end of the tested range. PaCER failed on a 2 mm CT, and
no supported patient in the test data had slices between 1 and 2 mm. The stored
electrode model is the last value set in the Lead-DBS GUI, not a verified implant
record. The check therefore cannot detect a wrong stored value that the request
repeats. MATLAB reads the stored model, which adds about 9 s to each request.

**After a run**, `hl_recon_check.m` tests each electrode on the post-op CT. Each
contact must have CT signal at or above the 99th percentile of the image within
2 mm, and the distance from the first to the last contact must be within 15% of the
electrode model. If a test fails, or the check cannot run, the job state is
`failed`. A reconstruction that a person corrected by hand skips the check and has
the state `human_approved`. These thresholds are heuristics, and a pass does not
replace a person's review. PaCER fits the model geometry, so the length test almost
always passes on PaCER results. A contact that moved along the metal shaft can also
pass the signal test.

## Requirements

- [Lead-DBS](https://github.com/netstim/leaddbs), cloned with
  `git clone https://github.com/netstim/leaddbs.git`. The tests used commit
  `ceee6cd` on `develop`. Set `LEADDBS_ROOT` to its folder, unless this repository
  sits inside the Lead-DBS folder.
- MATLAB (tested with R2024b), with SPM12 on the saved MATLAB path. The runner adds
  Lead-DBS to the path itself and does not call `savepath`.
- [uv](https://docs.astral.sh/uv/). The server declares its one dependency (`mcp`
  below version 2) in the file, so uv installs it in its cache and creates no
  environment in the repository.
- A Lead-DBS BIDS dataset with `rawdata/sub-XX/ses-preop/` and
  `rawdata/sub-XX/ses-postop/`. The dataset path must contain only the characters
  `A-Z a-z 0-9 _ - /`. Other characters make Lead-DBS open a dialog that stops the
  run (see `BLOCKERS.md`).
- Each patient needs an electrode model set once in the Lead-DBS GUI. Without it,
  the server refuses every run for that patient.

| Environment variable | Meaning |
|---|---|
| `LEADDBS_DATASET` | Required. The only dataset that the server can read or write. You set it, and the chat client cannot change it |
| `LEADDBS_ROOT` | The Lead-DBS folder. Required unless this repository sits inside it |
| `MATLAB_BIN` | Optional. The path to `matlab`. The default is `matlab` on `PATH`, then the newest `/Applications/MATLAB_R*.app/bin/matlab` |

## Connect a chat client

For Claude Desktop, add this block to
`~/Library/Application Support/Claude/claude_desktop_config.json` and restart the
app. Use the absolute path to `uv`, because Claude Desktop does not read the `PATH`
of your shell.

```json
{
  "mcpServers": {
    "leaddbs": {
      "command": "/Users/YOU/.local/bin/uv",
      "args": ["run", "--quiet", "/path/to/this/repository/server/leaddbs_mcp.py"],
      "env": {
        "LEADDBS_DATASET": "/path/to/your/BIDS_dataset",
        "LEADDBS_ROOT": "/path/to/leaddbs",
        "MATLAB_BIN": "/Applications/MATLAB_R2024b.app/bin/matlab"
      }
    }
  }
}
```

For Claude Code, run this command:

```bash
claude mcp add leaddbs --env LEADDBS_DATASET=/path/to/your/BIDS_dataset --env LEADDBS_ROOT=/path/to/leaddbs --env MATLAB_BIN=/Applications/MATLAB_R2024b.app/bin/matlab -- uv run --quiet /path/to/this/repository/server/leaddbs_mcp.py
```

Other MCP clients use the same command and environment variables. Only Claude Code
has been tested so far.

## Privacy

Consumer chat plans do not include a HIPAA business associate agreement (BAA). The
server therefore treats every tool output as data sent to a third party, and it
applies these rules:

1. **Pseudonyms.** The tools show only `P-` and 10 hex characters, an HMAC-SHA256
   of the BIDS ID. The key stays in `derivatives/leaddbs_headless/.pseudonym_key`.
   The server computes the mapping locally and stores no lookup table.
2. **Derived data only.** The tools return step flags, MNI contact coordinates,
   run times, and exit codes. They return no images, voxel data, DICOM headers,
   names, or absolute paths.
3. **Local QC images.** The runner copies the checkreg PNGs to
   `derivatives/leaddbs_headless/qc/<pseudonym>/` and renames the patient ID. The
   tools return only the paths, for a person to open on the same computer.
4. **Scrubbed log lines.** `hl_common.scrub` replaces the dataset path, the Lead-DBS
   path, the home folder, and other absolute paths. It replaces real IDs with
   pseudonyms and removes DICOM-style fields, dates, runs of 6 or more digits, and
   e-mail addresses. It uses patterns, so it cannot find a name in free text. Do not
   use patient names or medical record numbers as BIDS IDs.
5. **Closed inputs.** The chat client cannot pass a path, a method, or MATLAB code.
   The server checks `subject_id` against a pattern and `electrode_model` against a
   fixed list before any code runs.
6. **Local records.** `jobs/*/job.json`, `jobs/*/matlab.log`, `jobs/*/options.json`,
   and `provenance.jsonl` contain real IDs. They stay in the dataset's derivatives
   folder, and no tool returns them in full.

The chat client is outside these rules. In the tests, the client used notes from
earlier sessions and could store tool results on the computer. Real patient data
needs a separate compliance review before use with any hosted model.

## Provenance

Each run adds two lines to `<dataset>/derivatives/leaddbs_headless/provenance.jsonl`,
one at the start and one at the end. Each line records the job ID, pseudonym,
recipe, and dry-run flag. It also records the commit of Lead-DBS and of this
repository, and whether tracked files in each had changes. It also records the SHA-256 of every input file of the patient, hashed at
the start and again at the end, and the SHA-256 of `options.json`, which includes
the Lead-DBS preferences of the user.

## Review by a person (required)

The server never approves a localization. After `get_status` reports
`reconstruction: true`, open the patient in the Lead-DBS GUI. Review the checkreg
images and the electrode localization, and approve or correct them there. Later
runs do not overwrite an approved step.

The recipe does not determine the orientation of directional leads, because
`ea_runpacer.m` does not pass the PaCER rotation to Lead-DBS. Do not use segment
labels until a person sets the orientation in the GUI. In `contacts_mni`, `side1`
is the right hemisphere and `side2` is the left hemisphere.

## Tests

The unit tests need only Python 3:

```bash
python3 -B tests/test_ct_check.py
```

```bash
python3 -B tests/test_scrub.py
```

```bash
python3 -B tests/test_electrode_check.py
```

```bash
python3 -B tests/test_final_state.py
```

GitHub Actions runs these four tests on each push.

The smoke test runs the server over MCP stdio. The `--matlab` option also sends
real requests to the checks, and it starts a dry run if a patient that never ran can
pass them. Otherwise it reports the dry run as skipped.

```bash
uv run tests/smoke_test.py /path/to/dataset --matlab
```

## Limits

The server handles one recipe, one patient per job, and one dataset. It has no
queue and no cancel tool, so two jobs can run at the same time and compete for the
CPU. To stop a job, end its `runner.py` and MATLAB processes. Job state is kept in
JSON files, so a job stays `running` if the computer restarts during a run. A failed
run does not delete an earlier `desc-reconstruction.mat`, and the GUI can still open
that file. The `mcp` package is pinned below version 2, because version 2 renamed
`FastMCP`.

## License

This software calls [Lead-DBS](https://github.com/netstim/leaddbs), which uses the
GNU General Public License version 3, and it is distributed under the same license.
See [`LICENSE`](LICENSE). Lead-DBS, SPM, ANTs, PaCER, FSL, and the Lead-DBS
templates and atlases keep their own licenses. Some of those licenses do not allow
commercial use (see `LICENSE.md` in Lead-DBS). To cite this software, see
[`CITATION.cff`](CITATION.cff), and also cite Lead-DBS and the methods in the recipe.
