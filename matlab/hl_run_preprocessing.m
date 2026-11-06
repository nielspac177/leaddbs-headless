function hl_run_preprocessing(datasetDir, subjId, jobDir, dryRun, elmodel)
% Entry point for `matlab -batch`. Runs the validated preprocessing recipe
% (see ea_headless_options.m) for one subject, without any GUI.
%
% Writes into jobDir:
%   options.json  - the exact options struct used (hashed for provenance)
%   summary.json  - derived results only (step flags, MNI contact coords)
%
% dryRun = true builds and saves the options but does not call ea_run.

if nargin < 4
    dryRun = false;
end
if nargin < 5
    elmodel = 'Medtronic 3389';
end

hl_setpath;
ea_mkdir(jobDir);

options = ea_headless_options(datasetDir, subjId, 'elmodel', elmodel);

% ea_run adds prefs itself; store them here so the hash covers them too.
optsToSave = options;
optsToSave.prefs = ea_prefs('');
hl_writejson(fullfile(jobDir, 'options.json'), optsToSave);

summary = struct('recipe', options.headless.recipe, 'dryRun', dryRun, ...
    'status', 'options_built');

if ~dryRun
    ea_run('run', options);
    summary.status = 'pipeline_returned';
end

summary.steps = hl_stepflags(datasetDir, subjId, options);
summary.recon_check = struct('status', 'not_run', 'reasons', {{}});
if ~dryRun
    summary.recon_check = hl_check_reconstruction(datasetDir, subjId, options);
end
% File presence is not success: this flag needs the check to pass.
summary.steps.reconstruction = ismember(summary.recon_check.status, {'pass', 'human_approved'});
summary.contacts_mni = hl_contacts_mni(datasetDir, subjId, options);
hl_writejson(fullfile(jobDir, 'summary.json'), summary);
end


function hl_setpath
% Put Lead-DBS on the path WITHOUT ea_setpath, because ea_setpath calls
% savepath and would change the user's saved MATLAB path.
if ~isempty(which('ea_autocoord'))
    return
end
leaddbsRoot = fileparts(fileparts(fileparts(mfilename('fullpath'))));
addpath(leaddbsRoot);
excl = {'ext_libs', 'release', 'headless'};
d = dir(leaddbsRoot);
d = d([d.isdir] & ~startsWith({d.name}, '.') & ~ismember({d.name}, excl));
for i = 1:numel(d)
    addpath(genpath(fullfile(leaddbsRoot, d(i).name)));
end
extDir = fullfile(leaddbsRoot, 'ext_libs');
addpath(extDir);
d = dir(extDir);
d = d([d.isdir] & ~startsWith({d.name}, {'.', '@', 'mambaforge', 'SlicerNetstim', 'SlicerForLeadDBS'}));
for i = 1:numel(d)
    addpath(genpath(fullfile(extDir, d(i).name)));
end
addpath(fullfile(leaddbsRoot, 'headless'));
if isempty(which('spm'))
    error('hl:spm', 'SPM12 is not on the MATLAB path. Add it to your saved path first.');
end
end


function steps = hl_stepflags(datasetDir, subjId, options)
% Which pipeline outputs exist (file presence only, no image content).
steps = struct('coreg', false, 'normalization', false, ...
    'brainshift', false, 'reconstruction', false);
try
    bids = BIDSFetcher(datasetDir);
    subj = bids.getSubj(subjId, options.modality);
    % Recursive: the images are in coregistration/anat. The first character
    % class skips the macOS ._ files that exFAT creates.
    steps.coreg = ~isempty(ea_regexpdir(subj.coregDir, '^[^./][^/]*\.nii(\.gz)?$', 1));
    steps.normalization = ~isempty(ea_regexpdir(subj.normDir, '^[^./][^/]*\.(nii(\.gz)?|h5|mat)$', 1));
    steps.brainshift = isfield(subj, 'brainshift') && isfile(subj.brainshift.anat.scrf);
catch ME
    steps.error = ME.identifier;
end
end


function r = hl_check_reconstruction(datasetDir, subjId, options)
try
    bids = BIDSFetcher(datasetDir);
    subj = bids.getSubj(subjId, options.modality);
    ctFile = '';
    if isfield(subj.coreg.anat.postop, 'CT')
        ctFile = subj.coreg.anat.postop.CT;
    end
    r = hl_recon_check(subj.recon.recon, ctFile, options.elmodel, options.sides);
catch ME
    r = struct('status', 'fail', 'reasons', {{['check_error:', ME.identifier]}});
end
end


function c = hl_contacts_mni(datasetDir, subjId, options)
% Derived, non-identifying result: contact coordinates in MNI space.
c = struct();
try
    bids = BIDSFetcher(datasetDir);
    subj = bids.getSubj(subjId, options.modality);
    if ~isfile(subj.recon.recon)
        return
    end
    s = load(subj.recon.recon, 'reco');
    c.elmodel = s.reco.props(1).elmodel;
    for side = options.sides
        if numel(s.reco.mni.coords_mm) >= side && ~isempty(s.reco.mni.coords_mm{side})
            c.(sprintf('side%d', side)) = round(s.reco.mni.coords_mm{side}, 2);
        end
    end
catch ME
    c.error = ME.identifier;
end
end


function hl_writejson(file, s)
fid = fopen(file, 'w');
fprintf(fid, '%s', jsonencode(s, 'PrettyPrint', true));
fclose(fid);
end
