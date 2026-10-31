# Staged synthetic sleeve

Use the supplied candidate and explicitly authorized owned workspace. Check `reference`
for each command, the loaded `revolved_datum_readback: 1` capability, scope and shared
operation history. Read [the full recipe](../../../docs/REVOLVED-PART.md).

The intended mm sleeve has OD 20, ID 8 and length 25 along model Y, with axis x=0,z=3.
The default mm part's FRONT/RIGHT/TOP geometry must be independently verified first.
Do not use these names on a different template without reading its actual geometry.

1. Create an empty owned mm part through `part create`, with its own preview/confirmation.
2. Preview/confirm `feature datum-plane --model <actual-part> --request plane.json`.
   Read its actual position, normal and offset constraint before continuing.
3. Preview/confirm `feature datum-axis --model <actual-part> --request axis.json`.
   Read its actual intersection line and references.
4. Preview/confirm `feature revolve --model <actual-part> --request revolve.json`.
   Verify the sketch origin is (0,0,3), its axes are model +X/+Y, and its centerline is
   collinear with SLEEVE_AXIS. This example uses a **sketched centerline** to obtain
   native driving diameters; it does not pretend the named datum axis is a feature parent.
5. Discover actual diameter and length dimension IDs and inspect the current solid.
   Expected nominal volume is 2100π mm³ and
   bounds are (-10,0,-7)..(10,25,13) mm; check complete walls/rims, not volume alone.
6. Apply only explicit test material/tolerances as needed. Create the associated drawing
   with readable native diameter/length annotations, checking planned regions first.
   Change the driving length 25→28→25, regenerate/update the drawing at each state, and
   independently check geometry, unchanged properties and linked annotation values/layout.
7. Save both part and drawing, close all owned related models, and reopen the exact saved
   versions. Verify the model/drawing association and properties, then demonstrate continued
   editing with one more legal change/restore. Update the drawing, recheck and save both.
8. Export STEP/PDF from that same restored state. Independently consume STEP and actually
   inspect every rendered PDF page as the recipe specifies.

These are three separately confirmed leaf requests. They do not form a creating workflow.
Tokens, model/feature/dimension IDs and saved version paths must come from the actual run.
The numerical comparisons are engineering test checks, not manufacturing tolerances or signoff.
