# Compatibility and evidence

| Surface | Evidence | Claim |
|---|---|---|
| Portable Python source CLI | See `evidence/offline-tests.json` for exact interpreter/platform/time | Tested only in the recorded runtime |
| Mock observations and changes | Command-boundary and persistence tests | Simulation data handling, not native CAD |
| Native protocol | Subprocess/error-shape substitutes and private worker rejection tests | Protocol/failure behavior under controlled substitutes |
| Native PTC object model | Interface-shaped fake objects | Not installed SDK validation |
| Windows / installed Creo / licensing | No live run recorded | Unverified |
| Other Creo versions and language installations | No live matrix recorded | Unverified |
| Linux/macOS native automation | Not supported by this VB API worker | Portable/offline commands only |
| npm package / frozen executable / release signing | Not published or built | Not available |
| GitHub Actions matrix | Workflow definitions supplied; no remote run here | Proposed, not verified |
| Full spec conformance | Target v1.6.2, remaining work in SPEC_STATUS | Unpublishable |

Do not infer universal CAD compatibility from a Python version or a successful
metadata probe. The package's Python >=3.11 declaration is a target range; only
the exact runtime in the evidence has actually run here. Proposed CI expansion
does not turn untested platforms into tested ones.

## CREOSON route in 0.2.0

| Layer | Implemented/tested evidence | Not established |
|---|---|---|
| Client protocol | Published CREOSON/Creopyson fields; real loopback HTTP requests against independent stateful substitutes | Compatibility with actual CREOSON/Java/PTC runtime |
| Runtime | Python 3.13 on the recorded Linux host | Windows/macOS execution of this release |
| Request target | CREOSON 3.0.2-oriented interfaces; exact source blobs listed in UPSTREAM_SOURCES.md | Every function/version/license combination |
| Creo version | Explicit user declaration passed to `creo.set_creo_version` | Auto-detection or product licensing |
| Drawing/assembly | Named template/view and csys/fixed placement request mappings | Actual dimensions, solved orientation, degrees of freedom and interference |
| Save/reopen | Composed code and substitute-backed persistence comparisons | Genuine native BREP/model roundtrip |
| Export | Isolated staging, byte/header check and no-clobber publication | Actual native file correctness/renderability |

Source-backed implementation is not "verified version support." The tests do
not import PTC and the fixture files are not valid CAD files. No instruction here
waives the need for a disposable real-application run before reliance.
