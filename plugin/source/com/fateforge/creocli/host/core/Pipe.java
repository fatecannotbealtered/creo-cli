package com.fateforge.creocli.host.core;

import java.lang.foreign.Arena;
import java.lang.foreign.FunctionDescriptor;
import java.lang.foreign.Linker;
import java.lang.foreign.MemoryLayout;
import java.lang.foreign.MemorySegment;
import java.lang.foreign.StructLayout;
import java.lang.foreign.SymbolLookup;
import java.lang.invoke.MethodHandle;
import java.lang.invoke.VarHandle;
import java.nio.charset.StandardCharsets;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;

import static java.lang.foreign.ValueLayout.ADDRESS;
import static java.lang.foreign.ValueLayout.JAVA_INT;

/**
 * A Windows named pipe server for the host protocol (DCLI-270), through the Foreign
 * Function and Memory API: the JDK has no pipe server of its own. Only the current Windows
 * user may connect (the pipe's DACL names that user's SID alone), remote clients are
 * refused, and the first instance is created with FILE_FLAG_FIRST_PIPE_INSTANCE so no other
 * process can have claimed the name first. Each connection gets its own thread.
 */
public final class Pipe {
    /** One connected client. */
    public interface Stream {
        /** Up to {@code max} bytes, or an empty array at the end of the stream. */
        byte[] read(int max);

        void write(byte[] data);

        void close();
    }

    /** What to do with each connection; runs on that connection's own thread. */
    public interface Handler {
        void serve(Stream stream);
    }

    private static final int PIPE_ACCESS_DUPLEX = 0x3;
    private static final int FILE_FLAG_FIRST_PIPE_INSTANCE = 0x00080000;
    private static final int PIPE_REJECT_REMOTE_CLIENTS = 0x8;
    private static final int PIPE_UNLIMITED_INSTANCES = 255;
    private static final int ERROR_PIPE_CONNECTED = 535;
    private static final int GENERIC_READ_WRITE = 0xC0000000;
    private static final int OPEN_EXISTING = 3;
    private static final int TOKEN_QUERY = 0x8;
    private static final int TOKEN_USER = 1;
    private static final int BUFFER = 65536;

    private static final Linker LINKER = Linker.nativeLinker();
    private static final StructLayout CAPTURE = Linker.Option.captureStateLayout();
    private static final VarHandle LAST_ERROR = CAPTURE.varHandle(MemoryLayout.PathElement.groupElement("GetLastError"));
    private static final SymbolLookup KERNEL = SymbolLookup.libraryLookup("kernel32", Arena.global());
    private static final SymbolLookup ADVAPI = SymbolLookup.libraryLookup("advapi32", Arena.global());

    private static final MethodHandle CREATE_NAMED_PIPE = kernel("CreateNamedPipeW",
            FunctionDescriptor.of(ADDRESS, ADDRESS, JAVA_INT, JAVA_INT, JAVA_INT, JAVA_INT, JAVA_INT, JAVA_INT, ADDRESS), true);
    private static final MethodHandle CONNECT_NAMED_PIPE = kernel("ConnectNamedPipe",
            FunctionDescriptor.of(JAVA_INT, ADDRESS, ADDRESS), true);
    private static final MethodHandle DISCONNECT_NAMED_PIPE = kernel("DisconnectNamedPipe",
            FunctionDescriptor.of(JAVA_INT, ADDRESS), false);
    private static final MethodHandle READ_FILE = kernel("ReadFile",
            FunctionDescriptor.of(JAVA_INT, ADDRESS, ADDRESS, JAVA_INT, ADDRESS, ADDRESS), true);
    private static final MethodHandle WRITE_FILE = kernel("WriteFile",
            FunctionDescriptor.of(JAVA_INT, ADDRESS, ADDRESS, JAVA_INT, ADDRESS, ADDRESS), true);
    private static final MethodHandle FLUSH = kernel("FlushFileBuffers", FunctionDescriptor.of(JAVA_INT, ADDRESS), false);
    private static final MethodHandle CLOSE_HANDLE = kernel("CloseHandle", FunctionDescriptor.of(JAVA_INT, ADDRESS), false);
    private static final MethodHandle CREATE_FILE = kernel("CreateFileW",
            FunctionDescriptor.of(ADDRESS, ADDRESS, JAVA_INT, JAVA_INT, ADDRESS, JAVA_INT, JAVA_INT, ADDRESS), false);
    private static final MethodHandle GET_CURRENT_PROCESS = kernel("GetCurrentProcess", FunctionDescriptor.of(ADDRESS), false);
    private static final MethodHandle LOCAL_FREE = kernel("LocalFree", FunctionDescriptor.of(ADDRESS, ADDRESS), false);
    private static final MethodHandle OPEN_PROCESS_TOKEN = advapi("OpenProcessToken",
            FunctionDescriptor.of(JAVA_INT, ADDRESS, JAVA_INT, ADDRESS));
    private static final MethodHandle GET_TOKEN_INFORMATION = advapi("GetTokenInformation",
            FunctionDescriptor.of(JAVA_INT, ADDRESS, JAVA_INT, ADDRESS, JAVA_INT, ADDRESS));
    private static final MethodHandle SID_TO_STRING = advapi("ConvertSidToStringSidW",
            FunctionDescriptor.of(JAVA_INT, ADDRESS, ADDRESS));
    private static final MethodHandle SDDL_TO_SD = advapi("ConvertStringSecurityDescriptorToSecurityDescriptorW",
            FunctionDescriptor.of(JAVA_INT, ADDRESS, JAVA_INT, ADDRESS, ADDRESS));

    private static MethodHandle kernel(String name, FunctionDescriptor descriptor, boolean lastError) {
        MemorySegment symbol = KERNEL.find(name).orElseThrow(() -> new IllegalStateException("kernel32 has no " + name));
        return lastError ? LINKER.downcallHandle(symbol, descriptor, Linker.Option.captureCallState("GetLastError"))
                : LINKER.downcallHandle(symbol, descriptor);
    }

    private static MethodHandle advapi(String name, FunctionDescriptor descriptor) {
        return LINKER.downcallHandle(ADVAPI.find(name).orElseThrow(() -> new IllegalStateException("advapi32 has no " + name)),
                descriptor);
    }

    public final String name;
    private final Handler handler;
    private final MemorySegment securityAttributes;
    private final Set<MemorySegment> open = ConcurrentHashMap.newKeySet();
    private volatile boolean stopping;
    private Thread acceptor;

    /** A pipe named {@code \\.\pipe\<leaf>}; nothing is created before {@link #start()}. */
    public Pipe(String leaf, Handler handler) {
        this.name = "\\\\.\\pipe\\" + leaf;
        this.handler = handler;
        this.securityAttributes = currentUserOnly();
    }

    public synchronized void start() {
        MemorySegment first = create(true);
        acceptor = new Thread(() -> acceptLoop(first), "creo-cli-host-pipe");
        acceptor.setDaemon(true);
        acceptor.start();
    }

    /** Stop accepting and end every open connection. */
    public synchronized void stop() {
        if (stopping) {
            return;
        }
        stopping = true;
        // Wake the acceptor, which waits in ConnectNamedPipe, by connecting once ourselves.
        try (Arena arena = Arena.ofConfined()) {
            MemorySegment handle = (MemorySegment) CREATE_FILE.invokeExact(arena.allocateFrom(name, StandardCharsets.UTF_16LE),
                    GENERIC_READ_WRITE, 0, MemorySegment.NULL, OPEN_EXISTING, 0, MemorySegment.NULL);
            if (handle.address() != -1L) {
                int ignored = (int) CLOSE_HANDLE.invokeExact(handle);
            }
        } catch (Throwable ignored) {
            // The acceptor ends at its next connection, or with the JVM.
        }
        for (MemorySegment handle : open) {
            end(handle);
        }
    }

    // ------------------------------------------------------------------ server

    private void acceptLoop(MemorySegment handle) {
        while (true) {
            boolean connected;
            try (Arena arena = Arena.ofConfined()) {
                MemorySegment state = arena.allocate(CAPTURE);
                int ok = (int) CONNECT_NAMED_PIPE.invokeExact(state, handle, MemorySegment.NULL);
                connected = ok != 0 || (int) LAST_ERROR.get(state, 0L) == ERROR_PIPE_CONNECTED;
            } catch (Throwable failure) {
                connected = false;
            }
            if (stopping || !connected) {
                closeRaw(handle);
                if (stopping) {
                    return;
                }
            } else {
                MemorySegment client = handle;
                open.add(client);
                Thread thread = new Thread(() -> serve(client), "creo-cli-host-connection");
                thread.setDaemon(true);
                thread.start();
            }
            try {
                handle = create(false);
            } catch (RuntimeException failure) {
                return;
            }
        }
    }

    private void serve(MemorySegment handle) {
        try {
            handler.serve(new Connection(handle));
        } catch (Throwable ignored) {
            // A broken connection ends here; the CLI sees the closed stream.
        } finally {
            end(handle);
        }
    }

    /** End a connected client's handle, once: stop() and the connection's own thread may both try. */
    private void end(MemorySegment handle) {
        if (!open.remove(handle)) {
            return;
        }
        try {
            int a = (int) FLUSH.invokeExact(handle);
            int b = (int) DISCONNECT_NAMED_PIPE.invokeExact(handle);
        } catch (Throwable ignored) {
            // Closed below all the same.
        }
        closeRaw(handle);
    }

    private static void closeRaw(MemorySegment handle) {
        try {
            int c = (int) CLOSE_HANDLE.invokeExact(handle);
        } catch (Throwable ignored) {
            // Nothing more can be done with this handle.
        }
    }

    private MemorySegment create(boolean first) {
        try (Arena arena = Arena.ofConfined()) {
            MemorySegment state = arena.allocate(CAPTURE);
            int mode = PIPE_ACCESS_DUPLEX | (first ? FILE_FLAG_FIRST_PIPE_INSTANCE : 0);
            MemorySegment handle = (MemorySegment) CREATE_NAMED_PIPE.invokeExact(state,
                    arena.allocateFrom(name, StandardCharsets.UTF_16LE), mode, PIPE_REJECT_REMOTE_CLIENTS,
                    PIPE_UNLIMITED_INSTANCES, BUFFER, BUFFER, 0, securityAttributes);
            if (handle.address() == -1L) {
                throw new IllegalStateException("CreateNamedPipeW failed for " + name + ": error " + (int) LAST_ERROR.get(state, 0L));
            }
            return handle;
        } catch (RuntimeException failure) {
            throw failure;
        } catch (Throwable failure) {
            throw new IllegalStateException("CreateNamedPipeW failed: " + failure, failure);
        }
    }

    private static final class Connection implements Stream {
        private final MemorySegment handle;
        private final Arena arena = Arena.ofShared();
        private final MemorySegment buffer = arena.allocate(BUFFER);
        private final MemorySegment count = arena.allocate(JAVA_INT);
        private final MemorySegment state = arena.allocate(CAPTURE);

        Connection(MemorySegment handle) {
            this.handle = handle;
        }

        @Override
        public byte[] read(int max) {
            int wanted = Math.min(max, BUFFER);
            try {
                int ok = (int) READ_FILE.invokeExact(state, handle, buffer, wanted, count, MemorySegment.NULL);
                int got = count.get(JAVA_INT, 0);
                if (ok == 0 || got <= 0) {
                    return new byte[0];
                }
                return buffer.asSlice(0, got).toArray(java.lang.foreign.ValueLayout.JAVA_BYTE);
            } catch (Throwable failure) {
                return new byte[0];
            }
        }

        @Override
        public void write(byte[] data) {
            int done = 0;
            while (done < data.length) {
                int size = Math.min(BUFFER, data.length - done);
                MemorySegment.copy(data, done, buffer, java.lang.foreign.ValueLayout.JAVA_BYTE, 0, size);
                int ok;
                try {
                    ok = (int) WRITE_FILE.invokeExact(state, handle, buffer, size, count, MemorySegment.NULL);
                } catch (Throwable failure) {
                    throw new IllegalStateException("WriteFile failed: " + failure, failure);
                }
                int written = count.get(JAVA_INT, 0);
                if (ok == 0 || written <= 0) {
                    throw new IllegalStateException("WriteFile failed: error " + (int) LAST_ERROR.get(state, 0L));
                }
                done += written;
            }
        }

        @Override
        public void close() {
            // The server ends the handle when serve() returns.
        }
    }

    // ------------------------------------------------------------------ security

    /** SECURITY_ATTRIBUTES whose DACL allows the current user, and nobody else. */
    private static MemorySegment currentUserOnly() {
        Arena arena = Arena.global();
        String sid = currentUserSid();
        try {
            MemorySegment sd = arena.allocate(ADDRESS);
            int ok = (int) SDDL_TO_SD.invokeExact(arena.allocateFrom("D:P(A;;GA;;;" + sid + ")", StandardCharsets.UTF_16LE),
                    1, sd, MemorySegment.NULL);
            if (ok == 0) {
                throw new IllegalStateException("the pipe's security descriptor could not be built");
            }
            MemorySegment attributes = arena.allocate(24, 8);
            attributes.set(JAVA_INT, 0, 24);
            attributes.set(ADDRESS, 8, sd.get(ADDRESS, 0));
            attributes.set(JAVA_INT, 16, 0);
            return attributes;
        } catch (RuntimeException failure) {
            throw failure;
        } catch (Throwable failure) {
            throw new IllegalStateException("the pipe's security descriptor could not be built: " + failure, failure);
        }
    }

    /** The string SID of the user this process runs as, such as S-1-5-21-...-1001. */
    public static String currentUserSid() {
        try (Arena arena = Arena.ofConfined()) {
            MemorySegment process = (MemorySegment) GET_CURRENT_PROCESS.invokeExact();
            MemorySegment token = arena.allocate(ADDRESS);
            if ((int) OPEN_PROCESS_TOKEN.invokeExact(process, TOKEN_QUERY, token) == 0) {
                throw new IllegalStateException("OpenProcessToken failed");
            }
            MemorySegment tokenHandle = token.get(ADDRESS, 0);
            try {
                MemorySegment info = arena.allocate(256, 8);
                MemorySegment size = arena.allocate(JAVA_INT);
                if ((int) GET_TOKEN_INFORMATION.invokeExact(tokenHandle, TOKEN_USER, info, 256, size) == 0) {
                    throw new IllegalStateException("GetTokenInformation failed");
                }
                MemorySegment sid = info.get(ADDRESS, 0);
                MemorySegment text = arena.allocate(ADDRESS);
                if ((int) SID_TO_STRING.invokeExact(sid, text) == 0) {
                    throw new IllegalStateException("ConvertSidToStringSidW failed");
                }
                MemorySegment chars = text.get(ADDRESS, 0);
                String out = chars.reinterpret(1024).getString(0, StandardCharsets.UTF_16LE);
                MemorySegment freed = (MemorySegment) LOCAL_FREE.invokeExact(chars);
                return out;
            } finally {
                int closed = (int) CLOSE_HANDLE.invokeExact(tokenHandle);
            }
        } catch (RuntimeException failure) {
            throw failure;
        } catch (Throwable failure) {
            throw new IllegalStateException("the current user's SID could not be read: " + failure, failure);
        }
    }
}
