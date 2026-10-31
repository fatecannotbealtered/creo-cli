package com.fateforge.creocli.service;

import com.ptc.pfc.pfcModel.Model;
import com.ptc.pfc.pfcSession.Session;
import com.ptc.pfc.pfcSolid.Solid;
import com.ptc.pfc.pfcWindow.Window;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;
import java.util.function.LongSupplier;
import java.util.function.Supplier;

/** Close one typed model across real return-to-Creo boundaries; never create a window. */
final class ModelCloseLifecycle {
    private ModelCloseLifecycle() { }
    private static final AtomicReference<Controller> INSTANCE=new AtomicReference<>();
    private static final ThreadLocal<Runnable> GUARD=new ThreadLocal<>();
    private static final ThreadLocal<Ticket> ACTIVE_TICKET=new ThreadLocal<>();
    interface Read<T> { T run() throws Throwable; }
    static void boundary() {
        Runnable guard=GUARD.get();if(guard!=null)guard.run();
        NativeReadTrace.check();
    }
    static <T> T call(String label,Read<T> read) throws Throwable {
        boundary();
        try {return NativeReadTrace.call(label,()-> {
            Ticket ticket=ACTIVE_TICKET.get();
            boundary();
            if(ticket!=null && ticket.journal!=null)ticket.journal.event("call_begin",label,null);
            // A durable flush can consume the deadline or race HTTP cancellation.
            // Claim SDK entry only after the flush and the final ticket guard.
            if(ticket!=null)synchronized(ticket){boundary();ticket.sdkEntered.set(true);}
            else boundary();
            try{T value=read.run();
                if(ticket!=null && ticket.journal!=null)ticket.journal.event("call_end",label,null);
                return value;
            }catch(Throwable failure){
                if(ticket!=null && ticket.journal!=null)ticket.journal.event("call_throw",label,failure.getClass().getName());
                if(failure instanceof Exception)throw (Exception)failure;throw new RuntimeException(failure);
            }
        });}finally{boundary();}
    }
    static final class Scope implements AutoCloseable {
        final Runnable old;
        final Ticket previous;
        Scope(Ticket ticket,Runnable guard){old=GUARD.get();previous=ACTIVE_TICKET.get();GUARD.set(guard);ACTIVE_TICKET.set(ticket);}
        public void close(){if(old==null)GUARD.remove();else GUARD.set(old);
            if(previous==null)ACTIVE_TICKET.remove();else ACTIVE_TICKET.set(previous);}
    }
    interface Adapter {
        Object resolve(String name) throws Throwable;
        Map<String,Object> snapshot() throws Throwable;
        boolean modified(Object model) throws Throwable;
        void closeWindow(Object model,String target,String other) throws Throwable;
        void erase(Object model) throws Throwable;
        default void queueCurrentClose(Ticket ticket,Object model,String target,String empty) throws Throwable {
            throw new Failures.Refusal("E_UNSUPPORTED","fixed native current-close command unavailable");
        }
        /** Plain-file observation only: false must not enter any SDK getter. */
        default boolean currentCloseReturned(Ticket ticket) throws Throwable {return false;}
        /** Pure Java/OS cancellation only. */
        default void cancelCurrentClose(Ticket ticket) throws Throwable { }
    }
    static final class Ticket {
        static final int QUEUED=0,STAGING=1,WAIT_CLOSE=2,WAIT_ERASE=3,TERMINAL=4,CANCELLED=5,WAIT_CURRENT_CLOSE=6;
        final CompletableFuture<Map<String,Object>> answer=new CompletableFuture<>();
        final AtomicInteger phase=new AtomicInteger(QUEUED);
        final AtomicBoolean mutationStarted=new AtomicBoolean();
        final AtomicBoolean sdkEntered=new AtomicBoolean();
        final Map<String,Object> identity;
        final String generation;
        final long deadline;
        final String closeId=java.util.UUID.randomUUID().toString().replace("-","");
        volatile ModelCurrentClose.Journal journal;
        volatile ModelCurrentClose.Binding nativeClose;
        String requestSha256;
        long closeTick=-1,eraseTick=-1;
        Ticket(Map<String,Object> identity,String generation,long deadline){
            this.identity=new LinkedHashMap<>(identity);this.generation=generation;this.deadline=deadline;
        }
        boolean terminal(){return phase.get()==TERMINAL || phase.get()==CANCELLED;}
        boolean started(){return mutationStarted.get();}
    }
    static final class Entry {
        final Ticket ticket;final Object model;final String name,targetWindow,selectedOther;
        final Map<String,Object> before;
        Entry(Ticket ticket,Object model,String name,String targetWindow,String other,Map<String,Object> before){
            this.ticket=ticket;this.model=model;this.name=name;this.targetWindow=targetWindow;
            this.selectedOther=other;this.before=before;
        }
    }
    static final class Controller {
        final Adapter adapter;final Supplier<String> generation;final LongSupplier clock;
        final AtomicReference<Entry> pending=new AtomicReference<>();
        final AtomicReference<Map<String,Object>> stopped=new AtomicReference<>();
        final boolean durableJournal;
        volatile boolean initialized=true;
        Controller(Adapter adapter,Supplier<String> generation,LongSupplier clock){
            this(adapter,generation,clock,false);
        }
        Controller(Adapter adapter,Supplier<String> generation,LongSupplier clock,boolean durableJournal){
            this.adapter=adapter;this.generation=generation;this.clock=clock;this.durableJournal=durableJournal;
        }
        Ticket ticket(Map<String,Object> identity,long wait){
            long duration=Math.max(1,Math.min(wait,900_000L))*1_000_000L;
            return new Ticket(identity,generation.get(),clock.getAsLong()+duration);
        }
        boolean live(Ticket ticket){return initialized && !ticket.terminal() && stopped.get()==null
                && Objects.equals(ticket.generation,generation.get()) && clock.getAsLong()-ticket.deadline<0;}
        void healthy(){if(stopped.get()!=null)throw new Failures.Refusal("E_UNAVAILABLE",
                "model close stopped this generation; preserve original scene and operation");}
        Runnable guard(Ticket ticket){return ()->{
            if(!live(ticket)){
                if(!ticket.terminal())expire(ticket,"model_close_native_boundary_expired");
                throw new Failures.Refusal("E_UNAVAILABLE","model-close ticket expired or changed generation");
            }
        };}
        void stage(Ticket ticket,Map<String,Object> request,long tick){
            if(!ticket.phase.compareAndSet(Ticket.QUEUED,Ticket.STAGING))return;
            try(Scope scope=new Scope(ticket,guard(ticket));NativeReadTrace.Scope trace=NativeReadTrace.begin(ticket.identity)){
                boundary();healthy();
                ticket.requestSha256=ModelCurrentClose.sha256(Json.write(request));
                if(durableJournal)ticket.journal=ModelCurrentClose.Journal.open(ticket,request);
                if(pending.get()!=null)throw new Failures.Refusal("E_BUSY","another model close owns the toolkit queue");
                if(ContextActivation.blocksQueue() || OwnedSessionExit.blocksQueue())
                    throw new Failures.Refusal("E_BUSY","another lifecycle owns the toolkit queue");
                String name=Json.string(request,"model");
                Map<String,Object> expected=canonical(Json.object(request.get("expected_session"),"expected_session"));
                Map<String,Object> before=canonical(adapter.snapshot());
                if(!equivalent(expected,before))throw new Failures.Refusal("E_CONFLICT","model/window baseline changed before close dispatch");
                Object target=adapter.resolve(name);
                if(adapter.modified(target))throw new Failures.Refusal("E_CONFLICT","model has unsaved changes; close refused");
                List<Map<String,Object>> windows=rows(before,"windows");
                String targetWindow=null,other=null;
                for(Map<String,Object> row:windows){
                    if(name.equals(row.get("model"))) {
                        if(targetWindow!=null)throw new Failures.Refusal("E_VERIFY_INCOMPLETE","multiple target windows are not admitted");
                        targetWindow=(String)row.get("id");
                    } else if(other==null)other=(String)row.get("id");
                }
                if(targetWindow!=null && targetWindow.equals(before.get("active_window"))
                        && !name.equals(before.get("active_model")))
                    throw new Failures.Refusal("E_VERIFY_INCOMPLETE","activate the target's complete context before closing its current window");
                if(targetWindow==null || !targetWindow.equals(before.get("active_window")))other=null;
                boolean fixedCurrentClose=targetWindow!=null && lastCurrentPartWithEmptyBase(before,name,targetWindow,other);
                Entry entry=new Entry(ticket,target,name,targetWindow,fixedCurrentClose?null:other,before);
                if(!pending.compareAndSet(null,entry))throw new Failures.Refusal("E_BUSY","another model close is pending");
                boundary();ticket.mutationStarted.set(true);
                if(targetWindow!=null){
                    if(fixedCurrentClose){
                        ticket.closeTick=tick;ticket.phase.set(Ticket.WAIT_CURRENT_CLOSE);
                        adapter.queueCurrentClose(ticket,target,targetWindow,other);
                        if(ticket.journal!=null)ticket.journal.event("transport_return_ready","fixed_current_close_queued",null);
                        // Queue acknowledgement only. Service.drain now returns to Creo.
                    }else{
                        adapter.closeWindow(target,targetWindow,other);
                        boundary();ticket.closeTick=tick;ticket.phase.set(Ticket.WAIT_CLOSE);
                    }
                } else {
                    adapter.erase(target);
                    boundary();ticket.eraseTick=tick;ticket.phase.set(Ticket.WAIT_ERASE);
                }
            }catch(Throwable failure){fail(ticket,failure,"model_close_stage",null);}
        }
        boolean pump(long tick){
            if(stopped.get()!=null)return true;
            Entry entry=pending.get();if(entry==null)return false;
            Ticket ticket=entry.ticket;
            if(!live(ticket)){expire(ticket,"model_close_return_wait_expired");return true;}
            Map<String,Object> after=null;
            try(Scope scope=new Scope(ticket,guard(ticket));NativeReadTrace.Scope trace=NativeReadTrace.begin(ticket.identity)){
                if(ticket.phase.get()==Ticket.WAIT_CURRENT_CLOSE && tick>ticket.closeTick){
                    if(!adapter.currentCloseReturned(ticket))return true;
                    boundary();ticket.phase.set(Ticket.WAIT_CLOSE);
                    if(ticket.journal!=null)ticket.journal.event("normal_callback_return_observed","later_timer_tick",null);
                }
                if(ticket.phase.get()==Ticket.WAIT_CLOSE && tick>ticket.closeTick){
                    after=canonical(adapter.snapshot());
                    requireOtherModels(entry.before,after,entry.name);
                    requireWindows(entry.before,after,entry.name);
                    if(!hasModel(after,entry.name))throw new Failures.Refusal("E_VERIFY_INCOMPLETE","target disappeared before this close erased it");
                    if(!equivalent(modelRow(entry.before,entry.name),modelRow(after,entry.name)))
                        throw new Failures.Refusal("E_CONFLICT","target identity or metadata changed before erase");
                    if(adapter.modified(entry.model))throw new Failures.Refusal("E_CONFLICT","target became dirty while waiting for its window to close");
                    boundary();adapter.erase(entry.model);
                    boundary();ticket.eraseTick=tick;ticket.phase.set(Ticket.WAIT_ERASE);
                    if(ticket.journal!=null)ticket.journal.event("timer_return_ready","target_erase_returned",null);
                }else if(ticket.phase.get()==Ticket.WAIT_ERASE && tick>ticket.eraseTick){
                    after=canonical(adapter.snapshot());
                    requireOtherModels(entry.before,after,entry.name);
                    requireWindows(entry.before,after,entry.name);
                    if(hasModel(after,entry.name))throw new Failures.Refusal("E_VERIFY_INCOMPLETE","target is still in session after erase");
                    boundary();
                    if(ticket.journal!=null){ticket.journal.event("lifecycle_terminal","verified",null);ticket.journal.close();}
                    if(ticket.phase.compareAndSet(Ticket.WAIT_ERASE,Ticket.TERMINAL)){
                        ticket.answer.complete(Json.map("model",entry.name,"window_closed",entry.targetWindow!=null,
                                "erased",true,"window_close_error",null,"discarded_changes",false,
                                "lifecycle_before",entry.before,"lifecycle_after",after,
                                "target_window_before",entry.targetWindow,"selected_existing_window",entry.selectedOther,
                                "close_ticket_id",ticket.closeId,"current_close_dispatch",ticket.nativeClose==null?null:ModelCurrentClose.CONTRACT,
                                "window_close_tick",ticket.closeTick,"erase_tick",ticket.eraseTick,
                                "verification_tick",tick,"returned_to_creo_before_erase",entry.targetWindow==null || ticket.eraseTick>ticket.closeTick));
                    }
                    pending.compareAndSet(entry,null);
                }
            }catch(Throwable failure){fail(ticket,failure,"model_close_after_return",after);}
            return true;
        }
        void fail(Ticket ticket,Throwable failure,String stage,Map<String,Object> after){
            synchronized(ticket){
            if(ticket.terminal()){
                pending.updateAndGet(value->value!=null && value.ticket==ticket?null:value);
                return;
            }
            ModelCurrentClose.PrequeueRefusal refusal=failure instanceof ModelCurrentClose.PrequeueRefusal
                    ? (ModelCurrentClose.PrequeueRefusal)failure : null;
            if(refusal!=null && refusal.binding!=null && refusal.binding==ticket.nativeClose
                    && ticket.phase.get()==Ticket.WAIT_CURRENT_CLOSE && "model_close_stage".equals(stage))
                ticket.mutationStarted.set(false);
            else refusal=null;
            Map<String,Object> error=Json.map("code",failure instanceof Failures.Refusal
                    ? ((Failures.Refusal)failure).code : refusal!=null?"E_VERIFY_INCOMPLETE":"E_CREO","message",
                    failure instanceof Failures.Refusal || refusal!=null ? failure.getMessage() : failure.getClass().getName(),
                    "stage",stage,"started",ticket.started(),"sdk_read_entered",ticket.sdkEntered.get(),"retryable",false);
            if(refusal!=null)error.put("native_dispatch",Json.map("dispatch_contract",ModelCurrentClose.CONTRACT,
                    "state","refused_before_queue","queue_api_entered",false,"queue_acknowledged",false,
                    "native_function_return",refusal.status,"reason",refusal.reason,"mutation_started",false));
            Entry entry=pending.get();
            if(entry!=null && entry.ticket==ticket){
                error.put("close_observation",Json.map("before",entry.before,"after",after,
                        "target_window_before",entry.targetWindow,"selected_existing_window",entry.selectedOther));
            }
            if(ticket.started())stopped.compareAndSet(null,error);
            cancelNative(ticket);finishJournal(ticket,"failed");
            ticket.phase.set(Ticket.TERMINAL);
            ticket.answer.completeExceptionally(new Service.ToolkitFailure(error));
            pending.updateAndGet(value->value!=null && value.ticket==ticket?null:value);
            }
        }
        Map<String,Object> expire(Ticket ticket,String boundary){
            synchronized(ticket){
            for(;;){int old=ticket.phase.get();if(ticket.terminal())return stopped.get();
                if(!ticket.phase.compareAndSet(old,Ticket.CANCELLED))continue;
                boolean nativeEntered=ticket.started() || ticket.sdkEntered.get();
                Map<String,Object> error=Json.map("code","E_BUSY","message",
                        nativeEntered?"model close SDK work entered but did not complete before deadline; do not retry":"model close withdrawn before SDK entry",
                        "stage",boundary,"started",ticket.started(),"sdk_read_entered",ticket.sdkEntered.get(),"retryable",false);
                if(nativeEntered) {stopped.compareAndSet(null,error);NativeReadTrace.requestUnreturned(ticket.identity,error);}
                cancelNative(ticket);finishJournal(ticket,"cancelled");
                pending.updateAndGet(value->value!=null && value.ticket==ticket?null:value);
                ticket.answer.completeExceptionally(new Service.ToolkitFailure(error));return error;}
            }
        }
        void stop(){Entry entry=pending.get();if(entry!=null)expire(entry.ticket,"service_stop");initialized=false;}
        void cancelNative(Ticket ticket){
            try{adapter.cancelCurrentClose(ticket);}catch(Throwable failure){
                // No SDK fallback. The C command also has its own bounded monotonic deadline.
                stopped.compareAndSet(null,Json.map("code","E_UNAVAILABLE","stage","model_close_cancel_record_failed",
                        "started",ticket.started(),"retryable",false,"cause_type",failure.getClass().getName()));
            }
        }
        void finishJournal(Ticket ticket,String result){
            if(ticket.journal==null)return;
            try{ticket.journal.event("lifecycle_terminal",result,null);ticket.journal.close();}
            catch(Throwable failure){stopped.compareAndSet(null,Json.map("code","E_UNAVAILABLE","stage","model_close_journal_failed",
                    "started",ticket.started(),"retryable",false,"cause_type",failure.getClass().getName()));}
        }
    }
    @SuppressWarnings("unchecked")
    static List<Map<String,Object>> rows(Map<String,Object> data,String key){
        Object raw=data.get(key);if(!(raw instanceof List))throw new Failures.Refusal("E_VERIFY_INCOMPLETE","complete "+key+" required");
        List<Map<String,Object>> result=new ArrayList<>();for(Object row:(List<?>)raw)result.add(Json.object(row,key+" row"));return result;
    }
    static Map<String,Object> canonical(Map<String,Object> data){
        if(!Boolean.TRUE.equals(data.get("completed")))throw new Failures.Refusal("E_VERIFY_INCOMPLETE","complete management observation required");
        Map<String,Object> result=new LinkedHashMap<>(data);
        List<Map<String,Object>> models=rows(data,"models"),windows=rows(data,"windows");
        models.sort(Comparator.comparing(row->String.valueOf(row.get("model"))));
        windows.sort(Comparator.comparing(row->String.valueOf(row.get("id"))));
        result.put("models",models);result.put("windows",windows);return result;
    }
    static boolean equivalent(Object a,Object b){
        if(a instanceof Number && b instanceof Number)return ((Number)a).doubleValue()==((Number)b).doubleValue();
        if(a instanceof Map && b instanceof Map){Map<?,?> x=(Map<?,?>)a,y=(Map<?,?>)b;if(!x.keySet().equals(y.keySet()))return false;
            for(Object key:x.keySet())if(!equivalent(x.get(key),y.get(key)))return false;return true;}
        if(a instanceof List && b instanceof List){List<?> x=(List<?>)a,y=(List<?>)b;if(x.size()!=y.size())return false;
            for(int i=0;i<x.size();i++)if(!equivalent(x.get(i),y.get(i)))return false;return true;}
        return Objects.equals(a,b);
    }
    static boolean hasModel(Map<String,Object> data,String name){return rows(data,"models").stream().anyMatch(row->name.equals(row.get("model")));}
    static Map<String,Object> modelRow(Map<String,Object> data,String name){
        return rows(data,"models").stream().filter(row->name.equals(row.get("model"))).findFirst()
                .orElseThrow(()->new Failures.Refusal("E_VERIFY_INCOMPLETE","target model metadata absent"));
    }
    static boolean lastCurrentPartWithEmptyBase(Map<String,Object> before,String name,String target,String empty){
        List<Map<String,Object>> models=rows(before,"models"),windows=rows(before,"windows");
        return models.size()==1 && windows.size()==2 && empty!=null
                && name.equals(models.get(0).get("model")) && "part".equals(models.get(0).get("type"))
                && name.equals(before.get("active_model")) && target.equals(before.get("active_window"))
                && windows.stream().anyMatch(row->empty.equals(row.get("id"))&&row.get("model")==null);
    }
    static void requireOtherModels(Map<String,Object> old,Map<String,Object> now,String name){
        List<Map<String,Object>> expected=new ArrayList<>();for(Map<String,Object> row:rows(old,"models"))if(!name.equals(row.get("model")))expected.add(row);
        List<Map<String,Object>> actual=new ArrayList<>();for(Map<String,Object> row:rows(now,"models"))if(!name.equals(row.get("model")))actual.add(row);
        if(!equivalent(expected,actual))throw new Failures.Refusal("E_VERIFY_INCOMPLETE","non-target model metadata changed during close");
    }
    static void requireWindows(Map<String,Object> old,Map<String,Object> now,String name){
        List<Object> expected=new ArrayList<>(),actual=new ArrayList<>();java.util.Set<Object> affected=new java.util.HashSet<>();
        for(Map<String,Object> row:rows(old,"windows")){if(name.equals(row.get("model")))affected.add(row.get("id"));else expected.add(row);}
        for(Map<String,Object> row:rows(now,"windows")){
            if(affected.contains(row.get("id"))){if(row.get("model")!=null)throw new Failures.Refusal("E_VERIFY_INCOMPLETE","target window did not close or clear after return to Creo");}
            else actual.add(row);
        }
        if(!equivalent(expected,actual))throw new Failures.Refusal("E_VERIFY_INCOMPLETE","other window identities changed during close");
        if(!name.equals(old.get("active_model")) && !Objects.equals(old.get("active_window"),now.get("active_window")))
            throw new Failures.Refusal("E_VERIFY_INCOMPLETE","non-target active window changed during close");
    }
    private static final class NativeAdapter implements Adapter {
        Session session() throws Throwable{return call("close.GetProESession",Creo::session);}
        String name(Model m)throws Throwable{return Creo.plainName(call("close.Model.GetFileName",m::GetFileName));}
        public Object resolve(String name)throws Throwable{
            Session s=session();Model m=call("close.GetModelFromFileName",()->s.GetModelFromFileName(name));
            if(m==null)throw new Failures.Refusal("E_NOT_FOUND","close target absent");return m;
        }
        public boolean modified(Object m)throws Throwable{return call("close.GetIsModified",((Model)m)::GetIsModified);}
        public void erase(Object m)throws Throwable{call("close.Model.Erase",()->{((Model)m).Erase();return null;});}
        public void queueCurrentClose(Ticket ticket,Object model,String target,String empty)throws Throwable{
            ModelCurrentClose.queue(ticket,name((Model)model),target,empty);
        }
        public boolean currentCloseReturned(Ticket ticket)throws Throwable{return ModelCurrentClose.returned(ticket);}
        public void cancelCurrentClose(Ticket ticket)throws Throwable{ModelCurrentClose.cancel(ticket);}
        public void closeWindow(Object m,String target,String other)throws Throwable{
            Session s=session();Window w=call("close.GetModelWindow",()->s.GetModelWindow((Model)m));
            if(w==null || !target.equals(String.valueOf(call("close.Window.GetId",w::GetId))))
                throw new Failures.Refusal("E_CONFLICT","target window identity changed before close");
            Window current=call("close.GetCurrentWindow",s::GetCurrentWindow);
            if(current!=null && target.equals(String.valueOf(call("close.CurrentWindow.GetId",current::GetId))) && other!=null){
                Window selected=call("close.GetExistingOtherWindow",()->s.GetWindow(Integer.parseInt(other)));
                if(selected==null || !other.equals(String.valueOf(call("close.OtherWindow.GetId",selected::GetId))))
                    throw new Failures.Refusal("E_CONFLICT","selected existing window changed");
                call("close.SetCurrentWindow(existing other)",()->{s.SetCurrentWindow(selected);return null;});
            }
            call("close.Window.Close",()->{w.Close();return null;});
        }
        Map<String,Object> family(Solid solid)throws Throwable{
            try{
                com.ptc.pfc.pfcModel.ModelDescriptor descriptor;
                try{descriptor=call("close.GetImmediateGenericInfo",solid::GetImmediateGenericInfo);}
                catch(com.ptc.pfc.pfcExceptions.XToolkitNotFound empty){descriptor=null;}
                if(descriptor!=null)throw new Failures.Refusal("E_UNSUPPORTED","close lifecycle supports independently proved standalone models only");
                com.ptc.pfc.pfcFamily.FamilyTableRows rows=call("close.Family.ListRows",solid::ListRows);
                int count=rows==null?0:call("close.Family.RowCount",rows::getarraysize);
                com.ptc.pfc.pfcFamily.FamilyTableColumns cols=call("close.Family.ListColumns",solid::ListColumns);
                int columns=cols==null?0:call("close.Family.ColumnCount",cols::getarraysize);
                if(count!=0 || columns!=0)throw new Failures.Refusal("E_UNSUPPORTED","close lifecycle does not expand family-table support");
                return Json.map("complete",true,"kind","standalone","generic",null,"instances",List.of(),"row_count",0,"column_count",0,
                        "source","FamilyMember.GetImmediateGenericInfo/ListRows/ListColumns",
                        "empty_semantics","optional null/empty rows and columns; only documented GetImmediateGenericInfo XToolkitNotFound means no generic");
            }catch(Failures.Refusal failure){throw failure;}
        }
        public Map<String,Object> snapshot()throws Throwable{
            Session s=session();List<Object> modelRows=new ArrayList<>(),windowRows=new ArrayList<>();
            com.ptc.pfc.pfcModel.Models all=call("close.ListModels",s::ListModels);
            int count=all==null?0:call("close.ModelCount",all::getarraysize);
            if(count>16)throw new Failures.Refusal("E_UNSUPPORTED","model close supports at most16 models");
            for(int i=0;i<count;i++){
                final int at=i;Model m=call("close.Models.get",()->all.get(at));
                com.ptc.pfc.pfcModel.ModelType type=call("close.Model.GetType",m::GetType);
                if(type.getValue()==com.ptc.pfc.pfcModel.ModelType._MDL_2D_SECTION)continue;
                String filename=name(m),origin=call("close.Model.GetOrigin",m::GetOrigin);
                if(origin!=null && origin.trim().isEmpty())origin=null;
                Map<String,Object> originInfo=Json.map("complete",true,"state",origin==null?"no_origin":"saved","value",origin,"source","Model.GetOrigin","new_model_proven",false);
                List<Object> deps=new ArrayList<>();com.ptc.pfc.pfcModel.Dependencies found;
                try{found=call("close.ListDependencies",m::ListDependencies);}
                catch(com.ptc.pfc.pfcExceptions.XToolkitNotFound empty){found=null;}
                final com.ptc.pfc.pfcModel.Dependencies dependencyList=found;
                int n=dependencyList==null?0:call("close.DependencyCount",dependencyList::getarraysize);
                for(int j=0;j<n;j++){
                    final int index=j;com.ptc.pfc.pfcModel.Dependency dep=call("close.Dependencies.get",()->dependencyList.get(index));
                    com.ptc.pfc.pfcModel.ModelDescriptor d=call("close.Dependency.GetDepModel",dep::GetDepModel);
                    if(d==null)throw new Failures.Refusal("E_VERIFY_INCOMPLETE","dependency descriptor absent");
                    String file=call("close.Dependency.GetFileName",d::GetFileName);
                    if(file==null)throw new Failures.Refusal("E_VERIFY_INCOMPLETE","dependency filename absent");
                    deps.add(file.toLowerCase(java.util.Locale.ROOT));
                }
                modelRows.add(Json.map("model",filename,"type",Creo.typeName(type),"origin",origin,"origin_readback",originInfo,
                        "family",m instanceof Solid?family((Solid)m):null,
                        "modified",call("close.Model.GetIsModified",m::GetIsModified),
                        "version_stamp",call("close.Model.GetVersionStamp",m::GetVersionStamp),
                        "relation_id",call("close.Model.GetRelationId",m::GetRelationId),
                        "dependencies",deps,"dependencies_complete",true));
            }
            com.ptc.pfc.pfcWindow.Windows windows=call("close.ListWindows",s::ListWindows);
            int n=windows==null?0:call("close.WindowCount",windows::getarraysize);
            if(n>32)throw new Failures.Refusal("E_UNSUPPORTED","model close supports at most32 windows");
            for(int i=0;i<n;i++){
                final int index=i;Window w=call("close.Windows.get",()->windows.get(index));Model m;
                try{m=call("close.Window.GetModel",w::GetModel);}catch(com.ptc.pfc.pfcExceptions.XToolkitNotFound empty){m=null;}
                windowRows.add(Json.map("id",String.valueOf(call("close.Window.GetId",w::GetId)),"model",m==null?null:name(m)));
            }
            Window current;Model active;
            try{current=call("close.GetCurrentWindow",s::GetCurrentWindow);}catch(com.ptc.pfc.pfcExceptions.XToolkitNotFound empty){current=null;}
            try{active=call("close.GetCurrentModel",s::GetCurrentModel);}catch(com.ptc.pfc.pfcExceptions.XToolkitNotFound empty){active=null;}
            return canonical(Json.map("completed",true,"models",modelRows,"windows",windowRows,
                    "active_window",current==null?null:String.valueOf(call("close.CurrentWindow.GetId",current::GetId)),
                    "active_model",active==null?null:name(active),
                    "source","ListModels/ListWindows; native origin/version/modified/dependency getters",
                    "not_checked",List.of("camera and display settings","cross-instance object identity")));
        }
    }
    static void initialize(){INSTANCE.compareAndSet(null,new Controller(new NativeAdapter(),Service::instanceIdForReadback,System::nanoTime,true));}
    static boolean ready(){Controller c=INSTANCE.get();return c!=null && c.initialized && c.stopped.get()==null;}
    static Ticket ticket(Map<String,Object> identity,long wait){Controller c=INSTANCE.get();if(c==null)throw new Failures.Refusal("E_UNSUPPORTED","close lifecycle unavailable");return c.ticket(identity,wait);}
    static void stage(Ticket ticket,Map<String,Object> request,long tick){INSTANCE.get().stage(ticket,request,tick);}
    static boolean pump(long tick){Controller c=INSTANCE.get();return c!=null && c.pump(tick);}
    static boolean blocksQueue(){Controller c=INSTANCE.get();return c!=null && (c.pending.get()!=null || c.stopped.get()!=null);}
    static void healthy(){Controller c=INSTANCE.get();if(c!=null)c.healthy();}
    static Map<String,Object> status(){Controller c=INSTANCE.get();return Json.map("initialized",c!=null && c.initialized,"pending",c!=null && c.pending.get()!=null,"stopped",c==null?null:c.stopped.get());}
    static Map<String,Object> expire(Ticket ticket,String boundary){return INSTANCE.get().expire(ticket,boundary);}
    static void stop(){Controller c=INSTANCE.get();if(c!=null)c.stop();}
}
