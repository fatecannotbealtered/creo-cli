package com.fateforge.creocli.service;

import com.ptc.pfc.pfcFeature.Feature;
import com.ptc.wfc.wfcElementTree.Element;
import com.ptc.wfc.wfcElementTree.ElementTree;
import com.ptc.wfc.wfcElementTree.Elements;
import com.ptc.wfc.wfcFeature.FeatureElemTreeExtractOptions;
import com.ptc.wfc.wfcFeature.WFeature;
import com.ptc.wfc.wfcCollection.Collection;
import com.ptc.wfc.wfcCollection.SurfaceCollection;
import com.ptc.wfc.wfcCollection.SurfaceCollectionInstruction;
import com.ptc.wfc.wfcCollection.SurfaceCollectionInstructions;
import com.ptc.wfc.wfcCollection.SurfaceCollectionInstrType;
import com.ptc.wfc.wfcCollection.SurfaceCollectionReferences;
import com.ptc.wfc.wfcCollection.SurfaceCollectionRefType;
import com.ptc.wfc.wfcCollection.SurfaceCollectionRules;
import java.lang.ref.Reference;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/** Independent definition of a constant, unsplit, single-plane draft. */
final class DraftReadback {
    private DraftReadback() { }

    static Map<String, Object> definition(Feature feature) {
        List<Object> owners = new ArrayList<>();
        owners.add(feature);
        try {
            if (!"FEATTYPE_DRAFT".equals(Creo.enumName(feature.GetFeatType()))) return null;
            ElementTree tree = ((WFeature) feature).GetElementTree(null,
                    FeatureElemTreeExtractOptions.FEAT_EXTRACT_NO_OPTS);
            if (tree == null) throw incomplete("draft tree is unavailable");
            owners.add(tree);
            Elements elements = tree.ListTreeElements();
            owners.add(elements);
            Collection collection = one(elements, Ptc.PRO_E_STD_SURF_COLLECTION_APPL, owners).GetElemCollection();
            if (collection == null) throw incomplete("draft surface collection is unavailable");
            owners.add(collection);
            SurfaceCollection surfaces = collection.GetSurfCollection();
            if (surfaces == null) throw incomplete("draft surface collection type is unreadable");
            owners.add(surfaces);
            SurfaceCollectionInstructions instructions = surfaces.GetInstructions();
            owners.add(instructions);
            if (instructions == null || instructions.getarraysize() != 1)
                throw incomplete("one explicit draft surface instruction is required");
            SurfaceCollectionInstruction instruction = instructions.get(0);
            owners.add(instruction);
            if (instruction.GetType().getValue() != SurfaceCollectionInstrType._SURFCOLL_SINGLE_SURF
                    || !instruction.GetInclude())
                throw incomplete("draft surface selection is not a single included surface");
            SurfaceCollectionRules rules = instruction.GetRules();
            owners.add(rules);
            if (rules != null && rules.getarraysize() != 0)
                throw incomplete("rule-based draft selection is outside the bounded reader");
            SurfaceCollectionReferences references = instruction.GetSrfCollectionReferences();
            owners.add(references);
            if (references == null || references.getarraysize() != 1)
                throw incomplete("one native selected surface reference is required");
            com.ptc.wfc.wfcCollection.SurfaceCollectionReference reference = references.get(0);
            owners.add(reference);
            if (reference.GetRefType().getValue() != SurfaceCollectionRefType._SURFCOLL_REF_SINGLE
                    || reference.GetReference() == null)
                throw incomplete("draft surface reference is not a readable single item");
            com.ptc.pfc.pfcSelect.Selection selected = reference.GetReference();
            owners.add(selected);
            String face = Geometry.ref(selected.GetSelItem());
            String hinge = selection(elements, Ptc.PRO_E_DRAFT_NEUTRAL_PLANE_1, owners);
            String pull = selection(elements, Ptc.PRO_E_DIRECTION_REFERENCE, owners);
            int flip = integer(elements, Ptc.PRO_E_DIRECTION_FLIP, owners);
            if (flip != Ptc.PRO_DIRECTION_FLIP_ALONG && flip != Ptc.PRO_DIRECTION_FLIP_AGAINST)
                throw incomplete("draft pull-direction sense is unreadable");
            return Json.map("complete", true, "kind", "draft", "selected", List.of(face),
                    "hinge", hinge, "pull", pull, "flip_pull", flip == Ptc.PRO_DIRECTION_FLIP_AGAINST,
                    "angle", one(elements, Ptc.PRO_E_DRAFT_ANGLE_1, owners).GetValue().GetDoubleValue(),
                    "split", integer(elements, Ptc.PRO_E_DRAFT_SPLIT, owners) == Ptc.PRO_DRAFT_UI_SPLIT_NONE ? "none" : "other",
                    "mode", integer(elements, Ptc.PRO_E_DRAFT_CONSTANT_OR_VARIABLE, owners) == Ptc.PRO_DRAFT_UI_CONSTANT ? "constant" : "other",
                    "neutral_type", integer(elements, Ptc.PRO_E_DRAFT_NEUTRAL_OBJECT_TYPE_1, owners) == Ptc.PRO_DRAFT_UI_PLANE ? "plane" : "other",
                    "independent", integer(elements, Ptc.PRO_E_DRAFT_DEPENDENT_1, owners) == Ptc.PRO_DRAFT_UI_INDEPENDENT,
                    "include_tangent", integer(elements, Ptc.PRO_E_DRAFT_INCLUDE_TANGENT, owners) == Ptc.PRO_DRAFT_UI_INC_TANG,
                    "selection_rule", "single_included_surface", "rule_count", 0,
                    "source", "independent held WFeature draft tree and native collection/reference getters; no creation request used");
        } catch (Throwable failure) {
            return Json.map("complete", false, "kind", "draft", "source", "native draft tree/collection",
                    "error", Failures.error(failure));
        } finally {
            Reference.reachabilityFence(owners);
        }
    }

    private static Element one(Elements elements, int id, List<Object> owners) throws Exception {
        if (elements == null || elements.getarraysize() > 4096) throw incomplete("draft tree inventory unavailable");
        Element found = null;
        for (int i = 0; i < elements.getarraysize(); i++) {
            Element element = elements.get(i);
            owners.add(element);
            if (element.GetId() == id) {
                if (found != null) throw incomplete("ambiguous draft tree element " + id);
                found = element;
            }
        }
        if (found == null) throw incomplete("missing draft tree element " + id);
        return found;
    }

    private static int integer(Elements elements, int id, List<Object> owners) throws Exception {
        return one(elements, id, owners).GetValue().GetIntValue();
    }

    private static String selection(Elements elements, int id, List<Object> owners) throws Exception {
        com.ptc.pfc.pfcSelect.Selection selected = one(elements, id, owners).GetValue().GetSelectionValue();
        if (selected == null) throw incomplete("missing draft reference " + id);
        owners.add(selected);
        return Geometry.ref(selected.GetSelItem());
    }

    private static Failures.Refusal incomplete(String message) {
        return new Failures.Refusal("E_VERIFY_INCOMPLETE", message);
    }
}
