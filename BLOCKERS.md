# Headless blockers on the validated preprocessing path

Scope: `ea_run('run', options)` → `ea_autocoord` with the options from
`ea_headless_options.m`. The path covers coregistration (MR: SPM, CT: ANTs),
ANTs normalization, brainshift correction (coarse mask), and electrode
reconstruction. Line numbers refer to commit `ceee6cd` on `develop`.

This list was made for recipe `v1` (Refined TRAC/CORE). Recipe `v2` uses PaCER, so
the `ea_reconstruct_trajectory.m` and `ea_refinecoords.m` rows no longer apply.

No Lead-DBS file was patched. Each blocker is avoided by an option value or a
precondition. Where that is not enough, a proposed upstream fix is listed.

## A. Blocks or fails on this path unless avoided

| file:line | call | when reached | how the spike avoids it | proposed upstream default |
|---|---|---|---|---|
| `ea_command_line_run.m:14,57` | `app = lead_dbs; app.leadfigure.Visible='off'` | Always on the existing CLI path | Not used. The builder makes `options` without the app | Add a `-headless` CLI mode that calls a builder like `ea_headless_options` |
| `helpers/ea_checkSpecialChars.m:33` (from `ea_run.m:49`) | `uigetpref` (modal; waits) | A patient path has a character outside `[A-Za-z0-9_-/]`, such as a space or `.` | The builder rejects such dataset paths before MATLAB starts the run | If `~usejava('desktop') \|\| batchStartupOptionUsed`, print a warning and continue |
| `ea_run.m:27` | `questdlg` (auto server export) | `d3.autoserver && d3.write` | `d3.autoserver=0`, `d3.write=0` | Default to `'Cancel'` when there is no display |
| `ea_run.m:130` | `ea_load_pts(getappdata(options.leadfigure,…))` | After the run, unless `cmdlineCall` or `exportedJob` is set | `cmdlineCall=1` | Guard with `isfield(options,'leadfigure')` |
| `ea_run.m:52–85` | `parpool` branch uses `options.leadfigure` | More than one patient and `prefs.pp.do` | One subject per MATLAB call | Same guard as above |
| `ea_autocoord.m:308` | reconmethod is replaced by `prefs.reco.method.<modality>` | More than one patient | One subject per call | Keep the method passed in `options` |
| `ea_autocoord.m:183` | uses `bids` from the try/catch at lines 33–46 | Always. If the `BIDSFetcher` init failed silently, this line errors | `uipatdirs` = `<ds>/derivatives/leaddbs/sub-XX`, and the builder checks that `rawdata/` exists | Rethrow in Lead-DBS mode instead of printing a warning |
| `ea_reconstruct_trajectory.m:54–66` | `figure` + `ginput(1)` | `entrypoint=='Manual'`, or any side above 2 (line 32 forces Manual) | `entrypoint='STN, GPi or ViM'`, `sides ⊆ [1 2]` | Error out in batch mode |
| `ea_reconstruct_trajectory.m:170,252` | `progressfig` is used, but only created when `verbose>1` | Always | `verbose=3`. The figures are invisible under `-batch` and are closed again | Create `progressfig` only when needed, or guard its use |
| `ea_reconstruct_trajectory.m:128` | `keyboard` | When `ea_prepare_slice` throws (one patient) | `runner.py` starts MATLAB with stdin=/dev/null so it cannot wait at `K>>` | Replace with `rethrow` |
| `helpers/ea_crop_nii.m:95` | `keyboard` in a catch | Brainshift preparation, when cropping fails | stdin=/dev/null | Replace with `rethrow` |
| `helpers/ea_getscrfmat.m:13` | `keyboard` | `prefs.env.dev==1` and the matrices differ | Keep `prefs.env.dev=0` (default) | Remove it or turn it into a warning |
| `ea_subcorticalrefine.m:40` | opens the GUIDE `.fig` | `scrf.do=1` and brainshift not approved | Does not wait when `d2.write=d3.write=0` (`uiwait` at `:95` is skipped). With `autobrainshift=1` it computes and then calls `saveandclose` | Split `ea_compute_scrf` out so no figure is created |
| `ea_subcorticalrefine.m:185` | `msgbox` | `transform.instore` missing | Non-modal, does not block. The run continues and the msgbox text goes to the log | Print to the log instead |
| `helpers/ea_error.m:15` | `errordlg` (`showdlg` defaults to true) | Every `ea_error` | Non-modal, followed by `error()`. MATLAB exits with code 1, which `runner.py` records as `failed` | `showdlg = usejava('desktop')` |
| `ea_setpath.m:30` | `savepath` | When Lead-DBS sets its own path | `hl_run_preprocessing.m` adds the path itself without saving it | Make `savepath` optional |

## B. Present in the code but not reached with these options

| file:line | call | condition that keeps it off |
|---|---|---|
| `ea_autocoord.m:362–368` | `figure` + `ea_manualreconstruction` (manual correction GUI) | `refinelocalization=0`. **Human QC happens later, locally, in the normal Lead-DBS GUI.** |
| `ea_autocoord.m:387` | `questdlg` (FreeSurfer overwrite) | `ecog.extractsurface.do=0` |
| `ea_autocoord.m:274` | `ea_checkreg` (interactive) and `evalin('base',…)` | `checkreg=0` |
| `ea_autocoord.m:291` | `ea_runwarpdrive` (interactive WarpDrive in Slicer) | `normalize.refine=0` |
| `ea_autocoord.m:318–332` | Manual / Slicer / LeGUI reconstruction | `reconmethod='PaCER (Husch 2017)'` |
| `ea_handles2options.m` | `getappdata(handles.normsettings,'settings')` | Not called. `normalize.settings=[]` uses the method defaults from `prefs.machine.normsettings` |
| `ea_refinecoords.m:166–206` | `figure` + `print` | `prefs.reco.saveimg=0` (default) |

## C. Behaviour to know about

- `ea_mod2pacermod` (`ea_runpacer.m`) sends an empty type for models that it does
  not map, and PaCER then estimates the type. So `run_preprocessing` accepts only
  Medtronic 3387, Medtronic 3389, and Boston Scientific Vercise Directed.
- PaCER uses one connected metal component per electrode. On a 2 mm CT it found
  1 of 2 electrodes, and `ea_runpacer.m:20` stopped the run with an error.
- With more than one patient, `ea_run.m:95-100` takes `elmodel` and `sides` from each
  subject's `uiprefs.mat`. The spike runs one patient per call, so this branch is not
  reached. `ea_storeui` writes that file from the current GUI state, so it can hold a
  value that nobody chose on purpose. The server refuses a run when the requested
  model differs from this file (see README).
- `ea_prefs` creates `~/.leaddbs/` with default prefs on the first run. It does
  not prompt. The run reads per-user prefs, so `options.json` stores the full
  `prefs` struct and its hash is in the provenance record.
- `-batch` still needs a graphics stack for invisible figures (brainshift GUI,
  `progressfig`). Under `-nodisplay` on macOS this works for `figure`. Not yet
  verified for the GUIDE `.fig` of `ea_subcorticalrefine` (see README, "Not
  verified").
- Checkreg PNGs come from `ea_gencheckregfigs`, which uses the FSL `slicer`
  binary rather than MATLAB figures. They are therefore safe to produce headless.
