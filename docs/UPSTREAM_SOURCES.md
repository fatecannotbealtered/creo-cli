# Upstream interface sources

## Use and evidence

This implementation is original Python code based on publicly readable interface
specifications/examples, not a copy of a vendor CAD kernel. CREOSON is an external
execution dependency, not bundled here. Creopyson is consulted as an API reference,
not imported at runtime. Git blob identities below pin the text consulted; branch
links are convenient navigation and may later change.

The integration target is CREOSON 3.0.2, but this table does not prove that every
function has been exercised against that release or every supported Creo build.
`file.assemble`, `feature.list`, `file.get_transform`, `drawing.list_view_details`
and `dimension.list_detail` were cross-checked against release-tagged JSON
specifications; the remaining client mappings are source-snapshot evidence, not
full server conformance.

## Primary source map

| Domain | Repository/source | Consulted Git blob |
|---|---|---|
| file | [Zepmanbc/creopyson/creopyson/file.py](https://github.com/Zepmanbc/creopyson/blob/master/creopyson/file.py) | `228f71eb3fcb3a34764c4dc145686b79fffdf9b8` |
| parameter | [Zepmanbc/creopyson/creopyson/parameter.py](https://github.com/Zepmanbc/creopyson/blob/master/creopyson/parameter.py) | `cba1c8decb1c851bcea14f224b601baef4f93023` |
| dimension | [Zepmanbc/creopyson/creopyson/dimension.py](https://github.com/Zepmanbc/creopyson/blob/master/creopyson/dimension.py) | `91e4c616f23edeab574bb270510be245137c9009` |
| feature | [Zepmanbc/creopyson/creopyson/feature.py](https://github.com/Zepmanbc/creopyson/blob/master/creopyson/feature.py) | `fb2d7892d0c192bf68b700512e48ec886e3ca6e3` |
| interface | [Zepmanbc/creopyson/creopyson/interface.py](https://github.com/Zepmanbc/creopyson/blob/master/creopyson/interface.py) | `997640a896b69c0482dc0a3a1ef285a747d353c1` |
| view | [Zepmanbc/creopyson/creopyson/view.py](https://github.com/Zepmanbc/creopyson/blob/master/creopyson/view.py) | `ebdae69b795ef042f67da9f601781fa9b2b33e20` |
| drawing | [Zepmanbc/creopyson/creopyson/drawing.py](https://github.com/Zepmanbc/creopyson/blob/master/creopyson/drawing.py) | `e0ad14a5f1c5da6b261efc16efb8181432c4bf68` |
| bom | [Zepmanbc/creopyson/creopyson/bom.py](https://github.com/Zepmanbc/creopyson/blob/master/creopyson/bom.py) | `611209b7f6695bdce8f3d08bdaa4096d3bbdef54` |
| creo | [Zepmanbc/creopyson/creopyson/creo.py](https://github.com/Zepmanbc/creopyson/blob/master/creopyson/creo.py) | `678c83bdcafd67c5a838959c9080a20989c29d80` |
| connection | [Zepmanbc/creopyson/creopyson/connection.py](https://github.com/Zepmanbc/creopyson/blob/master/creopyson/connection.py) | `cc1bd8ebf59f3139d1906fda9e159e16bd78c109` |

Pinned assembly spec: [CREOSON v3.0.2 file-assemble.json](https://github.com/SimplifiedLogic/creoson/blob/v3.0.2/creoson-server/web/assets/creoson_stuff/jsonSpecs/file-assemble.json),
Git blob `cbfcdd4510e2fe0640e07790791bb288e028f39e`.
The spec's no-constraint default can prompt in the GUI; this adapter refuses that
route and requires explicit csys or fixed placement. Creo-major setup is explicit.

## Design decisions derived from source review

- Connection responses carry `sessionId` at the top level; data responses can be
  null. Neither shape is silently treated as a generic success payload.
- Published Creopyson requests omit an explicit timeout. The new transport adds
  a command deadline, bounds and no retries instead of inheriting those defaults.
- Feature suppression defaults in the client include clip/children. This adapter
  explicitly sets both false and verifies other observed features are unchanged.
- Feature resume also explicitly sets `with_children:false`.
- Image export has no separate dirname field in the referenced client. The new
  adapter joins the staged full filename, not an invented upstream parameter.
- Dimension edits require explicit length-unit expectations and model-dimension
  types; drawing and angular values are not silently coerced.
- Assembly reads can omit inactive/unregenerated objects even when some upstream
  filters are disabled. That omission is reported rather than called completeness.
- Mass properties retain unit context and never force density to 1.
- Isolated-part roundtrip composes documented save/close_window/erase/open calls;
  it does not invent a native upstream `roundtrip` method.

## Broader research, not imported dependencies

The earlier research also reviewed TOOLKIT feature-construction examples and other
Creo automation/MCP projects. None of those repositories' implementation code or
binaries are included in this increment. Arbitrary-script execution and unverified
claims of hundreds of native features are not translated into public capabilities.
Real SDK-based feature construction remains a separate implementation gap, not
something covered by the new protocol tests.

## Release-spec differences covered by regressions

The v3.0.2 `feature-list.json` examples spell a coordinate-system feature as
`COORDINATE SYSTEM`, while the request documentation also uses `COORD_SYS`.
Both documented spellings are accepted for a coordinate-system constraint.
Unnamed feature rows may omit `name`; their returned `feat_id` is preserved.
Feature lists expose visible features only, so regeneration and roundtrip checks
explicitly do not certify hidden features or complete BREP geometry.

The `dimension-list_detail.json` examples return dimension `text` as an array of
strings, not the scalar string described in the consulted Python client's prose.
The array is now typed and tested. `file-get_transform.json` includes scalar
`x_rot`, `y_rot`, `z_rot` in degrees as well as origin and axis vectors. Drawing
view results carry `text_height` and model identity. Exact source blob hashes
are in `docs/evidence/upstream-interface-sources.json`.

These are protocol-reference regressions, not recordings from a live application.

The released `JLDrawing.java` creation implementation adds
`DRAWINGCREATE_SHOW_ERROR_DIALOG`. Accordingly `drawing create` advertises
`interaction_risks` in both `reference` and the confirmation preview: an upstream
modal error may need a person, and the HTTP deadline cannot cancel the native
operation. No CLI fallback silently clicks dialogs or keeps retrying. Template
lookup (including workspace paths) and modal behavior require live compatibility
validation; a valid-looking local template file is not enough to establish either.
