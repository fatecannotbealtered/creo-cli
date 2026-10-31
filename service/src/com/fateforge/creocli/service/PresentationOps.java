package com.fateforge.creocli.service;

import com.ptc.pfc.pfcAssembly.Assembly;
import com.ptc.pfc.pfcBase.ScreenTransform;
import com.ptc.pfc.pfcBase.pfcBase;
import com.ptc.pfc.pfcComponentFeat.ComponentFeat;
import com.ptc.pfc.pfcExceptions.XToolkitBadContext;
import com.ptc.pfc.pfcModel.Model;
import com.ptc.pfc.pfcModel.ModelType;
import com.ptc.pfc.pfcSession.Session;
import com.ptc.pfc.pfcView.ViewOwner;
import com.ptc.pfc.pfcWindow.Window;
import com.ptc.wfc.wfcDisplay.WWindow;
import com.ptc.wfc.wfcModelItem.WModelItem;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/** Explicit model context, native fit, occurrence hide and explosion display operations. */
final class PresentationOps {
    private PresentationOps() { }

    static Map<String, Object> state(Map<String, Object> request) throws Exception {
        Session session = Creo.session();
        Model model = target(request);
        Window window = Creo.window(session, model), active = session.GetCurrentWindow();
        Model sessionCurrent = null;
        boolean currentRead = true;
        try { sessionCurrent = session.GetCurrentModel(); }
        catch (XToolkitBadContext absent) { currentRead = false; }
        Model windowModel = active == null ? null : active.GetModel();
        String currentName = sessionCurrent == null ? null : Creo.fileName(sessionCurrent);
        String windowName = windowModel == null ? null : Creo.fileName(windowModel);
        String currentType = sessionCurrent == null ? null : Creo.typeName(sessionCurrent.GetType());
        String windowType = windowModel == null ? null : Creo.typeName(windowModel.GetType());
        boolean completeContext = currentRead && currentName != null && windowName != null
                && currentName.equalsIgnoreCase(windowName) && currentType.equals(windowType);
        boolean current = completeContext && window != null && active != null
                && window.GetId() == active.GetId() && currentName.equalsIgnoreCase(Creo.fileName(model))
                && currentType.equals(Creo.typeName(model.GetType()));
        List<Object> visibility = new ArrayList<>();
        if (model instanceof Assembly) {
            com.ptc.pfc.pfcFeature.Features components = ((Assembly) model).ListFeaturesByType(Boolean.TRUE,
                    com.ptc.pfc.pfcFeature.FeatureType.FEATTYPE_COMPONENT);
            for (int i = 0; components != null && i < components.getarraysize(); i++) {
                ComponentFeat component = (ComponentFeat) components.get(i);
                visibility.add(Json.map("id", String.valueOf(component.GetId()),
                        "model", Creo.fileName(component.GetModelDescr()),
                        "hidden", ((WModelItem) component).IsHidden()));
            }
        }
        Object screen = null, transform = null, exploded = null;
        List<Object> namedViews = new ArrayList<>();
        if (current) {
            ScreenTransform value = window.GetScreenTransform();
            screen = Json.map("pan_x", value.GetPanX(), "pan_y", value.GetPanY(), "zoom", value.GetZoom());
            List<Object> rows = new ArrayList<>();
            com.ptc.pfc.pfcBase.Matrix3D matrix = ((ViewOwner) model).GetCurrentViewTransform().GetMatrix();
            for (int r = 0; r < 4; r++) {
                List<Object> row = new ArrayList<>();
                for (int c = 0; c < 4; c++) row.add(matrix.get(r, c));
                rows.add(row);
            }
            transform = rows;
            if (model instanceof Assembly) exploded = ((Assembly) model).GetIsExploded();
            com.ptc.pfc.pfcView.Views views = ((ViewOwner) model).ListViews();
            for (int i = 0; views != null && i < views.getarraysize(); i++)
                namedViews.add(views.get(i).GetName());
        }
        return Json.map("complete", true, "model", Creo.fileName(model),
                "target_identity", targetIdentity(model),
                "target_identity_source", "Model.GetFileName/GetType/GetOrigin/GetVersionStamp/GetRelationId",
                "window", window == null ? null : String.valueOf(window.GetId()),
                "active_window", active == null ? null : String.valueOf(active.GetId()),
                "active_model", windowName,
                "current_model", currentName, "current_model_type", currentType,
                "window_model", windowName, "window_model_type", windowType,
                "context_complete", completeContext,
                "context_reason", current ? "matching_session_current_model_and_window"
                        : !currentRead ? "Session.GetCurrentModel XToolkitBadContext"
                        : currentName == null || windowName == null ? "current_model_or_window_model_absent"
                        : !completeContext ? "current_model_and_window_model_disagree" : "target_is_inactive",
                "target_active", current, "screen", screen, "view_transform", transform,
                "context_readback", current ? "observed" : completeContext ? "not_checked_inactive_target" : "incomplete",
                "named_views", namedViews, "named_views_complete", current,
                "component_visibility", visibility, "is_exploded", exploded,
                "modified", model.GetIsModified(),
                "persistence", "display changes are session state; save/reopen qualification is separate",
                "source", "Session.GetCurrentModel/GetCurrentWindow/GetModelWindow; Model.GetType; Window.GetModel/GetScreenTransform; ViewOwner.GetCurrentViewTransform/ListViews; WModelItem.IsHidden; Assembly.GetIsExploded");
    }

    private static Model target(Map<String, Object> request) throws Exception {
        Model model = Creo.model(Creo.session(), Json.string(request, "model"));
        if (model.GetType().getValue() != ModelType._MDL_PART && model.GetType().getValue() != ModelType._MDL_ASSEMBLY)
            throw new Failures.Refusal("E_UNSUPPORTED", "display operations support a part or assembly only");
        return model;
    }

    /** Native identity bound to this typed model, independent of its current UI context. */
    static Map<String, Object> targetIdentity(Model model) throws Exception {
        String file=contextRead("Model.GetFileName(context identity)",model::GetFileName);
        ModelType type=contextRead("Model.GetType(context identity)",model::GetType);
        String origin=contextRead("Model.GetOrigin(context identity)",model::GetOrigin);
        // Same successful-value semantics as Creo.originInfo; failure is not caught
        // and reinterpreted as an empty origin in an activation identity.
        String value=origin==null || origin.trim().isEmpty() ? null : origin;
        return Json.map("model",Creo.plainName(file),"type",Creo.typeName(type),"origin",value,
                "version_stamp",contextRead("Model.GetVersionStamp(context identity)",model::GetVersionStamp),
                "relation_id",contextRead("Model.GetRelationId(context identity)",model::GetRelationId));
    }

    static <T> T contextRead(String name,NativeReadTrace.Call<T> call) {
        ContextActivation.beforeNativeCall();
        return NativeReadTrace.call(name,call);
    }

    static Window activateTarget(Session session, Model model) throws Exception {
        // Inline callers can only prove an existing context. Actual activation is
        // routed by Service through ContextActivation's native command callback,
        // return-to-Creo boundary and independent later-tick readback.
        try { return requireTargetContext(session, model); }
        catch (Failures.Refusal unavailable) {
            throw new Failures.Refusal("E_UNSUPPORTED", "inactive model requires the deferred native context command; inline activation is refused");
        }
    }

    static Window requireTargetContext(Session session, Model model) throws Exception {
        Model current = null;
        try { current = session.GetCurrentModel(); }
        catch (XToolkitBadContext absent) { /* complete context remains unavailable */ }
        Window window = session.GetCurrentWindow();
        Model owner = window == null ? null : window.GetModel();
        Window targetWindow = Creo.window(session, model);
        String expected = Creo.fileName(model);
        if (current == null || owner == null || targetWindow == null || window == null
                || window.GetId() != targetWindow.GetId()
                || !expected.equalsIgnoreCase(Creo.fileName(current))
                || !expected.equalsIgnoreCase(Creo.fileName(owner))
                || current.GetType().getValue() != model.GetType().getValue()
                || owner.GetType().getValue() != model.GetType().getValue())
            throw new Failures.Refusal("E_VERIFY_INCOMPLETE", "matching Session.GetCurrentModel and target window required; automatic activation is unqualified in this synchronous service");
        return window;
    }

    static Map<String, Object> activate(Map<String, Object> request) throws Exception {
        Model model = target(request);
        String name = Creo.fileName(model);
        try { activateTarget(Creo.session(), model); }
        catch (Throwable problem) { throw new Failures.Stage("display_activate", problem, Json.map("model", Creo.fileName(model))); }
        return Json.map("model", name, "setter_returned", true,
                "already_active", true, "activation_performed", false,
                "context_management", "complete existing native context verified; no activation fallback");
    }

    static Map<String, Object> fit(Map<String, Object> request) throws Exception {
        double margin = request.containsKey("margin") ? Json.number(request, "margin") : 0.1;
        if (margin < 0 || margin > 0.4) throw new Failures.Refusal("E_VALIDATION", "margin must be 0..0.4 per image edge");
        Model model = target(request);
        String view = Json.string(request, "view", "current");
        if (!java.util.Arrays.asList("current", "isometric", "front", "back", "top", "bottom", "left", "right").contains(view))
            throw new Failures.Refusal("E_VALIDATION", "unsupported fit orientation");
        try {
            Window window = requireTargetContext(Creo.session(), model);
            // This command intentionally retains its requested orientation and framing.
            // No restoration is claimed; artifact render --view current uses this exact view.
            Output.orientReversibly((ViewOwner) model, view, new ArrayList<Output.Rotation>());
            Map<String, Object> proof = fitWindow(window, margin);
            proof.put("view", view);
            List<Object> orientation = new ArrayList<>();
            com.ptc.pfc.pfcBase.Matrix3D matrix = ((ViewOwner) model).GetCurrentViewTransform().GetMatrix();
            for (int r = 0; r < 3; r++) {
                double length = Math.sqrt(matrix.get(r,0)*matrix.get(r,0) + matrix.get(r,1)*matrix.get(r,1) + matrix.get(r,2)*matrix.get(r,2));
                orientation.add(java.util.Arrays.asList(matrix.get(r,0)/length, matrix.get(r,1)/length, matrix.get(r,2)/length));
            }
            proof.put("orientation", orientation);
            return Json.map("model", Creo.fileName(model), "setter_returned", true, "fit", proof);
        } catch (Throwable problem) {
            throw new Failures.Stage("display_fit", problem, Json.map("model", Creo.fileName(model), "margin", margin));
        }
    }

    static Map<String, Object> fitWindow(Window window, double margin) throws Exception {
        ((WWindow) window).Refit();
        ScreenTransform fitted = window.GetScreenTransform();
        double zoom = fitted.GetZoom() * (1.0 - 2.0 * margin);
        window.SetScreenTransform(pfcBase.ScreenTransform_Create(fitted.GetPanX(), fitted.GetPanY(), zoom));
        window.Repaint();
        ScreenTransform actual = window.GetScreenTransform();
        return Json.map("margin", margin, "refit_zoom", fitted.GetZoom(), "requested_zoom", zoom,
                "observed_zoom", actual.GetZoom(), "observed_pan_x", actual.GetPanX(),
                "observed_pan_y", actual.GetPanY(), "source", "WWindow.Refit/Window.SetScreenTransform",
                "pixel_margin_verified", false);
    }

    static Map<String, Object> visibility(Map<String, Object> request) throws Exception {
        Model model = target(request);
        if (!(model instanceof Assembly)) throw new Failures.Refusal("E_VALIDATION", "component visibility requires an assembly");
        String ident = Json.string(request, "component");
        if (!ident.matches("[0-9]{1,9}")) throw new Failures.Refusal("E_VALIDATION", "component visibility requires exact direct occurrence id");
        ComponentFeat component = Assemblies.component((Assembly) model, ident);
        requireTargetContext(Creo.session(), model);
        WModelItem item = (WModelItem) component;
        boolean hidden = Json.bool(request, "hidden", false);
        try {
            if (item.IsHidden() != hidden) { if (hidden) item.Hide(); else item.Unhide(); }
        } catch (Throwable problem) {
            throw new Failures.Stage("display_component_visibility", problem, Json.map("model", Creo.fileName(model), "component", ident));
        }
        Creo.repaint(Creo.session());
        return Json.map("model", Creo.fileName(model), "component", ident, "setter_returned", true);
    }

    static Map<String, Object> unexplode(Map<String, Object> request) throws Exception {
        Model model = target(request);
        if (!(model instanceof Assembly)) throw new Failures.Refusal("E_VALIDATION", "unexplode requires an assembly");
        try {
            Window window = requireTargetContext(Creo.session(), model);
            Assembly assembly = (Assembly) model;
            if (assembly.GetIsExploded()) assembly.UnExplode();
            window.Repaint();
        } catch (Throwable problem) {
            throw new Failures.Stage("display_unexplode", problem, Json.map("model", Creo.fileName(model)));
        }
        return Json.map("model", Creo.fileName(model), "setter_returned", true);
    }
}
