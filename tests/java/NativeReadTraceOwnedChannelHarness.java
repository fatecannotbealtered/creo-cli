package com.fateforge.creocli.service;

import java.io.IOException;
import java.lang.reflect.Field;
import java.nio.ByteBuffer;
import java.nio.MappedByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.channels.FileLock;
import java.nio.channels.ReadableByteChannel;
import java.nio.channels.WritableByteChannel;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.FileSystems;
import java.nio.file.FileSystem;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

/** SDK-free owned JVMs only. The real default writer is exercised, not an injected Sink. */
public final class NativeReadTraceOwnedChannelHarness {
    private static final AtomicInteger CALLS = new AtomicInteger();
    private static Path state;
    private static Path journal;
    private static String mode;
    private static NativeReadTrace.Sink owner;
    private static Spy channel;
    private static int beforeRecords;
    private static int noReopenChecks;
    private static int blockedChecks;

    /** Deliberate plain JVM control error, never a PTC/native fault. */
    private static final class ControlledStorageError extends Error {
        private static final long serialVersionUID = 1L;
    }

    private static Object field(Object target, String name) throws Exception {
        Field field = target.getClass().getDeclaredField(name);
        field.setAccessible(true);
        return field.get(target);
    }
    private static Object runtime() throws Exception {
        Field field = NativeReadTrace.class.getDeclaredField("INSTANCE");
        field.setAccessible(true);
        return ((AtomicReference<?>) field.get(null)).get();
    }
    private static NativeReadTrace.Sink owned() throws Exception {
        return (NativeReadTrace.Sink) field(runtime(), "sink");
    }
    private static void require(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }
    private static NativeReadTrace.Scope request(String id) {
        return NativeReadTrace.begin(Json.map("diagnostic_request_id", id,
                "operation", "controlled.read", "cli_invocation_id", "owned-channel-fixture"));
    }
    private static int records() throws Exception {
        return ((List<?>) NativeReadTrace.inspectJournal(journal).get("complete_records")).size();
    }
    private static void initialize() throws Exception {
        List<Path> logs = List.of(state.resolve("std.out"), state.resolve("std.out.1"), state.resolve("trail.txt.1"));
        NativeReadTrace.initialize(state, Json.map("service_instance_id", "owned-channel-fixture",
                "java_process_id", String.valueOf(ProcessHandle.current().pid())), logs);
        owner = owned();
        FileChannel original = (FileChannel) field(owner, "channel");
        require(original != null && original.isOpen(), "default channel was not opened");
        channel = new Spy(original);
        Field held = owner.getClass().getDeclaredField("channel");
        held.setAccessible(true);
        held.set(owner, channel);
        beforeRecords = records();
    }
    private static void blocked() throws Exception {
        int before = CALLS.get();
        try (NativeReadTrace.Scope scope = request("must-not-run")) {
            NativeReadTrace.call("MustNotRun", CALLS::incrementAndGet);
            throw new AssertionError("stopped generation accepted another action");
        } catch (NativeReadTrace.Fatal expected) { }
        require(CALLS.get() == before, "action dispatched after stop");
        blockedChecks++;
    }
    private static void noReopen() throws Exception {
        Object held = field(owner, "channel");
        long size = Files.isRegularFile(journal) ? Files.size(journal) : -1;
        try {
            owner.append(journal, "{\"never_replayed\":true}\n".getBytes(StandardCharsets.UTF_8));
            throw new AssertionError("poisoned/closed owner accepted append");
        } catch (IOException expected) { }
        require(field(owner, "channel") == held, "poisoned owner reopened its channel");
        require((Files.isRegularFile(journal) ? Files.size(journal) : -1) == size, "append after poison changed bytes");
        noReopenChecks++;
    }
    private static void calls(int count) {
        try (NativeReadTrace.Scope scope = request("normal-owned-request")) {
            for (int i = 0; i < count; i++) NativeReadTrace.call("OwnedPlainGetter", CALLS::incrementAndGet);
        }
    }
    private static void setupFiles() throws Exception {
        Files.createDirectories(state);
        for (String name : List.of("std.out", "std.out.1", "trail.txt.1")) Files.write(state.resolve(name), new byte[0]);
    }
    private static void initializationFailure() throws Exception {
        FileChannel conflict = null;
        if ("init-mkdir-failure".equals(mode)) Files.write(state, new byte[] {7});
        else {
            setupFiles();
            if ("init-log-failure".equals(mode)) {
                Files.delete(state.resolve("std.out"));
                Files.createDirectory(state.resolve("std.out"));
            } else if ("init-open-failure".equals(mode)) {
                conflict = FileChannel.open(journal, StandardOpenOption.CREATE, StandardOpenOption.WRITE);
            }
        }
        try {
            NativeReadTrace.initialize(state, Json.map("service_instance_id", "owned-failed-init"), List.of(state.resolve("std.out")));
            throw new AssertionError("initialization failure was accepted");
        } catch (NativeReadTrace.Fatal expected) { }
        finally { if (conflict != null) conflict.close(); }
        owner = owned();
        require(Boolean.TRUE.equals(field(owner, "closed")), "failed initialization leaked an open writer");
        noReopen();
        blocked();
    }

    public static void main(String[] args) throws Exception {
        mode = args[0]; state = Path.of(args[1]).toAbsolutePath().normalize();
        journal = state.resolve("native-read-trace.ndjson");
        boolean externalBlocked = false;
        boolean parentRenameBlocked = false;
        int historyBytes = 0;
        if (mode.startsWith("init-")) {
            initializationFailure();
        } else if ("provider-refusal".equals(mode)) {
            Files.createDirectories(state);
            Path archive = state.resolve("unsupported-provider.zip");
            try (FileSystem filesystem = FileSystems.newFileSystem(archive, Map.of("create", "true"))) {
                state = filesystem.getPath("/diagnostic");
                journal = state.resolve("native-read-trace.ndjson");
                setupFiles();
                try {
                    NativeReadTrace.initialize(state, Json.map("service_instance_id", "provider-control"), List.of(state.resolve("std.out")));
                    throw new AssertionError("unsupported provider was accepted");
                } catch (NativeReadTrace.Fatal expected) { }
                owner = owned(); noReopen(); blocked();
            }
        } else if ("reparse-parent".equals(mode)) {
            setupFiles();
            try {
                NativeReadTrace.initialize(state, Json.map("service_instance_id", "provider-control"), List.of(state.resolve("std.out")));
                throw new AssertionError("unsupported provider/reparse parent was accepted");
            } catch (NativeReadTrace.Fatal expected) { }
            owner = owned(); noReopen(); blocked();
        } else {
            setupFiles();
            if ("history".equals(mode)) {
                String row = "{\"synthetic_history\":\"" + "x".repeat(262100) + "\"}\n";
                byte[] bytes = row.repeat(80).getBytes(StandardCharsets.UTF_8);
                Files.write(journal, bytes);
                try (FileChannel seed = FileChannel.open(journal, StandardOpenOption.WRITE)) { seed.force(true); }
                historyBytes = bytes.length;
            }
            initialize();
            if ("normal".equals(mode) || "history".equals(mode)) {
                calls("history".equals(mode) ? 60 : 4);
                require(field(owner, "channel") == channel && channel.isOpen(), "one owned handle not retained");
                require(channel.closes == 0, "request scope closed the writer");
                require(records() - beforeRecords == channel.forces, "successful record missing per-record force");
            } else if ("hang".equals(mode) || "halt".equals(mode)) {
                try (NativeReadTrace.Scope scope = request("owned-unreturned")) {
                    NativeReadTrace.call("OwnedGetterThatDoesNotReturn", () -> {
                        CALLS.incrementAndGet();
                        if ("halt".equals(mode)) Runtime.getRuntime().halt(73);
                        new CountDownLatch(1).await();
                        return null;
                    });
                }
            } else if ("concurrent".equals(mode)) {
                CountDownLatch start = new CountDownLatch(1);
                AtomicReference<Throwable> failure = new AtomicReference<>();
                List<Thread> workers = new ArrayList<>();
                for (int i = 0; i < 4; i++) {
                    final int index = i;
                    Thread worker = new Thread(() -> {
                        try { start.await(); try (NativeReadTrace.Scope scope = request("parallel-" + index)) {
                            for (int j = 0; j < 6; j++) NativeReadTrace.call("ParallelGetter", CALLS::incrementAndGet);
                        } } catch (Throwable failed) { failure.compareAndSet(null, failed); }
                    }, "owned-fixture-" + i);
                    workers.add(worker); worker.start();
                }
                start.countDown();
                for (Thread worker : workers) { worker.join(10000); require(!worker.isAlive(), "controlled worker did not finish"); }
                require(failure.get() == null && CALLS.get() == 24, "concurrent append failed");
                require(records() - beforeRecords == channel.forces && channel.closes == 0, "concurrent force/ownership lost");
            } else if ("expiry".equals(mode)) {
                CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1);
                AtomicReference<Throwable> unexpected = new AtomicReference<>();
                Thread toolkit = new Thread(() -> {
                    try (NativeReadTrace.Scope scope = request("owned-expiry")) {
                        NativeReadTrace.call("OwnedReturnsAfterExpiry", () -> {
                            CALLS.incrementAndGet(); entered.countDown(); release.await();
                            NativeReadTrace.effect("owned_returned_effect", Json.map("id", "19", "saved", false));
                            return 9;
                        });
                    } catch (NativeReadTrace.Fatal expected) { }
                    catch (Throwable failed) { unexpected.set(failed); }
                }, "owned-controlled-toolkit");
                toolkit.start(); entered.await();
                NativeReadTrace.requestUnreturned(Json.map("operation", "controlled.read", "diagnostic_request_id", "owned-expiry"),
                        Json.map("code", "E_BUSY", "started", true));
                require(channel.closes == 0 && channel.isOpen(), "HTTP expiry closed owned channel");
                blocked(); release.countDown(); toolkit.join(10000);
                require(!toolkit.isAlive() && unexpected.get() == null && CALLS.get() == 1, "late completion failed");
                require(channel.closes == 0 && records() - beforeRecords == channel.forces, "late evidence not forced");
            } else if ("external-access".equals(mode)) {
                Files.copy(journal, state.resolve("read-only-preserved.ndjson"));
                try (FileChannel other = FileChannel.open(journal, StandardOpenOption.WRITE, StandardOpenOption.TRUNCATE_EXISTING)) {
                    throw new AssertionError("external write sharing was allowed");
                } catch (IOException expected) { }
                try { Files.move(journal, state.resolve("moved.ndjson")); throw new AssertionError("delete sharing was allowed"); }
                catch (IOException expected) { }
                externalBlocked = true; calls(1);
            } else if ("parent-rename".equals(mode)) {
                Path moved = state.resolveSibling(state.getFileName() + "-moved");
                try { Files.move(state, moved); }
                catch (IOException expected) { parentRenameBlocked = true; }
                if (parentRenameBlocked) calls(1);
                else {
                    Files.createDirectories(state);
                    Files.copy(moved.resolve("native-read-trace.ndjson"), journal);
                    try { calls(1); throw new AssertionError("parent replacement accepted"); }
                    catch (NativeReadTrace.Fatal expected) { }
                    noReopen(); blocked();
                }
            } else if ("owner-finish".equals(mode)) {
                calls(1); ((AutoCloseable) owner).close();
                require(!channel.isOpen() && channel.closes == 1, "SDK-free owner finish did not close");
                noReopen();
                try { calls(1); throw new AssertionError("closed owner reused"); }
                catch (NativeReadTrace.Fatal expected) { }
                blocked();
            } else if ("wrong-path".equals(mode)) {
                try { owner.append(state.resolve("other.ndjson"), "{}\n".getBytes(StandardCharsets.UTF_8)); throw new AssertionError("wrong path accepted"); }
                catch (IOException expected) { }
                require(!Files.exists(state.resolve("other.ndjson")), "wrong path created");
                noReopen();
                try { calls(1); throw new AssertionError("poisoned path reused"); } catch (NativeReadTrace.Fatal expected) { }
                blocked();
            } else if ("extra-append".equals(mode) || "truncate".equals(mode)) {
                if ("truncate".equals(mode)) channel.delegate.truncate(Files.size(journal) - 1);
                else channel.delegate.write(ByteBuffer.wrap("{\"external\":true}\n".getBytes(StandardCharsets.UTF_8)));
                channel.delegate.force(true);
                long before = Files.size(journal);
                try { calls(1); throw new AssertionError("length drift accepted"); } catch (NativeReadTrace.Fatal expected) { }
                require(Files.size(journal) == before, "appended after length drift"); noReopen(); blocked();
            } else if ("closed-channel".equals(mode) || "interrupted-channel".equals(mode)) {
                if ("closed-channel".equals(mode)) channel.delegate.close();
                else Thread.currentThread().interrupt();
                try { owner.append(journal, "{}\n".getBytes(StandardCharsets.UTF_8)); throw new AssertionError("invalid channel accepted"); }
                catch (IOException expected) { }
                finally { Thread.interrupted(); }
                noReopen();
                try { calls(1); throw new AssertionError("invalid channel reopened"); } catch (NativeReadTrace.Fatal expected) { }
                blocked();
            } else {
                channel.fault = mode;
                try { calls(1); throw new AssertionError("storage fault accepted"); }
                catch (NativeReadTrace.Fatal expected) { }
                noReopen(); blocked();
                require(CALLS.get() == (mode.endsWith("-end") ? 1 : 0), "wrong action count at failed boundary");
            }
        }
        Map<String, Object> output = Json.map("ok", true, "kind", "default_owned_channel_SDK_free_no_CAD",
                "mode", mode, "calls", CALLS.get(), "native_diagnostic", NativeReadTrace.stopEvidence(),
                "history_bytes", historyBytes, "external_mutation_blocked", externalBlocked,
                "parent_rename_blocked", parentRenameBlocked, "actual_CAD_calls", 0,
                "injected_Sink", false, "explicit_fixture_owner_finish", "owner-finish".equals(mode),
                "no_reopen_checks_passed", noReopenChecks, "next_action_block_checks_passed", blockedChecks);
        if (channel != null) output.put("channel", Json.map("write_calls", channel.writes,
                "force_true_calls", channel.forces, "close_calls", channel.closes,
                "open_before_JVM_exit", channel.isOpen(), "records_before_spy", beforeRecords));
        System.out.println(Json.write(output));
    }

    /** Decorates the real FileChannel only inside this SDK-free child; never a product backend. */
    private static final class Spy extends FileChannel {
        final FileChannel delegate;
        int writes, forces, closes;
        String fault = "";
        String current = "";
        boolean partial;
        Spy(FileChannel delegate) { this.delegate = delegate; }
        private boolean boundary(String kind) { return fault.endsWith("-" + kind) && current.contains("\"event\":\"" + kind + "\""); }
        @Override public int write(ByteBuffer src) throws IOException {
            writes++;
            if (src.position() == 0) {
                ByteBuffer copy = src.duplicate(); byte[] bytes = new byte[copy.remaining()]; copy.get(bytes);
                current = new String(bytes, StandardCharsets.UTF_8); partial = false;
            }
            boolean selected = boundary("begin") || boundary("end");
            if (selected && fault.startsWith("unchecked-")) throw new UnsupportedOperationException("controlled provider failure");
            if (selected && fault.startsWith("security-")) throw new SecurityException("controlled provider security failure");
            if (selected && fault.startsWith("error-")) throw new ControlledStorageError();
            if (selected && (fault.startsWith("write-") || fault.startsWith("partial-") && partial))
                throw new IOException("controlled default-channel write failure");
            int limit = src.limit();
            src.limit(Math.min(limit, src.position() + 17));
            try { int count = delegate.write(src); partial = true; return count; }
            finally { src.limit(limit); }
        }
        @Override public void force(boolean metadata) throws IOException {
            require(metadata, "force(true) removed"); forces++;
            if (fault.startsWith("force-") && (boundary("begin") || boundary("end")))
                throw new IOException("controlled default-channel force failure");
            delegate.force(metadata);
        }
        @Override protected void implCloseChannel() throws IOException { closes++; delegate.close(); }
        @Override public int read(ByteBuffer dst) throws IOException { return delegate.read(dst); }
        @Override public long read(ByteBuffer[] dst, int offset, int length) throws IOException { return delegate.read(dst, offset, length); }
        @Override public int read(ByteBuffer dst, long position) throws IOException { return delegate.read(dst, position); }
        @Override public long write(ByteBuffer[] src, int offset, int length) throws IOException { return delegate.write(src, offset, length); }
        @Override public int write(ByteBuffer src, long position) throws IOException { return delegate.write(src, position); }
        @Override public long position() throws IOException { return delegate.position(); }
        @Override public FileChannel position(long position) throws IOException { delegate.position(position); return this; }
        @Override public long size() throws IOException { return delegate.size(); }
        @Override public FileChannel truncate(long size) throws IOException { delegate.truncate(size); return this; }
        @Override public long transferTo(long position, long count, WritableByteChannel target) throws IOException { return delegate.transferTo(position, count, target); }
        @Override public long transferFrom(ReadableByteChannel source, long position, long count) throws IOException { return delegate.transferFrom(source, position, count); }
        @Override public MappedByteBuffer map(MapMode mode, long position, long size) throws IOException { return delegate.map(mode, position, size); }
        @Override public FileLock lock(long position, long size, boolean shared) throws IOException { return delegate.lock(position, size, shared); }
        @Override public FileLock tryLock(long position, long size, boolean shared) throws IOException { return delegate.tryLock(position, size, shared); }
    }
}
