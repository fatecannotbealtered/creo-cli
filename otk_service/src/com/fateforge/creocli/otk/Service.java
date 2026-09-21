package com.fateforge.creocli.otk;

import com.ptc.pfc.pfcGlobal.pfcGlobal;
import com.ptc.pfc.pfcSession.Session;
import com.ptc.wfc.wfcSession.Timer;
import com.ptc.wfc.wfcSession.TimerAction_u;
import com.ptc.wfc.wfcSession.WSession;
import com.ptc.wfc.wfcSession.wfcSession;
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
import java.util.concurrent.BlockingQueue;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.Executors;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import java.util.concurrent.atomic.AtomicReference;

/**
 * Creo-side half of creo-cli: a loopback HTTP endpoint running inside Creo.
 *
 * <p>This lives in Creo's process rather than beside it because that is the only place
 * the geometry-creating API exists. Object TOOLKIT Java has no asynchronous connection
 * — {@code otk.jar} ships no {@code AsyncConnection} class — while the asynchronous
 * library, {@code pfcasync.jar}, carries only the {@code pfc} domain and not one of the
 * 2122 {@code wfc} classes. Creation lives in {@code wfc}, and {@code wfc} is reachable
 * only from a synchronous application that Creo itself loads.
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
 *   <li><b>No toolkit call happens on an HTTP thread.</b> See {@link #onToolkitThread}.
 * </ul>
 *
 * <p>{@code /health} touches no Creo API at all and answers "did Creo load and run this
 * code"; {@code /session} answers "does the Object TOOLKIT license activate for it".
 * Keeping them apart means a failure names its own cause instead of one endpoint
 * reporting two very different problems identically.
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
    private static final int HANDLER_THREADS = 4;
    /**
     * How long a request waits for Creo to come back to us. Generous, because the wait
     * is for a person: the toolkit thread is busy while a dialog is open or a
     * regeneration is running, and neither is an error.
     */
    private static final long TOOLKIT_TIMEOUT_SECONDS = 120;
    /**
     * How often Creo is asked to come back to us. Ten times a second: below what anyone
     * would notice as latency on a command, and far below what a CAD session notices as
     * load.
     */
    private static final int PUMP_PERIOD_MICROSECONDS = 100_000;
    /** Queued work run per tick, so a long queue cannot hold Creo's thread. */
    private static final int MAX_JOBS_PER_TICK = 8;

    private static final AtomicReference<HttpServer> RUNNING = new AtomicReference<>();
    /** The thread Creo drives, recorded so we can recognise it and never queue behind it. */
    private static final AtomicReference<Thread> TOOLKIT_THREAD = new AtomicReference<>();
    private static final AtomicReference<String> STARTUP_REPORT = new AtomicReference<>();
    /** Work waiting for the toolkit thread. Plain Java: no Creo API is involved in queuing. */
    private static final BlockingQueue<Runnable> QUEUE = new LinkedBlockingQueue<>();
    private static final AtomicReference<Timer> PUMP = new AtomicReference<>();

    private Service() {
    }

    /** Registry entry point. Public, static, void, no arguments — required by Creo. */
    public static void start() {
        try {
            if (RUNNING.get() != null) {
                log("start called while already running; ignoring");
                return;
            }
            // Creo calls start() on the toolkit thread, which is the one thread allowed
            // to talk to it. Everything else in this class routes work back here.
            TOOLKIT_THREAD.set(Thread.currentThread());

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

            STARTUP_REPORT.set(describeSession());
            log("session at startup: " + STARTUP_REPORT.get());
            startPump();
            log("toolkit pump running every " + (PUMP_PERIOD_MICROSECONDS / 1000) + "ms");
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
            Timer pump = PUMP.getAndSet(null);
            if (pump != null) {
                pump.Stop();
                pump.Destroy();
            }
            log("stopped");
        } catch (Throwable failure) {
            log("stop failed: " + describe(failure));
        }
    }

    /**
     * Run {@code work} on the thread Creo drives, and wait for its answer.
     *
     * <p>The toolkit is single-threaded in a way that is structural rather than merely
     * undocumented: Creo spawns this JVM and talks to it over one socket whose framing
     * carries no request identifiers, and the Java side keeps one static connection for
     * the whole process. Two threads calling at once would interleave halves of two
     * conversations, so a toolkit call issued from an HTTP thread simply never returns.
     * {@code wfcSession.InvokeLater} does not escape that — its own bytecode sends on
     * that same connection and then runs the dispatch loop on the calling thread.
     *
     * <p>So nothing here calls Creo from an HTTP thread. Work goes into an ordinary Java
     * queue, and the only thing that touches Creo is {@link #pump}, a toolkit timer
     * created on the toolkit thread during {@link #start()} and fired by Creo on that
     * same thread from then on. A request arriving while a dialog is open waits instead
     * of failing, because the queue simply is not drained until Creo comes back.
     *
     * <p>Calls that are already on the toolkit thread run inline. Queueing them would
     * deadlock: the pump cannot run until the thread waiting for it returns.
     */
    static <T> T onToolkitThread(ToolkitWork<T> work) throws Exception {
        if (Thread.currentThread() == TOOLKIT_THREAD.get()) {
            return work.run();
        }
        if (PUMP.get() == null) {
            throw new IllegalStateException("the toolkit pump is not running; "
                    + "see " + logPath() + " for what happened during start");
        }
        CompletableFuture<T> answer = new CompletableFuture<>();
        QUEUE.add(() -> {
            try {
                answer.complete(work.run());
            } catch (Throwable failure) {
                // Must not propagate: this runs inside a callback Creo is making.
                answer.completeExceptionally(failure);
            }
        });
        try {
            return answer.get(TOOLKIT_TIMEOUT_SECONDS, TimeUnit.SECONDS);
        } catch (ExecutionException wrapped) {
            Throwable cause = wrapped.getCause();
            throw cause instanceof Exception ? (Exception) cause : new IllegalStateException(cause);
        } catch (TimeoutException expired) {
            throw new IllegalStateException("Creo did not become free within "
                    + TOOLKIT_TIMEOUT_SECONDS + "s; it is most likely waiting for input", expired);
        }
    }

    /**
     * Ask Creo to call us back regularly, and drain the queue when it does.
     *
     * <p>Created here because here we are on the toolkit thread. Everything the timer
     * runs is therefore on that thread too, which is the entire point: the queue is
     * plain Java, and the only Creo API involved in the hand-off is this timer.
     */
    private static void startPump() throws Exception {
        Timer pump = wfcSession.CreateTimer(new TimerAction_u() {
            @Override
            public boolean OnTimer() {
                drain();
                return true;
            }
        });
        pump.Start(wfcSession.TimeValue_Create(0, PUMP_PERIOD_MICROSECONDS));
        PUMP.set(pump);
    }

    /**
     * Run what is waiting, bounded.
     *
     * <p>The bound matters more than it looks: this runs on the thread Creo needs back
     * to stay responsive, so a burst of queued work is spread over several ticks rather
     * than holding the CAD system for as long as the queue is long.
     */
    private static void drain() {
        for (int done = 0; done < MAX_JOBS_PER_TICK; done++) {
            Runnable job = QUEUE.poll();
            if (job == null) {
                return;
            }
            try {
                job.run();
            } catch (Throwable failure) {
                log("a queued job threw past its own handler: " + describe(failure));
            }
        }
    }

    /** Work that needs Creo. Handed to {@link #onToolkitThread} rather than called directly. */
    interface ToolkitWork<T> {
        T run() throws Exception;
    }

    /**
     * Liveness only. Touches no Creo API, so a success here means exactly one thing:
     * Creo loaded this class and is running it.
     */
    private static void health(HttpExchange exchange) throws IOException {
        respond(exchange, 200, "{\"ok\":true,\"service\":\"creo-cli-otk\",\"checked\":\"process_only\"}");
    }

    /**
     * Reads the session now, from this HTTP thread, by way of the toolkit thread.
     *
     * <p>Answering from a cache would be cheaper and would prove nothing. The point of
     * this endpoint is that the hand-off works on a live request.
     */
    private static void session(HttpExchange exchange) throws IOException {
        String body;
        try {
            body = onToolkitThread(Service::describeSession);
        } catch (Exception failure) {
            body = "{\"ok\":false,\"error\":\"" + escape(describe(failure)) + "\""
                    + ",\"at_startup\":" + (STARTUP_REPORT.get() == null ? "null" : STARTUP_REPORT.get()) + "}";
        }
        respond(exchange, 200, body);
    }

    /**
     * One reading of the session. Must run on the toolkit thread.
     *
     * <p>Whether the session casts to {@link WSession} is the question that decides what
     * this tool can do: {@code WSession} is where element trees are built, and element
     * trees are how features are created. A J-Link application gets a plain
     * {@code Session} here and can modify a model but never create one.
     */
    private static String describeSession() {
        try {
            Session session = pfcGlobal.GetProESession();
            boolean creation = session instanceof WSession;
            return "{\"ok\":true"
                    + ",\"session_reachable\":" + (session != null)
                    + ",\"session_class\":\"" + escape(session == null ? "null" : session.getClass().getName()) + "\""
                    + ",\"creation_api\":" + creation
                    + ",\"creo_version\":\"" + escape(String.valueOf(pfcGlobal.GetProEVersion())) + "\""
                    + ",\"creo_build\":\"" + escape(String.valueOf(pfcGlobal.GetProEBuildCode())) + "\""
                    + ",\"working_directory\":\"" + escape(session == null ? "" : session.GetCurrentDirectory()) + "\""
                    + ",\"thread\":\"" + escape(Thread.currentThread().getName()) + "\"}";
        } catch (Throwable failure) {
            return "{\"ok\":false,\"error\":\"" + escape(describe(failure)) + "\"}";
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
     * the catch blocks that keep exceptions away from Creo.
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
