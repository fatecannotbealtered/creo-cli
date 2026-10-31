package com.fateforge.creocli.service;

import com.ptc.pfc.pfcCommand.DefaultUICommandActionListener;
import com.ptc.pfc.pfcModel.Model;
import com.ptc.pfc.pfcSession.Session;
import com.ptc.pfc.pfcWindow.Window;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Objects;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;
import java.util.function.LongSupplier;
import java.util.function.Supplier;

/** One typed, bounded activation across a real return-to-Creo command boundary.
 * SDK objects stay in the toolkit-side Entry; HTTP only waits on a plain-data Ticket.
 * No caller-controlled text is ever passed to RunMacro.
 */
final class ContextActivation {
    static final String DISPATCH = "UICreateMaxPriorityCommand/RunMacro fixed registered command";
    static final String COMMAND = "creo_cli_context_activate";
    static final String MACRO = "~ Command `" + COMMAND + "`;";
    private static final AtomicReference<Controller> INSTANCE = new AtomicReference<>();
    private static final ThreadLocal<Runnable> BOUNDARY_GUARD=new ThreadLocal<>();
    private ContextActivation() { }

    static final class GuardScope implements AutoCloseable {
        final Runnable previous;
        GuardScope(Runnable guard) { previous=BOUNDARY_GUARD.get();BOUNDARY_GUARD.set(guard); }
        @Override public void close() {
            if(previous==null)BOUNDARY_GUARD.remove();else BOUNDARY_GUARD.set(previous);
        }
    }
    static void beforeNativeCall() {
        Runnable guard=BOUNDARY_GUARD.get();
        if(guard!=null)guard.run();
        NativeReadTrace.check();
    }

    /** Adapter boundary also permits controlled SDK-free state-machine tests. */
    interface Adapter {
        void register(Runnable callback) throws Throwable;
        Object resolve(String name) throws Throwable;
        Map<String, Object> identity(Object target) throws Throwable;
        boolean active(Object target) throws Throwable;
        void dispatch() throws Throwable;
        void activate(Object target, Runnable guard) throws Throwable;
        Map<String, Object> observe(Object target) throws Throwable;
    }

    static final class Ticket {
        static final int QUEUED=0, STAGING=1, DISPATCHED=2, CALLBACK=3, RETURNED=4,
                TERMINAL=5, CANCELLED=6;
        final CompletableFuture<Map<String, Object>> answer = new CompletableFuture<>();
        final AtomicInteger phase = new AtomicInteger(QUEUED);
        final String generation;
        final Map<String, Object> identity;
        final long deadline;
        volatile long scheduledTick=-1, callbackTick=-1;
        Ticket(String generation, Map<String, Object> identity, long deadline) {
            this.generation=generation;
            this.identity=new LinkedHashMap<>(identity);
            this.deadline=deadline;
        }
        boolean started() { return phase.get()!=QUEUED && phase.get()!=CANCELLED; }
        boolean expired(long now) { return now-deadline>=0; }
        boolean begin(long now) {
            if (expired(now)) return false;
            return phase.compareAndSet(QUEUED, STAGING);
        }
        boolean terminal() { int value=phase.get(); return value==TERMINAL || value==CANCELLED; }
        void success(Map<String, Object> result) {
            for (;;) {
                int old=phase.get();
                if (old==TERMINAL || old==CANCELLED) return;
                if (phase.compareAndSet(old, TERMINAL)) { answer.complete(result); return; }
            }
        }
        void failure(Map<String, Object> error) {
            for (;;) {
                int old=phase.get();
                if (old==TERMINAL || old==CANCELLED) return;
                if (phase.compareAndSet(old, TERMINAL)) {
                    answer.completeExceptionally(new Service.ToolkitFailure(error)); return;
                }
            }
        }
    }

    private static final class Entry {
        final Ticket ticket;
        final Object target;
        final Map<String, Object> expected;
        Entry(Ticket ticket,Object target,Map<String, Object> expected) {
            this.ticket=ticket; this.target=target; this.expected=new LinkedHashMap<>(expected);
        }
    }

    /** No SDK interaction in cancellation, stop evidence or capability queries. */
    static final class Controller {
        final Adapter adapter;
        final Supplier<String> generation;
        final LongSupplier clock;
        final AtomicReference<Entry> pending=new AtomicReference<>();
        final AtomicReference<Map<String,Object>> stopped=new AtomicReference<>();
        volatile boolean initialized;
        volatile String initializationError;
        volatile long tick;
        Controller(Adapter adapter,Supplier<String> generation,LongSupplier clock) {
            this.adapter=adapter; this.generation=generation; this.clock=clock;
        }
        void initialize() {
            try { adapter.register(this::callback); initialized=true; }
            catch (Throwable failure) { initializationError=failure.getClass().getName(); initialized=false; }
        }
        Ticket ticket(Map<String,Object> identity,long waitMillis) {
            long now=clock.getAsLong(), duration=Math.min(86_400_000L,Math.max(1L,waitMillis))*1_000_000L;
            long deadline=now+duration; // Subtraction-based expiry is safe across nanoTime wrap.
            return new Ticket(generation.get(),identity,deadline);
        }
        boolean ready() { return initialized && stopped.get()==null; }
        void healthy() {
            if (stopped.get()!=null)
                throw new Failures.Refusal("E_UNAVAILABLE", "model-context activation stopped this service generation; preserve its scene and original operation");
        }
        boolean live(Ticket ticket) {
            return !ticket.terminal() && stopped.get()==null && !ticket.expired(clock.getAsLong())
                    && Objects.equals(ticket.generation,generation.get());
        }
        Runnable guard(Ticket ticket,int phase) {
            return ()->{
                if(!live(ticket) || ticket.phase.get()!=phase) {
                    if(!ticket.terminal()) expire(ticket,"activation_native_boundary_expired_or_generation_changed");
                    throw new Failures.Refusal("E_UNAVAILABLE","activation expired or changed generation before the next native call");
                }
            };
        }
        void stage(Ticket ticket,Map<String,Object> request,long currentTick) {
            tick=currentTick;
            if (!ticket.begin(clock.getAsLong())) {
                ticket.failure(error("E_BUSY","activation expired before toolkit dispatch",false,"activation_queue"));
                return;
            }
            try (NativeReadTrace.Scope trace=NativeReadTrace.begin(ticket.identity);
                    GuardScope scope=new GuardScope(guard(ticket,Ticket.STAGING))) {
                NativeReadTrace.check(); healthy();
                beforeNativeCall();
                Object target=adapter.resolve(Json.string(request,"model"));
                beforeNativeCall();
                Map<String,Object> actual=adapter.identity(target);
                Map<String,Object> expected=request.containsKey("expected_target")
                        ? expected(request.get("expected_target")) : null;
                if (expected!=null) requireIdentity(expected,actual);
                beforeNativeCall();
                if (adapter.active(target)) {
                    ticket.success(Json.map("model",actual.get("model"),"setter_returned",true,
                            "already_active",true,"activation_performed",false,
                            "context_management","complete existing native context verified; no activation dispatched"));
                    return;
                }
                if (!initialized) throw new Failures.Refusal("E_UNSUPPORTED", "native maximum-priority context command is not initialized");
                if (expected==null) throw new Failures.Refusal("E_VALIDATION", "expected_target identity is required for automatic activation");
                if (!live(ticket)) throw new Failures.Refusal("E_BUSY", "activation expired before native command dispatch");
                Entry entry=new Entry(ticket,target,expected);
                if (!pending.compareAndSet(null,entry))
                    throw new Failures.Refusal("E_BUSY", "another typed activation is awaiting return to Creo");
                ticket.scheduledTick=currentTick;
                // Mark BEFORE RunMacro: if the native call does not return, its effects are unknown.
                if (!ticket.phase.compareAndSet(Ticket.STAGING,Ticket.DISPATCHED)) return;
                try(GuardScope dispatchGuard=new GuardScope(guard(ticket,Ticket.DISPATCHED))) {
                    beforeNativeCall();
                    NativeReadTrace.run("BaseSession.RunMacro(owned fixed context command)",adapter::dispatch);
                }
                // Do not observe or complete here. Service.drain ends this timer tick now.
            } catch (Throwable failure) {
                pending.updateAndGet(entry -> entry!=null && entry.ticket==ticket ? null : entry);
                failOnToolkit(ticket,failure,"activation_dispatch");
            }
        }
        void callback() {
            Entry entry=pending.get();
            if (entry==null) return;
            Ticket ticket=entry.ticket;
            // This check is pure Java. A late native command cannot execute a stale model action.
            if (!live(ticket)) { expire(ticket,"activation_callback_expired"); return; }
            if (!ticket.phase.compareAndSet(Ticket.DISPATCHED,Ticket.CALLBACK)) return;
            ticket.callbackTick=tick;
            try (NativeReadTrace.Scope trace=NativeReadTrace.begin(ticket.identity);
                    GuardScope scope=new GuardScope(guard(ticket,Ticket.CALLBACK))) {
                NativeReadTrace.check();
                beforeNativeCall();
                requireIdentity(entry.expected,adapter.identity(entry.target));
                beforeNativeCall();
                Object fresh=adapter.resolve((String)entry.expected.get("model"));
                beforeNativeCall();
                requireIdentity(entry.expected,adapter.identity(fresh));
                Runnable guard=ContextActivation::beforeNativeCall;
                guard.run();
                adapter.activate(entry.target,guard);
                // No SDK readback in this command callback. Return control to Creo first.
                if (live(ticket)) ticket.phase.compareAndSet(Ticket.CALLBACK,Ticket.RETURNED);
            } catch (Throwable failure) {
                pending.compareAndSet(entry,null);
                failOnToolkit(ticket,failure,"activation_callback");
            }
        }
        /** Called once at the start of a later timer callback. True blocks ordinary queue work. */
        boolean pump(long currentTick) {
            tick=currentTick;
            if (stopped.get()!=null) return true;
            Entry entry=pending.get();
            if (entry==null) return false;
            Ticket ticket=entry.ticket;
            if (!live(ticket)) { expire(ticket,"activation_return_wait_expired"); return true; }
            if (ticket.phase.get()!=Ticket.RETURNED || currentTick<=ticket.scheduledTick
                    || currentTick<=ticket.callbackTick) return true;
            try (NativeReadTrace.Scope trace=NativeReadTrace.begin(ticket.identity);
                    GuardScope scope=new GuardScope(guard(ticket,Ticket.RETURNED))) {
                NativeReadTrace.check();
                beforeNativeCall();
                Map<String,Object> state=adapter.observe(entry.target);
                Map<String,Object> actual=Json.object(state.get("target_identity"),"observed target identity");
                requireIdentity(entry.expected,actual);
                requireContext(entry.expected,state);
                if (!live(ticket)) { expire(ticket,"activation_verification_expired"); return true; }
                ticket.success(Json.map("model",entry.expected.get("model"),"setter_returned",true,
                        "already_active",false,"activation_performed",true,"activation_dispatch",DISPATCH,
                        "callback_returned",true,"verified_after_return_to_creo",true,
                        "scheduled_tick",ticket.scheduledTick,"callback_tick",ticket.callbackTick,
                        "verified_tick",currentTick,"expected_target",entry.expected,"observed_target",actual,
                        "native_context",state,
                        "context_management","native maximum-priority callback followed by independent later-tick context readback"));
                pending.compareAndSet(entry,null);
            } catch (Throwable failure) {
                pending.compareAndSet(entry,null);
                failOnToolkit(ticket,failure,"activation_verify_after_return");
            }
            return true; // Even successful completion yields before another SDK job can run.
        }
        boolean blocksQueue() { return pending.get()!=null || stopped.get()!=null; }
        Map<String,Object> expire(Ticket ticket,String boundary) {
            for (;;) {
                int old=ticket.phase.get();
                if (old==Ticket.TERMINAL) return null;
                if (old==Ticket.CANCELLED) return stopped.get();
                if (!ticket.phase.compareAndSet(old,Ticket.CANCELLED)) continue;
                boolean started=old!=Ticket.QUEUED;
                Map<String,Object> error=error("E_BUSY",started
                        ? "activation started but its final context was not observed before the deadline; do not retry"
                        : "activation withdrawn before toolkit dispatch",started,boundary);
                if (started) {
                    Map<String,Object> retained=new LinkedHashMap<>(error);
                    retained.put("blocking_request",new LinkedHashMap<>(ticket.identity));
                    stopped.compareAndSet(null,retained);
                    NativeReadTrace.requestUnreturned(ticket.identity,error);
                }
                ticket.answer.completeExceptionally(new Service.ToolkitFailure(error));
                return error;
            }
        }
        void stop() {
            Entry entry=pending.get();
            if (entry!=null) expire(entry.ticket,"service_stop");
            initialized=false;
        }
        void failOnToolkit(Ticket ticket,Throwable failure,String stage) {
            // A toolkit exception is a proxy. Reading its toolkit details after
            // cancellation would itself dispatch more SDK calls. Reduce to Java
            // class/plain refusal data; never invoke Failures.error here.
            if(ticket.terminal())return;
            if(!live(ticket)) {expire(ticket,"activation_failed_after_deadline_or_generation_change");return;}
            Map<String,Object> error;
            if(failure instanceof Service.ToolkitFailure)
                error=new LinkedHashMap<>(((Service.ToolkitFailure)failure).error);
            else if(failure instanceof NativeReadTrace.Fatal)
                error=NativeReadTrace.error(failure);
            else if(failure instanceof Failures.Refusal)
                error=Json.map("code",((Failures.Refusal)failure).code,"message",failure.getMessage());
            else error=Json.map("code","E_CREO","message","native context operation failed: "+failure.getClass().getName(),
                    "exception_class",failure.getClass().getName(),"native_exception_detail_getters_called",false);
            error.put("stage",stage);
            error.put("started",ticket.phase.get()>=Ticket.DISPATCHED);
            error.put("retryable",false);
            ticket.failure(error);
        }
    }

    static Map<String,Object> error(String code,String message,boolean started,String stage) {
        return Json.map("code",code,"message",message,"started",started,"retryable",false,
                "stage",stage,"activation_dispatch",DISPATCH);
    }
    static Map<String,Object> expected(Object value) {
        Map<String,Object> data=Json.object(value,"expected_target");
        if (!data.keySet().equals(java.util.Set.of("model","type","origin","version_stamp","relation_id")))
            throw new Failures.Refusal("E_VALIDATION","expected_target must contain the exact five native identity fields");
        for (String key:java.util.List.of("model","type","origin","version_stamp")) Json.string(data,key);
        Object relation=data.get("relation_id");
        if (!(relation instanceof Number) || !Double.isFinite(((Number)relation).doubleValue())
                || ((Number)relation).doubleValue()!=((Number)relation).intValue())
            throw new Failures.Refusal("E_VALIDATION","expected relation_id must be a native integer");
        String model=(String)data.get("model"),type=(String)data.get("type");
        if (!("part".equals(type) && model.endsWith(".prt")
                || "assembly".equals(type) && model.endsWith(".asm")))
            throw new Failures.Refusal("E_VALIDATION","expected model suffix and native type must agree");
        return new LinkedHashMap<>(data);
    }
    static void requireIdentity(Map<String,Object> expected,Map<String,Object> actual) {
        if (!actual.keySet().equals(expected.keySet()))
            throw new Failures.Refusal("E_VERIFY_INCOMPLETE","native target identity is incomplete");
        for (String key:expected.keySet()) {
            Object a=expected.get(key),b=actual.get(key);
            boolean same=a instanceof Number && b instanceof Number
                    ? ((Number)a).doubleValue()==((Number)b).doubleValue() : Objects.equals(a,b);
            if (!same) throw new Failures.Refusal("E_CONFLICT","native activation target identity changed: "+key);
        }
    }
    static void requireContext(Map<String,Object> expected,Map<String,Object> state) {
        Object name=expected.get("model"),type=expected.get("type");
        if (!Boolean.TRUE.equals(state.get("target_active"))
                || !Boolean.TRUE.equals(state.get("context_complete"))
                || !Objects.equals(name,state.get("current_model"))
                || !Objects.equals(name,state.get("window_model"))
                || !Objects.equals(type,state.get("current_model_type"))
                || !Objects.equals(type,state.get("window_model_type"))
                || state.get("window")==null || !Objects.equals(state.get("window"),state.get("active_window")))
            throw new Failures.Refusal("E_VERIFY_INCOMPLETE","later native current-model and target-window proof did not match");
    }

    private static final class NativeAdapter implements Adapter {
        private DefaultUICommandActionListener listener;
        private com.ptc.pfc.pfcCommand.UICommand command;
        public void register(Runnable callback) throws Throwable {
            listener=new DefaultUICommandActionListener() {
                @Override public void OnCommand() { callback.run(); }
            };
            command=NativeReadTrace.call("Session.UICreateMaxPriorityCommand(owned context command)",
                    ()->Creo.session().UICreateMaxPriorityCommand(COMMAND,listener));
        }
        public Object resolve(String name) throws Throwable {
            Session session=PresentationOps.contextRead("pfcGlobal.GetProESession(context resolve)",Creo::session);
            Model model;
            try { model=PresentationOps.contextRead("Session.GetModelFromFileName(context resolve)",()->session.GetModelFromFileName(name)); }
            catch(Throwable failure) {
                if(failure instanceof com.ptc.pfc.pfcExceptions.XToolkitNotFound)
                    throw new Failures.Refusal("E_NOT_FOUND","activation target is not loaded");
                throw failure;
            }
            if(model==null)throw new Failures.Refusal("E_NOT_FOUND","activation target is not loaded");
            return model;
        }
        public Map<String,Object> identity(Object target) throws Throwable { return PresentationOps.targetIdentity((Model)target); }
        public boolean active(Object target) throws Throwable {
            return Boolean.TRUE.equals(observe(target).get("target_active"));
        }
        public void dispatch() throws Throwable {
            Session session=PresentationOps.contextRead("pfcGlobal.GetProESession(context dispatch)",Creo::session);
            beforeNativeCall();
            session.RunMacro(MACRO);
        }
        public void activate(Object target,Runnable guard) throws Throwable {
            guard.run();
            Session session=Creo.session(); Model model=(Model)target;
            guard.run();
            Window window=NativeReadTrace.call("Session.CreateModelWindow(context activation)",()->session.CreateModelWindow(model));
            guard.run(); NativeReadTrace.run("Model.Display(context activation)",model::Display);
            guard.run(); NativeReadTrace.run("Window.Activate(maximum-priority owned command)",window::Activate);
        }
        public Map<String,Object> observe(Object target) throws Throwable {
            Model model=(Model)target;
            Session session=PresentationOps.contextRead("pfcGlobal.GetProESession(context proof)",Creo::session);
            Model current=optionalContext("Session.GetCurrentModel(context proof)",session::GetCurrentModel);
            Window window=optionalContext("Session.GetCurrentWindow(context proof)",session::GetCurrentWindow);
            Model owner=window==null ? null : optionalContext("Window.GetModel(context proof)",window::GetModel);
            Window targetWindow=optionalContext("Session.GetModelWindow(context proof)",()->session.GetModelWindow(model));
            String currentName=current==null ? null : Creo.plainName(PresentationOps.contextRead("CurrentModel.GetFileName(context proof)",current::GetFileName));
            String ownerName=owner==null ? null : Creo.plainName(PresentationOps.contextRead("WindowModel.GetFileName(context proof)",owner::GetFileName));
            String currentType=current==null ? null : Creo.typeName(PresentationOps.contextRead("CurrentModel.GetType(context proof)",current::GetType));
            String ownerType=owner==null ? null : Creo.typeName(PresentationOps.contextRead("WindowModel.GetType(context proof)",owner::GetType));
            Integer activeId=window==null ? null : PresentationOps.contextRead("Window.GetId(context proof)",window::GetId);
            Integer targetId=targetWindow==null ? null : PresentationOps.contextRead("TargetWindow.GetId(context proof)",targetWindow::GetId);
            Map<String,Object> identity=PresentationOps.targetIdentity(model);
            boolean complete=currentName!=null && currentName.equals(ownerName) && Objects.equals(currentType,ownerType);
            boolean active=complete && identity.get("model").equals(currentName)
                    && identity.get("type").equals(currentType) && activeId!=null && activeId.equals(targetId);
            return Json.map("target_identity",identity,"target_active",active,"context_complete",complete,
                    "current_model",currentName,"current_model_type",currentType,
                    "window_model",ownerName,"window_model_type",ownerType,
                    "active_window",activeId==null ? null : String.valueOf(activeId),
                    "window",targetId==null ? null : String.valueOf(targetId),
                    "source","independent Session.GetCurrentModel/GetCurrentWindow/GetModelWindow and model/type/window getters");
        }
        private <T>T optionalContext(String name,NativeReadTrace.Call<T> getter) throws Throwable {
            try { return PresentationOps.contextRead(name,getter); }
            catch(Throwable failure) {
                if(failure instanceof com.ptc.pfc.pfcExceptions.XToolkitBadContext
                        || failure instanceof com.ptc.pfc.pfcExceptions.XToolkitNotFound) return null;
                throw failure;
            }
        }
    }
    static void initialize() {
        Controller created=new Controller(new NativeAdapter(),Service::instanceIdForReadback,System::nanoTime);
        if (!INSTANCE.compareAndSet(null,created)) return;
        created.initialize();
    }
    static boolean ready() { Controller c=INSTANCE.get(); return c!=null && c.ready(); }
    static Map<String,Object> status() {
        Controller c=INSTANCE.get();
        return Json.map("initialized",c!=null && c.initialized,"available",ready(),
                "initialization_error",c==null ? "not_initialized" : c.initializationError,
                "pending",c!=null && c.pending.get()!=null,
                "stopped",c==null ? null : c.stopped.get(),"dispatch",DISPATCH);
    }
    static void healthy() { Controller c=INSTANCE.get(); if(c!=null)c.healthy(); }
    static Ticket ticket(Map<String,Object> identity,long waitMillis) {
        Controller c=INSTANCE.get();
        if(c==null) throw new Failures.Refusal("E_UNSUPPORTED","native context command not initialized");
        return c.ticket(identity,waitMillis);
    }
    static void stage(Ticket ticket,Map<String,Object> request,long tick) { INSTANCE.get().stage(ticket,request,tick); }
    static boolean pump(long tick) { Controller c=INSTANCE.get();return c!=null && c.pump(tick); }
    static boolean blocksQueue() { Controller c=INSTANCE.get();return c!=null && c.blocksQueue(); }
    static boolean hasStopped() { Controller c=INSTANCE.get();return c!=null && c.stopped.get()!=null; }
    static Map<String,Object> expire(Ticket ticket,String boundary) { return INSTANCE.get().expire(ticket,boundary); }
    static void stop() { Controller c=INSTANCE.get();if(c!=null)c.stop(); }
}
