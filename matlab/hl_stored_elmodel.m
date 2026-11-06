function hl_stored_elmodel(prefsFile, outFile)
% Write the electrode model saved for one patient to outFile.
% MATLAB reads it because a uiprefs file can be any .mat version.
% If the field is missing, MATLAB exits with an error, and the server refuses the run.

s = load(prefsFile, 'elmodel');
fid = fopen(outFile, 'w');
fprintf(fid, '%s', char(s.elmodel));
fclose(fid);
end
