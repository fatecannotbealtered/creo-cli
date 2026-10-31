package com.fateforge.creocli.service;

import com.ptc.pfc.pfcArgument.ArgValue;
import com.ptc.pfc.pfcFeature.Feature;
import com.ptc.pfc.pfcSelect.Selection;
import com.ptc.pfc.pfcSelect.Selections;
import com.ptc.wfc.wfcElementTree.Element;
import com.ptc.wfc.wfcElementTree.ElementTree;
import com.ptc.wfc.wfcElementTree.Elements;
import com.ptc.wfc.wfcFeature.FeatureElemTreeExtractOptions;
import com.ptc.wfc.wfcFeature.WFeature;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.lang.ref.Reference;

/** Independent retained feature definitions, never the creation request or a tree export. */
final class MachiningReadback {
    private MachiningReadback() { }

    static Map<String, Object> read(Feature feature) throws Exception {
        String type = Creo.enumName(feature.GetFeatType());
        if (!"FEATTYPE_HOLE".equals(type) && !"FEATTYPE_ROUND".equals(type)) {
            return null;
        }
        ElementTree owner = null;
        try {
            owner = ((WFeature) feature).GetElementTree(null,
                    FeatureElemTreeExtractOptions.FEAT_EXTRACT_NO_OPTS);
            Elements elements = owner.ListTreeElements();
            Map<String, Object> result = Json.map("complete", true,
                    "source", "WFeature.GetElementTree/ListTreeElements; independent feature getters",
                    "type", type);
            if ("FEATTYPE_HOLE".equals(type)) {
                int form = value(elements, Ptc.PRO_E_FEATURE_FORM).GetIntValue();
                result.put("form", form);
                if (form != Ptc.PRO_HLE_TYPE_STRAIGHT) {
                    return Json.map("complete", false, "source", "native feature tree",
                            "reason", "this reader covers straight holes only", "form", form);
                }
                result.put("diameter", value(elements, Ptc.PRO_E_DIAMETER).GetDoubleValue());
                int depth = value(elements, Ptc.PRO_E_HOLE_DEPTH_TO_TYPE).GetIntValue();
                result.put("through_all", depth == Ptc.PRO_HLE_STRGHT_THRU_ALL_DEPTH);
                result.put("depth_type", depth);
                result.put("from_type", value(elements, Ptc.PRO_E_HOLE_DEPTH_FROM_TYPE).GetIntValue());
                int placement = value(elements, Ptc.PRO_E_HLE_PL_TYPE).GetIntValue();
                result.put("placement_type", placement);
                result.put("placement_surface", reference(elements, Ptc.PRO_E_HLE_PRIM_REF));
                if (placement == Ptc.PRO_HLE_PL_TYPE_LIN) {
                    result.put("offsets", java.util.Arrays.asList(
                            Json.map("from", reference(elements, Ptc.PRO_E_HLE_DIM_REF1),
                                    "distance", value(elements, Ptc.PRO_E_HLE_DIM_DIST1).GetDoubleValue()),
                            Json.map("from", reference(elements, Ptc.PRO_E_HLE_DIM_REF2),
                                    "distance", value(elements, Ptc.PRO_E_HLE_DIM_DIST2).GetDoubleValue())));
                } else {
                    result.put("complete", false);
                    result.put("reason", "bounded definition reader requires linear placement");
                }
            } else {
                // Extracted rounds contain both LEG1 and LEG2 values. Read the explicit
                // LEG1 subtree; a global first-match would silently select ambiguous data.
                result.put("radius", value(element(elements, Ptc.PRO_E_RNDCH_LEG1).GetChildren(),
                        Ptc.PRO_E_RNDCH_LEG_VALUE).GetDoubleValue());
                result.put("constant", value(elements, Ptc.PRO_E_RNDCH_SHAPE_OPTIONS).GetIntValue()
                        == Ptc.PRO_ROUND_TYPE_CONSTANT);
                com.ptc.wfc.wfcCollection.CurveCollectionInstructions instructions =
                        element(element(elements, Ptc.PRO_E_RNDCH_REFERENCES).GetChildren(),
                        Ptc.PRO_E_STD_CURVE_COLLECTION_APPL).GetElemCollection()
                        .GetCrvCollection().GetInstructions();
                List<Object> refs = new ArrayList<>();
                for (int i = 0; instructions != null && i < instructions.getarraysize(); i++) {
                    Selections selected = instructions.get(i).GetReferences();
                    for (int j = 0; selected != null && j < selected.getarraysize(); j++) {
                        refs.add(Geometry.ref(selected.get(j).GetSelItem()));
                    }
                }
                result.put("edges", refs);
                result.put("reference_scope", "stored pre-round edge references; current solid geometry is separate");
                if (refs.isEmpty()) {
                    result.put("complete", false);
                    result.put("reason", "round collection references are unreadable");
                }
            }
            return result;
        } catch (Throwable failure) {
            return Json.map("complete", false, "source", "native feature tree",
                    "error", Failures.error(failure));
        } finally {
            Reference.reachabilityFence(owner);
            Reference.reachabilityFence(feature);
        }
    }

    private static Element element(Elements elements, int id) throws Exception {
        Element found = null;
        int count = elements == null ? 0 : elements.getarraysize();
        for (int i = 0; i < count; i++) {
            Element candidate = elements.get(i);
            if (candidate.GetId() == id) {
                if (found != null) {
                    throw new Failures.Refusal("E_VERIFY_INCOMPLETE", "ambiguous feature-tree element " + id);
                }
                found = candidate;
            }
        }
        if (found == null) {
            throw new Failures.Refusal("E_VERIFY_INCOMPLETE", "missing feature-tree element " + id);
        }
        return found;
    }

    private static ArgValue value(Elements elements, int id) throws Exception {
        return element(elements, id).GetValue();
    }

    private static String reference(Elements elements, int id) throws Exception {
        Selection selected = value(elements, id).GetSelectionValue();
        return Geometry.ref(selected.GetSelItem());
    }
}
