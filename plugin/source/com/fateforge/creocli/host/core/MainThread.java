package com.fateforge.creocli.host.core;

import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;

/**
 * The hand-off to the application's main thread (DCLI-276).
 *
 * <p>Pipe threads never call the application. They hand one task at a time to this class;
 * the application's timer calls {@link #pump()} on the main thread, which runs it. Only one
 * task exists at a time: a request that arrives while another is queued or running waits for
 * it, so short requests that meet, such as a job's worker and the poll of that job, take
 * turns. A request that cannot start within its pickup time, because another request holds
 * the main thread or the main thread takes nothing, is withdrawn and answered {@code E_BUSY}
 * -- nothing was dispatched. A task can ask to continue on a later tick, for work Creo allows only after
 * control went back to it (closing a window before erasing its model).
 */
public final class MainThread {
    /** What a task does on the main thread. */
    public interface Task {
        Object run() throws Exception;
    }

    /** Returned by a task that must finish on a later tick. */
    public static final class Later {
        final Task next;

        public Later(Task next) {
            this.next = next;
        }
    }

    /** No reply could be given within the deadline; the protocol layer sends nothing. */
    public static final Object NO_REPLY = new Object();

    private static final long RETRY_AFTER_MS = 500;
    private static final long GRACE_MS = 500;

    private final long pickupMs;
    private final Object lock = new Object();
    private Entry current;
    private volatile long lastTick;

    private static final class Entry {
        Task task;
        boolean started;
        boolean withdrawn;
        final CompletableFuture<Object> done = new CompletableFuture<>();
    }

    public MainThread(long pickupMs) {
        this.pickupMs = pickupMs;
    }

    /** When the main thread last ran the pump, in System.nanoTime() terms. */
    public long lastTick() {
        return lastTick;
    }

    public boolean busy() {
        synchronized (lock) {
            return current != null;
        }
    }

    /**
     * Run {@code task} on the main thread and return its result, or {@link #NO_REPLY} when
     * the deadline passes after it started. Throws {@link HostError} for a refusal.
     */
    public Object submit(Task task, long deadlineMs) {
        long start = System.nanoTime();
        Entry entry = new Entry();
        entry.task = task;
        long pickup = Math.max(1, Math.min(pickupMs, deadlineMs - 100));
        synchronized (lock) {
            while (current != null) {
                long waited = (System.nanoTime() - start) / 1_000_000;
                if (waited >= pickup) {
                    throw HostError.busy("Creo is running another request from creo-cli; nothing was sent.", RETRY_AFTER_MS);
                }
                try {
                    lock.wait(Math.min(20, pickup - waited));
                } catch (InterruptedException interrupted) {
                    Thread.currentThread().interrupt();
                    throw HostError.busy("The request was interrupted before it started.", RETRY_AFTER_MS);
                }
            }
            current = entry;
        }
        while (true) {
            synchronized (lock) {
                if (entry.started) {
                    break;
                }
                long waited = (System.nanoTime() - start) / 1_000_000;
                if (waited >= pickup) {
                    entry.withdrawn = true;
                    current = null;
                    lock.notifyAll();
                    throw HostError.busy("Creo's main thread did not take the request within " + pickup
                            + " ms; it is busy or a dialog is open. Nothing was sent.", RETRY_AFTER_MS);
                }
                try {
                    lock.wait(Math.min(20, pickup - waited));
                } catch (InterruptedException interrupted) {
                    Thread.currentThread().interrupt();
                    entry.withdrawn = true;
                    current = null;
                    lock.notifyAll();
                    throw HostError.busy("The request was interrupted before it started.", RETRY_AFTER_MS);
                }
            }
        }
        // Wait a little past the deadline: by then the CLI has stopped waiting and closed its end,
        // so it sees its own timeout rather than a connection this host closed first.
        long left = deadlineMs - (System.nanoTime() - start) / 1_000_000 + GRACE_MS;
        try {
            return entry.done.get(Math.max(1, left), TimeUnit.MILLISECONDS);
        } catch (TimeoutException late) {
            return NO_REPLY;
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
            return NO_REPLY;
        } catch (ExecutionException failed) {
            Throwable cause = failed.getCause();
            if (cause instanceof HostError) {
                throw (HostError) cause;
            }
            if (cause instanceof RuntimeException) {
                throw (RuntimeException) cause;
            }
            throw new IllegalStateException(cause);
        }
    }

    /** Called by the application's timer, on its main thread. Runs at most one step. */
    public void pump() {
        lastTick = System.nanoTime();
        Entry entry;
        synchronized (lock) {
            entry = current;
            if (entry == null || entry.withdrawn) {
                return;
            }
            entry.started = true;
            lock.notifyAll();
        }
        Object result;
        try {
            result = entry.task.run();
        } catch (Throwable failure) {
            finish(entry, null, failure);
            return;
        }
        if (result instanceof Later) {
            entry.task = ((Later) result).next;
            return;
        }
        finish(entry, result, null);
    }

    private void finish(Entry entry, Object result, Throwable failure) {
        synchronized (lock) {
            if (current == entry) {
                current = null;
                lock.notifyAll();
            }
        }
        if (failure != null) {
            entry.done.completeExceptionally(failure);
        } else {
            entry.done.complete(result);
        }
    }
}
