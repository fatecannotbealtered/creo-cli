# Contributing

Read `AGENTS.md` and `.agent/AGENT.md` first; the specs there take priority.

## The CLI

Python 3.11+, standard library only at run time.

```bash
python -m pip install -e ".[dev]"
python -m pytest tests
ruff check creo_cli tests scripts && ruff format --check creo_cli tests scripts
python scripts/test.py --evidence docs/evidence/offline-tests-1.0.0.json   # the suite, recorded
```

The tests drive the real CLI against `tests/fixture.py`, a stateful loopback substitute
of the service. For every public behaviour add a command-level test: the success path,
bad arguments, and the failures that matter (refused, lost reply, changed state).

A new command is declared next to its handler in `creo_cli/commands/`, with its output
schema, its service ops and, for a write, a plan whose preview is read from Creo and
whose verifier reads the result back. The registry, `reference`, the parser and output
validation all follow from the declaration.

## The service

Java 25 (the JDK Creo 13.4 requires), a Creo with the Object TOOLKIT Java component and
licence; for the native sketch library also Visual Studio 2022 Build Tools with the C++
workload and the Creo Parametric Toolkit component.

```bash
python scripts/reload_service.py --restart   # compile, unlock, register, restart Creo
python scripts/service_call.py '{"op": "session.status"}'
```

The reload refuses while models are open (a restart loses unsaved work) unless given
`--force`. A new op goes into `Ops.java` under the name of the command that calls it,
reads back what it did, and reports the reading. Element ids and values come from
`Ptc.java` under PTC's names, never as literals.

## Live evidence

A command is not `live_verified` until `scripts/record_live.py` has run it on a real
Creo (`docs/E2E.md`). Add its scenario there, run the recorder on a disposable
workspace, then add the command to `registry.LIVE_VERIFIED`; `tests/test_contract.py`
holds the mark to the record.

## Versions and specs

`package.json` is the version source: `node scripts/sync-version.js` propagates it and
`node scripts/check-version.js` verifies. `node scripts/sync-spec.js` re-vendors the fleet
spec and `node scripts/check-spec.js` verifies it. Record user-visible changes in
`CHANGELOG.md` and keep `README.md` and `README_zh.md` aligned.

Never commit CAD models, the unlocked service binaries, tokens, keys or the state
database.

## Releasing

The owner reviews the release candidate, tags it and pushes the tag.

1. On the licensed machine, on the release candidate: `python scripts/reload_service.py
   --restart`, then the live record (`docs/E2E.md`) and
   `python scripts/test.py --evidence docs/evidence/offline-tests-<version>.json`. Both
   records carry the fingerprint of the tree they ran on; a later edit makes them stale.
2. `python scripts/build_bundle.py --output dist --creo-build <build>` packs the unlocked
   jar and DLL as `dist/creo-cli-service-<version>.zip`.
3. Tag `v<version>` and push the tag. The release workflow tests, builds the Windows
   binary, signs the checksums, publishes the GitHub release and the npm packages.
4. Attach the bundle to that release: `gh release upload v<version>
   dist/creo-cli-service-<version>.zip`. The workflow cannot build it, because unlocking
   needs the TOOLKIT licence, and users install it from the release page.
