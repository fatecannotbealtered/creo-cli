# Live Acceptance

English | [中文](E2E_zh.md)

Live runs execute the behavior matrices of creo-cli on the real Creo Parametric, with the real adapter. They make real changes, so they use only the targets authorized below.

## Authorization Rules

Authorized Targets in this file is the only list of the files, folders and devices that live runs, and evaluations on the real Creo Parametric, may use. A target is added only by a person, or by a coding Agent when the person's own message grants it; the Agent then tells the person the line it added, and keeps the descriptions up to date itself. Each target is one list item that starts with the target in backticks, written the way the scope file writes targets: a `file://` URL of a file or folder, or `device:<id>` for a device, followed by a colon and a description of the target. A listed folder is a work folder: inside it, the coding Agent makes practice copies, output folders and evaluation workspaces without asking again. An instance of Creo Parametric has no lasting ID, so live runs use only instances started for the run, by a person or by the coding Agent, with documents from the listed files and folders; the coding Agent closes only the instances it started. Live runs use no other target.

Scope files for live runs grant only listed targets and the new documents of the instances started for the run. The matrix and evaluation runners write the scope files of their runs; for other live work, such as trying a command or installing the host component, the coding Agent writes its own without asking. A target that an evaluation question's `SCOPE` names is listed too.

## Authorized Targets

- `file:///D:/driver-work/creo-cli/targets/`: the work folder of creo-cli's live tests: the practice models (disc.prt, plate.prt, pair.asm, disc.drw), the stage parts the feature commands start from and their copies, the start folders of the Creo instances started for the runs, and the folders that exports, renders and new parts go to.
- `file:///D:/driver-work/creo-cli/evals/`: the folder for the evaluation workspaces.

## Procedure

Live runs are made on these machines:

One Windows 11 x64 computer with Creo Parametric 13.4.1.0, its Object TOOLKIT Java and a JDK 25, in session mode. Live runs use their own state directory (`CREO_CLI_STATE_DIR`). Before the first run, `creo-cli plugin install` is run with that state directory, `toolkit_registry_file <install_path>\protk.dat`, with the `install_path` that `creo-cli plugin get` shows, goes into the `config.pro` of the start folder of the Creo started for the run, and that Creo is started; `creo-cli session list` must show `plugin_loaded`. Live runs set `LOCALAPPDATA` for creo-cli to a folder of their own, so that the host component they install, and the `plugin install` and `plugin remove` rows, leave the person's own copy alone. Those rows use a second state directory, whose host component no running Creo has loaded: Windows keeps a loaded JAR open, so it could not be removed. The `read_back_mismatch` rows change the result through `--tamper`: a script that sets the dimension, parameter or feature name again through the host component, closes or opens the model again, deletes the file the write made or the version file the save wrote, or ends the Creo that `session open` started.

To run a behavior matrix on the real Creo Parametric:

1. Prepare the targets, such as a copy of a project made for testing in a listed folder, an instance started for the run or a device set up for testing. A target outside the listed ones is added under Authorized Targets first, as Authorization Rules says.
2. Set `CREO_CLI_STATE_DIR` to a separate directory for live runs.
3. Run `python scripts/spec.py matrix --command "<path>" --set <placeholder>=<value>`, with one `--set` for each placeholder the matrix uses, named without braces, such as `--set doc=<file>`: `{session}` takes an instance started for the run, `{doc}` an authorized document or file, `{device}` an authorized device, and `{dir}` a new empty directory inside an authorized folder. `{job}` takes a job ID; without it, the runner first runs the `normal` row of the long command that `--job-from` names, or of the only long command, and uses the job it starts. `{inputs}` needs no `--set`: it is `tests/inputs/`, whose files commands only read, so they need no authorization.
4. The runner runs the rows that apply, writes a live record to `docs/evidence/` and fills in the actual result and the `live:` evidence reference of each row. A row whose actual result differs from the expected one has failed.
5. A row that cannot be caused on demand on the real Creo Parametric, such as `disconnect`, may be marked `unrunnable` with the reason; the `normal`, `dialog` and `read_back_mismatch` rows never may. For `read_back_mismatch`, run the matrix with `--row read_back_mismatch`: the tool waits before its read-back, and in that time change what it just wrote in Creo Parametric, or delete the file it made.
6. Run `python scripts/spec.py generate` to update the support matrix and the index below, then commit the records with the matrices.

To run the evaluation questions on the real Creo Parametric, run `python scripts/spec.py eval --workspace-root <folder>` with a folder inside a listed folder. The runner writes each question's scope file and writes the evaluation report to `docs/evidence/`.

A live record counts as evidence only while its tool version has the same major and minor version as creo-cli. Records never hold secrets, and arguments that carry secrets show as `***`.

## Evidence Records

The live records in `docs/evidence/`, generated by `python scripts/spec.py generate`:

<!-- driver:evidence:start -->
| Record | Recorded at | Application | Platform | Result |
|---|---|---|---|---|
| [2026-11-08-090423-session-close.json](evidence/2026-11-08-090423-session-close.json) | 2026-11-08T09:04:23Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-08-090405-session-close.json](evidence/2026-11-08-090405-session-close.json) | 2026-11-08T09:04:05Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-08-090403-doc-save-as.json](evidence/2026-11-08-090403-doc-save-as.json) | 2026-11-08T09:04:03Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-08-090401-doc-create.json](evidence/2026-11-08-090401-doc-create.json) | 2026-11-08T09:04:01Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-08-085525-session-close.json](evidence/2026-11-08-085525-session-close.json) | 2026-11-08T08:55:25Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-08-085523-doc-save-as.json](evidence/2026-11-08-085523-doc-save-as.json) | 2026-11-08T08:55:23Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-08-085520-doc-create.json](evidence/2026-11-08-085520-doc-create.json) | 2026-11-08T08:55:20Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-08-085515-doc-save-as.json](evidence/2026-11-08-085515-doc-save-as.json) | 2026-11-08T08:55:15Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-08-085511-doc-create.json](evidence/2026-11-08-085511-doc-create.json) | 2026-11-08T08:55:11Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-08-085459-session-close.json](evidence/2026-11-08-085459-session-close.json) | 2026-11-08T08:54:59Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-08-085219-session-close.json](evidence/2026-11-08-085219-session-close.json) | 2026-11-08T08:52:19Z | Creo Parametric 13.4.1.0 | windows | 3 of 3 runs passed |
| [2026-11-08-083721-session-open.json](evidence/2026-11-08-083721-session-open.json) | 2026-11-08T08:37:21Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-08-083655-session-close.json](evidence/2026-11-08-083655-session-close.json) | 2026-11-08T08:36:55Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-08-083644-session-open.json](evidence/2026-11-08-083644-session-open.json) | 2026-11-08T08:36:44Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-08-083624-session-open.json](evidence/2026-11-08-083624-session-open.json) | 2026-11-08T08:36:24Z | Creo Parametric 13.4.1.0 | windows | 3 of 3 runs passed |
| [2026-11-08-083604-doc-save-as.json](evidence/2026-11-08-083604-doc-save-as.json) | 2026-11-08T08:36:04Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-08-083557-doc-save-as.json](evidence/2026-11-08-083557-doc-save-as.json) | 2026-11-08T08:35:57Z | Creo Parametric 13.4.1.0 | windows | 3 of 3 runs passed |
| [2026-11-08-083526-doc-save-as.json](evidence/2026-11-08-083526-doc-save-as.json) | 2026-11-08T08:35:26Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-08-083522-doc-save-as.json](evidence/2026-11-08-083522-doc-save-as.json) | 2026-11-08T08:35:22Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-08-083511-doc-save-as.json](evidence/2026-11-08-083511-doc-save-as.json) | 2026-11-08T08:35:11Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-08-083503-doc-create.json](evidence/2026-11-08-083503-doc-create.json) | 2026-11-08T08:35:03Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-08-083457-doc-create.json](evidence/2026-11-08-083457-doc-create.json) | 2026-11-08T08:34:57Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-08-083455-doc-create.json](evidence/2026-11-08-083455-doc-create.json) | 2026-11-08T08:34:55Z | Creo Parametric 13.4.1.0 | windows | 3 of 3 runs passed |
| [2026-11-08-083444-doc-create.json](evidence/2026-11-08-083444-doc-create.json) | 2026-11-08T08:34:44Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-223045-feature-delete.json](evidence/2026-11-07-223045-feature-delete.json) | 2026-11-07T22:30:45Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-223032-model-render.json](evidence/2026-11-07-223032-model-render.json) | 2026-11-07T22:30:32Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-223027-feature-update.json](evidence/2026-11-07-223027-feature-update.json) | 2026-11-07T22:30:27Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-223025-dimension-update.json](evidence/2026-11-07-223025-dimension-update.json) | 2026-11-07T22:30:25Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-214007-shell-create.json](evidence/2026-11-07-214007-shell-create.json) | 2026-11-07T21:40:07Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-214005-session-get.json](evidence/2026-11-07-214005-session-get.json) | 2026-11-07T21:40:05Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-214004-round-create.json](evidence/2026-11-07-214004-round-create.json) | 2026-11-07T21:40:04Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-214002-revolve-create.json](evidence/2026-11-07-214002-revolve-create.json) | 2026-11-07T21:40:02Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-214000-relation-update.json](evidence/2026-11-07-214000-relation-update.json) | 2026-11-07T21:40:00Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-213959-relation-list.json](evidence/2026-11-07-213959-relation-list.json) | 2026-11-07T21:39:59Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-213958-plane-create.json](evidence/2026-11-07-213958-plane-create.json) | 2026-11-07T21:39:58Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-213956-pattern-create.json](evidence/2026-11-07-213956-pattern-create.json) | 2026-11-07T21:39:56Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-213955-parameter-update.json](evidence/2026-11-07-213955-parameter-update.json) | 2026-11-07T21:39:55Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-213953-parameter-list.json](evidence/2026-11-07-213953-parameter-list.json) | 2026-11-07T21:39:53Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-213952-parameter-create.json](evidence/2026-11-07-213952-parameter-create.json) | 2026-11-07T21:39:52Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-213950-model-update.json](evidence/2026-11-07-213950-model-update.json) | 2026-11-07T21:39:50Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-213949-model-render.json](evidence/2026-11-07-213949-model-render.json) | 2026-11-07T21:39:49Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-213948-model-get.json](evidence/2026-11-07-213948-model-get.json) | 2026-11-07T21:39:48Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-213946-model-export.json](evidence/2026-11-07-213946-model-export.json) | 2026-11-07T21:39:46Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-213945-model-check.json](evidence/2026-11-07-213945-model-check.json) | 2026-11-07T21:39:45Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-213944-material-list.json](evidence/2026-11-07-213944-material-list.json) | 2026-11-07T21:39:44Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-213942-geometry-list.json](evidence/2026-11-07-213942-geometry-list.json) | 2026-11-07T21:39:42Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-213941-feature-update.json](evidence/2026-11-07-213941-feature-update.json) | 2026-11-07T21:39:41Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-213939-feature-list.json](evidence/2026-11-07-213939-feature-list.json) | 2026-11-07T21:39:39Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-213938-feature-get.json](evidence/2026-11-07-213938-feature-get.json) | 2026-11-07T21:39:38Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-213937-feature-delete.json](evidence/2026-11-07-213937-feature-delete.json) | 2026-11-07T21:39:37Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-213935-extrude-create.json](evidence/2026-11-07-213935-extrude-create.json) | 2026-11-07T21:39:35Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-213934-draft-create.json](evidence/2026-11-07-213934-draft-create.json) | 2026-11-07T21:39:34Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-213932-doc-save.json](evidence/2026-11-07-213932-doc-save.json) | 2026-11-07T21:39:32Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-213930-doc-open.json](evidence/2026-11-07-213930-doc-open.json) | 2026-11-07T21:39:30Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-213929-doc-get.json](evidence/2026-11-07-213929-doc-get.json) | 2026-11-07T21:39:29Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-213927-doc-close.json](evidence/2026-11-07-213927-doc-close.json) | 2026-11-07T21:39:27Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-213926-distance-get.json](evidence/2026-11-07-213926-distance-get.json) | 2026-11-07T21:39:26Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-213924-dimension-update.json](evidence/2026-11-07-213924-dimension-update.json) | 2026-11-07T21:39:24Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-213923-dimension-list.json](evidence/2026-11-07-213923-dimension-list.json) | 2026-11-07T21:39:23Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-213921-component-list.json](evidence/2026-11-07-213921-component-list.json) | 2026-11-07T21:39:21Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-213920-chamfer-create.json](evidence/2026-11-07-213920-chamfer-create.json) | 2026-11-07T21:39:20Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-213918-axis-create.json](evidence/2026-11-07-213918-axis-create.json) | 2026-11-07T21:39:18Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-213809-session-list.json](evidence/2026-11-07-213809-session-list.json) | 2026-11-07T21:38:09Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-213557-model-check.json](evidence/2026-11-07-213557-model-check.json) | 2026-11-07T21:35:57Z | Creo Parametric 13.4.1.0 | windows | 4 of 4 runs passed |
| [2026-11-07-213525-feature-delete.json](evidence/2026-11-07-213525-feature-delete.json) | 2026-11-07T21:35:25Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-213510-feature-delete.json](evidence/2026-11-07-213510-feature-delete.json) | 2026-11-07T21:35:10Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-213503-feature-delete.json](evidence/2026-11-07-213503-feature-delete.json) | 2026-11-07T21:35:03Z | Creo Parametric 13.4.1.0 | windows | 3 of 3 runs passed |
| [2026-11-07-213457-feature-delete.json](evidence/2026-11-07-213457-feature-delete.json) | 2026-11-07T21:34:57Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-213426-model-update.json](evidence/2026-11-07-213426-model-update.json) | 2026-11-07T21:34:26Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-213414-model-update.json](evidence/2026-11-07-213414-model-update.json) | 2026-11-07T21:34:14Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-213406-model-update.json](evidence/2026-11-07-213406-model-update.json) | 2026-11-07T21:34:06Z | Creo Parametric 13.4.1.0 | windows | 3 of 3 runs passed |
| [2026-11-07-213401-model-update.json](evidence/2026-11-07-213401-model-update.json) | 2026-11-07T21:34:01Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-213327-relation-update.json](evidence/2026-11-07-213327-relation-update.json) | 2026-11-07T21:33:27Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-213316-relation-update.json](evidence/2026-11-07-213316-relation-update.json) | 2026-11-07T21:33:16Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-213311-relation-update.json](evidence/2026-11-07-213311-relation-update.json) | 2026-11-07T21:33:11Z | Creo Parametric 13.4.1.0 | windows | 5 of 5 runs passed |
| [2026-11-07-213305-relation-update.json](evidence/2026-11-07-213305-relation-update.json) | 2026-11-07T21:33:05Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-213231-parameter-create.json](evidence/2026-11-07-213231-parameter-create.json) | 2026-11-07T21:32:31Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-213220-parameter-create.json](evidence/2026-11-07-213220-parameter-create.json) | 2026-11-07T21:32:20Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-213214-parameter-create.json](evidence/2026-11-07-213214-parameter-create.json) | 2026-11-07T21:32:14Z | Creo Parametric 13.4.1.0 | windows | 4 of 4 runs passed |
| [2026-11-07-213208-parameter-create.json](evidence/2026-11-07-213208-parameter-create.json) | 2026-11-07T21:32:08Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-213138-axis-create.json](evidence/2026-11-07-213138-axis-create.json) | 2026-11-07T21:31:38Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-213126-axis-create.json](evidence/2026-11-07-213126-axis-create.json) | 2026-11-07T21:31:26Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-213120-axis-create.json](evidence/2026-11-07-213120-axis-create.json) | 2026-11-07T21:31:20Z | Creo Parametric 13.4.1.0 | windows | 4 of 4 runs passed |
| [2026-11-07-213115-axis-create.json](evidence/2026-11-07-213115-axis-create.json) | 2026-11-07T21:31:15Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-213044-plane-create.json](evidence/2026-11-07-213044-plane-create.json) | 2026-11-07T21:30:44Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-213033-plane-create.json](evidence/2026-11-07-213033-plane-create.json) | 2026-11-07T21:30:33Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-213027-plane-create.json](evidence/2026-11-07-213027-plane-create.json) | 2026-11-07T21:30:27Z | Creo Parametric 13.4.1.0 | windows | 4 of 4 runs passed |
| [2026-11-07-213022-plane-create.json](evidence/2026-11-07-213022-plane-create.json) | 2026-11-07T21:30:22Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-212952-pattern-create.json](evidence/2026-11-07-212952-pattern-create.json) | 2026-11-07T21:29:52Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-212940-pattern-create.json](evidence/2026-11-07-212940-pattern-create.json) | 2026-11-07T21:29:40Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-212934-pattern-create.json](evidence/2026-11-07-212934-pattern-create.json) | 2026-11-07T21:29:34Z | Creo Parametric 13.4.1.0 | windows | 4 of 4 runs passed |
| [2026-11-07-212929-pattern-create.json](evidence/2026-11-07-212929-pattern-create.json) | 2026-11-07T21:29:29Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-212859-draft-create.json](evidence/2026-11-07-212859-draft-create.json) | 2026-11-07T21:28:59Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-212847-draft-create.json](evidence/2026-11-07-212847-draft-create.json) | 2026-11-07T21:28:47Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-212841-draft-create.json](evidence/2026-11-07-212841-draft-create.json) | 2026-11-07T21:28:41Z | Creo Parametric 13.4.1.0 | windows | 4 of 4 runs passed |
| [2026-11-07-212836-draft-create.json](evidence/2026-11-07-212836-draft-create.json) | 2026-11-07T21:28:36Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-212805-chamfer-create.json](evidence/2026-11-07-212805-chamfer-create.json) | 2026-11-07T21:28:05Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-212753-chamfer-create.json](evidence/2026-11-07-212753-chamfer-create.json) | 2026-11-07T21:27:53Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-212746-chamfer-create.json](evidence/2026-11-07-212746-chamfer-create.json) | 2026-11-07T21:27:46Z | Creo Parametric 13.4.1.0 | windows | 4 of 4 runs passed |
| [2026-11-07-212741-chamfer-create.json](evidence/2026-11-07-212741-chamfer-create.json) | 2026-11-07T21:27:41Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-212710-round-create.json](evidence/2026-11-07-212710-round-create.json) | 2026-11-07T21:27:10Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-212655-round-create.json](evidence/2026-11-07-212655-round-create.json) | 2026-11-07T21:26:55Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-212648-round-create.json](evidence/2026-11-07-212648-round-create.json) | 2026-11-07T21:26:48Z | Creo Parametric 13.4.1.0 | windows | 4 of 4 runs passed |
| [2026-11-07-212642-round-create.json](evidence/2026-11-07-212642-round-create.json) | 2026-11-07T21:26:42Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-212611-shell-create.json](evidence/2026-11-07-212611-shell-create.json) | 2026-11-07T21:26:11Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-212558-shell-create.json](evidence/2026-11-07-212558-shell-create.json) | 2026-11-07T21:25:58Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-212551-shell-create.json](evidence/2026-11-07-212551-shell-create.json) | 2026-11-07T21:25:51Z | Creo Parametric 13.4.1.0 | windows | 4 of 4 runs passed |
| [2026-11-07-212545-shell-create.json](evidence/2026-11-07-212545-shell-create.json) | 2026-11-07T21:25:45Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-212516-revolve-create.json](evidence/2026-11-07-212516-revolve-create.json) | 2026-11-07T21:25:16Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-212503-revolve-create.json](evidence/2026-11-07-212503-revolve-create.json) | 2026-11-07T21:25:03Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-212457-revolve-create.json](evidence/2026-11-07-212457-revolve-create.json) | 2026-11-07T21:24:57Z | Creo Parametric 13.4.1.0 | windows | 4 of 4 runs passed |
| [2026-11-07-212452-revolve-create.json](evidence/2026-11-07-212452-revolve-create.json) | 2026-11-07T21:24:52Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-212417-extrude-create.json](evidence/2026-11-07-212417-extrude-create.json) | 2026-11-07T21:24:17Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-212401-extrude-create.json](evidence/2026-11-07-212401-extrude-create.json) | 2026-11-07T21:24:01Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-212350-extrude-create.json](evidence/2026-11-07-212350-extrude-create.json) | 2026-11-07T21:23:50Z | Creo Parametric 13.4.1.0 | windows | 4 of 4 runs passed |
| [2026-11-07-212343-extrude-create.json](evidence/2026-11-07-212343-extrude-create.json) | 2026-11-07T21:23:43Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191427-model-check.json](evidence/2026-11-07-191427-model-check.json) | 2026-11-07T19:14:27Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191426-feature-delete.json](evidence/2026-11-07-191426-feature-delete.json) | 2026-11-07T19:14:26Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191424-model-update.json](evidence/2026-11-07-191424-model-update.json) | 2026-11-07T19:14:24Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191423-relation-update.json](evidence/2026-11-07-191423-relation-update.json) | 2026-11-07T19:14:23Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191421-parameter-create.json](evidence/2026-11-07-191421-parameter-create.json) | 2026-11-07T19:14:21Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191419-axis-create.json](evidence/2026-11-07-191419-axis-create.json) | 2026-11-07T19:14:19Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191418-plane-create.json](evidence/2026-11-07-191418-plane-create.json) | 2026-11-07T19:14:18Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191416-pattern-create.json](evidence/2026-11-07-191416-pattern-create.json) | 2026-11-07T19:14:16Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191414-draft-create.json](evidence/2026-11-07-191414-draft-create.json) | 2026-11-07T19:14:14Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191412-chamfer-create.json](evidence/2026-11-07-191412-chamfer-create.json) | 2026-11-07T19:14:12Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191411-round-create.json](evidence/2026-11-07-191411-round-create.json) | 2026-11-07T19:14:11Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191409-shell-create.json](evidence/2026-11-07-191409-shell-create.json) | 2026-11-07T19:14:09Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191407-revolve-create.json](evidence/2026-11-07-191407-revolve-create.json) | 2026-11-07T19:14:07Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191406-extrude-create.json](evidence/2026-11-07-191406-extrude-create.json) | 2026-11-07T19:14:06Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191404-relation-list.json](evidence/2026-11-07-191404-relation-list.json) | 2026-11-07T19:14:04Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191402-parameter-update.json](evidence/2026-11-07-191402-parameter-update.json) | 2026-11-07T19:14:02Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191401-parameter-list.json](evidence/2026-11-07-191401-parameter-list.json) | 2026-11-07T19:14:01Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191359-model-render.json](evidence/2026-11-07-191359-model-render.json) | 2026-11-07T19:13:59Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191358-model-get.json](evidence/2026-11-07-191358-model-get.json) | 2026-11-07T19:13:58Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191356-model-export.json](evidence/2026-11-07-191356-model-export.json) | 2026-11-07T19:13:56Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191354-material-list.json](evidence/2026-11-07-191354-material-list.json) | 2026-11-07T19:13:54Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191353-geometry-list.json](evidence/2026-11-07-191353-geometry-list.json) | 2026-11-07T19:13:53Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191352-feature-update.json](evidence/2026-11-07-191352-feature-update.json) | 2026-11-07T19:13:52Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191350-feature-list.json](evidence/2026-11-07-191350-feature-list.json) | 2026-11-07T19:13:50Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191348-feature-get.json](evidence/2026-11-07-191348-feature-get.json) | 2026-11-07T19:13:48Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191347-doc-save.json](evidence/2026-11-07-191347-doc-save.json) | 2026-11-07T19:13:47Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191345-doc-open.json](evidence/2026-11-07-191345-doc-open.json) | 2026-11-07T19:13:45Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191344-doc-close.json](evidence/2026-11-07-191344-doc-close.json) | 2026-11-07T19:13:44Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191342-distance-get.json](evidence/2026-11-07-191342-distance-get.json) | 2026-11-07T19:13:42Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191340-dimension-update.json](evidence/2026-11-07-191340-dimension-update.json) | 2026-11-07T19:13:40Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191339-dimension-list.json](evidence/2026-11-07-191339-dimension-list.json) | 2026-11-07T19:13:39Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191337-component-list.json](evidence/2026-11-07-191337-component-list.json) | 2026-11-07T19:13:37Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191335-model-check.json](evidence/2026-11-07-191335-model-check.json) | 2026-11-07T19:13:35Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191332-feature-delete.json](evidence/2026-11-07-191332-feature-delete.json) | 2026-11-07T19:13:32Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191329-model-update.json](evidence/2026-11-07-191329-model-update.json) | 2026-11-07T19:13:29Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191326-relation-update.json](evidence/2026-11-07-191326-relation-update.json) | 2026-11-07T19:13:26Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191322-parameter-create.json](evidence/2026-11-07-191322-parameter-create.json) | 2026-11-07T19:13:22Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191319-axis-create.json](evidence/2026-11-07-191319-axis-create.json) | 2026-11-07T19:13:19Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191316-plane-create.json](evidence/2026-11-07-191316-plane-create.json) | 2026-11-07T19:13:16Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191313-pattern-create.json](evidence/2026-11-07-191313-pattern-create.json) | 2026-11-07T19:13:13Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191310-draft-create.json](evidence/2026-11-07-191310-draft-create.json) | 2026-11-07T19:13:10Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191306-chamfer-create.json](evidence/2026-11-07-191306-chamfer-create.json) | 2026-11-07T19:13:06Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191303-round-create.json](evidence/2026-11-07-191303-round-create.json) | 2026-11-07T19:13:03Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191300-shell-create.json](evidence/2026-11-07-191300-shell-create.json) | 2026-11-07T19:13:00Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191257-revolve-create.json](evidence/2026-11-07-191257-revolve-create.json) | 2026-11-07T19:12:57Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191253-extrude-create.json](evidence/2026-11-07-191253-extrude-create.json) | 2026-11-07T19:12:53Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191250-relation-list.json](evidence/2026-11-07-191250-relation-list.json) | 2026-11-07T19:12:50Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191247-parameter-update.json](evidence/2026-11-07-191247-parameter-update.json) | 2026-11-07T19:12:47Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191244-parameter-list.json](evidence/2026-11-07-191244-parameter-list.json) | 2026-11-07T19:12:44Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191241-model-render.json](evidence/2026-11-07-191241-model-render.json) | 2026-11-07T19:12:41Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191238-model-get.json](evidence/2026-11-07-191238-model-get.json) | 2026-11-07T19:12:38Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191235-model-export.json](evidence/2026-11-07-191235-model-export.json) | 2026-11-07T19:12:35Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191232-material-list.json](evidence/2026-11-07-191232-material-list.json) | 2026-11-07T19:12:32Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191229-geometry-list.json](evidence/2026-11-07-191229-geometry-list.json) | 2026-11-07T19:12:29Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191226-feature-update.json](evidence/2026-11-07-191226-feature-update.json) | 2026-11-07T19:12:26Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191223-feature-list.json](evidence/2026-11-07-191223-feature-list.json) | 2026-11-07T19:12:23Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191220-feature-get.json](evidence/2026-11-07-191220-feature-get.json) | 2026-11-07T19:12:20Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191217-doc-save.json](evidence/2026-11-07-191217-doc-save.json) | 2026-11-07T19:12:17Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191214-doc-open.json](evidence/2026-11-07-191214-doc-open.json) | 2026-11-07T19:12:14Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191210-doc-close.json](evidence/2026-11-07-191210-doc-close.json) | 2026-11-07T19:12:10Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191207-distance-get.json](evidence/2026-11-07-191207-distance-get.json) | 2026-11-07T19:12:07Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191204-dimension-update.json](evidence/2026-11-07-191204-dimension-update.json) | 2026-11-07T19:12:04Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191201-dimension-list.json](evidence/2026-11-07-191201-dimension-list.json) | 2026-11-07T19:12:01Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191158-component-list.json](evidence/2026-11-07-191158-component-list.json) | 2026-11-07T19:11:58Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191143-component-list.json](evidence/2026-11-07-191143-component-list.json) | 2026-11-07T19:11:43Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191139-doc-save.json](evidence/2026-11-07-191139-doc-save.json) | 2026-11-07T19:11:39Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191127-feature-update.json](evidence/2026-11-07-191127-feature-update.json) | 2026-11-07T19:11:27Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191123-parameter-update.json](evidence/2026-11-07-191123-parameter-update.json) | 2026-11-07T19:11:23Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191119-dimension-update.json](evidence/2026-11-07-191119-dimension-update.json) | 2026-11-07T19:11:19Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191116-model-render.json](evidence/2026-11-07-191116-model-render.json) | 2026-11-07T19:11:16Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191114-model-export.json](evidence/2026-11-07-191114-model-export.json) | 2026-11-07T19:11:14Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191113-doc-close.json](evidence/2026-11-07-191113-doc-close.json) | 2026-11-07T19:11:13Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191111-doc-open.json](evidence/2026-11-07-191111-doc-open.json) | 2026-11-07T19:11:11Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191109-plugin-remove.json](evidence/2026-11-07-191109-plugin-remove.json) | 2026-11-07T19:11:09Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191108-plugin-install.json](evidence/2026-11-07-191108-plugin-install.json) | 2026-11-07T19:11:08Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191106-doc-save.json](evidence/2026-11-07-191106-doc-save.json) | 2026-11-07T19:11:06Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191104-feature-update.json](evidence/2026-11-07-191104-feature-update.json) | 2026-11-07T19:11:04Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191102-parameter-update.json](evidence/2026-11-07-191102-parameter-update.json) | 2026-11-07T19:11:02Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191100-dimension-update.json](evidence/2026-11-07-191100-dimension-update.json) | 2026-11-07T19:11:00Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191057-model-export.json](evidence/2026-11-07-191057-model-export.json) | 2026-11-07T19:10:57Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191055-doc-save.json](evidence/2026-11-07-191055-doc-save.json) | 2026-11-07T19:10:55Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191053-doc-save.json](evidence/2026-11-07-191053-doc-save.json) | 2026-11-07T19:10:53Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191047-doc-save.json](evidence/2026-11-07-191047-doc-save.json) | 2026-11-07T19:10:47Z | Creo Parametric 13.4.1.0 | windows | 3 of 3 runs passed |
| [2026-11-07-191036-doc-save.json](evidence/2026-11-07-191036-doc-save.json) | 2026-11-07T19:10:36Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191030-model-render.json](evidence/2026-11-07-191030-model-render.json) | 2026-11-07T19:10:30Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191027-model-export.json](evidence/2026-11-07-191027-model-export.json) | 2026-11-07T19:10:27Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191024-relation-list.json](evidence/2026-11-07-191024-relation-list.json) | 2026-11-07T19:10:24Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191022-parameter-update.json](evidence/2026-11-07-191022-parameter-update.json) | 2026-11-07T19:10:22Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191020-parameter-list.json](evidence/2026-11-07-191020-parameter-list.json) | 2026-11-07T19:10:20Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191019-model-get.json](evidence/2026-11-07-191019-model-get.json) | 2026-11-07T19:10:19Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191017-material-list.json](evidence/2026-11-07-191017-material-list.json) | 2026-11-07T19:10:17Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191015-geometry-list.json](evidence/2026-11-07-191015-geometry-list.json) | 2026-11-07T19:10:15Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191013-feature-update.json](evidence/2026-11-07-191013-feature-update.json) | 2026-11-07T19:10:13Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191011-feature-list.json](evidence/2026-11-07-191011-feature-list.json) | 2026-11-07T19:10:11Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191009-feature-get.json](evidence/2026-11-07-191009-feature-get.json) | 2026-11-07T19:10:09Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191008-doc-close.json](evidence/2026-11-07-191008-doc-close.json) | 2026-11-07T19:10:08Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191006-doc-list.json](evidence/2026-11-07-191006-doc-list.json) | 2026-11-07T19:10:06Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191005-doc-get.json](evidence/2026-11-07-191005-doc-get.json) | 2026-11-07T19:10:05Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191003-distance-get.json](evidence/2026-11-07-191003-distance-get.json) | 2026-11-07T19:10:03Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-191001-dimension-update.json](evidence/2026-11-07-191001-dimension-update.json) | 2026-11-07T19:10:01Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-190958-dimension-list.json](evidence/2026-11-07-190958-dimension-list.json) | 2026-11-07T19:09:58Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-190955-feature-update.json](evidence/2026-11-07-190955-feature-update.json) | 2026-11-07T19:09:55Z | Creo Parametric 13.4.1.0 | windows | 5 of 5 runs passed |
| [2026-11-07-190948-parameter-update.json](evidence/2026-11-07-190948-parameter-update.json) | 2026-11-07T19:09:48Z | Creo Parametric 13.4.1.0 | windows | 5 of 5 runs passed |
| [2026-11-07-190942-dimension-update.json](evidence/2026-11-07-190942-dimension-update.json) | 2026-11-07T19:09:42Z | Creo Parametric 13.4.1.0 | windows | 5 of 5 runs passed |
| [2026-11-07-190934-doc-close.json](evidence/2026-11-07-190934-doc-close.json) | 2026-11-07T19:09:34Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-190927-doc-close.json](evidence/2026-11-07-190927-doc-close.json) | 2026-11-07T19:09:27Z | Creo Parametric 13.4.1.0 | windows | 3 of 3 runs passed |
| [2026-11-07-190920-model-render.json](evidence/2026-11-07-190920-model-render.json) | 2026-11-07T19:09:20Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-190917-model-export.json](evidence/2026-11-07-190917-model-export.json) | 2026-11-07T19:09:17Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-190912-model-render.json](evidence/2026-11-07-190912-model-render.json) | 2026-11-07T19:09:12Z | Creo Parametric 13.4.1.0 | windows | 3 of 3 runs passed |
| [2026-11-07-190908-model-export.json](evidence/2026-11-07-190908-model-export.json) | 2026-11-07T19:09:08Z | Creo Parametric 13.4.1.0 | windows | 3 of 3 runs passed |
| [2026-11-07-190903-doc-open.json](evidence/2026-11-07-190903-doc-open.json) | 2026-11-07T19:09:03Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-190900-doc-open.json](evidence/2026-11-07-190900-doc-open.json) | 2026-11-07T19:09:00Z | Creo Parametric 13.4.1.0 | windows | 2 of 2 runs passed |
| [2026-11-07-190856-plugin-get.json](evidence/2026-11-07-190856-plugin-get.json) | 2026-11-07T19:08:56Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-190854-plugin-remove.json](evidence/2026-11-07-190854-plugin-remove.json) | 2026-11-07T19:08:54Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-190851-plugin-remove.json](evidence/2026-11-07-190851-plugin-remove.json) | 2026-11-07T19:08:51Z | Creo Parametric 13.4.1.0 | windows | 2 of 2 runs passed |
| [2026-11-07-190849-plugin-install.json](evidence/2026-11-07-190849-plugin-install.json) | 2026-11-07T19:08:49Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-190846-plugin-install.json](evidence/2026-11-07-190846-plugin-install.json) | 2026-11-07T19:08:46Z | Creo Parametric 13.4.1.0 | windows | 2 of 2 runs passed |
| [2026-11-07-190832-plugin-get.json](evidence/2026-11-07-190832-plugin-get.json) | 2026-11-07T19:08:32Z | Creo Parametric 13.4.1.0 | windows | 2 of 2 runs passed |
| [2026-11-07-190831-doc-get.json](evidence/2026-11-07-190831-doc-get.json) | 2026-11-07T19:08:31Z | Creo Parametric 13.4.1.0 | windows | 3 of 3 runs passed |
| [2026-11-07-190829-doc-list.json](evidence/2026-11-07-190829-doc-list.json) | 2026-11-07T19:08:29Z | Creo Parametric 13.4.1.0 | windows | 3 of 3 runs passed |
| [2026-11-07-190827-session-get.json](evidence/2026-11-07-190827-session-get.json) | 2026-11-07T19:08:27Z | Creo Parametric 13.4.1.0 | windows | 3 of 3 runs passed |
| [2026-11-07-190825-session-list.json](evidence/2026-11-07-190825-session-list.json) | 2026-11-07T19:08:25Z | Creo Parametric 13.4.1.0 | windows | 2 of 2 runs passed |
| [2026-11-07-190823-doc-close.json](evidence/2026-11-07-190823-doc-close.json) | 2026-11-07T19:08:23Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-190820-relation-list.json](evidence/2026-11-07-190820-relation-list.json) | 2026-11-07T19:08:20Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-190818-model-render.json](evidence/2026-11-07-190818-model-render.json) | 2026-11-07T19:08:18Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-190807-dimension-list.json](evidence/2026-11-07-190807-dimension-list.json) | 2026-11-07T19:08:07Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-190806-distance-get.json](evidence/2026-11-07-190806-distance-get.json) | 2026-11-07T19:08:06Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-190804-geometry-list.json](evidence/2026-11-07-190804-geometry-list.json) | 2026-11-07T19:08:04Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-190803-feature-list.json](evidence/2026-11-07-190803-feature-list.json) | 2026-11-07T19:08:03Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-190801-feature-get.json](evidence/2026-11-07-190801-feature-get.json) | 2026-11-07T19:08:01Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-190759-component-list.json](evidence/2026-11-07-190759-component-list.json) | 2026-11-07T19:07:59Z | Creo Parametric 13.4.1.0 | windows | 4 of 4 runs passed |
| [2026-11-07-190751-doc-open.json](evidence/2026-11-07-190751-doc-open.json) | 2026-11-07T19:07:51Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-190746-relation-list.json](evidence/2026-11-07-190746-relation-list.json) | 2026-11-07T19:07:46Z | Creo Parametric 13.4.1.0 | windows | 3 of 3 runs passed |
| [2026-11-07-190744-distance-get.json](evidence/2026-11-07-190744-distance-get.json) | 2026-11-07T19:07:44Z | Creo Parametric 13.4.1.0 | windows | 3 of 3 runs passed |
| [2026-11-07-190741-feature-get.json](evidence/2026-11-07-190741-feature-get.json) | 2026-11-07T19:07:41Z | Creo Parametric 13.4.1.0 | windows | 3 of 3 runs passed |
| [2026-11-07-190739-material-list.json](evidence/2026-11-07-190739-material-list.json) | 2026-11-07T19:07:39Z | Creo Parametric 13.4.1.0 | windows | 4 of 4 runs passed |
| [2026-11-07-190736-parameter-list.json](evidence/2026-11-07-190736-parameter-list.json) | 2026-11-07T19:07:36Z | Creo Parametric 13.4.1.0 | windows | 4 of 4 runs passed |
| [2026-11-07-190734-dimension-list.json](evidence/2026-11-07-190734-dimension-list.json) | 2026-11-07T19:07:34Z | Creo Parametric 13.4.1.0 | windows | 4 of 4 runs passed |
| [2026-11-07-190731-geometry-list.json](evidence/2026-11-07-190731-geometry-list.json) | 2026-11-07T19:07:31Z | Creo Parametric 13.4.1.0 | windows | 4 of 4 runs passed |
| [2026-11-07-190727-feature-list.json](evidence/2026-11-07-190727-feature-list.json) | 2026-11-07T19:07:27Z | Creo Parametric 13.4.1.0 | windows | 4 of 4 runs passed |
| [2026-11-07-190725-model-get.json](evidence/2026-11-07-190725-model-get.json) | 2026-11-07T19:07:25Z | Creo Parametric 13.4.1.0 | windows | 3 of 3 runs passed |
| [2026-11-07-190723-doc-open.json](evidence/2026-11-07-190723-doc-open.json) | 2026-11-07T19:07:23Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
| [2026-11-07-185503-doc-list.json](evidence/2026-11-07-185503-doc-list.json) | 2026-11-07T18:55:03Z | Creo Parametric 13.4.1.0 | windows | 1 of 1 runs passed |
<!-- driver:evidence:end -->
