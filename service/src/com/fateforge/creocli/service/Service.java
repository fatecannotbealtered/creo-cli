package com.fateforge.creocli.service;

import com.ptc.pfc.pfcGlobal.pfcGlobal;
import com.ptc.pfc.pfcSession.Session;
import com.ptc.wfc.wfcSession.Timer;
import com.ptc.wfc.wfcSession.TimerAction_u;
import com.ptc.wfc.wfcSession.WSession;
import com.ptc.wfc.wfcSession.wfcSession;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
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
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.BlockingQueue;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.Executors;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.ConcurrentHashMap;

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
    private static final String PORT_PROPERTY = "creocli.service.port";
    private static final String LOG_PROPERTY = "creocli.service.log";
    /** Small: this endpoint serves one local client, not a farm. */
    private static final int BACKLOG = 4;
    /** Bounded so a stop during a request cannot hang Creo's shutdown. */
    private static final int STOP_GRACE_SECONDS = 2;
    /** Small pool, not the dispatch thread: one slow handler must not wedge the rest. */
    private static final int HANDLER_THREADS = 4;
    /**
     * How often Creo is asked to come back to us. Ten times a second: below what anyone
     * would notice as latency on a command, and far below what a CAD session notices as
     * load.
     */
    private static final int PUMP_PERIOD_MICROSECONDS = 100_000;
    /** Queued work run per tick, so a long queue cannot hold Creo's thread. */
    private static final int MAX_JOBS_PER_TICK = 8;
    /** Requests are small JSON documents; anything larger is not one of ours. */
    private static final int MAX_REQUEST_BYTES = 1 << 20;
    private static final String TOKEN_HEADER = "X-Creo-Cli-Token";
    private static final String INVOCATION_HEADER = "X-Creo-Cli-Invocation-Id";
    private static final String DIAGNOSTIC_HEADER = "X-Creo-Cli-Diagnostic-Request-Id";
    private static final String TOKEN_PROPERTY = "creocli.service.token.file";
    /**
     * How long the caller is prepared to wait, in milliseconds. A caller that gives up
     * before Creo comes back must not leave its operation queued to run later -- behind a
     * dialog, say, which the person then closes. See {@link #onToolkitThread}.
     */
    private static final String WAIT_HEADER = "X-Creo-Cli-Wait-Ms";
    /**
     * The request/reply contract creo-cli checks before it sends an operation. Raised
     * whenever a reply changes shape, so a CLI never reads a reply it does not understand
     * from a service built from an older checkout.
     */
    static final int PROTOCOL = 2;
    /** Feature contract revision, not a loaded-JAR hash or a license/runtime guarantee. */
    static final String REVISION = "command-tree-2-readback-1";
    /** Counts actual entries into named adapter handlers; queued/withdrawn jobs do not count. */
    private static final ConcurrentHashMap<String, AtomicLong> DISPATCH_COUNTS = new ConcurrentHashMap<>();

    private static final AtomicReference<HttpServer> RUNNING = new AtomicReference<>();
    /** The thread Creo drives, recorded so we can recognise it and never queue behind it. */
    private static final AtomicReference<Thread> TOOLKIT_THREAD = new AtomicReference<>();
    private static final AtomicReference<String> STARTUP_REPORT = new AtomicReference<>();
    /** Process-only readiness; an HTTP listener alone does not prove a working toolkit pump. */
    private static final AtomicReference<String> STARTUP_STATE = new AtomicReference<>("not_started");
    private static final AtomicReference<String> STARTUP_ERROR = new AtomicReference<>();
    /** Work waiting for the toolkit thread. Plain Java: no Creo API is involved in queuing. */
    private static final BlockingQueue<Runnable> QUEUE = new LinkedBlockingQueue<>();
    private static final AtomicReference<Timer> PUMP = new AtomicReference<>();
    /** Native timer boundaries, never inferred from number of queued SDK jobs. */
    private static long PUMP_TICK;
    /**
     * A secret for this Creo session, written where only this user can read it.
     *
     * <p>Loopback is not a boundary on its own. Any process on the machine can connect,
     * and a web page can reach 127.0.0.1 through DNS rebinding. A browser cannot attach
     * a custom header to a cross-origin request without a preflight this server never
     * answers, and another user cannot read this user's profile, so requiring the
     * token in a header closes both.
     */
    private static final AtomicReference<String> TOKEN = new AtomicReference<>();
    /** New on each successful start, even when PTC reuses the same Java process. */
    private static final AtomicReference<String> INSTANCE_ID = new AtomicReference<>();
    /** The actual authenticated service generation; a local read, never a new UUID or CAD call. */
    static String instanceIdForReadback() { return INSTANCE_ID.get(); }
    /** The C library for sketches Java cannot build; null when absent or failed to load. */
    private static final AtomicReference<com.ptc.pfc.pfcProToolkit.Dll> SKETCH_LIBRARY = new AtomicReference<>();
    private static final AtomicReference<String> SKETCH_LIBRARY_STATUS = new AtomicReference<>("not loaded yet");
    /** The library's registry name; scripts/build_service.py writes the same one. */
    static final String SKETCH_LIBRARY_NAME = "creo_cli_sketch";
    /** The library's drawing functions: a dimension's text placed and read back where a drawing
     *  shows it, and a dimension made on the drawing deleted. */
    static final String DIMENSION_MOVE_FUNCTION = "creo_cli_dimension_move";
    static final String DIMENSION_PLACE_FUNCTION = "creo_cli_dimension_place";
    static final String DIMENSION_DELETE_FUNCTION = "creo_cli_dimension_delete";
    /** And a parts list's balloons, which Java cannot make. */
    static final String BOM_BALLOONS_FUNCTION = "creo_cli_bom_balloons";
    static final String BOM_REFERENCES_FUNCTION = "creo_cli_bom_references";
    static final String TOLERANCE_STANDARD_FUNCTION = "creo_cli_tolerance_standard";
    static final String TOLERANCE_DECIMALS_FUNCTION = "creo_cli_tolerance_decimals";
    static final String HOLE_INDEXES_FUNCTION = "creo_cli_hole_indexes";
    static final String COMPONENT_REPLACE_FUNCTION = "creo_cli_component_replace";
    static final String SECTION_EDGES_FUNCTION = "creo_cli_section_edges";
    static final String RAY_FUNCTION = "creo_cli_ray";

    private Service() {
    }

    /** Registry entry point. Public, static, void, no arguments — required by Creo. */
    public static void start() {
        try {
            if (RUNNING.get() != null) {
                log("start called while already running; ignoring");
                return;
            }
            STARTUP_STATE.set("starting");
            STARTUP_ERROR.set(null);
            // Creo calls start() on the toolkit thread, which is the one thread allowed
            // to talk to it. Everything else in this class routes work back here.
            TOOLKIT_THREAD.set(Thread.currentThread());

            HttpServer server = HttpServer.create(
                    new InetSocketAddress(InetAddress.getLoopbackAddress(), port()), BACKLOG);
            TOKEN.set(issueToken());
            INSTANCE_ID.set(java.util.UUID.randomUUID().toString());
            server.createContext("/health", Service::health);
            server.createContext("/session", Service::session);
            server.createContext("/op", Service::operation);
            server.setExecutor(Executors.newFixedThreadPool(HANDLER_THREADS, runnable -> {
                Thread thread = new Thread(runnable, "creo-cli-service-http");
                thread.setDaemon(true);
                return thread;
            }));
            server.start();
            RUNNING.set(server);
            log("listening on " + server.getAddress());

            initializeNativeDiagnostics();
            try (NativeReadTrace.Scope trace = NativeReadTrace.begin(Json.map(
                    "operation", "startup_session", "diagnostic_request_id", java.util.UUID.randomUUID().toString(),
                    "cli_invocation_id", null, "phase", "service-startup"))) {
                NativeReadTrace.check();
                STARTUP_REPORT.set(Json.write(describeSession()));
                NativeReadTrace.check();
            }
            log("session at startup: " + STARTUP_REPORT.get());
            ModelCloseLifecycle.initialize();
            ContextActivation.initialize();
            startPump();
            STARTUP_STATE.set("ready");
            log("toolkit pump running every " + (PUMP_PERIOD_MICROSECONDS / 1000) + "ms");
            // The native library is registered in protk.dat and loaded by Creo; the
            // order in which Creo starts the two is not specified, so a lookup that
            // fails this early is repeated on every later use rather than taken as final.
        } catch (Throwable failure) {
            // Creo called us; it must not receive an exception for our problem.
            String detail = describe(failure);
            STARTUP_ERROR.set(detail);
            STARTUP_STATE.set("failed");
            log("start failed: " + detail);
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
            STARTUP_STATE.set("stopping");
            boolean ownedNativeExit=OwnedSessionExit.invocationStarted() || OwnedSessionExit.blocksQueue()
                    || OwnedSessionExit.readerInFlight()
                    || ContextActivation.blocksQueue() || ModelCloseLifecycle.blocksQueue();
            OwnedSessionExit.normalStop();
            ContextActivation.stop();
            ModelCloseLifecycle.stop();
            server.stop(STOP_GRACE_SECONDS);
            Timer pump = PUMP.getAndSet(null);
            if (pump != null && !ownedNativeExit) {
                pump.Stop();
                pump.Destroy();
            }
            log("stopped");
            STARTUP_STATE.set("stopped");
        } catch (Throwable failure) {
            STARTUP_STATE.set("stop_failed");
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
     * queue, and the only thing that touches Creo is {@link #startPump the pump}, a toolkit timer
     * created on the toolkit thread during {@link #start()} and fired by Creo on that
     * same thread from then on. A request arriving while a dialog is open waits instead
     * of failing, because the queue simply is not drained until Creo comes back.
     *
     * <p>Calls that are already on the toolkit thread run inline. Queueing them would
     * deadlock: the pump cannot run until the thread waiting for it returns.
     *
     * <p>A caller that stops waiting withdraws its work if Creo has not started it, and
     * the reply says which of the two happened. Before this, a request that timed out
     * behind an open dialog stayed queued and ran whenever the dialog closed -- after
     * its caller had been told "busy, retry", so a retry built the feature twice.
     */
    static <T> T onToolkitThread(ToolkitWork<T> work, long waitMillis) throws ToolkitFailure {
        return onToolkitThread(work, waitMillis, null);
    }

    private static <T> T onToolkitThread(ToolkitWork<T> work, long waitMillis,
                                         Map<String, Object> requestIdentity) throws ToolkitFailure {
        requireContextQueueAvailable();
        if (Thread.currentThread() == TOOLKIT_THREAD.get()) {
            try {
                return work.run();
            } catch (Throwable failure) {
                throw ToolkitFailure.of(failure);
            }
        }
        if (PUMP.get() == null) {
            throw new ToolkitFailure(Json.map("code", "E_UNAVAILABLE", "message",
                    "the toolkit pump is not running; see " + logPath() + " for what happened during start",
                    "started", false));
        }
        CompletableFuture<T> answer = new CompletableFuture<>();
        // Queued -> running on the toolkit thread, or queued -> withdrawn here; never both.
        AtomicInteger state = new AtomicInteger(JOB_QUEUED);
        QUEUE.add(() -> {
            if (!state.compareAndSet(JOB_QUEUED, JOB_RUNNING)) {
                return; // withdrawn: its caller has already been told it did not run
            }
            try {
                requireContextQueueAvailable();
                answer.complete(work.run());
            } catch (Throwable failure) {
                // Must not propagate: this runs inside a callback Creo is making. And the
                // failure must not leave this thread as it is: see ToolkitFailure.
                answer.completeExceptionally(ToolkitFailure.of(failure));
            }
        });
        try {
            return answer.get(waitMillis, TimeUnit.MILLISECONDS);
        } catch (ExecutionException wrapped) {
            throw (ToolkitFailure) wrapped.getCause();
        } catch (InterruptedException stopping) {
            Thread.currentThread().interrupt();
            boolean withdrawn = state.compareAndSet(JOB_QUEUED, JOB_WITHDRAWN);
            if(!withdrawn)OwnedSessionExit.readerTimedOut(requestIdentity);
            throw new ToolkitFailure(Json.map("code", "E_UNAVAILABLE", "message", "the service is stopping",
                    "retryable", withdrawn, "started", !withdrawn));
        } catch (TimeoutException expired) {
            if (state.compareAndSet(JOB_QUEUED, JOB_WITHDRAWN)) {
                throw new ToolkitFailure(Json.map("code", "E_BUSY", "message", "Creo's thread did not become free "
                        + "within " + waitMillis + " ms -- another operation was running, or Creo is waiting for "
                        + "input in a dialog; the operation was withdrawn before it started, so nothing was done",
                        "retryable", true, "started", false));
            }
            OwnedSessionExit.readerTimedOut(requestIdentity);
            Map<String, Object> error = Json.map("code", "E_BUSY", "message", "the operation started but did not "
                    + "finish within " + waitMillis + " ms; it is still running in Creo and this reply cannot "
                    + "say how it ends", "retryable", false, "started", true);
            if (requestIdentity != null && NativeReadTrace.enabled()) {
                NativeReadTrace.requestUnreturned(requestIdentity, error);
                error.put("native_diagnostic", NativeReadTrace.stopEvidence());
            }
            throw new ToolkitFailure(error);
        }
    }

    private static final int JOB_QUEUED = 0;
    private static final int JOB_RUNNING = 1;
    private static final int JOB_WITHDRAWN = 2;

    /** Pure-Java gate: no queued observer or setter can run inside deferred activation. */
    private static void requireContextQueueAvailable() throws ToolkitFailure {
        if(OwnedSessionExit.blocksQueue())
            throw new ToolkitFailure(Json.map("code","E_UNAVAILABLE","message",
                    "owned session exit is pending or terminal; no further SDK call dispatched",
                    "started",false,"retryable",false,"owned_exit",OwnedSessionExit.status()));
        try {ModelCloseLifecycle.healthy();}
        catch(Failures.Refusal stopped) {
            throw new ToolkitFailure(Json.map("code",stopped.code,"message",stopped.getMessage(),
                    "started",false,"retryable",false,"model_close",ModelCloseLifecycle.status()));
        }
        if(ModelCloseLifecycle.blocksQueue())throw new ToolkitFailure(Json.map("code","E_BUSY","message",
                "model close is awaiting return-to-Creo verification; no other SDK call dispatched",
                "started",false,"retryable",false,"model_close",ModelCloseLifecycle.status()));
        try { ContextActivation.healthy(); }
        catch (Failures.Refusal stopped) {
            throw new ToolkitFailure(Json.map("code",stopped.code,"message",stopped.getMessage(),
                    "started",false,"retryable",false,"context_activation",ContextActivation.status()));
        }
        if (ContextActivation.blocksQueue())
            throw new ToolkitFailure(Json.map("code","E_BUSY","message",
                    "a native context command is awaiting return-to-Creo verification; no other CAD call was dispatched",
                    "started",false,"retryable",false,"context_activation",ContextActivation.status()));
    }

    /** HTTP waits on plain data while native activation crosses real callback boundaries. */
    private static Map<String,Object> activateOnToolkitThread(Map<String,Object> request,long waitMillis,
                                                               Map<String,Object> identity) throws ToolkitFailure {
        if (Thread.currentThread()==TOOLKIT_THREAD.get())
            throw new ToolkitFailure(Json.map("code","E_UNSUPPORTED","message",
                    "deferred activation must not wait on the toolkit thread","started",false,"retryable",false));
        requireContextQueueAvailable();
        if (PUMP.get()==null)
            throw new ToolkitFailure(Json.map("code","E_UNAVAILABLE","message",
                    "toolkit pump is not running","started",false,"retryable",false));
        ContextActivation.Ticket ticket;
        try { ticket=ContextActivation.ticket(identity,waitMillis); }
        catch (Failures.Refusal absent) {
            throw new ToolkitFailure(Json.map("code",absent.code,"message",absent.getMessage(),
                    "started",false,"retryable",false));
        }
        QUEUE.add(()-> {
            if (ticket.terminal()) return;
            try { requireContextQueueAvailable(); }
            catch(ToolkitFailure refused) {ticket.failure(refused.error);return;}
            DISPATCH_COUNTS.computeIfAbsent("display.activate",name->new AtomicLong()).incrementAndGet();
            ContextActivation.stage(ticket,request,PUMP_TICK);
        });
        try { return ticket.answer.get(waitMillis,TimeUnit.MILLISECONDS); }
        catch (ExecutionException wrapped) { throw (ToolkitFailure)wrapped.getCause(); }
        catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
            Map<String,Object> error=ContextActivation.expire(ticket,"activation_http_interrupted");
            if(error==null) return completedActivation(ticket);
            throw new ToolkitFailure(error);
        } catch (TimeoutException expired) {
            Map<String,Object> error=ContextActivation.expire(ticket,"activation_http_wait_expired");
            if(error==null) return completedActivation(ticket);
            throw new ToolkitFailure(error);
        }
    }

    /** Handles a completion winning the deadline race without a second SDK observation. */
    private static Map<String,Object> completedActivation(ContextActivation.Ticket ticket) throws ToolkitFailure {
        try { return ticket.answer.join(); }
        catch (java.util.concurrent.CompletionException wrapped) { throw (ToolkitFailure)wrapped.getCause(); }
    }

    /** A model close must yield between closing its window and erasing its model. */
    private static Map<String,Object> closeOnToolkitThread(Map<String,Object> request,long waitMillis,
                                                            Map<String,Object> identity) throws ToolkitFailure {
        if(Thread.currentThread()==TOOLKIT_THREAD.get())throw new ToolkitFailure(Json.map(
                "code","E_UNSUPPORTED","message","deferred close must not wait on toolkit thread",
                "started",false,"retryable",false));
        requireContextQueueAvailable();
        if(PUMP.get()==null)throw new ToolkitFailure(Json.map("code","E_UNAVAILABLE","message",
                "toolkit pump is not running","started",false,"retryable",false));
        ModelCloseLifecycle.Ticket ticket;
        try {ticket=ModelCloseLifecycle.ticket(identity,waitMillis);}
        catch(Failures.Refusal absent) {throw new ToolkitFailure(Json.map("code",absent.code,
                "message",absent.getMessage(),"started",false,"retryable",false));}
        QUEUE.add(()-> {
            if(ticket.terminal())return;
            try {requireContextQueueAvailable();}
            catch(ToolkitFailure refused) {
                if(ticket.phase.compareAndSet(ModelCloseLifecycle.Ticket.QUEUED,ModelCloseLifecycle.Ticket.TERMINAL))
                    ticket.answer.completeExceptionally(refused);
                return;
            }
            DISPATCH_COUNTS.computeIfAbsent("model.close",name->new AtomicLong()).incrementAndGet();
            ModelCloseLifecycle.stage(ticket,request,PUMP_TICK);
        });
        try {return ticket.answer.get(waitMillis,TimeUnit.MILLISECONDS);}
        catch(ExecutionException wrapped) {throw (ToolkitFailure)wrapped.getCause();}
        catch(InterruptedException interrupted) {
            Thread.currentThread().interrupt();
            Map<String,Object> error=ModelCloseLifecycle.expire(ticket,"model_close_http_interrupted");
            if(error!=null)throw new ToolkitFailure(error);
        }catch(TimeoutException expired) {
            Map<String,Object> error=ModelCloseLifecycle.expire(ticket,"model_close_http_wait_expired");
            if(error!=null)throw new ToolkitFailure(error);
        }
        try {return ticket.answer.join();}
        catch(java.util.concurrent.CompletionException wrapped) {throw (ToolkitFailure)wrapped.getCause();}
    }

    /** Pure Java stop gate, then the default120s or explicit drawing wait policy. */
    private static long waitMillis(HttpExchange exchange, String operation) {
        return NativeWaitBudget.milliseconds(NativeReadTrace::ensureHealthy, operation,
                exchange.getRequestHeaders().get(NativeWaitBudget.PROFILE_HEADER),
                exchange.getRequestHeaders().get(WAIT_HEADER));
    }

    /**
     * A failure from the toolkit thread, reduced to plain data before it leaves it.
     *
     * <p>Toolkit exceptions are proxies like everything else the toolkit hands out:
     * {@code XToolkitError.GetErrorCode()} and {@code GetToolkitFunctionName()} are
     * native methods that talk to Creo over the one shared connection. Formatting such
     * an exception on an HTTP thread is therefore a toolkit call from the wrong thread
     * -- and that is not a hypothetical. It happened: the connection was corrupted, Creo
     * logged a screen of "continuing from serious error", and this JVM died. The rule is
     * not only "no toolkit calls off the toolkit thread" but "no toolkit objects off
     * it", and an exception is an object.
     */
    static final class ToolkitFailure extends Exception {
        final Map<String, Object> error;

        ToolkitFailure(Map<String, Object> error) {
            super(String.valueOf(error.get("message")));
            this.error = error;
        }

        /** Must be called on the toolkit thread. */
        static ToolkitFailure of(Throwable failure) {
            if (failure instanceof NativeReadTrace.Fatal
                    || Boolean.TRUE.equals(NativeReadTrace.stopEvidence().get("stopped"))) {
                return new ToolkitFailure(NativeReadTrace.error(failure));
            }
            if (failure instanceof ToolkitFailure) {
                return (ToolkitFailure) failure;
            }
            Map<String, Object> error;
            try {
                error = Failures.error(failure);
            } catch (Throwable unreadable) {
                error = Json.map("code", "E_CREO", "message", failure.getClass().getName());
            }
            return new ToolkitFailure(error);
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
        if(OwnedSessionExit.pump()) {
            if(!OwnedSessionExit.invocationStarted())refuseStoppedQueue();
            return;
        }
        long tick=++PUMP_TICK;
        if(ModelCloseLifecycle.pump(tick)) {
            if(ModelCloseLifecycle.blocksQueue())refuseStoppedQueue();
            return;
        }
        if (ContextActivation.pump(tick)) {
            if(ContextActivation.hasStopped())refuseStoppedQueue();
            return;
        }
        for (int done = 0; done < MAX_JOBS_PER_TICK; done++) {
            Runnable job = QUEUE.poll();
            if (job == null) {
                return;
            }
            try {
                job.run();
                if (ContextActivation.blocksQueue() || OwnedSessionExit.blocksQueue() || ModelCloseLifecycle.blocksQueue()) {
                    if(OwnedSessionExit.blocksQueue() || ModelCloseLifecycle.blocksQueue())refuseStoppedQueue();
                    if(ContextActivation.hasStopped())refuseStoppedQueue();
                    return;
                }
            } catch (Throwable failure) {
                log("a queued job threw past its own handler: " + describe(failure));
            }
        }
    }

    /** Every queue wrapper checks the pure-Java stop gate before any SDK work. */
    private static void refuseStoppedQueue() {
        for(int done=0;done<MAX_JOBS_PER_TICK;done++) {
            if(!OwnedSessionExit.blocksQueue() && !ContextActivation.blocksQueue()
                    && !ModelCloseLifecycle.blocksQueue())return;
            Runnable job=QUEUE.poll();
            if(job==null)return;
            try {job.run();}
            catch(Throwable failure) {log("a stopped queue wrapper failed: "+failure.getClass().getName());}
        }
    }

    /** Work that needs Creo. Handed to {@link #onToolkitThread} rather than called directly. */
    interface ToolkitWork<T> {
        T run() throws Exception;
    }

    /**
     * The native sketch library, looked up on first use. Must run on the toolkit thread.
     *
     * <p>Creo loads it from protk.dat, which is the only place its path is known: Creo
     * loads this class through its own class loader, which records no code source, so
     * the service cannot find files beside its own jar. Creo is asked for the library
     * by its registry name first; failing that, by the id the library writes to
     * {@code ~/.creo-cli/native-sketch-id} when it starts, since PTC documents the id as
     * "an identifying string" without saying what it is.
     *
     * <p>Optional by design: without it every single-entity operation still works, and
     * multi-entity sketches are refused with the reason rather than attempted.
     */
    static com.ptc.pfc.pfcProToolkit.Dll sketchLibrary() {
        com.ptc.pfc.pfcProToolkit.Dll known = SKETCH_LIBRARY.get();
        if (known != null) {
            return known;
        }
        try {
            Session session = pfcGlobal.GetProESession();
            com.ptc.pfc.pfcProToolkit.Dll found = RuntimeProfile.NATIVE_ID_FILE.isEmpty()
                    ? lookUp(session, SKETCH_LIBRARY_NAME) : null;
            String how = "registry name";
            if (found == null) {
                Path idFile = RuntimeProfile.NATIVE_ID_FILE.isEmpty()
                        ? stateDirectory().resolve("native-sketch-id") : Paths.get(RuntimeProfile.NATIVE_ID_FILE);
                if (Files.isRegularFile(idFile)) {
                    String id = new String(Files.readAllBytes(idFile), StandardCharsets.US_ASCII).trim();
                    found = lookUp(session, id);
                    how = "handshake id " + id;
                }
            }
            if (found == null) {
                SKETCH_LIBRARY_STATUS.set("not registered or not running (neither its name nor a handshake id "
                        + "resolves); inspect the owned automatic-startup record, declared DLL identity "
                        + "and external trust/license blockers; no manual load or global restart");
                return null;
            }
            SKETCH_LIBRARY.set(found);
            SKETCH_LIBRARY_STATUS.set("loaded by Creo, found by " + how);
            return found;
        } catch (Throwable failure) {
            SKETCH_LIBRARY_STATUS.set("lookup failed: " + describe(failure));
            return null;
        }
    }

    private static com.ptc.pfc.pfcProToolkit.Dll lookUp(Session session, String id) {
        try {
            return session.GetProToolkitDll(id);
        } catch (Throwable absent) {
            return null;
        }
    }

    static String sketchLibraryStatus() {
        return SKETCH_LIBRARY_STATUS.get();
    }

    /** Pure Java registered-handle lookup; owned exit cannot initiate a late DLL lookup. */
    static com.ptc.pfc.pfcProToolkit.Dll loadedSketchLibrary() {return SKETCH_LIBRARY.get();}
    static boolean ownedExitOtherWorkQueued() {return !QUEUE.isEmpty();}

    /**
     * Liveness only. Touches no Creo API, so a success here means exactly one thing:
     * Creo loaded this class and is running it.
     */
    private static void health(HttpExchange exchange) throws IOException {
        respond(exchange, 200, Json.write(Json.map("ok", true, "service", "creo-cli", "protocol", PROTOCOL,
                "revision", REVISION, "source_sha256", BuildIdentity.SOURCE_SHA256,
                "process_id", ProcessHandle.current().pid(),
                "service_instance_id", INSTANCE_ID.get(),
                "runtime_class", Service.class.getName(),
                "startup_state", STARTUP_STATE.get(),
                "toolkit_pump_running", PUMP.get() != null,
                "startup_error", STARTUP_ERROR.get(),
                "native_library_cached", SKETCH_LIBRARY.get() != null,
                "native_library_lookup_status", SKETCH_LIBRARY_STATUS.get(),
                "runtime_configuration", Json.map(
                        "state_directory", stateDirectory().toAbsolutePath().normalize().toString(),
                        "native_id_file", (RuntimeProfile.NATIVE_ID_FILE.isEmpty()
                                ? stateDirectory().resolve("native-sketch-id")
                                : Paths.get(RuntimeProfile.NATIVE_ID_FILE)).toAbsolutePath().normalize().toString(),
                        "port", exchange.getLocalAddress().getPort(),
                        "portable_profile", RuntimeProfile.STATE_DIRECTORY.isEmpty()
                                && RuntimeProfile.NATIVE_ID_FILE.isEmpty() && RuntimeProfile.PORT == 0,
                        "java_version", System.getProperty("java.version"),
                        "java_home", System.getProperty("java.home")),
                "process_started_at", ProcessHandle.current().info().startInstant().map(Object::toString).orElse(null),
                "loaded_jar_hash", null, "loaded_jar_hash_status", "classloader_does_not_prove_path",
                "native_diagnostic", NativeReadTrace.stopEvidence(),
                "context_activation", ContextActivation.status(),
                "owned_exit",OwnedSessionExit.status(),
                "model_close_lifecycle",ModelCloseLifecycle.status(),
                "dispatch_counts", dispatchCounts(), "dispatch_counter_scope", "named_ops_handler_entry",
                "capabilities", Json.map("startup_readiness", 1, "geometry_binary64_readback", 1,
                        "source_part_appearance", 2, "source_part_appearance_reference", 1,
                        "source_part_appearance_unique_reference", 1, "protected_definition_readback", 1, "native_presentation", 2,
                        "model_context_activation", ContextActivation.ready() ? 1 : 0,
                        "owned_session_exit",1,
                        "model_close_lifecycle",ModelCloseLifecycle.ready()?1:0,
                        NativeWaitBudget.CAPABILITY, NativeWaitBudget.CAPABILITY_VERSION,
                        AssemblyConstraints.CAPABILITY, AssemblyConstraints.CAPABILITY_VERSION,
                        "dimension_regeneration_readback", 1, "resource_readers", 1, "drawing_window_activation", 1, "model_regeneration", 1, "bom_reference_readback", 2, "title_projection_arcs", 2, "explosion_state_readback", 2, "assembly_explosion_context_readback", 1, "render_state_restoration", 3, "machining_feature_readback", 1, "revolved_datum_readback", 1, "drawing_view_dependencies", 1, "drawing_view_exploded_readback", 1, "simple_drawing_note_readback", 1, "model_management_readback", 2, "family_dimension_runtime", 1, "prismatic_shell_readback", 2, "prismatic_draft_readback", 1, "prismatic_rib_readback", 3, "material_source_binding", 1, "numeric_tolerance_regeneration_readback", 1, "tolerance_standard_numeric_preservation", 1),
                "runtime_configuration_contract", 1,
                "checked", "process_only")));
    }

    private static Map<String, Object> dispatchCounts() {
        Map<String, Object> values = new java.util.TreeMap<>();
        DISPATCH_COUNTS.forEach((name, count) -> values.put(name, count.get()));
        return values;
    }

    /**
     * Reads the session now, from this HTTP thread, by way of the toolkit thread.
     *
     * <p>Answering from a cache would be cheaper and would prove nothing. The point of
     * this endpoint is that the hand-off works on a live request.
     */
    private static void session(HttpExchange exchange) throws IOException {
        if (!authorised(exchange)) {
            return;
        }
        Map<String, Object> identity;
        try { identity = requestIdentity(exchange, "/session"); }
        catch (IllegalArgumentException invalid) {
            respond(exchange, 400, Json.write(Json.map("ok", false, "error", Failures.error(invalid))));
            return;
        }
        Object body;
        try {
            long wait = waitMillis(exchange, "/session");
            body = onToolkitThread(() -> {
                try (NativeReadTrace.Scope trace = NativeReadTrace.begin(identity)) {
                    try {
                        NativeReadTrace.check();
                        Map<String, Object> data = describeSession();
                        NativeReadTrace.check();
                        data.putAll(responseIdentity(identity));
                        return data;
                    } catch (Throwable failure) { throw ToolkitFailure.of(failure); }
                }
            }, wait, identity);
        } catch (NativeReadTrace.Fatal failure) {
            body = Json.map("ok", false, "error", relatedError(NativeReadTrace.error(failure), identity));
        } catch (NativeWaitBudget.Refusal failure) {
            body = Json.map("ok", false, "error", relatedError(NativeWaitBudget.refusal(failure), identity));
        } catch (ToolkitFailure failure) {
            body = Json.map("ok", false, "error", relatedError(failure.error, identity),
                    "at_startup", STARTUP_REPORT.get() == null ? null : Json.parse(STARTUP_REPORT.get()));
        }
        respond(exchange, 200, Json.write(body));
    }

    /**
     * One modelling operation: {@code {"op": "...", ...}} in, the operation's own
     * read-back out.
     *
     * <p>The request is parsed and validated here, on the HTTP thread, so a malformed
     * one never costs Creo a tick. Only the work itself crosses to the toolkit thread.
     * There is no generic "run this" operation and there will not be one: every op is a
     * named, reviewed method, listed in {@link Ops}.
     */
    private static void operation(HttpExchange exchange) throws IOException {
        if (!authorised(exchange)) {
            return;
        }
        if (!"POST".equals(exchange.getRequestMethod())) {
            respond(exchange, 405, Json.write(Json.map("ok", false,
                    "error", Json.map("code", "E_VALIDATION", "message", "POST a JSON operation"))));
            return;
        }
        Map<String, Object> request;
        String op;
        try {
            request = Json.object(Json.parse(readBody(exchange)), "the request");
            op = Json.string(request, "op");
        } catch (IllegalArgumentException invalid) {
            respond(exchange, 400, Json.write(Json.map("ok", false, "error", Failures.error(invalid))));
            return;
        }
        long started = System.nanoTime();
        Map<String, Object> identity;
        try { identity = requestIdentity(exchange, op); }
        catch (IllegalArgumentException invalid) {
            respond(exchange, 400, Json.write(Json.map("ok", false, "error", Failures.error(invalid))));
            return;
        }
        Object reply;
        boolean exitPrepared=false;
        try {
            // Pure Java gate here and again after the toolkit queue is entered. A new
            // client cannot bypass a stop that belongs to this service generation.
            long wait = waitMillis(exchange, op);
            Map<String, Object> data = "display.activate".equals(op)
                    ? activateOnToolkitThread(request,wait,identity)
                    : "model.close".equals(op) ? closeOnToolkitThread(request,wait,identity) : onToolkitThread(() -> {
                try (NativeReadTrace.Scope trace = NativeReadTrace.begin(identity);
                     OwnedSessionExit.ReadScope read=OwnedSessionExit.readScope(op,request,identity)) {
                    try {
                        NativeReadTrace.check();
                        DISPATCH_COUNTS.computeIfAbsent(op, name -> new AtomicLong()).incrementAndGet();
                        Map<String, Object> value;
                        if ("diagnostic.note".equals(op)) {
                            if (!"1".equals(System.getenv("CREO_CLI_NATIVE_DIAGNOSTIC")))
                                throw new Failures.Refusal("E_VALIDATION", "internal note diagnostics are not enabled");
                            Session session = NativeReadTrace.call("pfcGlobal.GetProESession", pfcGlobal::GetProESession);
                            value = NoteDiagnostic.op(session, request);
                        } else if("session.exit".equals(op)) {
                            value=OwnedSessionExit.prepare(request,identity);
                        } else value = Ops.dispatch(op, request);
                        NativeReadTrace.check();
                        return value;
                    } catch (Throwable failure) {
                        if("session.exit-state".equals(op)||"session.exit".equals(op))
                            throw OwnedSessionExit.preflightFailure(failure);
                        throw ToolkitFailure.of(failure);
                    }
                }
            }, wait, identity);
            exitPrepared="session.exit".equals(op) && "request_scheduled".equals(data.get("status"));
            reply = Json.map("ok", true, "op", op, "data", data,
                    "diagnostic_request_id", identity.get("diagnostic_request_id"),
                    "cli_invocation_id", identity.get("cli_invocation_id"),
                    "elapsed_ms", (System.nanoTime() - started) / 1_000_000);
        } catch (NativeReadTrace.Fatal failure) {
            reply = Json.map("ok", false, "op", op, "error", relatedError(NativeReadTrace.error(failure), identity),
                    "elapsed_ms", (System.nanoTime() - started) / 1_000_000);
        } catch (NativeWaitBudget.Refusal failure) {
            reply = Json.map("ok", false, "op", op, "error", relatedError(NativeWaitBudget.refusal(failure), identity),
                    "elapsed_ms", (System.nanoTime() - started) / 1_000_000);
        } catch (ToolkitFailure failure) {
            // Plain data by now: formatting it here makes no toolkit call.
            log("op " + op + " failed: " + failure.error);
            reply = Json.map("ok", false, "op", op, "error", relatedError(failure.error, identity),
                    "elapsed_ms", (System.nanoTime() - started) / 1_000_000);
        }
        if(exitPrepared) {
            try {
                respond(exchange,200,Json.write(reply));
                OwnedSessionExit.arm(Json.string(request,"operation_id"));
            } catch(IOException failure) {
                OwnedSessionExit.cancel(Json.string(request,"operation_id"),"http_response_failed_before_arm");
                throw failure;
            }
        } else respond(exchange, 200, Json.write(reply));
    }

    /**
     * The session reading behind {@code /session}: {@link SessionOps#status} plus what only
     * a diagnostic needs. Must run on the toolkit thread. The models in session are listed
     * so that tooling can refuse to restart Creo over someone's open work.
     */
    private static Map<String, Object> describeSession() {
        try {
            Map<String, Object> out = Json.map("ok", true, "session_reachable", true);
            Map<String, Object> status = NativeReadTrace.call("SessionOps.status", SessionOps::status);
            out.putAll(status);
            out.put("deployment_policy",SessionOps.deploymentPolicy());
            out.put("recovery_configuration",SessionOps.recoveryConfiguration());
            out.put("models_in_session", status.get("models"));
            Session session = NativeReadTrace.call("pfcGlobal.GetProESession", pfcGlobal::GetProESession);
            out.put("session_class", session.getClass().getName());
            out.put("thread", Thread.currentThread().getName());
            return out;
        } catch (Throwable failure) {
            NativeReadTrace.rethrowFatal(failure);
            return Json.map("ok", false, "error", NativeReadTrace.active()
                    ? failure.getClass().getName() : describe(failure));
        }
    }

    /** Only process metadata and explicitly declared files; no toolkit access. */
    private static void initializeNativeDiagnostics() {
        if (!"1".equals(System.getenv("CREO_CLI_NATIVE_DIAGNOSTIC"))) return;
        ProcessHandle process = ProcessHandle.current();
        ProcessHandle parent = process.parent().orElse(null);
        Map<String, Object> identity = Json.map(
                "service_instance_id", INSTANCE_ID.get(), "service_source_sha256", BuildIdentity.SOURCE_SHA256,
                "runtime_class", Service.class.getName(),
                "java_process_id", String.valueOf(process.pid()),
                "java_started_at", process.info().startInstant().map(Object::toString).orElse(null),
                "parent_process_id", parent == null ? null : String.valueOf(parent.pid()),
                "parent_started_at", parent == null ? null : parent.info().startInstant().map(Object::toString).orElse(null));
        try {
            List<Path> logs = new ArrayList<>();
            String declared = System.getenv("CREO_CLI_NATIVE_DIAGNOSTIC_LOGS");
            if (declared != null) {
                Object parsed = Json.parse(declared);
                if (!(parsed instanceof List)) throw new IllegalArgumentException("native diagnostic logs must be a JSON array");
                for (Object value : (List<?>) parsed) {
                    if (!(value instanceof String)) throw new IllegalArgumentException("native diagnostic log paths must be strings");
                    logs.add(Paths.get((String) value));
                }
            }
            NativeReadTrace.initialize(stateDirectory(), identity, logs);
        } catch (NativeReadTrace.Fatal failure) { throw failure; }
        catch (Throwable failure) { NativeReadTrace.initializationFailed(stateDirectory(), identity, failure); }
    }

    private static Map<String, Object> requestIdentity(HttpExchange exchange, String operation) {
        String invocation = exchange.getRequestHeaders().getFirst(INVOCATION_HEADER);
        if (invocation != null && !invocation.matches("[A-Za-z0-9][A-Za-z0-9._:-]{0,127}"))
            throw new IllegalArgumentException("invalid " + INVOCATION_HEADER);
        String diagnostic = java.util.UUID.randomUUID().toString();
        exchange.getResponseHeaders().set(DIAGNOSTIC_HEADER, diagnostic);
        return Json.map("operation", operation, "diagnostic_request_id", diagnostic,
                "cli_invocation_id", invocation, "cli_invocation_id_status", invocation == null ? "absent" : "provided_header",
                "phase", "service-dispatch");
    }

    private static Map<String, Object> responseIdentity(Map<String, Object> identity) {
        return Json.map("diagnostic_request_id", identity.get("diagnostic_request_id"),
                "cli_invocation_id", identity.get("cli_invocation_id"));
    }

    private static Map<String, Object> relatedError(Map<String, Object> error, Map<String, Object> identity) {
        Map<String, Object> related = new java.util.LinkedHashMap<>(error);
        related.putAll(responseIdentity(identity));
        return related;
    }

    private static String issueToken() throws IOException {
        byte[] secret = new byte[32];
        new SecureRandom().nextBytes(secret);
        StringBuilder hex = new StringBuilder();
        for (byte b : secret) {
            hex.append(String.format("%02x", b));
        }
        Path file = tokenPath();
        Files.createDirectories(file.getParent());
        Files.write(file, hex.toString().getBytes(StandardCharsets.US_ASCII),
                StandardOpenOption.CREATE, StandardOpenOption.TRUNCATE_EXISTING, StandardOpenOption.WRITE);
        return hex.toString();
    }

    private static boolean authorised(HttpExchange exchange) throws IOException {
        String expected = TOKEN.get();
        String given = exchange.getRequestHeaders().getFirst(TOKEN_HEADER);
        boolean ok = expected != null && given != null && MessageDigest.isEqual(
                expected.getBytes(StandardCharsets.US_ASCII), given.getBytes(StandardCharsets.US_ASCII));
        if (!ok) {
            respond(exchange, 401, Json.write(Json.map("ok", false, "error", Json.map("code", "E_AUTH",
                    "message", "missing or wrong " + TOKEN_HEADER + "; read it from " + tokenPath()))));
        }
        return ok;
    }

    private static String readBody(HttpExchange exchange) throws IOException {
        try (InputStream in = exchange.getRequestBody()) {
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            byte[] buffer = new byte[8192];
            int read;
            while ((read = in.read(buffer)) > 0) {
                out.write(buffer, 0, read);
                if (out.size() > MAX_REQUEST_BYTES) {
                    throw new IllegalArgumentException("request larger than " + MAX_REQUEST_BYTES + " bytes");
                }
            }
            return new String(out.toByteArray(), StandardCharsets.UTF_8);
        }
    }

    static Path tokenPath() {
        if (!RuntimeProfile.STATE_DIRECTORY.isEmpty()) return stateDirectory().resolve("service-token");
        String configured = System.getProperty(TOKEN_PROPERTY);
        if (configured != null && !configured.isEmpty()) {
            return Paths.get(configured);
        }
        return stateDirectory().resolve("service-token");
    }

    static Path stateDirectory() {
        if (!RuntimeProfile.STATE_DIRECTORY.isEmpty()) return Paths.get(RuntimeProfile.STATE_DIRECTORY);
        String configured = System.getenv("CREO_CLI_CONFIG_DIR");
        return configured == null || configured.isEmpty()
                ? Paths.get(System.getProperty("user.home", "."), ".creo-cli") : Paths.get(configured);
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
        if (RuntimeProfile.PORT != 0) return RuntimeProfile.PORT;
        String configured = System.getProperty(PORT_PROPERTY);
        if (configured == null || configured.isEmpty()) configured = System.getenv("CREO_CLI_SERVICE_PORT");
        if (configured == null || configured.isEmpty()) {
            return DEFAULT_PORT;
        }
        try {
            int value = Integer.parseInt(configured.trim());
            if (value < 1024 || value > 65535)
                throw new IllegalArgumentException("configured Creo CLI port must be 1024..65535");
            return value;
        } catch (NumberFormatException invalid) {
            throw new IllegalArgumentException("configured Creo CLI port must be an integer", invalid);
        }
    }

    private static String describe(Throwable failure) {
        if (NativeReadTrace.enabled()) return failure.getClass().getName();
        Throwable cause = failure;
        while (cause.getCause() != null && cause.getCause() != cause) {
            cause = cause.getCause();
        }
        String message = cause.getMessage();
        return cause.getClass().getName() + (message == null ? "" : ": " + message);
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
        if (!RuntimeProfile.STATE_DIRECTORY.isEmpty()) return stateDirectory().resolve("service.log");
        String configured = System.getProperty(LOG_PROPERTY);
        if (configured != null && !configured.isEmpty()) {
            return Paths.get(configured);
        }
        return stateDirectory().resolve("service.log");
    }
}

