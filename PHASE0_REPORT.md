# Phase 0 evaluation: headless Lead-DBS through MCP

Status on 2026-11-10. Research use only.

## Summary

Phase 0 tested whether a chat client can run one fixed Lead-DBS preprocessing
pipeline through three MCP tools without the Lead-DBS GUI and without receiving
identifying data. The pipeline ran on the 10 patients of the public Lead-Tutor
dataset. PaCER reconstructed both electrodes in 4 patients. In those 4 patients,
the mean distance from the average of two experts was 0.36 mm over 8 electrodes.
The Lead-Tutor authors report 0.37 mm between their experts. The other 6 patients
did not produce a result: 4 have electrode models that the recipe does not support,
and PaCER failed on 2. A chat client used the tools correctly on the tested
requests after seven defects were fixed. No real ID or absolute path appeared in
the scanned tool results or replies.

**No person has reviewed a localization from this pipeline yet. Do not use these
results for analysis or for clinical decisions.**

## Recommendation

Phase 1 should start, as engineering work only. The results support a GUI-free
options builder and more tools, but they do not support a claim of validation. A
person must first review the four localizations, and the server must be tested in
at least one more chat client.

## Methods

### Data

The Lead-Tutor dataset contains 10 anonymized patients with a pre-op T1-weighted
MRI, a post-op CT, and an expert reference that the Lead-Tutor server holds. The CT
slice thickness was 0.5 mm in 1 patient, 1 mm in 7 patients, 1.26 mm in 1 patient,
and 2 mm in 1 patient. The stored electrode models were Boston Scientific Vercise
Directed in 5 patients, Medtronic B33005 in 3, Medtronic 3387 in 1, and Abbott 6172
in 1.

### Pipeline

Each run used recipe `preprocessing_v2`: SPM coregistration of the pre-op MRI, ANTs
coregistration of the post-op CT, ANTs normalization with default settings,
brainshift correction with a coarse mask, and PaCER reconstruction. Each run was one
`matlab -batch` call (MATLAB R2024b) on one Mac. After each run, an electrode check
tested each contact for metal-level CT signal within 2 mm and compared the contact
span with the electrode model.

### Comparison with the expert reference

For each patient where PaCER succeeded, the MNI marker coordinates (head, tail, and
one point on the shaft) were sent to the Lead-Tutor server, one patient per upload.
The server returned the distance of each marker from the average of two experts.
We did not use `ea_querytutor.m`, because it sends every reconstruction in the
dataset and labels patients by their position in a list. The server keeps only the
last upload for each user ID, so each result was downloaded before the next upload.
The server stores the markers and a machine ID (a hash of the Mac serial number),
and it uses plain HTTP. It is therefore suitable for public data only and is not a
tool of the MCP server.

### Comparison with the GUI options path

Patient 29781 ran a second time on a separate copy of its inputs, through
`ea_command_line_run`. This function starts the real `lead_dbs` app, sets its
controls, and reads the options through `ea_handles2options`, which is the same
function that the GUI uses. Nobody clicked the GUI. We compared the contact
coordinates of the two runs in native and MNI space.

### Chat client tests

The client was the Claude Code command line (`claude -p`) with the `haiku` model,
connected to the server over MCP stdio. Each request cost about US$0.015 to
US$0.016 by the client's estimate. A script scanned every tool result and reply for
the real patient IDs, the drive name, and the user name.

## Results

### Pipeline runs

| Patient | CT slices | Electrode model | Outcome | Time |
|---|---|---|---|---|
| 78754 | 0.5 mm | Vercise Directed | Electrode check passed | About 10 min |
| 29781 | 1 mm | Vercise Directed | Electrode check passed | 8.3 min |
| 57245 | 1 mm | Vercise Directed | Electrode check passed | 8.2 min |
| 80206 | 1 mm | Vercise Directed | Electrode check passed | 8.8 min |
| 33544 | 1 mm | Vercise Directed | PaCER failed: wrong electrode count | 8.2 min |
| 76325 | 2 mm | Medtronic 3387 | PaCER failed: 1 of 2 electrodes found | Not recorded |
| 15454, 84257, 93127 | 1 mm | Medtronic B33005 | Refused: model not supported | No run |
| 39468 | 1.26 mm | Abbott 6172 | Refused: model not supported, slices above 1 mm | No run |

Coregistration, normalization, brainshift correction, and the QC images worked on
every patient that ran. Brainshift correction opened no blocking window under
`matlab -batch -nodisplay`. On all 1 mm runs, PaCER could not detect the electrode
type from the image and used the model that the server gave it. PaCER logs the
Vercise Directed model as "Boston Vercise Directional", which is its own name for
the same model (`ea_runpacer.m:57`).

The failure on 33544 is the same failure as on the 2 mm CT, so slice thickness does
not explain all PaCER failures. PaCER reports that a wrong brain mask on an unusual
CT is the usual cause, but we did not confirm this. On the 2 mm CT, a CT threshold
of 2000 showed one continuous lead and one lead in pieces. The earlier TRAC/CORE
recipe (`v1`) ran on the same 2 mm CT without an error, but its contacts were not
on the metal and spanned about 6.8 mm instead of 9 mm. The electrode check failed
that result on both sides, which is how the check was first tested.

### Distance from the expert reference

| Patient | CT slices | `markers(1)` head / tail / mean | `markers(2)` head / tail / mean |
|---|---|---|---|
| 78754 | 0.5 mm | 0.17 / 0.17 / 0.17 mm | 0.49 / 0.46 / 0.48 mm |
| 29781 | 1 mm | 0.40 / 0.53 / 0.47 mm | 0.20 / 0.49 / 0.34 mm |
| 57245 | 1 mm | 0.37 / 0.53 / 0.45 mm | 0.18 / 0.18 / 0.18 mm |
| 80206 | 1 mm | 0.53 / 0.66 / 0.59 mm | 0.16 / 0.20 / 0.18 mm |

Over the 8 electrodes, the mean distance was 0.36 mm, the median was 0.40 mm, and
the largest was 0.59 mm. The Lead-Tutor authors report 0.37 mm between their
experts and 0.66 mm between non-experts and experts. No electrode was farther from
the experts than 0.66 mm. On the result page for 78754, `markers(1)` was in the
green band (up to 0.35 mm) and `markers(2)` was in the yellow band (0.35 to
0.70 mm). The band limits come from the chart code of the page, because the server
returns no color. The server also returned rotation differences of 10° to 79°. The
pipeline does not determine lead orientation, so these values do not measure it.
The published difference between experts is 4.68°.

### Agreement with the GUI options path

| Space | Hemisphere | Mean contact difference | Largest contact difference |
|---|---|---|---|
| Native | Right | 0.13 mm | 0.13 mm |
| Native | Left | 0.14 mm | 0.15 mm |
| MNI | Right | 0.17 mm | 0.24 mm |
| MNI | Left | 0.12 mm | 0.15 mm |

Both runs recorded the same coregistration, normalization, and brainshift methods
and the same ANTs settings. This run also showed a side effect of the Lead-DBS app:
it changed the per-user preference file `~/.leaddbs/ea_prefs_user.mat` and added a
line to `ea_prefs_user.m`. We restored both files from a backup. The headless path
does not change the `.mat` file.

### Chat client behavior

The first test, on 2026-11-06, used four requests. The client listed the patients
with correct IDs, states, and coordinates. It refused to give coordinates for a
failed run and gave the failure reason. It chose a correct patient for a dry run but
stopped before the job finished, which took 25 s. After a fix, it separated real
runs from dry runs. After the electrode model check was added, a request with a
wrong model was refused, no job started, and the client asked the user to check the
implant record instead of trying the stored model.

The second test, on 2026-11-09, used five requests. The client did not recommend a
method outside the recipe, called the electrode check value a ratio with no unit,
named the correct hemisphere for each side, and gave the PaCER error for the failed
run. A dry run on the 2 mm patient was refused with `ct_slices_too_thick`, and the
client did not retry. No job started during this test.

The tests found seven defects, and each one was fixed and tested again:

1. A log line returned the Lead-DBS install path, which contained a person's first
   name.
2. `list_subjects` showed a dry run as `finished`, in the same way as a real run.
3. The server accepted a wrong electrode model and ran a dry run with Vercise
   Directed for a Medtronic B33005 patient.
4. The Lead-DBS error text suggests TRAC/CORE, so the client offered a method that
   the tools cannot run and that had failed on this dataset.
5. The client called `weakest_contact_vs_metal`, a ratio, a distance.
6. The client stated that side 1 is the left hemisphere. Side 1 is the right
   hemisphere (`ea_headless_options.m:18`).
7. The cause of the PaCER failure was above the 20 log lines that the tool returns.

### Earlier synthetic test

On 2026-10-26, before real data was available, the server ran on a synthetic BIDS
dataset with empty NIfTI files and one patient with a name-like ID. The server
exposed exactly three tools, returned pseudonyms only, and rejected raw IDs and
unknown electrode models. The scrubber removed the path, the patient ID, a DICOM
`PatientName` field, a medical record number, and a date, and it kept decimal
values. A dry run went from the MCP request to `options.json` in about 13 s, and it
wrote two provenance lines.

## Limitations

The evaluation used one public dataset, one computer, and one chat client with one
model. Only 4 of 10 patients produced a result, so the expert comparison applies
only to patients where PaCER succeeds. The comparison is not fully independent,
because the experts also worked in Lead-DBS and could start from a PaCER result
before their manual refinement. The GUI comparison used one patient and did not
include a repeated headless run, so it does not separate the effect of the options
path from normal variation between runs.

The 1 mm CT limit comes from 6 patients and is not a validated value. The stored
electrode model is the last GUI setting, not an implant record. The pipeline does
not determine the orientation of directional leads. The log scrubber uses patterns,
and the dataset is public, so the privacy result does not show that the rules
protect real patient data. The chat client used notes from earlier sessions, so
its replies drew on more than the tools. ChatGPT, Claude Desktop, and local-model
clients are not tested. Consumer Claude and ChatGPT plans include no HIPAA BAA, so
real patient use needs a separate compliance review.

## Open items for Phase 0

1. A person reviews 78754, 29781, 57245, and 80206 in the Lead-DBS GUI.
2. Test the server in Claude Desktop.

## Next steps (Phase 1)

1. Add a `nogui` flag to Lead-DBS that removes each dialog listed in `BLOCKERS.md`.
2. Add a schema for each recipe.
3. Investigate the PaCER failures, for example with a supplied brain mask.
4. Keep the per-user Lead-DBS preferences unchanged during a run.
