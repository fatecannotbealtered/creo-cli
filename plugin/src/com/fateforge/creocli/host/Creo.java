package com.fateforge.creocli.host;

import com.fateforge.creocli.host.core.HostError;
import com.fateforge.creocli.host.core.Json;
import com.ptc.cipjava.jxthrowable;
import com.ptc.pfc.pfcDimension.BaseDimension;
import com.ptc.pfc.pfcExceptions.XToolkitNotFound;
import com.ptc.pfc.pfcFeature.Feature;
import com.ptc.pfc.pfcFeature.Features;
import com.ptc.pfc.pfcGlobal.pfcGlobal;
import com.ptc.pfc.pfcModel.Model;
import com.ptc.pfc.pfcModel.ModelType;
import com.ptc.pfc.pfcModelItem.ModelItemType;
import com.ptc.pfc.pfcModelItem.ModelItems;
import com.ptc.pfc.pfcSession.Session;
import com.ptc.pfc.pfcSolid.Solid;

import java.util.HashSet;
import java.util.Locale;
import java.util.Map;
import java.util.Set;

/**
 * What every command needs from Creo: the session, names, and the objects a command names.
 * Everything here runs on Creo's main thread.
 */
final class Creo {
    private Creo() {
    }

    static Session session() throws jxthrowable {
        return pfcGlobal.GetProESession();
    }

    /** A model's file name as Creo writes it, without a family instance's generic: bracket.prt. */
    static String fileName(Model model) throws jxthrowable {
        String name = model.GetFileName();
        return name == null ? null : name.replaceFirst("<[^>]*>", "").toLowerCase(Locale.ROOT);
    }

    static String kind(Model model) throws jxthrowable {
        int type = model.GetType().getValue();
        return type == ModelType._MDL_PART ? "part" : type == ModelType._MDL_ASSEMBLY ? "assembly"
                : type == ModelType._MDL_DRAWING ? "drawing" : enumName(model.GetType()).toLowerCase(Locale.ROOT);
    }

    static Solid solid(Model model) throws jxthrowable {
        if (!(model instanceof Solid)) {
            throw new HostError(HostError.VALIDATION, fileName(model) + " is a " + kind(model)
                    + "; this command works on parts and assemblies.");
        }
        return (Solid) model;
    }

    /**
     * The constant's name of a toolkit enumeration value -- FEATTYPE_PROTRUSION -- not the
     * localized label Creo shows a person, which is neither stable nor safe as an identifier.
     */
    static String enumName(Object value) {
        if (value == null) {
            return null;
        }
        try {
            int wanted = (Integer) value.getClass().getMethod("getValue").invoke(value);
            for (java.lang.reflect.Field field : value.getClass().getFields()) {
                if (java.lang.reflect.Modifier.isStatic(field.getModifiers()) && field.getType() == value.getClass()
                        && (Integer) value.getClass().getMethod("getValue").invoke(field.get(null)) == wanted) {
                    return field.getName();
                }
            }
            return value.getClass().getSimpleName() + "#" + wanted;
        } catch (Exception unreadable) {
            return String.valueOf(value);
        }
    }

    /** The name without Creo's prefix, lowercase: FEATTYPE_DATUM_PLANE becomes datum_plane. */
    static String shortName(Object value, String prefix) {
        String name = enumName(value);
        if (name == null) {
            return null;
        }
        return (name.startsWith(prefix) ? name.substring(prefix.length()) : name).toLowerCase(Locale.ROOT);
    }

    // ------------------------------------------------------------------ features

    /** The features a person sees in the model tree; internal datums of a feature are left out. */
    static Set<Integer> visibleFeatureIds(Solid solid) throws jxthrowable {
        Set<Integer> ids = new HashSet<>();
        Features shown = solid.ListFeaturesByType(Boolean.TRUE, null);
        for (int i = 0; shown != null && i < shown.getarraysize(); i++) {
            ids.add(shown.get(i).GetId());
        }
        return ids;
    }

    /** A feature by its ID or by the name a person sees. */
    static Feature feature(Solid solid, String wanted) throws jxthrowable {
        Features all = solid.ListFeaturesByType(Boolean.FALSE, null);
        Feature byName = null;
        for (int i = 0; all != null && i < all.getarraysize(); i++) {
            Feature f = all.get(i);
            if (wanted.equals(String.valueOf(f.GetId()))) {
                return f;
            }
            if (byName == null && wanted.equalsIgnoreCase(String.valueOf(f.GetName()))) {
                byName = f;
            }
        }
        if (byName != null) {
            return byName;
        }
        throw new HostError(HostError.NOT_FOUND, "No feature has the ID or name " + wanted + " in " + fileName((Model) solid)
                + "; feature list shows them.");
    }

    static Map<String, Object> featureRow(Feature f) throws jxthrowable {
        Integer number = null;
        try {
            number = f.GetNumber();
        } catch (Throwable unnumbered) {
            // Suppressed and unregenerated features have no number.
        }
        return Json.map("id", f.GetId(), "number", number, "name", f.GetName(),
                "type", shortName(f.GetFeatType(), "FEATTYPE_"), "status", shortName(f.GetStatus(), "FEAT_"));
    }

    // ------------------------------------------------------------------ dimensions

    /** A dimension by its symbol (d12, or a name a person gave it), and the feature that owns it. */
    static Object[] dimension(Solid solid, String wanted) throws jxthrowable {
        Features all = solid.ListFeaturesByType(Boolean.FALSE, null);
        for (int i = 0; all != null && i < all.getarraysize(); i++) {
            Feature f = all.get(i);
            ModelItems dims = f.ListSubItems(ModelItemType.ITEM_DIMENSION);
            for (int j = 0; dims != null && j < dims.getarraysize(); j++) {
                BaseDimension dim = (BaseDimension) dims.get(j);
                if (wanted.equalsIgnoreCase(dim.GetSymbol())) {
                    return new Object[] {dim, f};
                }
            }
        }
        throw new HostError(HostError.NOT_FOUND, "No dimension is named " + wanted + " in " + fileName((Model) solid)
                + "; dimension list shows them.");
    }

    /** Found, or null: GetModel documents null for a model not in session, and Creo 13.4 throws instead. */
    static Model inSession(Session session, String base, ModelType type) throws jxthrowable {
        try {
            return session.GetModel(base, type);
        } catch (XToolkitNotFound absent) {
            return null;
        }
    }
}
