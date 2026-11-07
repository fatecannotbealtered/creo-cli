---
id: creo-sketches
title: How to write a sketch for extrude create and revolve create
kind: guide
applies_to: [extrude create, revolve create]
tags: [sketch, modeling]
---
`--sketch` is a JSON object; every length key ends in `_mm`.

- `plane`: the sketch plane. A datum such as `TOP`, a face of an earlier feature such as `BASE/end` (its end face), `BASE/start` or `BASE/side[+x]` (its side face facing +x), or `surface:<id>` from `geometry list`.
- `x_axis`: the model axis the sketch's x runs along, such as `+x`; it must lie in the plane. The sketch's y is the plane's normal crossed with x: on `TOP` with `x_axis` `+x`, y runs along -z. Coordinates are measured from the model origin projected onto the plane.
- `references`: datum planes or planar faces across the sketch plane, such as `RIGHT` and `FRONT`. Only listed references can be constrained or dimensioned to.
- `entities`: each with an `id`. Profiles: `rectangle` (`width_mm` along x, `height_mm` along y, optional `corner_radius_mm`) and `circle` (`diameter_mm`). Raw entities: `line` (`start_mm`, `end_mm`), `arc` (`center_mm`, `radius_mm`, `start_deg`, `end_deg`, counterclockwise), `centerline`, `point` (`at_mm`), and `axis` (`start_mm`, `end_mm`), the one line a revolve turns about. An axis is infinite: fix it with `vertical` or `horizontal` and one point `on` a reference; two points on the same reference leave its angle open. A rectangle's sides are `id.left`, `id.right`, `id.top`, `id.bottom`; its rounded corners `id.c1` to `id.c4`.
- `constraints`: `symmetric` (a profile about a reference: `{"type": "symmetric", "entity": "body", "about": "RIGHT"}`; or two points `a` and `b` about a reference or centerline; mirroring one profile's center such as `b1.center` places and fixes the other's), `horizontal`, `vertical`, `coincident` (`a`, `b` points such as `line1.end`), `on` (`point` on `entity`), `tangent`, `parallel`, `perpendicular`, `equal` (two lines of the same length, or two circles of the same size: a diameter on one fixes both).
- `dimensions`: `{"name": "BODY_LENGTH", "measure": "body.width"}` for an entity's own size (`width`, `height`, `corner_radius`, `diameter`, `radius`, `length`), or `{"name": "SOCKET_X", "from": "RIGHT", "to": "socket.center", "value_mm": -102}` for a distance; the sign of `value_mm` says on which side of `from` along the sketch axis. A name goes into Creo, so `dimension update --id SOCKET_X` changes it later; without one Creo names it, such as d12.

The sketch must be fully defined: every position and size fixed by a constraint or a named or unnamed dimension. Creo's intent manager would otherwise add weak dimensions that move unpredictably when another dimension changes. The preview lists what is missing for rectangles and circles (`blocked_by`, such as "nothing fixes its x position"); for raw entities Creo finds it when the call is applied, the call is refused with the dimensions Creo needed, and the model is left as it was.

The extrude goes along `--direction`, a model axis across the sketch plane, by default along the plane's normal; the result reports the bounding box, so check it. The box is Creo's outline of the part: around curved faces, such as rounds on drafted walls, it can be a few hundredths of a millimetre larger than the part, so measure an exact size with `distance get`. A cut (`--remove`) that would remove nothing, or an extrude that would add nothing, is refused and taken back. Faces of a feature can be named afterwards by their place: `BASE/start` lies on its sketch plane, `BASE/end` is the far face, `BASE/side` the rest; a filter such as `[+x]` keeps the faces whose normal points that way. When several faces match, the call is refused with `E_AMBIGUOUS` and the candidates' surface IDs.
