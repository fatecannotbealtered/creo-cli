# Bounded stepped sleeve

These are three **separate leaf requests**, not a creating workflow or a script to replay.
Use the public EXE and [construction recipe](../../../docs/REVOLVED-PART.md). Create a new owned
empty mm part, inspect its real datums and preserve the first-version/persistence receipt.

The frozen model-space intent is a line parallel to Y at x=0,z=-4, full 360 degrees, Y=0..30,
outer radius 12 over Y=0..12 and radius 8 over Y=12..30, and a continuous radius 3 bore.
Expected volume is 2610π mm³; bounds are [-12,0,-16]..[12,30,8]. Sketch coordinates use +X/+Y
on the negative offset plane. Numeric comparisons are not manufacturing tolerances.

1. Preview/confirm `feature datum-plane` with `plane.json` on the explicit model. Independently
   read its signed position, normal and constraint; then resolve its actual name/identity.
2. Preview/confirm `feature datum-axis` with `axis.json`. Independently read the full infinite
   line and both references. Display endpoints are not a finite engineering axis length.
3. Preview/confirm `feature revolve` with `revolve.json`. Require actual section placement,
   external-axis reference, complete native surface/rim proof, volume and boundaries.
4. Discover driving dimension IDs from this model. In the recorded example, radial sketch
   dimensions were linear distances; they are not driving diameters. Freeze a legal axial
   edit and expected geometry changes before confirming it.
5. Apply an explicitly synthetic material and supported numeric tolerance using the
   [property recipe](../../../docs/ENGINEERING-PROPERTIES.md). Independently check density units,
   mass, deviations and unrelated geometry. Unknown author/approver fields stay blank.
6. Create an associated drawing before the dimension roundtrip. Plan annotation regions,
   inspect preview feedback and actual post-move bounds, preserve REF where used, and check
   association after edits. Incomplete bounds require inspection without repeating the move.
7. Save both, close the drawing and every owned related model, reopen from the saved files,
   and demonstrate another explicit edit/restoration. Export STEP/PDF from the final state.
   Independently check STEP geometry/units and render/view every PDF page. STEP does not
   prove material, tolerances or native editability; readable pages are not manufacturing signoff.

The recorded drawing includes a static REF note with diameter equivalents. It was checked
against the frozen radii; automatic note updates after changing radii are outside this case.
Dynamic section-caption editing was refused natively. Its failure was preserved; a separate
dimension move supplied the tested layout correction.

Use the same request bytes, file identity, scope and target for each preview/confirmation pair.
Keep its operation ID. A lost reply, stale input or partial result is inspected and explicitly
registered before any remaining actions; creating again is not recovery. See
[round16 evidence](https://github.com/fatecannotbealtered/creo-cli/blob/6d93cf09f74c107ae80970838e136ce69ce328a2/docs/evidence/round16-20261013/README.md) for measured coverage.
