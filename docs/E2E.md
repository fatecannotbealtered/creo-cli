# Live Acceptance

English | [中文](E2E_zh.md)

Live runs execute the behavior matrices of creo-cli on the real Creo Parametric, with the real adapter. They make real changes, so they use only the targets a person has authorized below.

## Authorized Targets

This section is the only list of the Creo Parametric instances, files, folders and devices that live runs may use. Only a person adds a target to it, or a coding Agent the person explicitly asks to in their own message, once the person agrees to the target it showed. Each target is one list item that starts with the target in backticks, written the way the scope file writes targets: a `file://` URL of a file or folder, or `device:<id>` for a device, followed by a colon and a description of the target. An instance of Creo Parametric has no lasting ID, so live runs use only instances a person started for the run, with documents from the files and folders listed here. Live runs use no other target, and the scope file for live runs grants only the targets listed here.

- `file:///D:/driver-work/creo-cli/targets/`: practice models made for creo-cli's live tests (disc.prt, plate.prt, pair.asm, disc.drw), and the folder exports and renders go to.
- `file:///D:/driver-work/creo-cli/evals/`: the folder for the evaluation workspaces.

## Procedure

Live runs are made on these machines:

One Windows 11 x64 computer with Creo Parametric 13.4.1.0, its Object TOOLKIT Java and a JDK 25, in session mode. Live runs use their own state directory (`CREO_CLI_STATE_DIR`). Before the first run, `creo-cli plugin install` is run with that state directory, the person adds `toolkit_registry_file <install_path>\protk.dat`, with the `install_path` that `creo-cli plugin get` shows, to the `config.pro` of the Creo started for the run, and then starts Creo; `creo-cli session list` must show `plugin_loaded`. Live runs set `LOCALAPPDATA` for creo-cli to a folder of their own, so that the host component they install, and the `plugin install` and `plugin remove` rows, leave the person's own copy alone. Those rows use a second state directory, whose host component no running Creo has loaded: Windows keeps a loaded JAR open, so it could not be removed. The `read_back_mismatch` rows change the result through `--tamper`: a script that sets the dimension, parameter or feature name again through the host component, closes or opens the model again, or deletes the file the write made or the version file the save wrote.

To run a behavior matrix on the real Creo Parametric:

1. A person prepares the targets, such as a copy of a project made for testing, an instance started for the run or a device set up for testing, and lists them under Authorized Targets.
2. A person writes a scope file, or explicitly asks the coding Agent to, that grants only those targets, with the effects the commands under test need, and points `CREO_CLI_SCOPE_FILE` at it. Set `CREO_CLI_STATE_DIR` to a separate directory for live runs.
3. Run `python scripts/spec.py matrix --command "<path>" --set <placeholder>=<value>`, with one `--set` for each placeholder the matrix uses, named without braces, such as `--set doc=<file>`: `{session}` takes an authorized instance, `{doc}` an authorized document or file, `{device}` an authorized device, and `{dir}` a new empty directory inside an authorized folder. `{job}` takes a job ID; without it, the runner first runs the `normal` row of the long command that `--job-from` names, or of the only long command, and uses the job it starts. `{inputs}` needs no `--set`: it is `tests/inputs/`, whose files commands only read, so they need no authorization.
4. The runner runs the rows that apply, writes a live record to `docs/evidence/` and fills in the actual result and the `live:` evidence reference of each row. A row whose actual result differs from the expected one has failed.
5. A row that cannot be caused on demand on the real Creo Parametric, such as `disconnect`, may be marked `unrunnable` with the reason; the `normal`, `dialog` and `read_back_mismatch` rows never may. For `read_back_mismatch`, run the matrix with `--row read_back_mismatch`: the tool waits before its read-back, and in that time change what it just wrote in Creo Parametric, or delete the file it made.
6. Run `python scripts/spec.py generate` to update the support matrix and the index below, then commit the records with the matrices.

To run the evaluation questions on the real Creo Parametric, a person lists a folder for the evaluation workspaces under Authorized Targets, together with any other target a question's `SCOPE` names, such as a device. Then run `python scripts/spec.py eval --workspace-root <folder>`. The runner writes each question's scope file itself, granting only the question's documents and the targets its `SCOPE` names, and writes the evaluation report to `docs/evidence/`.

A live record counts as evidence only while its tool version has the same major and minor version as creo-cli. Records never hold secrets, and arguments that carry secrets show as `***`.

## Evidence Records

The live records in `docs/evidence/`, generated by `python scripts/spec.py generate`:

<!-- driver:evidence:start -->
No live record yet.
<!-- driver:evidence:end -->
