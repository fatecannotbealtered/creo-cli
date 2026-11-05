# Creo Parametric Capability Survey

English | [中文](APPLICATION_zh.md)

This survey records what Creo Parametric can do and how it can be automated. It is filled in before commands are designed: every domain command of creo-cli names the capability IDs it implements, and every capability has a disposition.

## Application

- Name: Creo Parametric
- Vendor: {{fill: the vendor of Creo Parametric}}
- Versions surveyed: {{fill: the Creo Parametric versions this survey was made on; creo-cli supports >=13.4 <13.5}}

The operating systems and CPU architectures on which Creo Parametric runs, or in device mode the device driver or SDK; the platform packages of creo-cli follow from this table:

| Operating system | CPU architectures |
|---|---|
| Windows | x64 |

{{fill: check the table: keep only the rows of the systems on which Creo Parametric (in device mode, the device driver or SDK) runs, and add arm64 where it also runs on arm64; systems are Windows, macOS or Linux, architectures x64 or arm64, comma-separated; then replace this line with the source of these facts}}

## Automation Interfaces

Every interface Creo Parametric offers, and where code that calls it must run. An interface the CLI can call is used from the adapter layer in `creo_cli/adapter/`. An interface that works only inside the process of Creo Parametric or on its main thread needs a host component in `plugin/`.

| Interface | Called from | Notes |
|---|---|---|
| {{fill: an interface, such as a Python API, COM, the command line of Creo Parametric, a file format, a plugin SDK or a script language}} | {{fill: the CLI, or only inside the process or on the main thread}} | {{fill: version limits, licensing or stability notes}} |

## Object Model

{{fill: the objects of Creo Parametric, from documents down to the objects inside them, with their names in the user interface and the manual; these names become command nouns}}

## Units and Coordinates

{{fill: the internal units and the display units, the origin and axis directions of each coordinate system, and how angles are measured}}

## Threading and Blocking

{{fill: the main-thread rules, how Creo Parametric shows that it is busy, and the dialogs that block automation, such as license, save, error and update dialogs}}

## Read-back

{{fill: for each kind of change, how creo-cli can read it back and how exactly: rounding, snapping to a grid, tolerances}}

## Save and Undo

{{fill: how saving works, how unsaved changes show, whether save-as exists, and whether undo exists and through which interface}}

## Instances and Concurrency

{{fill: whether several instances can run at once, how to tell them apart, and what happens when a person works in Creo Parametric at the same time}}

## Licensing

{{fill: the license types, which license automation needs, and the license dialogs Creo Parametric shows}}

## Capabilities

Each capability has one row with an ID `CAP-nnn`, unique in this survey, and one disposition: `provided` (a domain command offers it), `deferred` (worth offering, left for a later version), `excluded` (will not be offered, for example because it is unsafe or cannot be automated reliably) or `unknown` (not yet known whether Creo Parametric allows it). Every row names the interface that reaches the capability; a row other than `provided` gives the reason in one line.

| ID | Capability | Interface | Disposition | Reason |
|---|---|---|---|---|
| CAP-001 | {{fill: a capability of Creo Parametric}} | {{fill: the interface that reaches it}} | unknown | {{fill: why, or - when provided}} |

## Risks

Each risk or limit found in the survey becomes an entry in `knowledge/`, or gives here the reason it is left out.

{{fill: the risks and limits found in the survey, one list item each, with the knowledge entry it became or the reason it has none}}
