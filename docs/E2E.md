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
| Record | Recorded at | Application | Platform | Result |
|---|---|---|---|---|
| [2026-11-06-163428-component-list.json](evidence/2026-11-06-163428-component-list.json) | 2026-11-06T16:34:28Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-163253-session-list.json](evidence/2026-11-06-163253-session-list.json) | 2026-11-06T16:32:53Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-163248-session-get.json](evidence/2026-11-06-163248-session-get.json) | 2026-11-06T16:32:48Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-163246-relation-list.json](evidence/2026-11-06-163246-relation-list.json) | 2026-11-06T16:32:46Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-163245-parameter-update.json](evidence/2026-11-06-163245-parameter-update.json) | 2026-11-06T16:32:45Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-163243-parameter-list.json](evidence/2026-11-06-163243-parameter-list.json) | 2026-11-06T16:32:43Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-163242-model-render.json](evidence/2026-11-06-163242-model-render.json) | 2026-11-06T16:32:42Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-163240-model-get.json](evidence/2026-11-06-163240-model-get.json) | 2026-11-06T16:32:40Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-163239-model-export.json](evidence/2026-11-06-163239-model-export.json) | 2026-11-06T16:32:39Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-163238-material-list.json](evidence/2026-11-06-163238-material-list.json) | 2026-11-06T16:32:38Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-163237-geometry-list.json](evidence/2026-11-06-163237-geometry-list.json) | 2026-11-06T16:32:37Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-163236-feature-update.json](evidence/2026-11-06-163236-feature-update.json) | 2026-11-06T16:32:36Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-163235-feature-list.json](evidence/2026-11-06-163235-feature-list.json) | 2026-11-06T16:32:35Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-163233-feature-get.json](evidence/2026-11-06-163233-feature-get.json) | 2026-11-06T16:32:33Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-163232-doc-save.json](evidence/2026-11-06-163232-doc-save.json) | 2026-11-06T16:32:32Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-163231-doc-open.json](evidence/2026-11-06-163231-doc-open.json) | 2026-11-06T16:32:31Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-163230-doc-get.json](evidence/2026-11-06-163230-doc-get.json) | 2026-11-06T16:32:30Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-163229-doc-close.json](evidence/2026-11-06-163229-doc-close.json) | 2026-11-06T16:32:29Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-163227-distance-get.json](evidence/2026-11-06-163227-distance-get.json) | 2026-11-06T16:32:27Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-163226-dimension-update.json](evidence/2026-11-06-163226-dimension-update.json) | 2026-11-06T16:32:26Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-163224-dimension-list.json](evidence/2026-11-06-163224-dimension-list.json) | 2026-11-06T16:32:24Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-163159-relation-list.json](evidence/2026-11-06-163159-relation-list.json) | 2026-11-06T16:31:59Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-163158-parameter-update.json](evidence/2026-11-06-163158-parameter-update.json) | 2026-11-06T16:31:58Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-163157-parameter-list.json](evidence/2026-11-06-163157-parameter-list.json) | 2026-11-06T16:31:57Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-163156-model-render.json](evidence/2026-11-06-163156-model-render.json) | 2026-11-06T16:31:56Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-163154-model-get.json](evidence/2026-11-06-163154-model-get.json) | 2026-11-06T16:31:54Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-163153-model-export.json](evidence/2026-11-06-163153-model-export.json) | 2026-11-06T16:31:53Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-163152-material-list.json](evidence/2026-11-06-163152-material-list.json) | 2026-11-06T16:31:52Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-163151-geometry-list.json](evidence/2026-11-06-163151-geometry-list.json) | 2026-11-06T16:31:51Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-163150-feature-update.json](evidence/2026-11-06-163150-feature-update.json) | 2026-11-06T16:31:50Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-163148-feature-list.json](evidence/2026-11-06-163148-feature-list.json) | 2026-11-06T16:31:48Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-163147-feature-get.json](evidence/2026-11-06-163147-feature-get.json) | 2026-11-06T16:31:47Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-163146-doc-save.json](evidence/2026-11-06-163146-doc-save.json) | 2026-11-06T16:31:46Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-163145-doc-open.json](evidence/2026-11-06-163145-doc-open.json) | 2026-11-06T16:31:45Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-163144-doc-close.json](evidence/2026-11-06-163144-doc-close.json) | 2026-11-06T16:31:44Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-163142-distance-get.json](evidence/2026-11-06-163142-distance-get.json) | 2026-11-06T16:31:42Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-163141-dimension-update.json](evidence/2026-11-06-163141-dimension-update.json) | 2026-11-06T16:31:41Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-163140-dimension-list.json](evidence/2026-11-06-163140-dimension-list.json) | 2026-11-06T16:31:40Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-163139-component-list.json](evidence/2026-11-06-163139-component-list.json) | 2026-11-06T16:31:39Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-163137-relation-list.json](evidence/2026-11-06-163137-relation-list.json) | 2026-11-06T16:31:37Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-163135-parameter-update.json](evidence/2026-11-06-163135-parameter-update.json) | 2026-11-06T16:31:35Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-163132-parameter-list.json](evidence/2026-11-06-163132-parameter-list.json) | 2026-11-06T16:31:32Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-163130-model-render.json](evidence/2026-11-06-163130-model-render.json) | 2026-11-06T16:31:30Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-163128-model-get.json](evidence/2026-11-06-163128-model-get.json) | 2026-11-06T16:31:28Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-163125-model-export.json](evidence/2026-11-06-163125-model-export.json) | 2026-11-06T16:31:25Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-163123-material-list.json](evidence/2026-11-06-163123-material-list.json) | 2026-11-06T16:31:23Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-163120-geometry-list.json](evidence/2026-11-06-163120-geometry-list.json) | 2026-11-06T16:31:20Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-163117-feature-update.json](evidence/2026-11-06-163117-feature-update.json) | 2026-11-06T16:31:17Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-163115-feature-list.json](evidence/2026-11-06-163115-feature-list.json) | 2026-11-06T16:31:15Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-163112-feature-get.json](evidence/2026-11-06-163112-feature-get.json) | 2026-11-06T16:31:12Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-163109-doc-save.json](evidence/2026-11-06-163109-doc-save.json) | 2026-11-06T16:31:09Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-163107-doc-open.json](evidence/2026-11-06-163107-doc-open.json) | 2026-11-06T16:31:07Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-163104-doc-close.json](evidence/2026-11-06-163104-doc-close.json) | 2026-11-06T16:31:04Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-163101-distance-get.json](evidence/2026-11-06-163101-distance-get.json) | 2026-11-06T16:31:01Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-163059-dimension-update.json](evidence/2026-11-06-163059-dimension-update.json) | 2026-11-06T16:30:59Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-163056-dimension-list.json](evidence/2026-11-06-163056-dimension-list.json) | 2026-11-06T16:30:56Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-163054-component-list.json](evidence/2026-11-06-163054-component-list.json) | 2026-11-06T16:30:54Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-163049-component-list.json](evidence/2026-11-06-163049-component-list.json) | 2026-11-06T16:30:49Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-163047-doc-save.json](evidence/2026-11-06-163047-doc-save.json) | 2026-11-06T16:30:47Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-163039-feature-update.json](evidence/2026-11-06-163039-feature-update.json) | 2026-11-06T16:30:39Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-163036-parameter-update.json](evidence/2026-11-06-163036-parameter-update.json) | 2026-11-06T16:30:36Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-163032-dimension-update.json](evidence/2026-11-06-163032-dimension-update.json) | 2026-11-06T16:30:32Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-163029-model-render.json](evidence/2026-11-06-163029-model-render.json) | 2026-11-06T16:30:29Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-163028-model-export.json](evidence/2026-11-06-163028-model-export.json) | 2026-11-06T16:30:28Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-163027-doc-close.json](evidence/2026-11-06-163027-doc-close.json) | 2026-11-06T16:30:27Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-163025-doc-open.json](evidence/2026-11-06-163025-doc-open.json) | 2026-11-06T16:30:25Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-163024-plugin-remove.json](evidence/2026-11-06-163024-plugin-remove.json) | 2026-11-06T16:30:24Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-163023-plugin-install.json](evidence/2026-11-06-163023-plugin-install.json) | 2026-11-06T16:30:23Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-163022-doc-save.json](evidence/2026-11-06-163022-doc-save.json) | 2026-11-06T16:30:22Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-163020-feature-update.json](evidence/2026-11-06-163020-feature-update.json) | 2026-11-06T16:30:20Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-163018-parameter-update.json](evidence/2026-11-06-163018-parameter-update.json) | 2026-11-06T16:30:18Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-163015-dimension-update.json](evidence/2026-11-06-163015-dimension-update.json) | 2026-11-06T16:30:15Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-163012-model-export.json](evidence/2026-11-06-163012-model-export.json) | 2026-11-06T16:30:12Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-163011-doc-save.json](evidence/2026-11-06-163011-doc-save.json) | 2026-11-06T16:30:11Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-163009-doc-save.json](evidence/2026-11-06-163009-doc-save.json) | 2026-11-06T16:30:09Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-163004-doc-save.json](evidence/2026-11-06-163004-doc-save.json) | 2026-11-06T16:30:04Z | Creo Parametric 13.4.1.0 | windows | 3 of 3 runs passed |
| [2026-11-06-162957-doc-save.json](evidence/2026-11-06-162957-doc-save.json) | 2026-11-06T16:29:57Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-162953-model-render.json](evidence/2026-11-06-162953-model-render.json) | 2026-11-06T16:29:53Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-162950-model-export.json](evidence/2026-11-06-162950-model-export.json) | 2026-11-06T16:29:50Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-162947-relation-list.json](evidence/2026-11-06-162947-relation-list.json) | 2026-11-06T16:29:47Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-162946-parameter-update.json](evidence/2026-11-06-162946-parameter-update.json) | 2026-11-06T16:29:46Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-162943-parameter-list.json](evidence/2026-11-06-162943-parameter-list.json) | 2026-11-06T16:29:43Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-162942-model-get.json](evidence/2026-11-06-162942-model-get.json) | 2026-11-06T16:29:42Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-162940-material-list.json](evidence/2026-11-06-162940-material-list.json) | 2026-11-06T16:29:40Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-162939-geometry-list.json](evidence/2026-11-06-162939-geometry-list.json) | 2026-11-06T16:29:39Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-162938-feature-update.json](evidence/2026-11-06-162938-feature-update.json) | 2026-11-06T16:29:38Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-162936-feature-list.json](evidence/2026-11-06-162936-feature-list.json) | 2026-11-06T16:29:36Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-162934-feature-get.json](evidence/2026-11-06-162934-feature-get.json) | 2026-11-06T16:29:34Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-162933-doc-close.json](evidence/2026-11-06-162933-doc-close.json) | 2026-11-06T16:29:33Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-162932-doc-list.json](evidence/2026-11-06-162932-doc-list.json) | 2026-11-06T16:29:32Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-162930-doc-get.json](evidence/2026-11-06-162930-doc-get.json) | 2026-11-06T16:29:30Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-162928-distance-get.json](evidence/2026-11-06-162928-distance-get.json) | 2026-11-06T16:29:28Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-162925-dimension-update.json](evidence/2026-11-06-162925-dimension-update.json) | 2026-11-06T16:29:25Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-162922-dimension-list.json](evidence/2026-11-06-162922-dimension-list.json) | 2026-11-06T16:29:22Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-162919-feature-update.json](evidence/2026-11-06-162919-feature-update.json) | 2026-11-06T16:29:19Z | Creo Parametric 13.4.1.0 | windows | 5 of 5 runs passed |
| [2026-11-06-162914-parameter-update.json](evidence/2026-11-06-162914-parameter-update.json) | 2026-11-06T16:29:14Z | Creo Parametric 13.4.1.0 | windows | 5 of 5 runs passed |
| [2026-11-06-162907-dimension-update.json](evidence/2026-11-06-162907-dimension-update.json) | 2026-11-06T16:29:07Z | Creo Parametric 13.4.1.0 | windows | 5 of 5 runs passed |
| [2026-11-06-162902-doc-close.json](evidence/2026-11-06-162902-doc-close.json) | 2026-11-06T16:29:02Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-162856-doc-close.json](evidence/2026-11-06-162856-doc-close.json) | 2026-11-06T16:28:56Z | Creo Parametric 13.4.1.0 | windows | 3 of 3 runs passed |
| [2026-11-06-162850-model-render.json](evidence/2026-11-06-162850-model-render.json) | 2026-11-06T16:28:50Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-162847-model-export.json](evidence/2026-11-06-162847-model-export.json) | 2026-11-06T16:28:47Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-162843-model-render.json](evidence/2026-11-06-162843-model-render.json) | 2026-11-06T16:28:43Z | Creo Parametric 13.4.1.0 | windows | 3 of 3 runs passed |
| [2026-11-06-162840-model-export.json](evidence/2026-11-06-162840-model-export.json) | 2026-11-06T16:28:40Z | Creo Parametric 13.4.1.0 | windows | 3 of 3 runs passed |
| [2026-11-06-162836-doc-open.json](evidence/2026-11-06-162836-doc-open.json) | 2026-11-06T16:28:36Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-162834-doc-open.json](evidence/2026-11-06-162834-doc-open.json) | 2026-11-06T16:28:34Z | Creo Parametric 13.4.1.0 | windows | 2 of 2 runs passed |
| [2026-11-06-162832-plugin-get.json](evidence/2026-11-06-162832-plugin-get.json) | 2026-11-06T16:28:32Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-162830-plugin-remove.json](evidence/2026-11-06-162830-plugin-remove.json) | 2026-11-06T16:28:30Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-162828-plugin-remove.json](evidence/2026-11-06-162828-plugin-remove.json) | 2026-11-06T16:28:28Z | Creo Parametric 13.4.1.0 | windows | 2 of 2 runs passed |
| [2026-11-06-162826-plugin-install.json](evidence/2026-11-06-162826-plugin-install.json) | 2026-11-06T16:28:26Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-162822-plugin-install.json](evidence/2026-11-06-162822-plugin-install.json) | 2026-11-06T16:28:22Z | Creo Parametric 13.4.1.0 | windows | 2 of 2 runs passed |
| [2026-11-06-162816-plugin-get.json](evidence/2026-11-06-162816-plugin-get.json) | 2026-11-06T16:28:16Z | Creo Parametric 13.4.1.0 | windows | 2 of 2 runs passed |
| [2026-11-06-162815-doc-get.json](evidence/2026-11-06-162815-doc-get.json) | 2026-11-06T16:28:15Z | Creo Parametric 13.4.1.0 | windows | 3 of 3 runs passed |
| [2026-11-06-162814-doc-list.json](evidence/2026-11-06-162814-doc-list.json) | 2026-11-06T16:28:14Z | Creo Parametric 13.4.1.0 | windows | 3 of 3 runs passed |
| [2026-11-06-162812-session-get.json](evidence/2026-11-06-162812-session-get.json) | 2026-11-06T16:28:12Z | Creo Parametric 13.4.1.0 | windows | 3 of 3 runs passed |
| [2026-11-06-162811-session-list.json](evidence/2026-11-06-162811-session-list.json) | 2026-11-06T16:28:11Z | Creo Parametric 13.4.1.0 | windows | 2 of 2 runs passed |
| [2026-11-06-162810-doc-close.json](evidence/2026-11-06-162810-doc-close.json) | 2026-11-06T16:28:10Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-162808-relation-list.json](evidence/2026-11-06-162808-relation-list.json) | 2026-11-06T16:28:08Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-162806-model-render.json](evidence/2026-11-06-162806-model-render.json) | 2026-11-06T16:28:06Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-162805-model-render.json](evidence/2026-11-06-162805-model-render.json) | 2026-11-06T16:28:05Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-162802-feature-update.json](evidence/2026-11-06-162802-feature-update.json) | 2026-11-06T16:28:02Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-162759-dimension-update.json](evidence/2026-11-06-162759-dimension-update.json) | 2026-11-06T16:27:59Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-162757-dimension-list.json](evidence/2026-11-06-162757-dimension-list.json) | 2026-11-06T16:27:57Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-162755-distance-get.json](evidence/2026-11-06-162755-distance-get.json) | 2026-11-06T16:27:55Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-162753-geometry-list.json](evidence/2026-11-06-162753-geometry-list.json) | 2026-11-06T16:27:53Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-162752-feature-list.json](evidence/2026-11-06-162752-feature-list.json) | 2026-11-06T16:27:52Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-162750-feature-get.json](evidence/2026-11-06-162750-feature-get.json) | 2026-11-06T16:27:50Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-162748-component-list.json](evidence/2026-11-06-162748-component-list.json) | 2026-11-06T16:27:48Z | Creo Parametric 13.4.1.0 | windows | 4 of 4 runs passed |
| [2026-11-06-162742-doc-open.json](evidence/2026-11-06-162742-doc-open.json) | 2026-11-06T16:27:42Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-162738-relation-list.json](evidence/2026-11-06-162738-relation-list.json) | 2026-11-06T16:27:38Z | Creo Parametric 13.4.1.0 | windows | 3 of 3 runs passed |
| [2026-11-06-162735-distance-get.json](evidence/2026-11-06-162735-distance-get.json) | 2026-11-06T16:27:35Z | Creo Parametric 13.4.1.0 | windows | 3 of 3 runs passed |
| [2026-11-06-162732-feature-get.json](evidence/2026-11-06-162732-feature-get.json) | 2026-11-06T16:27:32Z | Creo Parametric 13.4.1.0 | windows | 3 of 3 runs passed |
| [2026-11-06-162730-material-list.json](evidence/2026-11-06-162730-material-list.json) | 2026-11-06T16:27:30Z | Creo Parametric 13.4.1.0 | windows | 4 of 4 runs passed |
| [2026-11-06-162727-parameter-list.json](evidence/2026-11-06-162727-parameter-list.json) | 2026-11-06T16:27:27Z | Creo Parametric 13.4.1.0 | windows | 4 of 4 runs passed |
| [2026-11-06-162725-dimension-list.json](evidence/2026-11-06-162725-dimension-list.json) | 2026-11-06T16:27:25Z | Creo Parametric 13.4.1.0 | windows | 4 of 4 runs passed |
| [2026-11-06-162721-geometry-list.json](evidence/2026-11-06-162721-geometry-list.json) | 2026-11-06T16:27:21Z | Creo Parametric 13.4.1.0 | windows | 4 of 4 runs passed |
| [2026-11-06-162718-feature-list.json](evidence/2026-11-06-162718-feature-list.json) | 2026-11-06T16:27:18Z | Creo Parametric 13.4.1.0 | windows | 4 of 4 runs passed |
| [2026-11-06-162715-model-get.json](evidence/2026-11-06-162715-model-get.json) | 2026-11-06T16:27:15Z | Creo Parametric 13.4.1.0 | windows | 3 of 3 runs passed |
| [2026-11-06-162713-doc-open.json](evidence/2026-11-06-162713-doc-open.json) | 2026-11-06T16:27:13Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-06-162710-doc-list.json](evidence/2026-11-06-162710-doc-list.json) | 2026-11-06T16:27:10Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
<!-- driver:evidence:end -->
