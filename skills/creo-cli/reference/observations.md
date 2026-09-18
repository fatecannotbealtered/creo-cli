# Reading observations

Portable snapshots record model metadata, parameters, dimensions, feature metadata
and relation text. They do not carry complete BREP geometry or every dependency.
Native revision is a digest of these observations, not a PTC version-control stamp.

Keep the exact reported unit-system name. Only linear dimension edits are allowed;
angular, radius/diameter, relation-driven and unknown dimensions are not writable.
No automatic units conversion occurs. Check the dimension's ID, symbol and type.

Mock values exercise contracts only. A changed hole_pitch in `.creo.json` does not
create or move a physical hole. Counts and PASS-like verification concern precisely
the checks named in the result. Always report provenance and `not_checked`.
