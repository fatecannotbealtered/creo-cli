package com.fateforge.creocli.service;

import com.ptc.pfc.pfcAssembly.Assembly;
import com.ptc.pfc.pfcComponentFeat.ComponentFeat;
import com.ptc.pfc.pfcFeature.FeatureType;
import com.ptc.pfc.pfcFeature.Features;
import com.ptc.pfc.pfcModel.Model;
import com.ptc.pfc.pfcModel.ModelType;
import com.ptc.pfc.pfcSolid.Solid;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/** Read one bounded resource. Completion covers the declared getters, not every field in Creo. */
final class Resources {
    private Resources() { }

    static Map<String, Object> geometry(Map<String, Object> request, boolean bounds) throws Exception {
        Solid solid = Creo.solid(Creo.session(), Json.string(request, "model"));
        Object data = bounds ? Creo.outline(solid) : Creo.massProperties(solid);
        if (data == null || data instanceof Map && ((Map<?, ?>) data).get("error") != null) {
            throw new Failures.Refusal("E_VERIFY_INCOMPLETE", "native geometry getter failed");
        }
        return Json.map("model", Creo.fileName((Model) solid), "units", Creo.units(solid),
                "data", data, "completed", true,
                "model_accuracy", Json.map("absolute", solid.GetAbsoluteAccuracy(),
                        "relative", solid.GetRelativeAccuracy(), "source", "Solid.GetAbsoluteAccuracy/GetRelativeAccuracy"),
                "source", bounds ? "Solid.GetGeomOutline" : "Solid.GetMassProperty",
                "accuracy", bounds ? "approximate_outline" : "native_mass_properties",
                "not_checked", bounds ? List.of("exact_extrema", "consumer_geometry") : List.of("manufacturability"));
    }

    static Map<String, Object> components(Map<String, Object> request, boolean placement) throws Exception {
        Solid solid = Creo.solid(Creo.session(), Json.string(request, "model"));
        if (((Model) solid).GetType().getValue() != ModelType._MDL_ASSEMBLY) {
            throw new Failures.Refusal("E_VALIDATION", "model is not an assembly");
        }
        List<Object> rows = new ArrayList<>();
        Features all = solid.ListFeaturesByType(Boolean.TRUE, FeatureType.FEATTYPE_COMPONENT);
        if (all == null) throw new Failures.Refusal("E_VERIFY_INCOMPLETE", "component inventory is null");
        int loose = 0;
        for (int i = 0; i < all.getarraysize(); i++) {
            ComponentFeat component = (ComponentFeat) all.get(i);
            Map<String, Object> row = Assemblies.row(component, Creo.fileName(component.GetModelDescr()));
            row.put("component_path", List.of(component.GetId()));
            if (placement && (!row.containsKey("placed") || !row.containsKey("packaged")
                    || !row.containsKey("underconstrained") || row.get("placement_error") != null)) {
                throw new Failures.Refusal("E_VERIFY_INCOMPLETE", "component placement getter failed");
            }
            if (Boolean.TRUE.equals(row.get("packaged")) || Boolean.TRUE.equals(row.get("underconstrained"))) loose++;
            rows.add(row);
        }
        Map<String, Object> out = Json.map("model", Creo.fileName((Model) solid), "items", rows,
                "source", "Solid.ListFeaturesByType/ComponentFeat getters", "completed", true,
                "scope", "top_level", "coverage", Json.map("count", rows.size(), "recursive", false,
                        "required_fields", placement ? List.of("id", "model", "placed", "packaged", "underconstrained")
                                : List.of("id", "model", "status")),
                "not_checked", List.of("nested_occurrences", "global_interference"));
        if (placement) out.put("not_fully_constrained", loose);
        return out;
    }

    static Map<String, Object> applyLayout(Map<String, Object> request) throws Exception {
        Object raw = request.get("views");
        if (!(raw instanceof List) || ((List<?>) raw).isEmpty() || ((List<?>) raw).size() > 24) {
            throw new Failures.Refusal("E_VALIDATION", "layout requires1..24 view moves");
        }
        String name = Json.string(request, "model");
        for (Object item : (List<?>) raw) {
            if (!(item instanceof Map) || !(((Map<?, ?>) item).get("view") instanceof String)
                    || !(((Map<?, ?>) item).get("at") instanceof List)) {
                throw new Failures.Refusal("E_VALIDATION", "invalid view move");
            }
        }
        for (Object item : (List<?>) raw) {
            Map<?, ?> move = (Map<?, ?>) item;
            Views.move(Json.map("model", name, "view", move.get("view"), "at", move.get("at")));
        }
        return Drawings.resources(Json.map("model", name, "kind", "views", "sheet", request.get("sheet")));
    }

    static Map<String, Object> exploded(Map<String, Object> request) throws Exception {
        Solid solid = Creo.solid(Creo.session(), Json.string(request, "model"));
        if (((Model) solid).GetType().getValue() != ModelType._MDL_ASSEMBLY) {
            throw new Failures.Refusal("E_VALIDATION", "model is not an assembly");
        }
        List<Object> rows = Assemblies.explodedStatesStrict((Assembly) solid);
        return Json.map("model", Creo.fileName((Model) solid), "items", rows, "completed", true,
                "source", "Assembly.ListItems(ITEM_EXPLODED_STATE)", "scope", "named_states",
                "coverage", Json.map("count", rows.size(), "required_fields", List.of("id", "name")),
                "not_checked", List.of("all_move_fields"));
    }
}
