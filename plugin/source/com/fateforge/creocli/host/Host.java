package com.fateforge.creocli.host;

import com.fateforge.creocli.host.core.HostError;
import com.fateforge.creocli.host.core.Json;
import com.fateforge.creocli.host.core.MainThread;
import com.fateforge.creocli.host.core.Pipe;
import com.fateforge.creocli.host.core.Protocol;
import com.ptc.cipjava.stringseq;
import com.ptc.pfc.pfcGlobal.pfcGlobal;
import com.ptc.pfc.pfcSession.Session;
import com.ptc.wfc.wfcSession.Timer;
import com.ptc.wfc.wfcSession.TimerAction_u;
import com.ptc.wfc.wfcSession.wfcSession;

import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.security.SecureRandom;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Optional;

/**
 * The host component of creo-cli (DCLI-262): an Object TOOLKIT Java application Creo starts
 * from its registry file. {@link #start()} and {@link #stop()} are the entry points named
 * there; Creo calls both on its main thread.
 *
 * <p>At start the host finds its state directory, works out the session ID of this Creo
 * process exactly as the CLI does (DCLI-203), starts a timer that hands queued requests to
 * the main thread every 100 ms (DCLI-276), opens a named pipe only the current user can
 * reach (DCLI-270) and writes its discovery file to hosts/ (DCLI-271).
 */
public final class Host {
    public static final String PLUGIN_VERSION = "1.0.0";
    public static final String PROTOCOL_VERSION = "1.2.0";
    static final String CONFIG_FILE = "creo-cli-host.json";
    private static final int PUMP_MICROSECONDS = 100_000;
    private static final long PICKUP_MS = 1500;
    private static final List<String> METHODS = Arrays.asList(
            "documents", "open_doc", "save_doc", "close_doc", "read", "preview", "apply", "read_back");

    private static Host running;

    private final Path stateDir;
    private final Path home;
    private final String sessionId;
    private final long pid;
    private final int generation;
    private final String applicationVersion;
    private final MainThread main = new MainThread(PICKUP_MS);
    private final Docs docs;
    private final Ops ops;
    private Pipe pipe;
    private Timer timer;
    private Path discovery;

    private Host(Path stateDir, Path home, long pid, String sessionId, String applicationVersion) {
        this.stateDir = stateDir;
        this.home = home;
        this.pid = pid;
        this.sessionId = sessionId;
        this.applicationVersion = applicationVersion;
        this.generation = nextGeneration(home, sessionId);
        this.docs = new Docs(sessionId);
        this.ops = new Ops(docs);
    }

    // ------------------------------------------------------------------ entry points

    public static synchronized void start() {
        if (running != null) {
            return;
        }
        try {
            Session session = pfcGlobal.GetProESession();
            Path[] where = locate(session);
            Path state = where[0];
            Path home = where[1];
            long pid = creoPid();
            String id = sessionId(pid);
            String version = String.valueOf(pfcGlobal.GetProEVersion());
            Host host = new Host(state, home, pid, id, version);
            host.docs.listen(session);
            host.timer = wfcSession.CreateTimer(new TimerAction_u() {
                @Override
                public boolean OnTimer() {
                    host.main.pump();
                    return true;
                }
            });
            host.timer.Start(wfcSession.TimeValue_Create(0, PUMP_MICROSECONDS));
            host.pipe = new Pipe("creo-cli-" + id + "-" + random(), stream -> Protocol.serve(stream, host::call));
            host.pipe.start();
            host.discovery = host.writeDiscovery();
            running = host;
            log(home, "started " + id + " generation " + host.generation + " on " + host.pipe.name);
        } catch (Throwable failure) {
            log(fallbackHome(), "start failed: " + failure);
        }
    }

    public static synchronized void stop() {
        Host host = running;
        running = null;
        if (host == null) {
            return;
        }
        try {
            if (host.discovery != null) {
                Files.deleteIfExists(host.discovery);
            }
        } catch (Throwable ignored) {
            // A stale file names a process that is gone; session list drops it.
        }
        if (host.pipe != null) {
            host.pipe.stop();
        }
        try {
            if (host.timer != null) {
                host.timer.Stop();
                host.timer.Destroy();
            }
        } catch (Throwable ignored) {
            // Creo is stopping the application anyway.
        }
        log(host.home, "stopped " + host.sessionId);
    }

    // ------------------------------------------------------------------ methods

    /** One request from a pipe thread: hello here, everything else on the main thread. */
    private Object call(String method, Map<String, Object> params) {
        Long deadline = Json.integer(params, "deadline_ms");
        long deadlineMs = deadline == null ? 5000 : Math.max(1, deadline);
        if ("hello".equals(method)) {
            return hello(params);
        }
        if (!METHODS.contains(method)) {
            throw new HostError(HostError.UNSUPPORTED, "This host has no method " + method + ".");
        }
        boolean write = Arrays.asList("open_doc", "save_doc", "close_doc", "apply").contains(method);
        return main.submit(() -> {
            try {
                return run(method, params);
            } catch (HostError refused) {
                throw refused;
            } catch (com.ptc.cipjava.jxthrowable refused) {
                throw new HostError(HostError.NATIVE, "Creo refused " + method + ".", write ? "unknown" : "not_started")
                        .nativeMessage(refused.toString());
            } catch (RuntimeException failure) {
                throw new HostError(HostError.NATIVE, "The host failed in " + method + ": " + failure,
                        write ? "unknown" : "not_started");
            }
        }, deadlineMs);
    }

    private Object run(String method, Map<String, Object> params) throws Exception {
        switch (method) {
            case "documents":
                return Json.map("items", docs.list());
            case "open_doc":
                return docs.open(required(params, "path"));
            case "save_doc":
                return docs.save(docs.model(required(params, "document")));
            case "close_doc":
                return docs.close(docs.model(required(params, "document")), Boolean.TRUE.equals(Json.bool(params, "discard")));
            case "read":
                return ops.read(params);
            case "preview":
                return ops.preview(params);
            case "apply":
                return ops.apply(params);
            default:
                return ops.readBack(params);
        }
    }

    private static String required(Map<String, Object> params, String key) {
        String value = Json.string(params, key, null);
        if (value == null || value.isEmpty()) {
            throw new HostError(HostError.VALIDATION, "The request has no " + key + ".");
        }
        return value;
    }

    private Map<String, Object> hello(Map<String, Object> params) {
        return Json.map(
                "protocol_version", PROTOCOL_VERSION,
                "plugin_version", PLUGIN_VERSION,
                "application", Json.map("name", "Creo Parametric", "version", applicationVersion),
                "session", Json.map("id", sessionId, "generation", generation),
                "methods", METHODS);
    }

    // ------------------------------------------------------------------ session identity

    /**
     * The Creo process: xtop.exe itself when the JVM runs inside it, otherwise the nearest
     * xtop.exe among the JVM's ancestors.
     */
    static long creoPid() {
        ProcessHandle process = ProcessHandle.current();
        for (int depth = 0; process != null && depth < 4; depth++) {
            Optional<String> command = process.info().command();
            if (command.isPresent() && command.get().toLowerCase(Locale.ROOT).endsWith("xtop.exe")) {
                return process.pid();
            }
            process = process.parent().orElse(null);
        }
        throw new IllegalStateException("no xtop.exe among the JVM's process and its ancestors");
    }

    /**
     * creo-{pid}-{start}, exactly as the CLI's session_id builds it: the start is the
     * process creation time in whole seconds of the Windows FILETIME (since 1601).
     */
    static String sessionId(long pid) {
        Instant started = ProcessHandle.of(pid).flatMap(p -> p.info().startInstant())
                .orElseThrow(() -> new IllegalStateException("the start time of process " + pid + " is unknown"));
        long filetimeSeconds = Math.floorDiv(started.toEpochMilli(), 1000L) + 11_644_473_600L;
        return "creo-" + pid + "-" + Long.toHexString(filetimeSeconds);
    }

    /** How many times a host started in this Creo process: the session's generation (DCLI-203). */
    /** The generation counters live in the host's own folder, sessions/, one per Creo process. */
    private static int nextGeneration(Path home, String sessionId) {
        Path file = home.resolve("sessions").resolve(sessionId + ".generation");
        forgetEndedSessions(file.getParent());
        int next = 0;
        try {
            if (Files.isRegularFile(file)) {
                next = Integer.parseInt(new String(Files.readAllBytes(file), StandardCharsets.UTF_8).trim()) + 1;
            }
            Files.createDirectories(file.getParent());
            Files.write(file, String.valueOf(next).getBytes(StandardCharsets.UTF_8));
        } catch (IOException | NumberFormatException unreadable) {
            return next;
        }
        return next;
    }

    /** The generation files of Creo processes that have ended (creo-PID-START.generation); each Creo start leaves one. */
    private static void forgetEndedSessions(Path hosts) {
        try (java.util.stream.Stream<Path> files = Files.list(hosts)) {
            files.forEach(path -> {
                java.util.regex.Matcher name = java.util.regex.Pattern.compile("^creo-([0-9]+)-[0-9a-f]+\\.generation$")
                        .matcher(path.getFileName().toString());
                if (name.matches() && ProcessHandle.of(Long.parseLong(name.group(1))).isEmpty()) {
                    try {
                        Files.deleteIfExists(path);
                    } catch (IOException ignored) {
                        // Another host removes it next time.
                    }
                }
            });
        } catch (IOException | RuntimeException unreadable) {
            // No hosts folder yet, or it cannot be listed: nothing to forget.
        }
    }

    // ------------------------------------------------------------------ state directory and discovery

    /**
     * The state directory plugin install wrote into the host's configuration, and the host's own
     * folder, where that configuration is: the creo-cli-host.json beside the registry file Creo
     * loaded -- named by toolkit_registry_file in config.pro, or protk.dat in the folder Creo
     * started in. Without one: CREO_CLI_STATE_DIR, else ~/.creo-cli, and %LOCALAPPDATA%\creo-cli\host.
     * The host writes only its discovery file into the state directory (DSEC-031).
     */
    static Path[] locate(Session session) {
        List<String> registries = new ArrayList<>();
        for (String option : new String[] {"toolkit_registry_file", "protkdat", "creotkdat"}) {
            try {
                stringseq values = session.GetConfigOptionValues(option);
                for (int i = 0; values != null && i < values.getarraysize(); i++) {
                    registries.add(values.get(i));
                }
            } catch (Throwable none) {
                // Not set.
            }
        }
        registries.add(new File(System.getProperty("user.dir", "."), "protk.dat").getPath());
        for (String registry : registries) {
            Path config = new File(registry.trim()).getAbsoluteFile().toPath().resolveSibling(CONFIG_FILE);
            if (Files.isRegularFile(config)) {
                try {
                    Object parsed = Json.parse(new String(Files.readAllBytes(config), StandardCharsets.UTF_8));
                    if (parsed instanceof Map) {
                        @SuppressWarnings("unchecked")
                        String dir = Json.string((Map<String, Object>) parsed, "state_dir", null);
                        if (dir != null && !dir.isEmpty()) {
                            return new Path[] {new File(dir).toPath(), config.getParent()};
                        }
                    }
                } catch (IOException | IllegalArgumentException unreadable) {
                    // Try the next one.
                }
            }
        }
        return new Path[] {fallbackState(), fallbackHome()};
    }

    private static Path fallbackHome() {
        String local = System.getenv("LOCALAPPDATA");
        File base = local != null && !local.isEmpty() ? new File(local)
                : new File(System.getProperty("user.home", "."), "AppData\\Local");
        return new File(new File(base, "creo-cli"), "host").toPath();
    }

    private static Path fallbackState() {
        String env = System.getenv("CREO_CLI_STATE_DIR");
        if (env != null && !env.isEmpty()) {
            return new File(env).toPath();
        }
        return new File(System.getProperty("user.home", "."), ".creo-cli").toPath();
    }

    private Path writeDiscovery() throws IOException {
        Path hosts = stateDir.resolve("hosts");
        Files.createDirectories(hosts);
        Path file = hosts.resolve(sessionId + ".json");
        Map<String, Object> data = Json.map(
                "address", pipe.name,
                "pid", pid,
                "application", Json.map("name", "Creo Parametric", "version", applicationVersion),
                "protocol_version", PROTOCOL_VERSION,
                "plugin_version", PLUGIN_VERSION,
                "started_at", Instant.now().truncatedTo(ChronoUnit.SECONDS).toString());
        Path temp = hosts.resolve(sessionId + ".json.tmp");
        Files.write(temp, Json.write(data).getBytes(StandardCharsets.UTF_8));
        Files.move(temp, file, StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE);
        return file;
    }

    private static String random() {
        byte[] bytes = new byte[8];
        new SecureRandom().nextBytes(bytes);
        StringBuilder hex = new StringBuilder();
        for (byte b : bytes) {
            hex.append(String.format("%02x", b));
        }
        return hex.toString();
    }

    private static void log(Path home, String line) {
        try {
            Files.createDirectories(home);
            Files.write(home.resolve("host.log"),
                    (Instant.now().truncatedTo(ChronoUnit.SECONDS) + " " + line + System.lineSeparator()).getBytes(StandardCharsets.UTF_8),
                    java.nio.file.StandardOpenOption.CREATE, java.nio.file.StandardOpenOption.APPEND);
        } catch (Throwable ignored) {
            // Nowhere left to write.
        }
    }
}
