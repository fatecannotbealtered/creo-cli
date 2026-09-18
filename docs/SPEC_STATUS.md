# Spec status — no silent fork

Target: `fatecannotbealtered/ai-native-cli-spec@v1.6.2`.
Immutable commit: `abbebfdf03dbfa28d1378b2fe3dd55ac34b22981`.
Annotated tag object: `508b3022984547d780d5cab823cf05839d19e9d8`.

The source snapshot records the intended pin but **does not claim that the full
normative spec suite is vendored or that conformance has passed**. The container
could read GitHub through its connector, but direct archive/raw downloads and
remote write tooling were unavailable during this build. See recorded preflight.
The small `contract/bootstrap.json` is explicitly noncanonical; it does not replace
the upstream `contract/contract.json`.

Acquire exact sources from the immutable commit:

```bash
python scripts/bootstrap_spec.py
# Or use a local Git clone containing the pinned commit, without network:
python scripts/bootstrap_spec.py --from /path/to/ai-native-cli-spec
python scripts/bootstrap_spec.py --check
```

The script copies the 13 paths in the upstream spec registry, verifies Git blob
identities and writes the lock last. It does not use edited working-tree versions
from a local clone. Acquisition alone is not conformance: integrate the upstream
`gen-contract.js` runtime output, run the upstream spec/codegen guard and then
review the whole public contract against the pinned source. Do not edit normative
files to make the local implementation appear compliant.

## Known remaining gates

1. Exact normative files and generated canonical runtime module must be integrated.
2. Audit all public commands/flags/errors/schemas, not just leaf dispatch coverage.
3. Run a formatter/linter and dependency audit; compilation is not linting.
4. Validate Skill behavior across representative agent tasks/models; stored prompts
   alone are not executed evaluations.
5. Record real SDK and disposable-part live evidence, including persistence/reopen
   before claiming that capability is live-verified. The 0.2.0 CREOSON route has
   implemented disk-version backups and guarded save/reopen request sequences;
   these have only been exercised against a stateful HTTP substitute.
6. Build/install/release provenance must be tested before distributing binaries/npm.

`reference.release_readiness` stays unpublishable. The release workflow and
`prepublishOnly` fail closed; changing a status constant alone is not enough.
The stronger fail-closed consumed-token ledger policy is documented in ADR 0001,
not represented as an upstream rule that was never written.
