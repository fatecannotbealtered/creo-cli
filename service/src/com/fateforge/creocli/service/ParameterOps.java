package com.fateforge.creocli.service;

import com.ptc.cipjava.jxthrowable;
import com.ptc.pfc.pfcModel.Model;
import com.ptc.pfc.pfcModelItem.ParamValue;
import com.ptc.pfc.pfcModelItem.ParamValueType;
import com.ptc.pfc.pfcModelItem.Parameter;
import com.ptc.pfc.pfcModelItem.Parameters;
import com.ptc.pfc.pfcModelItem.pfcModelItem;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/**
 * parameter.list and parameter.set: a model's own parameters -- part number, description,
 * material callouts, the values relations read. Types are kept: a string parameter takes a
 * string, a real one a number, and a value is never coerced from one type to another.
 */
final class ParameterOps {

    private ParameterOps() {
    }

    static Map<String, Object> list(Map<String, Object> request) throws Exception {
        Model model = Creo.model(Creo.session(), Json.string(request, "model"));
        List<Object> rows = new ArrayList<>();
        Parameters all = model.ListParams();
        for (int i = 0; all != null && i < all.getarraysize(); i++) {
            rows.add(row(all.get(i)));
        }
        return Json.map("model", Creo.fileName(model), "parameters", rows);
    }

    static Map<String, Object> row(Parameter p) throws jxthrowable {
        ParamValue value = p.GetValue();
        String units = null;
        try {
            com.ptc.pfc.pfcUnits.Unit unit = p.GetUnits();
            units = unit == null ? null : unit.GetName();
        } catch (Throwable none) {
            // Unitless.
        }
        boolean driven = false;
        try {
            driven = p.GetIsRelationDriven();
        } catch (Throwable unreadable) {
            // Treated as free.
        }
        String description = null;
        try {
            description = p.GetDescription();
        } catch (Throwable none) {
            // No description.
        }
        return Json.map(
                "name", p.GetName(),
                "type", type(value),
                "value", plain(value),
                "units", units,
                "designated", p.GetIsDesignated(),
                "relation_driven", driven,
                "description", description == null || description.isEmpty() ? null : description);
    }

    /** string, integer, boolean, real, note: the parameter types a person picks from. */
    static String type(ParamValue value) throws jxthrowable {
        if (value == null) {
            return null;
        }
        int d = value.Getdiscr().getValue();
        return d == ParamValueType._PARAM_STRING ? "string"
                : d == ParamValueType._PARAM_INTEGER ? "integer"
                : d == ParamValueType._PARAM_BOOLEAN ? "boolean"
                : d == ParamValueType._PARAM_DOUBLE ? "real"
                : d == ParamValueType._PARAM_NOTE ? "note" : Creo.enumName(value.Getdiscr()).toLowerCase(Locale.ROOT);
    }

    static Object plain(ParamValue value) throws jxthrowable {
        if (value == null) {
            return null;
        }
        int d = value.Getdiscr().getValue();
        return d == ParamValueType._PARAM_STRING ? value.GetStringValue()
                : d == ParamValueType._PARAM_INTEGER ? (Object) value.GetIntValue()
                : d == ParamValueType._PARAM_BOOLEAN ? (Object) value.GetBoolValue()
                : d == ParamValueType._PARAM_DOUBLE ? (Object) value.GetDoubleValue()
                : d == ParamValueType._PARAM_NOTE ? (Object) value.GetNoteId() : null;
    }

    /**
     * Set a parameter, or create it when {@code create} is true and it does not exist. The
     * request states the type; an existing parameter of another type is refused rather than
     * converted, and a relation-driven one is refused because the relation would overwrite
     * the value at the next regeneration.
     */
    static Map<String, Object> set(Map<String, Object> request) throws Exception {
        Model model = Creo.model(Creo.session(), Json.string(request, "model"));
        String name = Json.string(request, "name");
        String type = Json.string(request, "type");
        boolean create = Json.bool(request, "create", false);
        ParamValue value = value(type, request.get("value"));
        Parameter existing = null;
        try {
            existing = model.GetParam(name);
        } catch (Throwable absent) {
            // Created below, if asked to.
        }
        Map<String, Object> before = null;
        Parameter p;
        if (existing != null) {
            before = row(existing);
            if (!type.equals(before.get("type"))) {
                throw new Failures.Refusal("E_CONFLICT", "parameter " + name + " is of type " + before.get("type")
                        + ", not " + type + "; a value is never converted between types");
            }
            if (Boolean.TRUE.equals(before.get("relation_driven"))) {
                throw new Failures.Refusal("E_CONFLICT", "parameter " + name
                        + " is driven by a relation, which would overwrite the value");
            }
            existing.SetValue(value);
            p = existing;
        } else if (create) {
            p = model.CreateParam(name, value);
        } else {
            throw new Failures.Refusal("E_NOT_FOUND", "no parameter named " + name + " in " + Creo.fileName(model)
                    + "; set create to make it");
        }
        return Json.map("model", Creo.fileName(model), "parameter", row(p), "before", before,
                "created", existing == null);
    }

    static ParamValue value(String type, Object raw) {
        try {
            switch (type) {
                case "string":
                    if (raw instanceof String) {
                        return pfcModelItem.CreateStringParamValue((String) raw);
                    }
                    break;
                case "integer":
                    if (raw instanceof Double && ((Double) raw) == Math.rint((Double) raw)
                            && Math.abs((Double) raw) <= Integer.MAX_VALUE) {
                        return pfcModelItem.CreateIntParamValue(((Double) raw).intValue());
                    }
                    break;
                case "real":
                    if (raw instanceof Double) {
                        return pfcModelItem.CreateDoubleParamValue((Double) raw);
                    }
                    break;
                case "boolean":
                    if (raw instanceof Boolean) {
                        return pfcModelItem.CreateBoolParamValue((Boolean) raw);
                    }
                    break;
                default:
                    throw new Failures.Refusal("E_VALIDATION", "'type' must be string, integer, real or boolean");
            }
        } catch (jxthrowable failure) {
            throw new IllegalStateException(failure);
        }
        throw new Failures.Refusal("E_VALIDATION", "'value' is not a " + type);
    }
}
