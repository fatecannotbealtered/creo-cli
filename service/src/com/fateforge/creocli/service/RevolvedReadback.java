package com.fateforge.creocli.service;

import com.ptc.pfc.pfcFeature.Feature;
import com.ptc.pfc.pfcArgument.ArgValue;
import com.ptc.pfc.pfcArgument.ArgValueType;
import com.ptc.pfc.pfcModelItem.ModelItem;
import com.ptc.pfc.pfcSelect.Selection;
import com.ptc.wfc.wfcElementTree.Element;
import com.ptc.wfc.wfcElementTree.ElementTree;
import com.ptc.wfc.wfcElementTree.Elements;
import com.ptc.wfc.wfcElemIds.wfcElemIds;
import com.ptc.wfc.wfcFeature.FeatureElemTreeExtractOptions;
import com.ptc.wfc.wfcFeature.WFeature;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.lang.ref.Reference;

/** Read retained datum/revolve definitions. No setter result or request is used. */
final class RevolvedReadback {
    private RevolvedReadback() { }

    static Map<String, Object> read(Feature feature) {
        // Element/Elements proxies borrow tree storage. Keep the owner and sequences
        // reachable throughout the read; never leave only a temporary GetElementTree().
        List<Object> owners = new ArrayList<>();
        owners.add(feature);
        try {
            String type = Creo.enumName(feature.GetFeatType());
            boolean plane = "FEATTYPE_DATUM_PLANE".equals(type);
            boolean axis = "FEATTYPE_DATUM_AXIS".equals(type);
            if (!plane && !axis && !"FEATTYPE_PROTRUSION".equals(type)
                    && !"FEATTYPE_CUT".equals(type)) {
                return null;
            }
            ElementTree extracted = ((WFeature) feature).GetElementTree(null,
                    FeatureElemTreeExtractOptions.FEAT_EXTRACT_NO_OPTS);
            if (extracted == null) {
                return Json.map("complete", false, "source", "native feature tree",
                        "reason", "this feature has no extractable constructor tree; geometry is separate");
            }
            owners.add(extracted);
            Map<Integer, List<Element>> tree = index(extracted.ListTreeElements(), owners);
            if (!plane && !axis && integer(tree, Ptc.PRO_E_FEATURE_FORM) != Ptc.PRO_REVOLVE) {
                return null;
            }
            Map<String, Object> out = Json.map("complete", true, "source",
                    "WFeature.GetElementTree/ListTreeElements; independent native definition",
                    "kind", plane ? "datum_plane" : axis ? "datum_axis" : "revolve");
            if (plane || axis) {
                List<Object> constraints = new ArrayList<>();
                boolean hasDefaultPlane = false;
                int group = plane ? Ptc.PRO_E_DTMPLN_CONSTRAINT : Ptc.PRO_E_DTMAXIS_CONSTRAINT;
                for (Element constraintElement : tree.getOrDefault(group, java.util.Collections.emptyList())) {
                    Map<Integer, List<Element>> children = index(constraintElement.GetChildren(), owners);
                    int constraint = integer(children, plane ? Ptc.PRO_E_DTMPLN_CONSTR_TYPE
                            : Ptc.PRO_E_DTMAXIS_CONSTR_TYPE);
                    boolean defaultPlane = isDefaultPlane(plane, constraint);
                    hasDefaultPlane |= defaultPlane;
                    Map<String, Object> row = Json.map("type", constraint);
                    Element ref = optional(children, plane ? Ptc.PRO_E_DTMPLN_CONSTR_REF
                            : Ptc.PRO_E_DTMAXIS_CONSTR_REF);
                    readDatumReference(row, plane, constraint, ref, owners);
                    if (defaultPlane) {
                        Set<Integer> supported = Set.of(wfcElemIds.PRO_E_DTMPLN_CONSTR_TYPE,
                                wfcElemIds.PRO_E_DTMPLN_CONSTR_REF, wfcElemIds.PRO_E_DTMPLN_CONSTR_REF_OFFSET,
                                wfcElemIds.PRO_E_DTMPLN_CONSTR_REF_ANGLE, wfcElemIds.PRO_E_DTMPLN_SEC_IND,
                                wfcElemIds.PRO_E_DTMPLN_OFF_CSYS, wfcElemIds.PRO_E_DTMPLN_OFF_CSYS_OFFSET);
                        if (!supported.containsAll(children.keySet())) {
                            throw new Failures.Refusal("E_VERIFY_INCOMPLETE", "default datum has unclassified constraint elements");
                        }
                        if (children.values().stream().anyMatch(values -> values.size() != 1)) {
                            throw new Failures.Refusal("E_VERIFY_INCOMPLETE", "default datum has duplicate constraint elements");
                        }
                        row.put("inapplicable_element_presence", Json.map(
                                "offset", children.containsKey(wfcElemIds.PRO_E_DTMPLN_CONSTR_REF_OFFSET),
                                "angle", children.containsKey(wfcElemIds.PRO_E_DTMPLN_CONSTR_REF_ANGLE),
                                "section", children.containsKey(wfcElemIds.PRO_E_DTMPLN_SEC_IND),
                                "csys_axis", children.containsKey(wfcElemIds.PRO_E_DTMPLN_OFF_CSYS),
                                "csys_offset", children.containsKey(wfcElemIds.PRO_E_DTMPLN_OFF_CSYS_OFFSET)));
                    }
                    if (plane && constraint == Ptc.PRO_DTMPLN_OFFS) {
                        row.put("kind", "offset");
                        row.put("distance", element(children, Ptc.PRO_E_DTMPLN_CONSTR_REF_OFFSET)
                                .GetValue().GetDoubleValue());
                    } else if (axis && constraint == Ptc.PRO_DTMAXIS_CONSTR_TYPE_THRU) {
                        row.put("kind", "through");
                    } else {
                        row.put("kind", "other");
                    }
                    constraints.add(row);
                }
                out.put("constraints", constraints);
                out.put("complete", !constraints.isEmpty());
                if (hasDefaultPlane) {
                    // A no-reference constraint alone is not a complete datum
                    // definition: read actual flip and fit too, or remain incomplete.
                    try {
                        if (constraints.size() != 1) {
                            throw new Failures.Refusal("E_VERIFY_INCOMPLETE", "default datum must have one observed constraint");
                        }
                        out.put("default_reference_observation_complete", true);
                        out.putAll(defaultPlaneDetails(tree, owners));
                        Map<String, Object> entireTree = DefinitionObservation.read(feature);
                        out.put("tree_observation", entireTree);
                        out.put("complete", Boolean.TRUE.equals(entireTree.get("complete")));
                        out.put("definition_coverage", "default datum semantics and entire serialized native element tree, including optional flip/fit/outline");
                    } catch (Throwable failure) {
                        out.put("complete", false);
                        out.put("error", Failures.error(failure));
                        out.put("definition_coverage", "default constraint observed; required flip or fit observation incomplete");
                    }
                }
            } else {
                out.put("angle", element(tree, Ptc.PRO_E_REV_ANGLE_TO_VAL).GetValue().GetDoubleValue());
                int angleType = integer(tree, Ptc.PRO_E_REV_ANGLE_TO_TYPE);
                out.put("angle_mode", angleType == Ptc.PRO_REV_ANG_TO_ANGLE ? "one_side"
                        : angleType == Ptc.PRO_REV_ANG_SYMMETRIC ? "symmetric" : "other");
                out.put("from_none", integer(tree, Ptc.PRO_E_REV_ANGLE_FROM_TYPE) == Ptc.PRO_REV_ANG_FROM_NONE);
                out.put("solid", integer(tree, Ptc.PRO_E_EXT_SURF_CUT_SOLID_TYPE) == Ptc.PRO_REV_FEAT_TYPE_SOLID);
                out.put("add_material", integer(tree, Ptc.PRO_E_REMOVE_MATERIAL) == Ptc.PRO_REV_MATERIAL_ADD);
                out.put("no_thin", integer(tree, Ptc.PRO_E_FEAT_FORM_IS_THIN) == Ptc.PRO_REV_FEAT_FORM_NO_THIN);
                out.put("sketch_plane", reference(tree, Ptc.PRO_E_STD_SEC_PLANE));
                out.put("orient_ref", reference(tree, Ptc.PRO_E_STD_SEC_PLANE_ORIENT_REF));
                boolean external = integer(tree, Ptc.PRO_E_REVOLVE_AXIS_OPT) == Ptc.PRO_REV_AXIS_EXT_REF;
                out.put("axis_kind", external ? "external" : "sketched");
                if (external) {
                    out.put("axis_reference", reference(tree, Ptc.PRO_E_REVOLVE_AXIS));
                }
            }
            return out;
        } catch (Throwable failure) {
            return Json.map("complete", false, "source", "native datum/revolve tree",
                    "error", Failures.error(failure));
        } finally {
            Reference.reachabilityFence(owners);
        }
    }

    private static Map<Integer, List<Element>> index(Elements elements, List<Object> owners) throws Exception {
        Map<Integer, List<Element>> out = new HashMap<>();
        if (elements == null) {
            return out;
        }
        owners.add(elements);
        int count = elements.getarraysize();
        if (count > 4096) {
            throw new Failures.Refusal("E_VERIFY_INCOMPLETE", "native tree exceeds the bounded reader limit");
        }
        for (int i = 0; i < count; i++) {
            Element element = elements.get(i);
            owners.add(element);
            out.computeIfAbsent(element.GetId(), key -> new ArrayList<>()).add(element);
        }
        return out;
    }

    private static Element optional(Map<Integer, List<Element>> elements, int id) throws Exception {
        List<Element> values = elements.get(id);
        if (values == null || values.isEmpty()) {
            return null;
        }
        if (values.size() != 1) {
            throw new Failures.Refusal("E_VERIFY_INCOMPLETE", "ambiguous native element " + id);
        }
        return values.get(0);
    }

    private static Element element(Map<Integer, List<Element>> elements, int id) throws Exception {
        Element found = optional(elements, id);
        if (found == null) {
            throw new Failures.Refusal("E_VERIFY_INCOMPLETE", "missing native element " + id);
        }
        return found;
    }

    /** Read the selection, distinguishing documented reference-free defaults from missing data. */
    private static void readDatumReference(Map<String, Object> row, boolean plane, int constraint,
                                           Element element, List<Object> owners) throws Exception {
        boolean defaultPlane = isDefaultPlane(plane, constraint);
        ArgValue value = element == null ? null : element.GetValue();
        if (value == null) {
            if (!defaultPlane) {
                throw new Failures.Refusal("E_VERIFY_INCOMPLETE",
                        "datum constraint reference value is unavailable for type " + constraint);
            }
            // PTC documents DEF_X/Y/Z as needing no reference. Preserve whether the
            // native reference element existed and whether its optional value was null.
            row.put("reference", null);
            row.put("reference_status", "not_required_for_default_datum_plane");
            row.put("reference_observation", Json.map("status", "not_applicable", "complete", true,
                    "reason", "documented default X/Y/Z datum constraint requires no reference",
                    "constraint_type", constraint));
            row.put("reference_element_present", element != null);
            return;
        }
        if (defaultPlane) {
            // The supported observation is only the documented no-reference
            // default. A populated value needs independent type/owner/path proof.
            throw new Failures.Refusal("E_VERIFY_INCOMPLETE",
                    "default datum has a populated reference outside the bounded reader scope");
        }
        owners.add(value);
        ArgValueType valueType = value.Getdiscr();
        if (valueType == null || valueType.getValue() != ArgValueType._ARG_V_SELECTION) {
            throw new Failures.Refusal("E_VERIFY_INCOMPLETE", "datum constraint reference is not a selection");
        }
        Selection selected = value.GetSelectionValue();
        if (selected == null) {
            throw new Failures.Refusal("E_VERIFY_INCOMPLETE", "datum constraint selection is unavailable");
        }
        owners.add(selected);
        ModelItem item = selected.GetSelItem();
        if (item == null) {
            throw new Failures.Refusal("E_VERIFY_INCOMPLETE", "datum constraint selected item is unavailable");
        }
        owners.add(item);
        String reference = Geometry.ref(item);
        if (reference == null || reference.isEmpty()) {
            throw new Failures.Refusal("E_VERIFY_INCOMPLETE", "datum constraint selected item has no identity");
        }
        row.put("reference", reference);
    }

    private static boolean isDefaultPlane(boolean plane, int constraint) {
        return plane && (constraint == Ptc.PRO_DTMPLN_DEF_X
                || constraint == Ptc.PRO_DTMPLN_DEF_Y || constraint == Ptc.PRO_DTMPLN_DEF_Z);
    }

    private static int observedInteger(Map<Integer, List<Element>> elements, int id, List<Object> owners)
            throws Exception {
        ArgValue value = element(elements, id).GetValue();
        if (value == null) throw new Failures.Refusal("E_VERIFY_INCOMPLETE", "native integer value unavailable for element " + id);
        owners.add(value);
        ArgValueType type = value.Getdiscr();
        if (type == null || type.getValue() != ArgValueType._ARG_V_INTEGER) {
            throw new Failures.Refusal("E_VERIFY_INCOMPLETE", "native element is not an integer: " + id);
        }
        return value.GetIntValue();
    }

    private static Map<String, Object> defaultPlaneDetails(Map<Integer, List<Element>> tree, List<Object> owners)
            throws Exception {
        Element flipElement = optional(tree, wfcElemIds.PRO_E_DTMPLN_FLIP_DIR);
        Integer flip = flipElement == null ? null : observedInteger(tree, wfcElemIds.PRO_E_DTMPLN_FLIP_DIR, owners);
        if (flip == null) return Json.map("flip_status", "not_applicable", "fit_status", "covered_by_entire_native_tree");
        if (flip != Ptc.PRO_DTMPLN_FLIP_DIR_NO && flip != Ptc.PRO_DTMPLN_FLIP_DIR_YES) {
            throw new Failures.Refusal("E_VERIFY_INCOMPLETE", "default datum flip is unclassified");
        }
        Element fit = optional(tree, wfcElemIds.PRO_E_DTMPLN_FIT);
        if (fit == null) return Json.map("flip_raw", flip, "fit_status", "not_applicable");
        if (!fit.GetIsCompound()) {
            throw new Failures.Refusal("E_VERIFY_INCOMPLETE", "default datum fit group is not compound");
        }
        Map<Integer, List<Element>> values = index(fit.GetChildren(), owners);
        Set<Integer> known = Set.of(wfcElemIds.PRO_E_DTMPLN_FIT_TYPE, wfcElemIds.PRO_E_DTMPLN_FIT_REF,
                wfcElemIds.PRO_E_DTMPLN_FIT_DTM_RAD, wfcElemIds.PRO_E_DTMPLN_FIT_OUTLINE);
        if (!known.containsAll(values.keySet())) {
            throw new Failures.Refusal("E_VERIFY_INCOMPLETE", "default datum fit has unclassified elements");
        }
        int fitType = observedInteger(values, wfcElemIds.PRO_E_DTMPLN_FIT_TYPE, owners);
        if (fitType != Ptc.PRO_DTMPLN_FIT_DEFAULT) {
            throw new Failures.Refusal("E_VERIFY_INCOMPLETE", "only an explicitly observed default datum fit is supported");
        }
        return Json.map("flip_raw", flip, "fit", Json.map("type_raw", fitType, "mode", "default",
                        "element_presence", Json.map("reference", values.containsKey(wfcElemIds.PRO_E_DTMPLN_FIT_REF),
                                "radius", values.containsKey(wfcElemIds.PRO_E_DTMPLN_FIT_DTM_RAD),
                                "outline", values.containsKey(wfcElemIds.PRO_E_DTMPLN_FIT_OUTLINE)),
                        "not_checked", List.of("datum_display_outline")),
                "definition_coverage", "default datum constraint, flip and default fit only; root tree and display outline not fully read");
    }

    private static int integer(Map<Integer, List<Element>> elements, int id) throws Exception {
        return element(elements, id).GetValue().GetIntValue();
    }

    private static String reference(Map<Integer, List<Element>> elements, int id) throws Exception {
        return Geometry.ref(element(elements, id).GetValue().GetSelectionValue().GetSelItem());
    }
}
