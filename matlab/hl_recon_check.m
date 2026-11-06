function r = hl_recon_check(reconFile, ctFile, elmodel, sides)
% Sanity check of an electrode reconstruction against the post-op CT.
%
% A run can exit 0 and write plausible coordinates that are not on the
% electrodes. This check fails such a result. It has two tests per side:
%   1. Every contact has metal-level CT signal within SEARCH_RADIUS_MM.
%   2. The first-to-last contact length matches the electrode model.
%
% A pass does NOT validate a localization: a human must still review it.
% The thresholds are heuristics, not validated limits.
%
% Output r has only derived values (no paths, IDs, or image data):
%   r.status  - 'pass', 'fail', or 'human_approved'
%   r.reasons - cell of reason codes (empty on pass)
%   r.sides   - per-side measurements

SEARCH_RADIUS_MM = 2;    % allows for normal localization error
METAL_PERCENTILE = 99;   % of positive CT voxels; scale-free across scanners
LENGTH_TOLERANCE = 0.15; % fraction of the model's first-to-last contact length

r = struct('status', 'fail', 'reasons', {{}}, 'sides', struct([]));
try
    if ~isfile(reconFile)
        r.reasons = {'no_reconstruction'};
        return
    end
    if ~isfile(ctFile)
        r.reasons = {'no_coregistered_ct'};
        return
    end
    s = load(reconFile, 'reco');
    if hl_all_corrected(s.reco, sides)
        r.status = 'human_approved'; % a person placed these contacts
        return
    end
    if ~isfield(s.reco, 'native')
        r.reasons = {'no_native_coordinates'};
        return
    end

    expected = hl_model_length(elmodel);
    V = spm_vol(ctFile);
    Y = spm_read_vols(V);
    metal = prctile(Y(Y > 0), METAL_PERCENTILE);
    offsets = hl_sphere(SEARCH_RADIUS_MM);

    reasons = {};
    for i = 1:numel(sides)
        side = sides(i);
        coords = s.reco.native.coords_mm{side};

        peaks = zeros(size(coords, 1), 1);
        for k = 1:size(coords, 1)
            peaks(k) = hl_local_max(V, coords(k, :), offsets);
        end
        % Use the contacts, not the markers: the bad TRAC/CORE run had
        % head-to-tail markers of 9 mm with contacts that spanned less.
        len = norm(coords(1, :) - coords(end, :));

        onMetal = all(peaks >= metal);
        lengthOk = abs(len - expected) <= LENGTH_TOLERANCE * expected;
        if ~onMetal
            reasons{end+1} = sprintf('side%d_contact_not_on_metal', side); %#ok<AGROW>
        end
        if ~lengthOk
            reasons{end+1} = sprintf('side%d_length_mismatch', side); %#ok<AGROW>
        end
        r.sides(i).side = side;
        r.sides(i).weakest_contact_vs_metal = round(min(peaks) / metal, 2);
        r.sides(i).length_mm = round(len, 2);
        r.sides(i).expected_length_mm = round(expected, 2);
    end
    r.reasons = reasons;
    if isempty(reasons)
        r.status = 'pass';
    end
catch ME
    % Fail closed. Identifier only: a message can hold a path.
    r.status = 'fail';
    r.reasons = {['check_error:', ME.identifier]};
end
end


function tf = hl_all_corrected(reco, sides)
tf = isfield(reco, 'props') && numel(reco.props) >= max(sides) ...
    && isfield(reco.props, 'manually_corrected') ...
    && all(arrayfun(@(k) isequal(reco.props(k).manually_corrected, 1), sides));
end


function len = hl_model_length(elmodel)
% First-to-last contact length from the Lead-DBS electrode model file.
opts = ea_resolve_elspec(struct('elmodel', elmodel));
m = load(fullfile(ea_getearoot, 'templates', 'electrode_models', opts.elspec.matfname), 'electrode');
len = norm(m.electrode.coords_mm(1, :) - m.electrode.coords_mm(end, :));
end


function offsets = hl_sphere(radius)
% Sample points in a sphere, on a 0.5 mm grid.
g = -radius:0.5:radius;
[x, y, z] = ndgrid(g, g, g);
offsets = [x(:), y(:), z(:)];
offsets = offsets(sum(offsets.^2, 2) <= radius^2, :);
end


function peak = hl_local_max(V, point, offsets)
mm = point + offsets;
vx = V.mat \ [mm, ones(size(mm, 1), 1)]';
peak = max(spm_sample_vol(V, vx(1, :), vx(2, :), vx(3, :), 1));
end
