package com.fateforge.creocli.otk;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;

import java.io.IOException;
import java.io.OutputStream;
import java.io.PrintWriter;
import java.io.StringWriter;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardOpenOption;
import java.time.Instant;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicReference;

/**
 * Creo-side half of creo-cli: a loopback HTTP endpoint running inside Creo.
 *
 * <p>This lives in Creo's process rather than beside it because that is the only place
 * the geometry-creating API exists. Object TOOLKIT Java has no asynchronous connection
 * — {@code otk.jar} ships no {@code AsyncConnection} class and its method list contains
 * no asynchronous entry point — while the asynchronous library, {@code pfcasync.jar},
 * carries only the {@code pfc} domain and therefore cannot create features. Creation
 * lives in {@code wfc}, and {@code wfc} is reachable only from a synchronous
 * application that Creo itself loads.
 *
 * <p>Being a guest in someone else's process sets the rules for everything here:
 *
 * <ul>
 *   <li>{@code start} returns promptly. Creo calls it on its own thread and waits.
 *   <li>Nothing throws out of {@code start} or {@code stop}. An exception escaping
 *       into Creo is a failure of this program presented to the user as a failure of
 *       their CAD system.
 *   <li>The listener binds the loopback address explicitly, never a wildcard.
 *   <li>Diagnostics go to a file. There is no console to write to, and stdout inside
 *       Creo belongs to Creo.
 * </ul>
 *
 * <p>This first version deliberately separates two questions that are easy to confuse
 * when something does not work: {@code /health} touches no Creo API at all and answers
 * "did Creo load and run this code", while {@code /session} makes one API call and
 * answers "does the Object TOOLKIT license activate for it". A single endpoint doing
 * both would report one failure for two very different causes.
 */
public final class Service {

    /** Matches creo-cli's default endpoint; overridable for a second Creo session. */
    private static final int DEFAULT_PORT = 9057;
    private static final String PORT_PROPERTY = "creocli.otk.port";
    private static final String LOG_PROPERTY = "creocli.otk.log";
    /** Small: this endpoint serves one local client, not a farm. */
    private static final int BACKLOG = 4;
    /** Bounded so a stop during a request cannot hang Creo's shutdown. */
    private static final int STOP_GRACE_SECONDS = 2;
    /** Small pool, not the dispatch thread: one slow handler must not wedge the rest. */
    private static final int HANDLER_THREADS = 2;

    private static final AtomicReference<HttpServer> RUNNING = new AtomicReference<>();
    /**
     * What the toolkit told us during {@link #start()}, which is the only moment we are
     * on the thread Creo drives.
     *
     * <p>Calling the toolkit from a request thread blocks: Creo spawns this JVM and
     * talks to it over a socket, and the connection is serviced by the thread Creo
     * calls into, not by ours. Observed directly -- a probe issued from a handler never
     * returned and, because handlers then ran on the dispatch thread, took the whole
     * endpoint with it. The session is therefore read once, here, and reported from
     * cache until there is a way to hand work back to that thread.
     */
    private static final AtomicReference<String> TOOLKIT_REPORT = new AtomicReference<>();

    private Service() {
    }

    /** Registry entry point. Public, static, void, no arguments — required by Creo. */
    public static void start() {
        try {
            if (RUNNING.get() != null) {
                log("start called while already running; ignoring");
                return;
            }
            HttpServer server = HttpServer.create(
                    new InetSocketAddress(InetAddress.getLoopbackAddress(), port()), BACKLOG);
            server.createContext("/health", Service::health);
            server.createContext("/session", Service::session);
            server.setExecutor(Executors.newFixedThreadPool(HANDLER_THREADS, runnable -> {
                Thread thread = new Thread(runnable, "creo-cli-otk-http");
                thread.setDaemon(true);
                return thread;
            }));
            server.start();
            RUNNING.set(server);
            log("listening on " + server.getAddress());
            // Still on Creo's thread here, so this is the one place the toolkit answers.
            TOOLKIT_REPORT.set(probeToolkit());
            log("toolkit probe: " + TOOLKIT_REPORT.get());
        } catch (Throwable failure) {
            // Creo called us; it must not receive an exception for our problem.
            log("start failed: " + describe(failure));
        }
    }

    /** Registry entry point, same contract as {@link #start()}. */
    public static void stop() {
        try {
            HttpServer server = RUNNING.getAndSet(null);
            if (server == null) {
                log("stop called while not running; ignoring");
                return;
            }
            server.stop(STOP_GRACE_SECONDS);
            log("stopped");
        } catch (Throwable failure) {
            log("stop failed: " + describe(failure));
        }
    }

    /**
     * Liveness only. Touches no Creo API, so a success here means exactly one thing:
     * Creo loaded this class and is running it.
     */
    private static void health(HttpExchange exchange) throws IOException {
        respond(exchange, 200, "{\"ok\":true,\"service\":\"creo-cli-otk\",\"checked\":\"process_only\"}");
    }

    /** Reports what the toolkit answered at startup. Makes no call of its own. */
    private static void session(HttpExchange exchange) throws IOException {
        String report = TOOLKIT_REPORT.get();
        respond(exchange, 200, report == null
                ? "{\"ok\":false,\"error\":\"toolkit was not probed; start() did not complete\"}"
                : report);
    }

    /**
     * One Object TOOLKIT call, made on Creo's own thread during startup.
     *
     * <p>Reaching the session proves the licence activated for this application, which
     * is the question a liveness check cannot answer. Reflection rather than a direct
     * reference keeps this class loadable when {@code otk.jar} is absent: the failure
     * is then a readable message here instead of a {@code NoClassDefFoundError} while
     * Creo is loading the application, which is far harder to see from the Creo side.
     */
    private static String probeToolkit() {
        try {
            Class<?> global = Class.forName("com.ptc.pfc.pfcGlobal.pfcGlobal");
            Object creoSession = global.getMethod("GetProESession").invoke(null);
            String version = String.valueOf(global.getMethod("GetProEVersion").invoke(null));
            String build = String.valueOf(global.getMethod("GetProEBuildCode").invoke(null));
            return "{\"ok\":true,\"probed\":\"at_startup\""
                    + ",\"session_reachable\":" + (creoSession != null)
                    + ",\"creo_version\":\"" + escape(version) + "\""
                    + ",\"creo_build\":\"" + escape(build) + "\"}";
        } catch (Throwable failure) {
            return "{\"ok\":false,\"probed\":\"at_startup\",\"error\":\""
                    + escape(describe(failure)) + "\"}";
        }
    }

    private static void respond(HttpExchange exchange, int status, String body) throws IOException {
        byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().add("Content-Type", "application/json; charset=utf-8");
        exchange.sendResponseHeaders(status, bytes.length);
        try (OutputStream out = exchange.getResponseBody()) {
            out.write(bytes);
        }
    }

    private static int port() {
        String configured = System.getProperty(PORT_PROPERTY);
        if (configured == null || configured.isEmpty()) {
            return DEFAULT_PORT;
        }
        try {
            int value = Integer.parseInt(configured.trim());
            return value >= 1024 && value <= 65535 ? value : DEFAULT_PORT;
        } catch (NumberFormatException ignored) {
            return DEFAULT_PORT;
        }
    }

    private static String describe(Throwable failure) {
        Throwable cause = failure;
        while (cause.getCause() != null && cause.getCause() != cause) {
            cause = cause.getCause();
        }
        String message = cause.getMessage();
        return cause.getClass().getName() + (message == null ? "" : ": " + message);
    }

    private static String escape(String value) {
        StringBuilder out = new StringBuilder(value.length() + 16);
        for (int i = 0; i < value.length(); i++) {
            char c = value.charAt(i);
            switch (c) {
                case '"': out.append("\\\""); break;
                case '\\': out.append("\\\\"); break;
                case '\n': out.append("\\n"); break;
                case '\r': out.append("\\r"); break;
                case '\t': out.append("\\t"); break;
                default:
                    if (c < 0x20) {
                        out.append(String.format("\\u%04x", (int) c));
                    } else {
                        out.append(c);
                    }
            }
        }
        return out.toString();
    }

    /**
     * Append one line to the log file, swallowing every failure.
     *
     * <p>Logging that can throw would defeat its own purpose here: these calls sit in
     * the catch blocks that keep exceptions away from Creo. A full stack trace is kept
     * for start failures because that is the case with no other evidence anywhere.
     */
    private static void log(String message) {
        try {
            Path path = logPath();
            Files.createDirectories(path.getParent());
            StringWriter line = new StringWriter();
            new PrintWriter(line).printf("%s  %s%n", Instant.now(), message);
            Files.write(path, line.toString().getBytes(StandardCharsets.UTF_8),
                    StandardOpenOption.CREATE, StandardOpenOption.APPEND);
        } catch (Throwable ignored) {
            // Nothing to fall back to: no console, and Creo's stdout is not ours.
        }
    }

    private static Path logPath() {
        String configured = System.getProperty(LOG_PROPERTY);
        if (configured != null && !configured.isEmpty()) {
            return Paths.get(configured);
        }
        String home = System.getProperty("user.home", ".");
        return Paths.get(home, ".creo-cli", "otk-service.log");
    }
}
