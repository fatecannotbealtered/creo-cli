package com.fateforge.creocli.service;

import com.ptc.pfc.pfcArgument.ArgValue;
import com.ptc.pfc.pfcArgument.ArgValueType;
import com.ptc.pfc.pfcFeature.FeatureType;
import com.ptc.pfc.pfcModelItem.ModelItem;
import com.ptc.pfc.pfcModelItem.ModelItemType;
import com.ptc.pfc.pfcSelect.Selection;
import com.ptc.wfc.wfcElementTree.Element;
import com.ptc.wfc.wfcElementTree.ElementTree;
import com.ptc.wfc.wfcElementTree.Elements;
import com.ptc.wfc.wfcElemIds.wfcElemIds;
import com.ptc.wfc.wfcFeature.WFeature;
import java.lang.reflect.InvocationHandler;
import java.lang.reflect.Proxy;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/** Synthetic SDK-interface regression; no Creo process, SDK native calls or CAD writes. */
public final class DatumReferenceReadbackHarness {
    private DatumReferenceReadbackHarness() { }

    private static final class LocalElements extends Elements {
        private final List<Element> elements;
        LocalElements(List<Element> elements) { super(0); this.elements = elements; }
        @Override public int getarraysize() { return elements.size(); }
        @Override public Element get(int index) { return elements.get(index); }
        @Override public void xdelete() { }
    }

    private static final class LocalValue extends ArgValue {
        final int integer;
        final ArgValueType type;
        final Selection selection;
        LocalValue(int integer, ArgValueType type, Selection selection) {
            super(0); this.integer = integer; this.type = type; this.selection = selection;
        }
        @Override public int GetIntValue() { return integer; }
        @Override public ArgValueType Getdiscr() { return type; }
        @Override public Selection GetSelectionValue() { return selection; }
        @Override public void xdelete() { }
    }

    @SuppressWarnings("unchecked")
    private static <T> T proxy(Class<T> type, InvocationHandler handler) {
        return (T) Proxy.newProxyInstance(type.getClassLoader(), new Class<?>[]{type}, handler);
    }

    private static Object defaultObjectMethod(Object proxy, java.lang.reflect.Method method, Object[] args) {
        return switch (method.getName()) {
            case "toString" -> "synthetic SDK object";
            case "hashCode" -> System.identityHashCode(proxy);
            case "equals" -> proxy == args[0];
            case "getptr" -> 0L;
            case "xdelete" -> null;
            default -> throw new UnsupportedOperationException(method.getName());
        };
    }

    private static Element element(int id, ArgValue value, Elements children) {
        return proxy(Element.class, (proxy, method, args) -> switch (method.getName()) {
            case "GetId" -> id;
            case "GetValue" -> value;
            case "GetChildren" -> children;
            case "GetIsCompound" -> children != null;
            default -> defaultObjectMethod(proxy, method, args);
        });
    }

    private static Selection selection(boolean hasItem) {
        ModelItem item = hasItem ? proxy(ModelItem.class, (proxy, method, args) -> switch (method.getName()) {
            case "GetType" -> ModelItemType.ITEM_AXIS;
            case "GetName" -> "TEST_AXIS";
            case "GetId" -> 37;
            default -> defaultObjectMethod(proxy, method, args);
        }) : null;
        return proxy(Selection.class, (proxy, method, args) -> switch (method.getName()) {
            case "GetSelItem" -> item;
            default -> defaultObjectMethod(proxy, method, args);
        });
    }

    private static Map<String, Object> read(boolean plane, int constraint, boolean hasElement,
                                             ArgValue reference, boolean duplicate) {
        return read(plane, constraint, hasElement, reference, duplicate, true);
    }

    private static Map<String, Object> read(boolean plane, int constraint, boolean hasElement,
                                             ArgValue reference, boolean duplicate, boolean hasFlipAndFit) {
        return read(plane, constraint, hasElement, reference, duplicate, hasFlipAndFit,
                Ptc.PRO_DTMPLN_FLIP_DIR_NO, Ptc.PRO_DTMPLN_FIT_DEFAULT, false);
    }

    private static Map<String, Object> read(boolean plane, int constraint, boolean hasElement,
                                             ArgValue reference, boolean duplicate, boolean hasFlipAndFit,
                                             int flip, int fitMode, boolean unknownFitElement) {
        return read(plane, constraint, hasElement, reference, duplicate, hasFlipAndFit,
                hasFlipAndFit, flip, fitMode, unknownFitElement, false);
    }

    private static Map<String, Object> read(boolean plane, int constraint, boolean hasElement,
                                             ArgValue reference, boolean duplicate, boolean hasFlip,
                                             boolean hasFit, int flip, int fitMode,
                                             boolean unknownFitElement, boolean unknownConstraintElement) {
        return read(plane, constraint, hasElement, reference, duplicate, hasFlip, hasFit, flip, fitMode,
                unknownFitElement, unknownConstraintElement, false);
    }

    private static Map<String, Object> read(boolean plane, int constraint, boolean hasElement,
                                             ArgValue reference, boolean duplicate, boolean hasFlip,
                                             boolean hasFit, int flip, int fitMode,
                                             boolean unknownFitElement, boolean unknownConstraintElement,
                                             boolean duplicateInapplicableElement) {
        return read(plane, constraint, hasElement, reference, duplicate, hasFlip, hasFit, flip, fitMode,
                unknownFitElement, unknownConstraintElement, duplicateInapplicableElement, false);
    }

    private static Map<String, Object> read(boolean plane, int constraint, boolean hasElement,
                                             ArgValue reference, boolean duplicate, boolean hasFlip,
                                             boolean hasFit, int flip, int fitMode,
                                             boolean unknownFitElement, boolean unknownConstraintElement,
                                             boolean duplicateInapplicableElement, boolean unknownRootElement) {
        int group = plane ? Ptc.PRO_E_DTMPLN_CONSTRAINT : Ptc.PRO_E_DTMAXIS_CONSTRAINT;
        int typeId = plane ? Ptc.PRO_E_DTMPLN_CONSTR_TYPE : Ptc.PRO_E_DTMAXIS_CONSTR_TYPE;
        int refId = plane ? Ptc.PRO_E_DTMPLN_CONSTR_REF : Ptc.PRO_E_DTMAXIS_CONSTR_REF;
        List<Element> children = new ArrayList<>();
        children.add(element(typeId, new LocalValue(constraint, ArgValueType.ARG_V_INTEGER, null), null));
        if (hasElement) children.add(element(refId, reference, null));
        if (duplicate) children.add(element(refId, reference, null));
        if (unknownConstraintElement) children.add(element(999998, null, null));
        if (duplicateInapplicableElement) {
            children.add(element(wfcElemIds.PRO_E_DTMPLN_CONSTR_REF_OFFSET, null, null));
            children.add(element(wfcElemIds.PRO_E_DTMPLN_CONSTR_REF_OFFSET, null, null));
        }
        Element groupElement = element(group, null, new LocalElements(children));
        List<Element> roots = new ArrayList<>();
        roots.add(groupElement);
        if (unknownRootElement) roots.add(element(999997, null, null));
        if (hasFlip) {
            roots.add(element(wfcElemIds.PRO_E_DTMPLN_FLIP_DIR,
                    new LocalValue(flip, ArgValueType.ARG_V_INTEGER, null), null));
        }
        if (hasFit) {
            Element fitType = element(wfcElemIds.PRO_E_DTMPLN_FIT_TYPE,
                    new LocalValue(fitMode, ArgValueType.ARG_V_INTEGER, null), null);
            List<Element> fitChildren = new ArrayList<>();
            fitChildren.add(fitType);
            if (unknownFitElement) fitChildren.add(element(999999, null, null));
            roots.add(element(wfcElemIds.PRO_E_DTMPLN_FIT, null, new LocalElements(fitChildren)));
        }
        ElementTree tree = proxy(ElementTree.class, (proxy, method, args) -> switch (method.getName()) {
            case "ListTreeElements" -> new LocalElements(roots);
            default -> defaultObjectMethod(proxy, method, args);
        });
        WFeature feature = proxy(WFeature.class, (proxy, method, args) -> switch (method.getName()) {
            case "GetFeatType" -> plane ? FeatureType.FEATTYPE_DATUM_PLANE : FeatureType.FEATTYPE_DATUM_AXIS;
            case "GetElementTree" -> tree;
            default -> defaultObjectMethod(proxy, method, args);
        });
        return RevolvedReadback.read(feature);
    }

    private static void require(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> first(Map<String, Object> result) {
        return (Map<String, Object>) ((List<Object>) result.get("constraints")).get(0);
    }

    private static void incomplete(Map<String, Object> result, String reason) {
        require(Boolean.FALSE.equals(result.get("complete")), reason + " must be incomplete");
        Object raw = result.get("error");
        if (raw == null && result.get("tree_observation") instanceof Map) {
            require(!Boolean.TRUE.equals(((Map<?, ?>) result.get("tree_observation")).get("complete")),
                    reason + " requires a successful entire tree observation");
            return;
        }
        require(raw instanceof Map && "E_VERIFY_INCOMPLETE".equals(((Map<?, ?>) raw).get("code")),
                reason + " must be a typed incomplete result");
    }

    public static void main(String[] args) {
        List<String> passed = new ArrayList<>();
        for (int kind : new int[]{Ptc.PRO_DTMPLN_DEF_X, Ptc.PRO_DTMPLN_DEF_Y, Ptc.PRO_DTMPLN_DEF_Z}) {
            Map<String, Object> result = read(true, kind, true, null, false);
            require(Boolean.FALSE.equals(result.get("complete")), "partial default tree must not be called complete");
            require(Boolean.TRUE.equals(result.get("default_reference_observation_complete")), "default reference is observed");
            Map<String, Object> row = first(result);
            require(row.containsKey("reference") && row.get("reference") == null, "null reference preserved");
            require("not_required_for_default_datum_plane".equals(row.get("reference_status")), "reason preserved");
            require(Boolean.TRUE.equals(row.get("reference_element_present")), "element presence preserved");
            require(((Number) result.get("flip_raw")).intValue() == Ptc.PRO_DTMPLN_FLIP_DIR_NO, "actual flip recorded");
            require("default".equals(((Map<?, ?>) result.get("fit")).get("mode")), "actual fit recorded");
        }
        passed.add("all_three_default_types_accept_present_element_with_null_value");

        Map<String, Object> absent = read(true, Ptc.PRO_DTMPLN_DEF_X, false, null, false);
        require(Boolean.FALSE.equals(absent.get("complete")) && Boolean.FALSE.equals(first(absent).get("reference_element_present")),
                "default with absent element must be distinguishable");
        passed.add("default_without_reference_element_is_distinguished");

        Map<String, Object> missingDetails = read(true, Ptc.PRO_DTMPLN_DEF_X, true, null, false, false);
        require(Boolean.FALSE.equals(missingDetails.get("complete")), "missing optional flip and fit still require a successful entire tree observation");
        require(first(missingDetails).containsKey("reference_status"), "partial default observation must be retained");
        incomplete(read(true, Ptc.PRO_DTMPLN_DEF_X, true, null, false, false, true,
                Ptc.PRO_DTMPLN_FLIP_DIR_NO, Ptc.PRO_DTMPLN_FIT_DEFAULT, false, false), "missing flip");
        incomplete(read(true, Ptc.PRO_DTMPLN_DEF_X, true, null, false, true, false,
                Ptc.PRO_DTMPLN_FLIP_DIR_NO, Ptc.PRO_DTMPLN_FIT_DEFAULT, false, false), "missing fit");
        incomplete(read(true, Ptc.PRO_DTMPLN_DEF_X, true, null, false, true, 9,
                Ptc.PRO_DTMPLN_FIT_DEFAULT, false), "unclassified flip");
        incomplete(read(true, Ptc.PRO_DTMPLN_DEF_X, true, null, false, true, Ptc.PRO_DTMPLN_FLIP_DIR_NO,
                9, false), "unsupported fit mode");
        incomplete(read(true, Ptc.PRO_DTMPLN_DEF_X, true, null, false, true, Ptc.PRO_DTMPLN_FLIP_DIR_NO,
                Ptc.PRO_DTMPLN_FIT_DEFAULT, true), "unclassified fit element");
        incomplete(read(true, Ptc.PRO_DTMPLN_DEF_X, true, null, false, true, true,
                Ptc.PRO_DTMPLN_FLIP_DIR_NO, Ptc.PRO_DTMPLN_FIT_DEFAULT, false, true), "unclassified constraint element");
        incomplete(read(true, Ptc.PRO_DTMPLN_DEF_X, true, null, false, true, true,
                Ptc.PRO_DTMPLN_FLIP_DIR_NO, Ptc.PRO_DTMPLN_FIT_DEFAULT, false, false, true), "duplicate inapplicable elements");
        Map<String, Object> unknownRoot = read(true, Ptc.PRO_DTMPLN_DEF_X, true, null, false, true, true,
                Ptc.PRO_DTMPLN_FLIP_DIR_NO, Ptc.PRO_DTMPLN_FIT_DEFAULT, false, false, false, true);
        require(Boolean.FALSE.equals(unknownRoot.get("complete")), "unknown root tree cannot become complete");
        passed.add("default_without_actual_flip_and_fit_remains_incomplete");

        LocalValue valid = new LocalValue(0, ArgValueType.ARG_V_SELECTION, selection(true));
        incomplete(read(true, Ptc.PRO_DTMPLN_DEF_X, true, valid, false), "populated default reference");
        Map<String, Object> selected = read(true, Ptc.PRO_DTMPLN_THRU, true, valid, false);
        require(Boolean.TRUE.equals(selected.get("complete")) && "TEST_AXIS".equals(first(selected).get("reference")),
                "valid non-default selection must retain its identity");
        passed.add("valid_selection_retains_reference");

        incomplete(read(true, Ptc.PRO_DTMPLN_THRU, true, null, false), "required reference value missing");
        incomplete(read(true, Ptc.PRO_DTMPLN_THRU, false, null, false), "required reference element missing");
        incomplete(read(false, Ptc.PRO_DTMAXIS_CONSTR_TYPE_THRU, true, null, false), "axis reference missing");
        for (int kind : new int[]{Ptc.PRO_DTMPLN_DEF_X, Ptc.PRO_DTMPLN_DEF_Y, Ptc.PRO_DTMPLN_DEF_Z}) {
            incomplete(read(false, kind, true, null, false), "axis must not be classified as default plane");
        }
        incomplete(read(true, Ptc.PRO_DTMPLN_THRU, true, new LocalValue(0, ArgValueType.ARG_V_INTEGER, null), false), "wrong value type");
        incomplete(read(true, Ptc.PRO_DTMPLN_THRU, true, new LocalValue(0, ArgValueType.ARG_V_SELECTION, null), false), "null selection");
        incomplete(read(true, Ptc.PRO_DTMPLN_THRU, true, new LocalValue(0, ArgValueType.ARG_V_SELECTION, selection(false)), false), "null selected item");
        incomplete(read(true, Ptc.PRO_DTMPLN_DEF_X, true, null, true), "ambiguous reference elements");
        passed.add("missing_wrong_or_ambiguous_nondefault_references_remain_incomplete");

        System.out.println(Json.write(Json.map("scope", "synthetic SDK interfaces; no CAD calls", "passed", passed)));
    }
}
