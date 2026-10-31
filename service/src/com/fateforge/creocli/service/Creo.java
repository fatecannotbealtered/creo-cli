package com.fateforge.creocli.service;

import com.ptc.cipjava.jxthrowable;
import com.ptc.pfc.pfcExceptions.XToolkitNotFound;
import com.ptc.pfc.pfcFeature.Feature;
import com.ptc.pfc.pfcGlobal.pfcGlobal;
import com.ptc.pfc.pfcModel.Model;
import com.ptc.pfc.pfcModel.ModelType;
import com.ptc.pfc.pfcModelItem.ModelItem;
import com.ptc.pfc.pfcModelItem.ModelItemType;
import com.ptc.pfc.pfcSelect.Selection;
import com.ptc.pfc.pfcSelect.pfcSelect;
import com.ptc.pfc.pfcSession.Session;
import com.ptc.pfc.pfcSolid.Solid;
import com.ptc.pfc.pfcWindow.Window;
import com.ptc.wfc.wfcElementTree.ElemPathItemType;
import com.ptc.wfc.wfcElementTree.ElemPathItems;
import com.ptc.wfc.wfcElementTree.Elements;
import com.ptc.wfc.wfcElementTree.wfcElementTree;
import com.ptc.wfc.wfcFeatureInstructions.FeatCreateOption;
import com.ptc.wfc.wfcFeatureInstructions.FeatCreateOptions;

import java.io.File;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.regex.Pattern;

/**
 * What every operation needs from Creo: finding models and features by the names a person
 * uses, and reading back what a model holds. Everything here runs on the toolkit thread.
 */
final class Creo {

    /** Creo model names: a letter, then letters, digits, '_' or '-', 31 at most. */
    private static final Pattern MODEL_NAME = Pattern.compile("[A-Za-z][A-Za-z0-9_-]{0,30}");

    private Creo() {
    }

    static Session session() throws jxthrowable {
        return NativeReadTrace.call("pfcGlobal.GetProESession(Creo.session)", pfcGlobal::GetProESession);
    }

    // ------------------------------------------------------------------ names

    /** A model's name split into what Creo looks it up by: base name and type. */
    static final class Name {
        final String base;
        final ModelType type;
        final String extension;

        Name(String base, ModelType type, String extension) {
            this.base = base;
            this.type = type;
            this.extension = extension;
        }

        String fileName() {
            return base.toLowerCase(Locale.ROOT) + "." + extension;
        }
    }

    /**
     * {@code block}, {@code block.prt}, {@code gear.asm}, {@code block.drw} -- or a file
     * name with its version, {@code block.prt.3}. A bare name is a part.
     */
    /**
     * A model's file name as every command uses it: a family instance's is its own, where
     * Creo writes it after its generic's -- pin_6x40<pin>.prt -- and the name is not one a
     * model can be asked for by.
     */
    static String fileName(Model model) throws jxthrowable {
        return model == null ? null : plainName(model.GetFileName());
    }

    static String fileName(com.ptc.pfc.pfcModel.ModelDescriptor descriptor) throws jxthrowable {
        return descriptor == null ? null : plainName(descriptor.GetFileName());
    }

    static String plainName(String name) {
        return name == null ? null : name.replaceFirst("<[^>]*>", "");
    }

    static Name name(String raw) {
        String text = raw.replaceFirst("\\.[0-9]+$", "");
        String lower = text.toLowerCase(Locale.ROOT);
        String[][] kinds = {{"prt", "part"}, {"asm", "assembly"}, {"drw", "drawing"}};
        for (String[] kind : kinds) {
            if (lower.endsWith("." + kind[0])) {
                return checked(text.substring(0, text.length() - 4), kind[0]);
            }
        }
        return checked(text, "prt");
    }

    private static Name checked(String base, String extension) {
        if (!MODEL_NAME.matcher(base).matches()) {
            throw new Failures.Refusal("E_VALIDATION", "'" + base + "' is not a valid Creo model name: start "
                    + "with a letter, then letters, digits, '_' or '-', at most 31 characters");
        }
        ModelType type = "asm".equals(extension) ? ModelType.MDL_ASSEMBLY
                : "drw".equals(extension) ? ModelType.MDL_DRAWING : ModelType.MDL_PART;
        return new Name(base, type, extension);
    }

    /** part, assembly, drawing -- the words the CLI uses, not Creo's enumeration names. */
    static String typeName(ModelType type) {
        if (type == null) {
            return null;
        }
        int value = type.getValue();
        if (value == ModelType._MDL_PART) {
            return "part";
        }
        if (value == ModelType._MDL_ASSEMBLY) {
            return "assembly";
        }
        if (value == ModelType._MDL_DRAWING) {
            return "drawing";
        }
        return enumName(type).toLowerCase(Locale.ROOT);
    }

    // ------------------------------------------------------------------ lookup

    /**
     * The model of that name and type in session, or null.
     *
     * <p>{@code GetModel} documents a null return for a model that is not in session; on
     * Creo 13.4 it throws {@code XToolkitNotFound} instead. Both are handled, so the answer
     * does not depend on which one a given release does.
     */
    static Model find(Session session, Name name) throws jxthrowable {
        try {
            return session.GetModel(name.base, name.type);
        } catch (XToolkitNotFound absent) {
            return null;
        }
    }

    static Model model(Session session, String raw) throws jxthrowable {
        Name name = name(raw);
        Model model = find(session, name);
        if (model == null) {
            // A bare name means a part; say so when what is in session by that name is not one.
            List<String> same = new ArrayList<>();
            com.ptc.pfc.pfcModel.Models all = session.ListModels();
            for (int i = 0; all != null && i < all.getarraysize(); i++) {
                String file = fileName(all.get(i));
                if (file.replaceFirst("\\.[^.]*$", "").equalsIgnoreCase(name.base)) {
                    same.add(file);
                }
            }
            throw new Failures.Refusal("E_NOT_FOUND", "no " + typeName(name.type) + " named " + name.base
                    + " is in session" + (same.isEmpty() ? ""
                    : "; " + String.join(", ", same) + (same.size() == 1 ? " is" : " are")
                            + " -- name it with its extension"));
        }
        return model;
    }

    static Solid solid(Session session, String raw) throws jxthrowable {
        Model model = model(session, raw);
        if (!(model instanceof Solid)) {
            throw new Failures.Refusal("E_VALIDATION", Creo.fileName(model) + " is not a part or assembly");
        }
        return (Solid) model;
    }

    static Solid part(Session session, String raw) throws jxthrowable {
        Model model = model(session, raw);
        if (model.GetType().getValue() != ModelType._MDL_PART) {
            throw new Failures.Refusal("E_VALIDATION", Creo.fileName(model) + " is not a part");
        }
        return (Solid) model;
    }

    /** A feature by the name a person sees, or by its id. */
    static Feature feature(Solid solid, String wanted) throws jxthrowable {
        com.ptc.pfc.pfcFeature.Features all = solid.ListFeaturesByType(Boolean.FALSE, null);
        for (int i = 0; all != null && i < all.getarraysize(); i++) {
            Feature f = all.get(i);
            if (wanted.equalsIgnoreCase(String.valueOf(f.GetName())) || wanted.equals(String.valueOf(f.GetId()))) {
                return f;
            }
        }
        throw new Failures.Refusal("E_NOT_FOUND", "no feature named or numbered " + wanted + " in "
                + Creo.fileName((Model) solid));
    }

    /**
     * Where a sketch goes: a datum plane by name, or a flat face of the part as surface:id --
     * a boss sketched on the face it stands on, as a person clicks the face.
     */
    static Selection sketchPlane(Solid solid, String name) throws jxthrowable {
        if (!name.toLowerCase(Locale.ROOT).startsWith("surface:")) {
            return datumSurface(solid, name);
        }
        ModelItem item = Geometry.item(solid, name);
        if (!(item instanceof com.ptc.pfc.pfcGeometry.Plane)) {
            throw new Failures.Refusal("E_VALIDATION", name + " is not flat: a sketch goes on a datum plane or a "
                    + "flat face");
        }
        return pfcSelect.CreateModelItemSelection(item, null);
    }

    static Selection datumSurface(Solid solid, String name) throws jxthrowable {
        ModelItem item = solid.GetItemByName(ModelItemType.ITEM_SURFACE, name);
        if (item == null) {
            throw new Failures.Refusal("E_NOT_FOUND", "no datum plane named " + name + " in "
                    + Creo.fileName((Model) solid) + "; it has " + datumPlaneNames(solid));
        }
        return pfcSelect.CreateModelItemSelection(item, null);
    }

    /**
     * The datum planes, by the names a person sees in the model tree.
     *
     * <p>Listed as features: a datum plane's surface answers {@code GetItemByName} with the
     * feature's name but reports no name of its own when enumerated. Visible ones only:
     * the internal plane each extrusion carries is listed as no_name, and offering it as
     * somewhere to sketch would be offering nonsense.
     */
    static List<Object> datumPlaneNames(Solid solid) throws jxthrowable {
        List<Object> names = new ArrayList<>();
        com.ptc.pfc.pfcFeature.Features planes =
                solid.ListFeaturesByType(Boolean.TRUE, com.ptc.pfc.pfcFeature.FeatureType.FEATTYPE_DATUM_PLANE);
        for (int i = 0; planes != null && i < planes.getarraysize(); i++) {
            String name = planes.get(i).GetName();
            if (name != null && !name.isEmpty()) {
                names.add(name);
            }
        }
        return names;
    }

    /**
     * The ids of the features a person sees in the model tree, or null when Creo will not
     * list them. Every extrusion built from an element tree brings an internal datum plane
     * with it; it is part of the feature, not something to act on.
     */
    static Set<Integer> visibleFeatureIds(Solid solid) {
        try {
            Set<Integer> ids = new HashSet<>();
            com.ptc.pfc.pfcFeature.Features shown = solid.ListFeaturesByType(Boolean.TRUE, null);
            for (int i = 0; shown != null && i < shown.getarraysize(); i++) {
                ids.add(shown.get(i).GetId());
            }
            return ids;
        } catch (Throwable unreadable) {
            return null;
        }
    }

    /** One feature as every reply lists it. */
    static Map<String, Object> featureRow(Feature f, Set<Integer> visible) throws jxthrowable {
        Integer number = null;
        try {
            number = f.GetNumber();
        } catch (Throwable unnumbered) {
            // Suppressed and unregenerated features have no number.
        }
        return Json.map("id", f.GetId(), "name", f.GetName(), "type", enumName(f.GetFeatType()),
                "status", enumName(f.GetStatus()), "number", number,
                "visible", visible == null ? null : visible.contains(f.GetId()));
    }

    // ------------------------------------------------------------------ read-back

    /**
     * The constant's name for a toolkit enumeration value -- FEATTYPE_PROTRUSION, not the
     * localized label Creo shows a person ("鎷変几" on this machine), which is neither stable
     * nor safe to hand an agent as an identifier.
     */
    static String enumName(Object value) {
        if (value == null) {
            return null;
        }
        try {
            int wanted = (Integer) value.getClass().getMethod("getValue").invoke(value);
            for (java.lang.reflect.Field field : value.getClass().getFields()) {
                if (java.lang.reflect.Modifier.isStatic(field.getModifiers())
                        && field.getType() == value.getClass()
                        && (Integer) value.getClass().getMethod("getValue").invoke(field.get(null)) == wanted) {
                    return field.getName();
                }
            }
            return value.getClass().getSimpleName() + "#" + wanted;
        } catch (Exception unreadable) {
            return String.valueOf(value);
        }
    }

    /** The model's unit system, read from the model rather than inferred from a file name. */
    static Map<String, Object> units(Solid solid) {
        try {
            com.ptc.pfc.pfcUnits.UnitSystem system = solid.GetPrincipalUnits();
            return Json.map(
                    "system", system.GetName(),
                    "length", system.GetUnit(com.ptc.pfc.pfcBase.UnitType.UNIT_LENGTH).GetName(),
                    "mass", system.GetUnit(com.ptc.pfc.pfcBase.UnitType.UNIT_MASS).GetName());
        } catch (Throwable unreadable) {
            return Json.map("error", unreadable.getClass().getSimpleName());
        }
    }

    /**
     * The solid's volume, or why it could not be measured -- never a silent zero. The
     * mass-property call can refuse a part whose density was never set; a density used only
     * where the model has none leaves the volume exact.
     */
    static Map<String, Object> measure(Solid solid) {
        Map<String, Object> firstError;
        try {
            com.ptc.pfc.pfcSolid.MassProperty mass = solid.GetMassProperty(null);
            return Json.map("value", mass.GetVolume(), "mass", mass.GetMass(), "method", "model_density");
        } catch (Throwable failure) {
            firstError = Failures.error(failure);
        }
        try {
            return Json.map("value", solid.GetMassPropertyWithDensity(null,
                    com.ptc.pfc.pfcSolid.MPDensityUse.MP_DENSITY_USE_IF_MISSING, 1.0).GetVolume(),
                    "mass", null, "method", "density_if_missing");
        } catch (Throwable failure) {
            return Json.map("value", null, "error", firstError, "second_error", Failures.error(failure));
        }
    }

    /**
     * Mass properties as the Mass Properties dialog reports them, in the model's units. A
     * part whose material has no density still has an exact volume, area and centre of
     * gravity -- measured with a density used only where the model has none -- and a mass
     * and density of null, not zero.
     */
    static Map<String, Object> massProperties(Solid solid) {
        Map<String, Object> units = units(solid);
        Object length = units.get("length");
        Map<String, Object> out = Json.map("volume", null, "surface_area", null, "mass", null, "density", null,
                "center_of_gravity", null, "units", Json.map("length", length, "mass", units.get("mass"),
                        "volume", length + "^3", "area", length + "^2"));
        com.ptc.pfc.pfcSolid.MassProperty mass = null;
        boolean densityKnown = true;
        try {
            mass = solid.GetMassProperty(null);
        } catch (Throwable noDensity) {
            densityKnown = false;
            try {
                mass = solid.GetMassPropertyWithDensity(null,
                        com.ptc.pfc.pfcSolid.MPDensityUse.MP_DENSITY_USE_IF_MISSING, 1.0);
            } catch (Throwable unmeasured) {
                out.put("error", Failures.error(unmeasured));
                return out;
            }
        }
        try {
            out.put("volume", mass.GetVolume());
            out.put("surface_area", mass.GetSurfaceArea());
            if (densityKnown) {
                out.put("mass", mass.GetMass());
                out.put("density", mass.GetDensity());
            }
            com.ptc.pfc.pfcBase.Point3D cog = mass.GetGravityCenter();
            out.put("center_of_gravity", cog == null ? null : Geometry.point(cog));
        } catch (Throwable unreadable) {
            out.put("error", Failures.error(unreadable));
        }
        return out;
    }

    static Double volumeOf(Map<String, Object> measurement) {
        Object value = measurement.get("value");
        return value instanceof Double ? (Double) value : null;
    }

    /** The solid's bounding box in model units, or why there is none. */
    static Object outline(Solid solid) {
        try {
            com.ptc.pfc.pfcBase.Outline3D box = solid.GetGeomOutline();
            List<Object> corners = new ArrayList<>();
            for (int i = 0; i < 2; i++) {
                com.ptc.pfc.pfcBase.Point3D p = box.get(i);
                corners.add(java.util.Arrays.asList(p.get(0), p.get(1), p.get(2)));
            }
            return corners;
        } catch (Throwable failure) {
            return Json.map("error", Failures.error(failure));
        }
    }

    static List<Object> bodies(Solid solid) {
        List<Object> out = new ArrayList<>();
        try {
            com.ptc.pfc.pfcModelItem.ModelItems items = solid.ListItems(ModelItemType.ITEM_BODY);
            for (int i = 0; items != null && i < items.getarraysize(); i++) {
                out.add(bodyInfo((com.ptc.pfc.pfcSolid.SolidBody) items.get(i)));
            }
        } catch (Throwable unreadable) {
            out.add(Json.map("error", Failures.error(unreadable)));
        }
        return out;
    }

    static Map<String, Object> bodyInfo(com.ptc.pfc.pfcSolid.SolidBody body) {
        if (body == null) {
            return null;
        }
        Map<String, Object> info = Json.map();
        try {
            info.put("id", body.GetId());
            info.put("name", body.GetName());
            info.put("state", enumName(body.GetBodyState()));
        } catch (Throwable unreadable) {
            info.put("error", Failures.error(unreadable));
        }
        return info;
    }

    /**
     * A model Creo keeps in session for its own use, not one anybody opened: the 2D sections
     * (s2d0001.sec, ...) a feature's sketch leaves behind once its tree has been read.
     */
    static boolean internal(Model model) {
        try {
            return model.GetType().getValue() == com.ptc.pfc.pfcModel.ModelType._MDL_2D_SECTION;
        } catch (Throwable unreadable) {
            return false;
        }
    }

    static int surfaceCount(Solid solid) {
        try {
            return surfaces(solid).size();
        } catch (Throwable unreadable) {
            return -1;
        }
    }

    /**
     * Every face of the solid. Measured: ListItems(ITEM_SURFACE) refuses a part of more than
     * one body (XToolkitMultibodyUnsupported in ProSolidSurfaceVisit), so a part a new body
     * was made in is read body by body.
     */
    static List<com.ptc.pfc.pfcGeometry.Surface> surfaces(Solid solid) throws jxthrowable {
        List<com.ptc.pfc.pfcGeometry.Surface> out = new ArrayList<>();
        try {
            com.ptc.pfc.pfcModelItem.ModelItems all = solid.ListItems(ModelItemType.ITEM_SURFACE);
            for (int i = 0; all != null && i < all.getarraysize(); i++) {
                out.add((com.ptc.pfc.pfcGeometry.Surface) all.get(i));
            }
            return out;
        } catch (com.ptc.pfc.pfcExceptions.XToolkitMultibodyUnsupported severalBodies) {
            java.util.Set<Integer> seen = new java.util.HashSet<>();
            com.ptc.pfc.pfcModelItem.ModelItems bodies = solid.ListItems(ModelItemType.ITEM_BODY);
            for (int b = 0; bodies != null && b < bodies.getarraysize(); b++) {
                com.ptc.pfc.pfcGeometry.Surfaces own = ((com.ptc.pfc.pfcSolid.SolidBody) bodies.get(b)).ListSurfaces();
                for (int i = 0; own != null && i < own.getarraysize(); i++) {
                    if (seen.add(own.get(i).GetId())) {
                        out.add(own.get(i));
                    }
                }
            }
            return out;
        }
    }

    /**
     * Where the model was retrieved from, as Creo reports it -- measured on Creo 13.4 as the
     * full path of the version file -- or null for a model that has none.
     */
    static String origin(Model model) {
        Map<String, Object> observed = originInfo(model);
        if (!Boolean.TRUE.equals(observed.get("complete")))
            throw new Failures.Refusal("E_VERIFY_INCOMPLETE", "native GetOrigin failed; storage directory is unproved");
        return (String) observed.get("value");
    }

    /** A successful empty origin is distinct from a failed getter, and proves no saved path. */
    static Map<String, Object> originInfo(Model model) {
        try {
            String origin = model.GetOrigin();
            String value = origin == null || origin.trim().isEmpty() ? null : origin;
            return Json.map("complete", true, "state", value == null ? "no_origin" : "saved",
                    "value", value, "source", "Model.GetOrigin",
                    "new_model_proven", false);
        } catch (Throwable unreadable) {
            return Json.map("complete", false, "state", "unreadable", "value", null,
                    "source", "Model.GetOrigin", "error", Failures.error(unreadable),
                    "new_model_proven", false);
        }
    }

    static Boolean modified(Model model) {
        try {
            return model.GetIsModified();
        } catch (Throwable unreadable) {
            return null;
        }
    }

    static Window window(Session session, Model model) {
        try {
            return session.GetModelWindow(model);
        } catch (Throwable none) {
            return null;
        }
    }

    /** Display a model window. This is not proof of Session.GetCurrentModel activation. */
    static boolean show(Session session, Model model) {
        try {
            session.CreateModelWindow(model);
            model.Display();
            return true;
        } catch (jxthrowable noWindow) {
            return false;
        }
    }

    static void repaint(Session session) {
        try {
            Window window = session.GetCurrentWindow();
            if (window != null) {
                window.Repaint();
            }
        } catch (jxthrowable ignored) {
            // Cosmetic; the model is already correct.
        }
    }

    /**
     * The directory a model is stored into: where it came from, else the working directory.
     * Measured on Creo 13.4: a part opened from a subdirectory is saved back into it.
     */
    static File storeDirectory(Model model, Session session) throws jxthrowable {
        String origin = origin(model);
        if (origin != null) {
            File from = new File(origin);
            File directory = from.isDirectory() ? from : from.getParentFile();
            if (directory != null && directory.isDirectory()) {
                return directory;
            }
        }
        return new File(session.GetCurrentDirectory());
    }

    /** The highest-numbered version Creo wrote: block.prt.3 over block.prt.2. */
    static File newestVersion(File directory, String fileName) {
        File[] candidates = directory.listFiles((dir, n) ->
                n.equalsIgnoreCase(fileName) || n.toLowerCase(Locale.ROOT).startsWith(fileName + "."));
        File best = null;
        int bestVersion = -1;
        if (candidates != null) {
            for (File candidate : candidates) {
                String suffix = candidate.getName().substring(fileName.length());
                int version;
                try {
                    version = suffix.isEmpty() ? 0 : Integer.parseInt(suffix.substring(1));
                } catch (NumberFormatException notAVersion) {
                    version = -1;
                }
                if (version > bestVersion) {
                    bestVersion = version;
                    best = candidate;
                }
            }
        }
        return best;
    }

    // ------------------------------------------------------------------ element trees

    static com.ptc.wfc.wfcElementTree.Element add(Elements elements, int id, com.ptc.pfc.pfcArgument.ArgValue value,
                                                  int level) throws jxthrowable {
        com.ptc.wfc.wfcElementTree.Element element = wfcElementTree.Element_Create(id, value, level);
        elements.append(element);
        return element;
    }

    static FeatCreateOptions options(FeatCreateOption option) throws jxthrowable {
        FeatCreateOptions options = FeatCreateOptions.create();
        options.append(option);
        return options;
    }

    static com.ptc.wfc.wfcElementTree.ElementPath path(int... ids) throws jxthrowable {
        ElemPathItems items = ElemPathItems.create();
        for (int id : ids) {
            items.append(wfcElementTree.ElemPathItem_Create(ElemPathItemType.ELEM_PATH_ITEM_TYPE_ID, id));
        }
        return wfcElementTree.ElementPath_Create(items);
    }

    /**
     * Delete features, and every feature that depends on them, the way Creo 13 accepts.
     *
     * <p>{@code Solid.ExecuteFeatureOps} is deprecated since Creo 4 and answered every delete
     * on Creo 13.4 with {@code XToolkitBadContext} -- including on a freshly opened part --
     * which is why "the native library's features cannot be deleted from Java" looked true
     * for a while. {@code WSolid.DeleteFeatures} is its successor; {@code CLIP} deletes the
     * dependent children with each feature, as PTC recommends over leaving them to fail
     * regeneration.
     */
    static void deleteFeatures(Solid solid, int... ids) throws jxthrowable {
        com.ptc.cipjava.intseq seq = com.ptc.cipjava.intseq.create();
        for (int id : ids) {
            seq.append(id);
        }
        com.ptc.wfc.wfcFeatureInstructions.FeatSuppressOrDeleteOptions options =
                com.ptc.wfc.wfcFeatureInstructions.FeatSuppressOrDeleteOptions.create();
        options.append(com.ptc.wfc.wfcFeatureInstructions.FeatSuppressOrDeleteOption.FEAT_SUPP_OR_DEL_CLIP);
        ((com.ptc.wfc.wfcSolid.WSolid) solid).DeleteFeatures(seq, options,
                com.ptc.wfc.wfcSolidInstructions.wfcSolidInstructions.WRegenInstructions_Create());
    }

    /** Work that may throw anything, for {@link #withConfig}. */
    interface Work<T> {
        T run() throws Exception;
    }

    /**
     * Run with one session config option changed, and put it back however the work ends: an
     * agent's operation must not leave the person's Creo behaving differently afterwards.
     */
    static <T> T withConfig(Session session, String option, String value, Work<T> work) throws Exception {
        return withConfig(session, option, value, "yes", work);
    }

    /** As above; {@code unset} is what to put back when the option had no value before. */
    static <T> T withConfig(Session session, String option, String value, String unset, Work<T> work)
            throws Exception {
        String previous = session.GetConfigOption(option);
        session.SetConfigOption(option, value);
        Throwable workFailure = null;
        try {
            return work.run();
        } catch (Throwable failure) {
            workFailure = failure;
            throw failure;
        } finally {
            try {
                session.SetConfigOption(option, previous == null || previous.isEmpty() ? unset : previous);
            } catch (Throwable failure) {
                if (workFailure != null) failure.addSuppressed(workFailure);
                throw new Failures.Stage("config_restore", failure,
                        Json.map("option", option, "expected", previous == null || previous.isEmpty() ? unset : previous));
            }
        }
    }
}
