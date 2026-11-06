function options = ea_headless_options(datasetDir, subjId, varargin)
% Build a complete, GUI-free options struct for the validated
% "preprocessing" recipe: coregistration -> normalization -> brainshift
% correction -> electrode reconstruction (PaCER, post-op CT only).
%
% This replaces the GUI path in ea_command_line_run.m, which creates the
% lead_dbs app, hides it and converts its handles via ea_handles2options.
% Here no figure is created. Because options has no 'leadfigure' field,
% ea_autocoord builds the BIDSFetcher itself from options.uipatdirs.
%
% Usage:
%   options = ea_headless_options('/path/to/BIDSdataset', '01');
%   ea_run('run', options);
%
% Optional name-value pairs (validated, everything else is fixed):
%   'elmodel'  - electrode model name, must be in ea_resolve_elspec list
%                (default 'Medtronic 3389')
%   'sides'    - subset of [1 2] (1 = right, 2 = left), default [1 2]
%   'modality' - 'CT' (default) or 'MRI'; preferred post-op modality.
%                BIDSFetcher falls back to the one that is present.
%
% The recipe parameters (methods) are FIXED on purpose: the MCP server
% must not let an LLM select arbitrary methods. Change them here, in
% one place, after validation.

RECIPE.coregmr_method  = 'SPM (Friston 2007)';
RECIPE.coregct_method  = 'ANTs (Avants 2008)';
RECIPE.norm_method     = 'ANTs (Avants 2008)';
RECIPE.scrf_mask       = 'Coarse mask (Schönecker 2008)';
RECIPE.recon_method    = 'PaCER (Husch 2017)'; % prefs.reco.method.CT default

p = inputParser;
p.addRequired('datasetDir', @(x) ischar(x) || isstring(x));
p.addRequired('subjId', @(x) ischar(x) || isstring(x));
p.addParameter('elmodel', 'Medtronic 3389', @(x) ischar(x) || isstring(x));
p.addParameter('sides', [1 2], @(x) isnumeric(x) && ~isempty(x) && all(ismember(x, [1 2])));
p.addParameter('modality', 'CT', @(x) any(strcmpi(x, {'CT', 'MRI'})));
p.parse(datasetDir, subjId, varargin{:});
datasetDir = char(p.Results.datasetDir);
subjId = erase(char(p.Results.subjId), 'sub-');

% Validate inputs
datasetDir = erase(datasetDir, filesep + textBoundary('end'));
if ~isfolder(fullfile(datasetDir, 'rawdata'))
    error('ea_headless:dataset', 'Not a Lead-DBS BIDS dataset (no rawdata/ folder): %s', datasetDir);
end
% ea_checkSpecialChars (called by ea_run) opens a modal uigetpref dialog
% for any path character outside [A-Za-z0-9_-/]. Fail early instead.
if ~isempty(regexp(datasetDir, '[^A-Za-z0-9_\-/]', 'once'))
    error('ea_headless:path', ['Dataset path contains spaces or special ' ...
        'characters; Lead-DBS would open a blocking dialog. Move or rename it.']);
end
if isempty(regexp(subjId, '^[A-Za-z0-9]+$', 'once'))
    error('ea_headless:subjId', 'Subject ID must be BIDS-alphanumeric.');
end
if ~isfolder(fullfile(datasetDir, 'rawdata', ['sub-', subjId]))
    error('ea_headless:subjId', 'Subject not found in rawdata/.');
end
elms = ea_resolve_elspec;
elmodel = char(p.Results.elmodel);
if ~ismember(elmodel, elms)
    error('ea_headless:elmodel', 'Unknown electrode model "%s".', elmodel);
end

patdir = fullfile(datasetDir, 'derivatives', 'leaddbs', ['sub-', subjId]);

%% Run control (what ea_run / ea_autocoord check)
options = struct;
options.leadprod = 'dbs';
options.cmdlineCall = 1;    % ea_run: skip GUI refresh (ea_load_pts)
options.uipatdirs = {patdir};
options.subjInd = 1;
options.earoot = ea_getearoot;
switch upper(p.Results.modality)
    case 'CT'
        options.modality = 2;
    otherwise
        options.modality = 1;
end

%% Import: off (data must already be in BIDS rawdata/)
options.importdcm.do = 0;
options.importnii.do = 0;

%% Pre-steps: off
options.acpc.do = 0;
options.resize.do = 0;

%% Coregistration
options.coregmr.do = 1;
options.coregmr.method = RECIPE.coregmr_method;
options.coregmr.check = 0;
options.coregct.do = 1;
options.coregct.method = RECIPE.coregct_method;
options.coregb0.addSyN = 0;
options.overwriteapproved = 0; % never overwrite human-approved steps

%% Normalization
options.normalize.do = 1;
options.normalize.method = RECIPE.norm_method;
options.normalize.settings = []; % method defaults (no settings dialog)
options.normalize.refine = 0;    % WarpDrive is interactive -> off
options.checkreg = 0;            % ea_checkreg is an interactive GUI -> off

%% Brainshift correction
options.scrf.do = 1;
options.scrf.mask = RECIPE.scrf_mask;

%% Electrode reconstruction
options.doreconstruction = 1;
options.reconmethod = RECIPE.recon_method;
options.elmodel = elmodel;
options.sides = p.Results.sides;
options.maskwindow = 10;
options.automask = 1;
options.refinelocalization = 0; % manual-correction GUI -> off (human QC later)
options.numcontacts = 4;

% Tracking parameters (same values as ea_handles2options)
options.endtolerance = 10;
options.sprungwert = 4;
options.refinesteps = 0;
options.tra_stdfactor = 0.9;
options.cor_stdfactor = 1.0;
options.autoimprove = 0;
options.axiscontrast = 8;
options.zresolution = 10;
% verbose must be >= 2: ea_reconstruct_trajectory uses progressfig
% unconditionally but only creates it when verbose > 1. With 3 the
% figures are created (invisible under -batch) and closed again.
options.verbose = 3;
% 'Manual' would call ginput (blocks). Auto entry point instead.
options.entrypoint = 'STN, GPi or ViM';
options.entrypointn = 1;

%% Atlas / space: template space, no patient-specific atlases
options.atl.genpt = 0;
options.atl.can = 1;
options.atl.pt = 0;
options.atl.ptnative = 0;
options.native = 0;
options.atlasset = 'DISTAL Minimal (Ewert 2017)';

%% Visualization and export: off (no rendering, no server export)
options.d2.write = 0;
options.d2.atlasopacity = 0.15;
options.d3.write = 0;
options.d3.prolong_electrode = 2;
options.d3.verbose = 'off';
options.d3.elrendering = 1;
options.d3.exportBB = 0;
options.d3.hlactivecontacts = 0;
options.d3.showactivecontacts = 1;
options.d3.showpassivecontacts = 1;
options.d3.showisovolume = 0;
options.d3.isovscloud = 0;
options.d3.mirrorsides = 0;
options.d3.autoserver = 0;  % else ea_run shows a questdlg
options.d3.expdf = 0;
options.d3.writeatlases = 0;
options.writeoutpm = 0;
options.expstatvat.do = 0;
options.fiberthresh = 10;
options.writeoutstats = 1;
options.colormap = 'parula(64)';

%% Optional modules: off
options.dolc = 0;
options.ecog.extractsurface.do = 0;

%% Recipe tag for provenance
options.headless.recipe = 'preprocessing_v2';
options.headless.methods = RECIPE;

% Fill any remaining defaults without overriding the fields above.
options = ea_defaultoptions(options);
