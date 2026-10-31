# Parameter-driven mounting plate

This example uses the editable plate request in `plate.json`, explicit mm units, and
a user-authorized disposable workspace/scope. Discover schemas with `reference`.
Each write below requires its own dry-run and confirmation; `workflow run` still uses
the legacy lifecycle.

1. Create and extrude the native plate. Change its width to 72 mm, then independently
   read `dimension list` and retain the actual sketch width dimension's **name**.
2. `parameter set --model <part.prt> --name PLATE_LENGTH --type real --value 72 --create`.
   Create a relation request `{"relations":["<actual width dimension name> = PLATE_LENGTH"]}`
   and apply it with `relation set`. Never assume the dimension is named `d4`.
3. Set PLATE_LENGTH to 80; `model regenerate`; read parameters, relations, dimensions,
   feature flags and volume. Update the associated drawing and read its edge-to-hole
   reference dimension. Set the parameter back to 72 and regenerate.
4. Create a diameter 10 mm circular boss centered at (0,10), with symmetric total
   extrusion depth 4 mm. Rename its actual feature ID to MOUNT_BOSS. Suppress and resume
   that same ID; independently check status and the volume difference `π × 25 × 2` mm³.
5. Save both native part and drawing, close and reopen only these owned models. Repeat
   the parameter change/readback to prove the relation and feature remain editable.

The complete recorded harness is `scripts/run_parameter_feature_case.py`. Its plate
volume tolerance is 0.05 mm³ and dimension tolerance is 0.001 mm. It also refuses a
stale parameter preview after a newer change. See `docs/ENGINEERING-WORKFLOW.md` for
the drawing association, PDF review, unknown-operation recovery and capability limits.
