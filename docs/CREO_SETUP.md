# Creo installation prerequisites

Everything this CLI does beyond reading files on disk goes through a Creo API, and
those APIs are **optional components chosen when Creo is installed**. Selecting them
costs nothing and adds a few GB; missing them is not recoverable without re-running
the installer, and on some deliveries not recoverable at all.

Read this before installing Creo, not after.

## What to select

In the Creo installer, on the **Customize Application** step, expand **API Toolkits**:

| Component | Needed for | Required? |
|---|---|---|
| **Creo Object TOOLKIT Java** | Everything. Ships `pfcasync.jar` (J-Link) and `otk.jar`. | **Yes** |
| VB API for Creo Parametric | The independent native COM route, a second way in | Recommended |
| Creo Parametric Toolkit | C API, if a future backend needs it | Optional |
| Creo Object TOOLKIT C++ | C++ API, same | Optional |

**Do not look for a component called "J-Link".** There has not been one since Creo
4.0; J-Link is installed as part of Creo Object TOOLKIT Java, and is free with a Creo
seat. That naming gap is the single most expensive thing to discover late.

Nothing else in the installer matters here. Extensions (Simulation Live, Ansys, Flow
Analysis, Mold Analysis and so on) are separately licensed and unrelated; selecting
them only costs disk space and menu clutter.

## What it looks like when it worked

```bash
creo-cli doctor --compact
```

```
pass  creo_api_toolkit   pfcasync.jar found at <load point>\Common Files\text\java\pfcasync.jar
```

A `fail` on that check names the missing file and the component that ships it. The
probe finds the installation by enumerating the standard load points, so it works
whether Creo landed in `C:\Program Files\PTC` or somewhere like
`D:\PTC\Creo13.4\Creo 13.4.1.0`.

## Java, for the creation route only

Creo 13.4 requires **Java 25**, and starts a synchronous Object TOOLKIT Java
application in a JVM it launches itself. When it cannot find a suitable one the
application fails while loading -- before any of its own code runs, so there is no
application log to read and the only symptom is Creo reporting that the start failed.

Point Creo at a Java 25 runtime explicitly rather than relying on detection:

```powershell
setx PRO_JAVA_COMMAND "<jdk25 install dir>\bin\java.exe"
```

Then restart Creo; the variable does not reach a running process. `PRO_JAVA_COMMAND`
takes precedence over the `jlink_java_command` config option. `doctor` reports this as
`creo_otk_java_runtime`.

The CREOSON route does not need this: that service runs outside Creo in a JVM of its
own choosing.

## Licensing

J-Link needs no license module. Reading models, editing parameters and dimensions,
family tables, drawings and exports all run on it.

**Creating geometry is different.** Feature creation lives in the `wfc` namespace of
`otk.jar`, which J-Link does not ship, and reaching it requires the
`ObjectToolkitJava` license module. Check what a seat actually carries:

```
<Creo load point>\Parametric\bin\ptcstatus.bat
```

Look for `TOOLKIT`, `ObjectToolkit` and `ObjectToolkitJava`. Without them the CLI
still does everything on the J-Link route; it cannot create features.

## Deliveries that cannot be fixed

A Creo trial delivered through an application-streaming player (Numecent Cloudpaging,
which PTC uses for its trial program) excludes the API toolkits and has **no installer
to re-run** — the application executes from an encrypted sandbox rather than being
installed. `doctor` detects this and says so rather than suggesting an installer run
that cannot happen. Such a trial cannot be used with this CLI at all; a standard
licensed installation is required.
