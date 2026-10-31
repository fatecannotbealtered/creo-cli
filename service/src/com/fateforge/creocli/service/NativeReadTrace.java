package com.fateforge.creocli.service;

import com.sun.nio.file.ExtendedOpenOption;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.NoSuchFileException;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.nio.file.attribute.BasicFileAttributes;
import java.nio.file.attribute.FileTime;
import java.security.MessageDigest;
import java.time.Instant;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicReference;

/** Durable, local-only call boundaries. Nothing here may inspect a toolkit proxy. */
final class NativeReadTrace {
    private NativeReadTrace() { }

    interface Call<T> { T run() throws Throwable; }
    interface VoidCall { void run() throws Throwable; }
    interface Sink { void append(Path path, byte[] bytes) throws IOException; }

    /** One writer for one RuntimeState, retained until JVM teardown, never request cleanup.
     * Windows sharing denies other write/delete handles but retains read-only inspection.
     * No unsupported-provider fallback, reopening, buffering, batching or native callbacks.
     */
    private static final class OwnedJournal implements Sink, AutoCloseable {
        private final Path journal;
        private final Path parent;
        private FileChannel channel;
        private Object fileKey;
        private Object parentKey;
        private FileTime creationTime;
        private FileTime parentCreationTime;
        private long expectedEnd;
        private boolean attempted;
        private boolean closed;
        private Throwable failure;

        OwnedJournal(Path journal) {
            this.journal = journal;
            this.parent = journal.getParent();
        }

        private BasicFileAttributes attributes(Path path, boolean directory) throws IOException {
            BasicFileAttributes attrs = Files.readAttributes(path, BasicFileAttributes.class, LinkOption.NOFOLLOW_LINKS);
            if (attrs.isSymbolicLink() || (directory ? !attrs.isDirectory() : !attrs.isRegularFile())
                    || !path.equals(path.toRealPath()))
                throw new IOException("owned diagnostic journal path is not a direct regular path");
            return attrs;
        }

        private void openOnce() throws IOException {
            if (attempted) throw new IOException("owned diagnostic journal will not reopen");
            attempted = true;
            Files.createDirectories(parent);
            BasicFileAttributes beforeParent = attributes(parent, true);
            BasicFileAttributes before = Files.exists(journal, LinkOption.NOFOLLOW_LINKS)
                    ? attributes(journal, false) : null;
            channel = FileChannel.open(journal, StandardOpenOption.CREATE, StandardOpenOption.WRITE,
                    StandardOpenOption.APPEND, LinkOption.NOFOLLOW_LINKS,
                    ExtendedOpenOption.NOSHARE_WRITE, ExtendedOpenOption.NOSHARE_DELETE);
            BasicFileAttributes after = attributes(journal, false);
            BasicFileAttributes afterParent = attributes(parent, true);
            if (!sameIdentity(beforeParent, afterParent)
                    || before != null && (!sameIdentity(before, after) || before.size() != after.size()))
                throw new IOException("owned diagnostic journal changed during open");
            fileKey = after.fileKey();
            parentKey = afterParent.fileKey();
            creationTime = after.creationTime();
            parentCreationTime = afterParent.creationTime();
            expectedEnd = after.size();
            verify(expectedEnd);
        }

        private static boolean sameIdentity(BasicFileAttributes before, BasicFileAttributes after) {
            // Windows BasicFileAttributes has no fileKey. Creation time is only an
            // auxiliary drift check; the required sharing mode owns write/delete access.
            Object key = before.fileKey();
            return (key == null ? after.fileKey() == null : key.equals(after.fileKey()))
                    && before.creationTime().equals(after.creationTime());
        }

        private void verify(long length) throws IOException {
            if (!channel.isOpen()) throw new IOException("owned diagnostic journal channel is closed");
            BasicFileAttributes directory = attributes(parent, true);
            BasicFileAttributes attrs = attributes(journal, false);
            if (!(parentKey == null ? directory.fileKey() == null : parentKey.equals(directory.fileKey()))
                    || !parentCreationTime.equals(directory.creationTime())
                    || !(fileKey == null ? attrs.fileKey() == null : fileKey.equals(attrs.fileKey()))
                    || !creationTime.equals(attrs.creationTime())
                    || attrs.size() != length || channel.size() != length)
                throw new IOException("owned diagnostic journal identity or length changed");
        }

        @Override public synchronized void append(Path path, byte[] bytes) throws IOException {
            if (closed || failure != null) throw new IOException("owned diagnostic journal is closed or poisoned", failure);
            try {
                if (!journal.equals(path)) throw new IOException("owned diagnostic journal path mismatch");
                if (channel == null) openOnce();
                verify(expectedEnd);
                long nextEnd = Math.addExact(expectedEnd, bytes.length);
                ByteBuffer buffer = ByteBuffer.wrap(bytes);
                while (buffer.hasRemaining()) channel.write(buffer);
                channel.force(true);
                verify(nextEnd);
                expectedEnd = nextEnd;
            } catch (Throwable failed) {
                poison(failed);
                if (failed instanceof IOException) throw (IOException) failed;
                if (failed instanceof RuntimeException) throw (RuntimeException) failed;
                if (failed instanceof Error) throw (Error) failed;
                throw new IOException("owned diagnostic journal I/O failed", failed);
            }
        }

        private void poison(Throwable failed) {
            if (failure == null) failure = failed;
            closed = true;
            if (channel != null) {
                try { channel.close(); }
                catch (Throwable closeFailure) { if (closeFailure != failed) failed.addSuppressed(closeFailure); }
            }
        }

        /** Only failed initialization/I/O cleanup, or an SDK-free fixture owner, closes early.
         * Production never calls this from Scope.close, timeout, sticky stop or Service.stop.
         */
        @Override public synchronized void close() throws IOException {
            if (closed) return;
            closed = true;
            if (channel != null) {
                try { channel.close(); }
                catch (IOException failed) { failure = failed; throw failed; }
            }
        }
    }
    private static final AtomicReference<RuntimeState> INSTANCE = new AtomicReference<>();
    private static final ThreadLocal<Context> CURRENT = new ThreadLocal<>();
    private static final int MAX_POLL_BYTES = 1 << 20;
    private static final int MAX_TAIL_BYTES = 65536;

    /** A local stop, deliberately distinct from an unreturned native read. */
    static final class Fatal extends Error {
        private static final long serialVersionUID = 1L;
        final String reason;
        final String boundary;
        Fatal(String reason, String boundary, Throwable cause) {
            super("native diagnostic stopped: " + reason + " at " + boundary, cause);
            this.reason = reason;
            this.boundary = boundary;
        }
    }

    private static final class RuntimeState {
        final Path journal;
        final Map<String, Object> identity;
        final Sink sink;
        final List<LogCursor> logs = new ArrayList<>();
        final AtomicReference<Fatal> stopped = new AtomicReference<>();
        final AtomicReference<Map<String, Object>> latest = new AtomicReference<>(Map.of("status", "no_call_observed"));
        final AtomicReference<Map<String, Object>> lastCall = new AtomicReference<>(Map.of("status", "no_call_observed"));
        final List<Map<String, Object>> effects = new ArrayList<>();
        volatile Map<String, Object> unreturnedRequest;
        volatile boolean initialized;
        long sequence;
        RuntimeState(Path state, Map<String, Object> identity, Sink sink) {
            journal = state.toAbsolutePath().normalize().resolve("native-read-trace.ndjson");
            this.identity = pureMap(identity);
            this.sink = sink == null ? new OwnedJournal(journal) : sink;
        }
    }

    private static final class Context {
        final RuntimeState runtime;
        final Map<String, Object> fields;
        final Map<String, Integer> traversals = new LinkedHashMap<>();
        Context(RuntimeState runtime, Map<String, Object> fields) {
            this.runtime = runtime;
            this.fields = new LinkedHashMap<>(fields);
            for (String key : List.of("phase", "drawing_observed", "note_id", "line_index", "fragment_index"))
                this.fields.putIfAbsent(key, "unobserved");
        }
    }

    static final class Scope implements AutoCloseable {
        private final Context previous;
        private final Map<String, Object> saved;
        private final boolean request;
        private Scope(Context previous, Map<String, Object> saved, boolean request) {
            this.previous = previous;
            this.saved = saved;
            this.request = request;
        }
        @Override public void close() {
            // Closing an individual request never clears the service-instance stop.
            if (request) { if (previous == null) CURRENT.remove(); else CURRENT.set(previous); }
            else if (previous != null) { previous.fields.clear(); previous.fields.putAll(saved); }
        }
    }

    /** Configure once per service generation. Called only for an explicitly enabled diagnostic. */
    static synchronized void initialize(Path state, Map<String, Object> identity, List<Path> logs) {
        initialize(state, identity, logs, null);
    }

    /** Package-private injection for SDK-free tests; production never supplies a replacement sink. */
    static synchronized void initialize(Path state, Map<String, Object> identity, List<Path> logs, Sink sink) {
        if (INSTANCE.get() != null) {
            RuntimeState existing = INSTANCE.get();
            if (!existing.identity.equals(pureMap(identity)))
                throw stop(existing, "diagnostic_generation_identity_changed", "initialize", null);
            check();
            return;
        }
        RuntimeState runtime = new RuntimeState(state, identity, sink);
        INSTANCE.set(runtime);
        try {
            for (Path path : logs) {
                if (!path.isAbsolute()) throw new IOException("declared native log path must be absolute");
                runtime.logs.add(new LogCursor(path.toAbsolutePath().normalize()));
            }
            if (runtime.logs.isEmpty()) throw new IOException("no native logs declared");
            persist(runtime, event(runtime, "diagnostic_initialized", null, 0), "initialize");
            poll(runtime, "initialize");
            runtime.initialized = true;
        } catch (Fatal fatal) { closeFailedInitialization(runtime, fatal); throw fatal; }
        catch (Throwable failure) {
            Fatal fatal = stop(runtime, "native_log_observation_unreliable", "initialize", failure);
            closeFailedInitialization(runtime, fatal);
            throw fatal;
        }
    }

    private static void closeFailedInitialization(RuntimeState runtime, Throwable original) {
        if (!runtime.initialized && runtime.sink instanceof OwnedJournal) {
            try { ((OwnedJournal) runtime.sink).close(); }
            catch (Throwable closeFailure) { if (closeFailure != original) original.addSuppressed(closeFailure); }
        }
    }

    static boolean enabled() { return INSTANCE.get() != null; }
    static boolean active() { return CURRENT.get() != null; }

    static void initializationFailed(Path state, Map<String, Object> identity, Throwable failure) {
        RuntimeState runtime = INSTANCE.get();
        if (runtime == null) {
            RuntimeState candidate = new RuntimeState(state, identity, null);
            INSTANCE.compareAndSet(null, candidate);
            runtime = INSTANCE.get();
        }
        Map<String, Object> observed = event(runtime, "diagnostic_configuration_invalid", null, runtime.sequence);
        observed.put("failure_class", failure.getClass().getName());
        try { persist(runtime, observed, "initialize"); }
        catch (Fatal fatal) { closeFailedInitialization(runtime, fatal); throw fatal; }
        Fatal fatal = stop(runtime, "diagnostic_configuration_invalid", "initialize", failure);
        closeFailedInitialization(runtime, fatal);
        throw fatal;
    }

    /** Bind plain request identity inside the real toolkit closure, not on its HTTP thread. */
    static Scope begin(Map<String, Object> identity) {
        RuntimeState runtime = INSTANCE.get();
        Context previous = CURRENT.get();
        if (runtime == null) return new Scope(previous, null, true);
        check();
        Map<String, Object> fields = new LinkedHashMap<>(runtime.identity);
        fields.putAll(pureMap(identity));
        Context context = new Context(runtime, fields);
        CURRENT.set(context);
        try {
            persist(runtime, event(runtime, "request_begin", null, runtime.sequence), "request_begin");
            return new Scope(previous, null, true);
        } catch (Throwable failure) {
            if (previous == null) CURRENT.remove(); else CURRENT.set(previous);
            throw failure;
        }
    }

    static Scope scope(String... pairs) {
        if (pairs.length % 2 != 0) throw new IllegalArgumentException("scope expects key/value pairs");
        Context context = CURRENT.get();
        if (context == null) return new Scope(null, null, false);
        check();
        Map<String, Object> saved = new LinkedHashMap<>(context.fields);
        for (int i = 0; i < pairs.length; i += 2) context.fields.put(pairs[i], pairs[i + 1]);
        return new Scope(context, saved, false);
    }

    static void stage(String stage) { known("phase", stage); }
    static void phase(String stage) { stage(stage); }
    static void known(String key, Object value) {
        Context context = CURRENT.get();
        if (context != null) {
            if (!allowCompletionEvidence(context.runtime)) ensureHealthy();
            context.fields.put(key, pure(value));
        }
    }
    static Object knownValue(String key) {
        Context context = CURRENT.get();
        return context == null ? null : pure(context.fields.get(key));
    }
    static int traversal(String stage) {
        Context context = CURRENT.get();
        if (context == null) return 0;
        if (!allowCompletionEvidence(context.runtime)) ensureHealthy();
        int count = context.traversals.getOrDefault(stage, 0) + 1;
        context.traversals.put(stage, count);
        known("traversal_ordinal", count);
        return count;
    }

    /** An already obtained effect fact; recording it never obtains an object ID or calls CAD. */
    static void effect(String name, Map<String, Object> facts) {
        RuntimeState runtime = INSTANCE.get();
        if (runtime == null) return;
        if (!allowCompletionEvidence(runtime)) ensureHealthy();
        Map<String, Object> out = event(runtime, "effect", null, runtime.sequence);
        out.put("effect", name);
        out.put("effect_contract_version", 1);
        out.put("facts", pureMap(facts));
        persist(runtime, out, "effect");
        synchronized (runtime) { runtime.effects.add(out); }
    }

    /** Check the sticky gate without polling. Safe for catch blocks and HTTP health. */
    static void ensureHealthy() {
        RuntimeState runtime = INSTANCE.get();
        if (runtime != null && runtime.stopped.get() != null) throw runtime.stopped.get();
    }
    /** Observe only declared local logs, then refuse the next native dispatch if needed. */
    static void check() {
        ensureHealthy();
        RuntimeState runtime = INSTANCE.get();
        if (runtime != null) poll(runtime, "before_next_dispatch");
        ensureHealthy();
    }
    static void rethrowFatal(Throwable failure) {
        if (failure instanceof Fatal) throw (Fatal) failure;
        ensureHealthy();
    }

    static <T> T call(String getter, Call<T> action) {
        check();
        Context context = CURRENT.get();
        if (context == null) return unchecked(action);
        RuntimeState runtime = context.runtime;
        long sequence;
        synchronized (runtime) { sequence = ++runtime.sequence; }
        Map<String, Object> begin = event(runtime, "begin", getter, sequence);
        begin.put("native_call_state", "begin_durable_before_call; entry_not_independently_observed_until_end");
        persist(runtime, begin, "begin");
        long started = System.nanoTime();
        T value;
        try { value = action.run(); }
        catch (Throwable failure) {
            // Never inspect message/toString or toolkit exception-detail getters.
            Map<String, Object> end = event(runtime, "end", getter, sequence);
            end.put("duration_ns", Math.max(0L, System.nanoTime() - started));
            end.put("native_call_entered", true);
            end.put("result", "threw");
            end.put("exception_class", failure.getClass().getName());
            if (runtime.stopped.get() == null || allowCompletionEvidence(runtime)) persist(runtime, end, "end");
            rethrowFatal(failure);
            poll(runtime, "after_call_threw");
            return NativeReadTrace.<RuntimeException, T>raise(failure);
        }
        Map<String, Object> end = event(runtime, "end", getter, sequence);
        end.put("duration_ns", Math.max(0L, System.nanoTime() - started));
        end.put("native_call_entered", true);
        end.put("result", value == null ? "returned_null"
                : value instanceof String || value instanceof Number || value instanceof Boolean
                ? "returned_scalar" : "returned_object");
        if (value instanceof Integer || value instanceof Long || value instanceof Boolean
                || value instanceof Double && Double.isFinite((Double) value)) end.put("scalar_value", pure(value));
        // Classification only; no proxy is serialized or converted to a string.
        persist(runtime, end, "end");
        poll(runtime, "after_call_returned");
        return value;
    }
    static void run(String name, VoidCall action) { call(name, () -> { action.run(); return null; }); }
    private static <T> T unchecked(Call<T> action) {
        try { return action.run(); }
        catch (Throwable failure) { return NativeReadTrace.<RuntimeException, T>raise(failure); }
    }
    @SuppressWarnings("unchecked") private static <E extends Throwable, T> T raise(Throwable failure) throws E { throw (E) failure; }

    static Map<String, Object> latest() {
        RuntimeState runtime = INSTANCE.get();
        return runtime == null ? Json.map("status", "disabled") : pureMap(runtime.latest.get());
    }
    static Map<String, Object> stopEvidence() {
        RuntimeState runtime = INSTANCE.get();
        if (runtime == null) return Json.map("contract_version", 1, "enabled", false, "stopped", false);
        Fatal fatal = runtime.stopped.get();
        Map<String, Object> out = Json.map("contract_version", 1, "enabled", true, "stopped", fatal != null,
                "scope", "this_service_instance_not_a_global_database_lock", "last", latest(),
                "last_call", pureMap(runtime.lastCall.get()),
                "journal", runtime.journal.toString(),
                "observation_limit", "buffered_native_logs_only; no_cancellation_of_a_call_already_entered");
        if (fatal != null) {
            out.put("reason", fatal.reason);
            out.put("boundary", fatal.boundary);
            out.put("cause_class", fatal.getCause() == null ? null : fatal.getCause().getClass().getName());
        }
        synchronized (runtime) { out.put("effects", pure(runtime.effects)); }
        if (runtime.unreturnedRequest != null) out.put("unreturned_request", pureMap(runtime.unreturnedRequest));
        return out;
    }

    /** HTTP wait expiry is an observation of an unfinished request, never native cancellation. */
    static void requestUnreturned(Map<String, Object> identity, Map<String, Object> originalError) {
        RuntimeState runtime = INSTANCE.get();
        if (runtime == null || runtime.stopped.get() != null) return;
        Map<String, Object> facts = pureMap(identity);
        facts.put("original_error", pureMap(originalError));
        facts.put("native_cancelled", false);
        facts.put("completion", "not_observed_at_http_wait_expiry");
        runtime.unreturnedRequest = facts;
        Map<String, Object> event = event(runtime, "request_wait_expired_while_started", null, runtime.sequence);
        event.putAll(facts);
        try { persist(runtime, event, "request_wait_expiry"); }
        catch (Fatal persistenceFailure) { return; }
        stop(runtime, "native_request_unreturned_at_wait_expiry", "request_wait_expiry", null);
    }

    private static boolean allowCompletionEvidence(RuntimeState runtime) {
        Fatal stopped = runtime.stopped.get();
        return stopped != null && "native_request_unreturned_at_wait_expiry".equals(stopped.reason);
    }
    static Map<String, Object> error(Throwable failure) {
        return Json.map("code", "E_NATIVE_DIAGNOSTIC", "retryable", false,
                "message", "Native diagnostics stopped this service instance; preserve the scene and do not dispatch more CAD calls.",
                "exception_class", failure.getClass().getName(), "native_diagnostic", stopEvidence());
    }

    /** A fresh process can inspect durable complete records and retain a damaged tail. */
    static Map<String, Object> inspectJournal(Path path) throws Exception {
        byte[] bytes = Files.readAllBytes(path);
        List<Object> complete = new ArrayList<>();
        int start = 0;
        for (int index = 0; index < bytes.length; index++) {
            if (bytes[index] != '\n') continue;
            complete.add(Json.parse(new String(bytes, start, index - start, StandardCharsets.UTF_8)));
            start = index + 1;
        }
        byte[] tail = java.util.Arrays.copyOfRange(bytes, start, bytes.length);
        return Json.map("journal", path.toAbsolutePath().normalize().toString(),
                "bytes", bytes.length, "bytes_sha256", sha256(bytes), "complete_records", complete,
                "incomplete_tail_offset", start, "incomplete_tail_bytes", tail.length,
                "incomplete_tail_sha256", sha256(tail), "complete", tail.length == 0);
    }

    private static Map<String, Object> event(RuntimeState runtime, String kind, String getter, long sequence) {
        Context context = CURRENT.get();
        Map<String, Object> out = new LinkedHashMap<>(context == null ? runtime.identity : context.fields);
        out.put("trace_schema", 2);
        out.put("event", kind);
        out.put("getter", getter);
        out.put("sequence", sequence);
        out.put("observed_at", Instant.now().toString());
        out.put("observed_monotonic_ns", System.nanoTime());
        out.put("thread_id", Thread.currentThread().getId());
        out.put("thread_name", Thread.currentThread().getName());
        return out;
    }
    private static synchronized void persist(RuntimeState runtime, Map<String, Object> event, String boundary) {
        if (!(allowCompletionEvidence(runtime) && ("end".equals(boundary) || "effect".equals(boundary)))) ensureHealthy();
        try {
            runtime.sink.append(runtime.journal, (Json.write(pureMap(event)) + "\n").getBytes(StandardCharsets.UTF_8));
            Map<String, Object> status = new LinkedHashMap<>(event);
            status.put("journal", runtime.journal.toString());
            status.put("status", "begin".equals(boundary) ? "call_started_no_end_yet" : "record_durable");
            runtime.latest.set(status);
            if ("begin".equals(event.get("event")) || "end".equals(event.get("event"))) runtime.lastCall.set(status);
        } catch (Throwable failure) {
            Map<String, Object> status = new LinkedHashMap<>(event);
            status.put("status", "diagnostic_persistence_failed");
            status.put("boundary", boundary);
            status.put("failure_class", failure.getClass().getName());
            runtime.latest.set(status);
            if ("begin".equals(event.get("event")) || "end".equals(event.get("event"))) runtime.lastCall.set(status);
            throw stop(runtime, "diagnostic_persistence_failed", boundary, failure);
        }
    }
    private static Fatal stop(RuntimeState runtime, String reason, String boundary, Throwable cause) {
        Fatal candidate = new Fatal(reason, boundary, cause);
        runtime.stopped.compareAndSet(null, candidate);
        return runtime.stopped.get();
    }

    /** A synchronous file observer. Never calls or inspects a CAD object. */
    private static synchronized void poll(RuntimeState runtime, String boundary) {
        ensureHealthy();
        boolean seriousDetected = false;
        for (LogCursor cursor : runtime.logs) {
            try {
                Map<String, Object> observed = cursor.poll(runtime.sequence);
                if (observed == null) continue;
                Map<String, Object> event = event(runtime, "native_log_window", null, runtime.sequence);
                event.put("window", observed);
                event.put("poll_boundary", boundary);
                persist(runtime, event, "native_log_window");
                // Finish observing the declared file channels; this performs no CAD
                // work and keeps std.out/trail evidence separate rather than adding it.
                seriousDetected |= Boolean.TRUE.equals(observed.get("serious_detected"));
            } catch (Fatal fatal) { throw fatal; }
            catch (Throwable failure) {
                Map<String, Object> status = event(runtime, "native_log_unreliable", null, runtime.sequence);
                status.put("path", cursor.path.toString());
                status.put("failure_class", failure.getClass().getName());
                persist(runtime, status, "native_log_unreliable");
                throw stop(runtime, "native_log_observation_unreliable", boundary, failure);
            }
        }
        if (seriousDetected) throw stop(runtime, "native_serious_message_observed", boundary, null);
    }

    private static final class LogCursor {
        final Path path;
        String fileIdentity;
        long offset;
        long previousSequence;
        byte[] tail = new byte[0];
        byte[] anchor = new byte[0];
        boolean initialized;
        boolean existed;
        LogCursor(Path path) { this.path = path; }

        Map<String, Object> poll(long sequence) throws Exception {
            Instant before = Instant.now();
            long monotonicBefore = System.nanoTime();
            BasicFileAttributes attrs;
            try { attrs = Files.readAttributes(path, BasicFileAttributes.class, LinkOption.NOFOLLOW_LINKS); }
            catch (NoSuchFileException absent) {
                if (existed) throw new IOException("declared native log disappeared", absent);
                if (initialized) return null;
                initialized = true;
                return Json.map("path", path.toString(), "status", "absent_at_initial_observation",
                        "offset_start", 0, "offset_end", 0, "serious_detected", false,
                        "observed_at_start", before.toString(), "observed_at_end", Instant.now().toString());
            }
            if (!attrs.isRegularFile()) throw new IOException("declared native log is not a regular file");
            String identity = attrs.fileKey() == null ? "creation_time:" + attrs.creationTime() : "file_key:" + attrs.fileKey();
            if (existed && !identity.equals(fileIdentity)) throw new IOException("declared native log identity changed");
            if (existed && attrs.size() < offset) throw new IOException("declared native log truncated");
            boolean newFile = !existed;
            if (newFile) {
                fileIdentity = identity;
                existed = true;
                // Existing log bytes are retained and scanned too; no silent seek-to-end.
            }
            boolean first = !initialized || newFile;
            initialized = true;
            long start = offset;
            long size = attrs.size();
            if (size - offset > MAX_POLL_BYTES) throw new IOException("native log increment exceeds bounded observation capacity");
            byte[] bytes = new byte[(int) (size - offset)];
            try (FileChannel channel = FileChannel.open(path, StandardOpenOption.READ)) {
                if (anchor.length > 0) {
                    channel.position(offset - anchor.length);
                    byte[] verify = new byte[anchor.length];
                    ByteBuffer anchorBuffer = ByteBuffer.wrap(verify);
                    while (anchorBuffer.hasRemaining()) {
                        if (channel.read(anchorBuffer) < 0) throw new IOException("native log shortened during prefix validation");
                    }
                    if (!java.util.Arrays.equals(anchor, verify)) throw new IOException("native log previously observed bytes changed");
                }
                channel.position(offset);
                ByteBuffer buffer = ByteBuffer.wrap(bytes);
                while (buffer.hasRemaining()) {
                    int read = channel.read(buffer);
                    if (read < 0) throw new IOException("native log shortened during observation");
                }
                int anchorLength = (int) Math.min(size, 4096L);
                anchor = new byte[anchorLength];
                channel.position(size - anchorLength);
                ByteBuffer anchorBuffer = ByteBuffer.wrap(anchor);
                while (anchorBuffer.hasRemaining()) {
                    if (channel.read(anchorBuffer) < 0) throw new IOException("native log shortened during anchor observation");
                }
            }
            BasicFileAttributes after = Files.readAttributes(path, BasicFileAttributes.class, LinkOption.NOFOLLOW_LINKS);
            String afterIdentity = after.fileKey() == null ? "creation_time:" + after.creationTime() : "file_key:" + after.fileKey();
            if (!identity.equals(afterIdentity) || after.size() < size) throw new IOException("native log changed identity or shortened during observation");
            if (size == start && !first) return null;
            byte[] combined = new byte[tail.length + bytes.length];
            System.arraycopy(tail, 0, combined, 0, tail.length);
            System.arraycopy(bytes, 0, combined, tail.length, bytes.length);
            String text = new String(combined, StandardCharsets.ISO_8859_1);
            String searchable = text.toLowerCase(java.util.Locale.ROOT);
            List<Map<String, Object>> matches = new ArrayList<>();
            for (String marker : List.of("ORDER_DEBUG", "continuing from serious error")) {
                String needle = marker.toLowerCase(java.util.Locale.ROOT);
                int at = searchable.indexOf(needle);
                while (at >= 0) {
                    long absolute = start - tail.length + at;
                    // Include a marker split across polls, but never re-count an old complete one.
                    if (absolute + marker.length() > start) matches.add(Json.map(
                            "marker", marker, "byte_offset", absolute,
                            "bounded_context", text.substring(Math.max(0, at - 48), Math.min(text.length(), at + marker.length() + 128))));
                    at = searchable.indexOf(needle, at + marker.length());
                }
            }
            int newline = text.lastIndexOf('\n');
            int tailStart = newline < 0 ? 0 : newline + 1;
            if (combined.length - tailStart > MAX_TAIL_BYTES) throw new IOException("native log unterminated line exceeds observation capacity");
            tail = java.util.Arrays.copyOfRange(combined, tailStart, combined.length);
            Map<String, Object> out = Json.map("path", path.toString(), "file_identity", identity,
                    "file_identity_source", attrs.fileKey() == null ? "creation_time_fallback" : "filesystem_file_key",
                    "offset_start", start, "offset_end", size, "bytes_sha256", sha256(bytes),
                    "partial_line_bytes", tail.length, "partial_line_sha256", sha256(tail),
                    "status", "increment_observed", "serious_detected", !matches.isEmpty(), "matches", matches,
                    "observed_at_start", before.toString(), "observed_at_end", Instant.now().toString(),
                    "monotonic_start_ns", monotonicBefore, "monotonic_end_ns", System.nanoTime(),
                    "candidate_call_sequence_after", previousSequence, "candidate_call_sequence_through", sequence,
                    "native_event_time_known", false, "channels_are_not_additive_event_counts", true,
                    "native_message_event_count", "not_established_by_marker_count", "_untrusted", List.of("matches"));
            offset = size;
            previousSequence = sequence;
            return out;
        }
    }
    private static String sha256(byte[] bytes) throws Exception {
        StringBuilder out = new StringBuilder();
        for (byte value : MessageDigest.getInstance("SHA-256").digest(bytes)) out.append(String.format("%02x", value & 255));
        return out.toString();
    }
    private static Map<String, Object> pureMap(Map<?, ?> value) {
        Map<String, Object> out = new LinkedHashMap<>();
        for (Map.Entry<?, ?> entry : value.entrySet()) {
            if (!(entry.getKey() instanceof String)) throw new IllegalArgumentException("diagnostic keys must be text");
            out.put((String) entry.getKey(), pure(entry.getValue()));
        }
        return out;
    }
    private static Object pure(Object value) {
        if (value == null || value instanceof String || value instanceof Boolean || value instanceof Integer || value instanceof Long) return value;
        if (value instanceof Double && Double.isFinite((Double) value)) return value;
        if (value instanceof Map) return pureMap((Map<?, ?>) value);
        if (value instanceof List) {
            List<Object> out = new ArrayList<>();
            for (Object item : (List<?>) value) out.add(pure(item));
            return out;
        }
        throw new IllegalArgumentException("diagnostic values must be already captured plain data");
    }
}
