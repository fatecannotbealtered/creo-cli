package com.fateforge.creocli.service;

import com.ptc.cipjava.jxthrowable;
import com.ptc.pfc.pfcGlobal.pfcGlobal;
import com.ptc.pfc.pfcModel.Model;
import com.ptc.pfc.pfcModel.ModelType;
import com.ptc.pfc.pfcModel.pfcModel;
import com.ptc.pfc.pfcSession.Session;
import com.ptc.pfc.pfcSolid.Solid;
import com.ptc.pfc.pfcWindow.Window;

import java.io.File;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.regex.Pattern;

/** The life of a model: create, open, save, close, and what it holds. */
final class ModelOps {
    static Map<String, Object> regenerate(Map<String, Object> request) throws Exception {
        Solid solid = Creo.solid(Creo.session(), Json.string(request, "model"));
        com.ptc.wfc.wfcSolidInstructions.WRegenInstructions how =
                com.ptc.wfc.wfcSolidInstructions.wfcSolidInstructions.WRegenInstructions_Create();
        how.SetUndoIfFail(true);
        how.SetNoResolveMode(true);
        ((com.ptc.wfc.wfcSolid.WSolid) solid).WRegenerate(how);
        return Json.map("model", Creo.fileName((Model) solid),
                "regeneration_check", Dimensions.regenerationCheck(solid));
    }

    /** The config option a person's File > New > Part is driven by. */
    private static final String PART_TEMPLATE_OPTION = "template_solidpart";
    private static final String ASSEMBLY_TEMPLATE_OPTION = "template_designasm";

    private ModelOps() {
    }

    // ------------------------------------------------------------------ model.list

    static Map<String, Object> list(Map<String, Object> request) throws Exception {
        Session session = Creo.session();
        Model current = null;
        try {
            current = session.GetCurrentModel();
        } catch (Throwable none) {
            // Nothing is current.
        }
        List<Object> rows = new ArrayList<>();
        com.ptc.pfc.pfcModel.Models open = session.ListModels();
        for (int i = 0; open != null && i < open.getarraysize(); i++) {
            Model model = open.get(i);
            if (Creo.internal(model)) {
                continue;
            }
            rows.add(Json.map(
                    "model", Creo.fileName(model),
                    "type", Creo.typeName(model.GetType()),
                    "modified", Creo.modified(model),
                    "origin", Creo.origin(model),
                    "displayed", Creo.window(session, model) != null,
                    "active", current != null && Creo.fileName(current).equalsIgnoreCase(Creo.fileName(model))));
        }
        return Json.map("models", rows);
    }

    // ------------------------------------------------------------------ part.create

    /**
     * A new part, made the way File > New > Part makes one: copied from a template, so it
     * arrives with the datum planes, coordinate system, units and parameters a person would
     * get. {@code BaseSession.CreatePart} would be one call and produces a part with no
     * datums at all. {@code CopyAndRetrieve} writes {@code name.prt.1} into the working
     * directory at once, unlike File > New.
     */
    static Map<String, Object> createPart(Map<String, Object> request) throws Exception {
        return create(request, false);
    }

    static Map<String, Object> createAssembly(Map<String, Object> request) throws Exception {
        return create(request, true);
    }

    private static Map<String, Object> create(Map<String, Object> request, boolean assembly) throws Exception {
        String raw = Json.string(request, "name");
        Creo.Name name = Creo.name(assembly && !raw.contains(".") ? raw + ".asm" : raw);
        ModelType type = assembly ? ModelType.MDL_ASSEMBLY : ModelType.MDL_PART;
        String kind = assembly ? "assembly" : "part";
        if (name.type.getValue() != type.getValue()) {
            throw new Failures.Refusal("E_VALIDATION", kind + ".create makes " + kind + "s; '" + name.fileName()
                    + "' names another type");
        }
        Session session = Creo.session();
        if (Creo.find(session, name) != null) {
            throw new Failures.Refusal("E_CONFLICT", "a " + kind + " named " + name.base + " is already in session");
        }
        String template = template(session, request, assembly);
        Creo.Name templateName = Creo.name(new File(template).getName());
        boolean templateWasInSession = Creo.find(session, templateName) != null;
        // RetrieveModel ignores the descriptor's path -- PTC's method index says so -- and
        // looks only in the working directory and search path; a template lives elsewhere.
        com.ptc.pfc.pfcModel.ModelDescriptor descriptor =
                pfcModel.ModelDescriptor_Create(type, templateName.base, null);
        descriptor.SetPath(new File(template).getParent());
        Model source = session.RetrieveModelWithOpts(descriptor,
                com.ptc.pfc.pfcSession.pfcSession.RetrieveModelOptions_Create());
        Model part = source.CopyAndRetrieve(name.base, null);
        if (!templateWasInSession) {
            try {
                source.Erase(); // retrieving the template was our doing; leave no litter
            } catch (jxthrowable ignored) {
                // Still referenced by something; harmless to leave.
            }
        }
        boolean shown = Json.bool(request, "display", true) && Creo.show(session, part);
        return Json.map(
                "model", Creo.fileName(part),
                "template", template,
                "units", Creo.units((Solid) part),
                "datum_planes", Creo.datumPlaneNames((Solid) part),
                "displayed", shown,
                "working_directory", session.GetCurrentDirectory(),
                "origin", Creo.origin(part),
                "modified", Creo.modified(part));
    }

    /**
     * Which template to copy. The caller must choose; there is no silent default. The Creo
     * this was built against is configured with an inch template, so "a new part" is an
     * inch part, and a 40 x 20 x 10 request would give a block a metre long whose volume
     * then checks out perfectly because the numbers agree in the model's own units.
     */
    private static String template(Session session, Map<String, Object> request, boolean assembly) throws jxthrowable {
        String path = Json.string(request, "template", null);
        String units = Json.string(request, "units", null);
        if ((path == null) == (units == null)) {
            throw new Failures.Refusal("E_VALIDATION", "give exactly one of 'units' (mmns, inlbs, session_default) "
                    + "or 'template' (a path)");
        }
        if (path == null) {
            switch (units) {
                case "mmns":
                case "inlbs":
                    path = new File(new File(creoCommonFiles(), "templates"),
                            units + (assembly ? "_asm_design_abs.asm" : "_part_solid_abs.prt")).getPath();
                    break;
                case "session_default":
                    String option = assembly ? ASSEMBLY_TEMPLATE_OPTION : PART_TEMPLATE_OPTION;
                    path = session.GetConfigOption(option);
                    if (path == null || path.trim().isEmpty()) {
                        throw new Failures.Refusal("E_CONFIG", option + " is not set in this Creo session");
                    }
                    break;
                default:
                    throw new Failures.Refusal("E_VALIDATION", "'units' must be mmns, inlbs or session_default");
            }
        }
        path = expand(path.trim());
        if (!new File(path).isFile()) {
            throw new Failures.Refusal("E_NOT_FOUND", "template " + path + " does not exist");
        }
        return path;
    }

    /** Config values keep Creo's variables unexpanded: {@code $PRO_DIRECTORY\templates\...}. */
    static String expand(String value) {
        String common = creoCommonFiles().getPath();
        String out = value.replace("${PRO_DIRECTORY}", common).replace("$PRO_DIRECTORY", common);
        java.util.regex.Matcher variable = Pattern.compile("\\$\\{?([A-Za-z_][A-Za-z0-9_]*)\\}?").matcher(out);
        StringBuilder expanded = new StringBuilder();
        while (variable.find()) {
            String replacement = System.getenv(variable.group(1));
            variable.appendReplacement(expanded, java.util.regex.Matcher.quoteReplacement(
                    replacement == null ? variable.group() : replacement));
        }
        variable.appendTail(expanded);
        return expanded.toString();
    }

    /**
     * The installation's Common Files directory, which Creo calls PRO_DIRECTORY. Found from
     * where {@code otk.jar} was loaded, since Creo does not reliably pass the environment
     * to the JVM it starts.
     */
    static File creoCommonFiles() {
        String fromEnvironment = System.getenv("PRO_DIRECTORY");
        if (fromEnvironment != null && new File(fromEnvironment, "templates").isDirectory()) {
            return new File(fromEnvironment);
        }
        try {
            java.net.URL jar = pfcGlobal.class.getProtectionDomain().getCodeSource().getLocation();
            return new File(jar.toURI()).getParentFile().getParentFile().getParentFile();
        } catch (Exception unknown) {
            throw new Failures.Refusal("E_CONFIG", "cannot locate the Creo installation from inside the session: " + unknown);
        }
    }

    // ------------------------------------------------------------------ model.open

    /**
     * Bring an existing model into session, as File > Open does. Creo opens the newest
     * version in the file's directory, whichever version is named.
     */
    static Map<String, Object> open(Map<String, Object> request) throws Exception {
        File file = new File(Json.string(request, "path"));
        if (!file.isFile()) {
            throw new Failures.Refusal("E_NOT_FOUND", file + " does not exist");
        }
        Creo.Name name = Creo.name(file.getName());
        Session session = Creo.session();
        String instance = Json.string(request, "instance", null);
        Model found = Creo.find(session, name);
        if (found != null && instance == null) {
            throw new Failures.Refusal("E_CONFLICT", name.fileName() + " is already in session");
        }
        Model model = found;
        boolean genericOpened = false;
        if (model == null) {
            com.ptc.pfc.pfcModel.ModelDescriptor descriptor = pfcModel.ModelDescriptor_Create(name.type, name.base, null);
            descriptor.SetPath(file.getAbsoluteFile().getParent());
            model = session.RetrieveModelWithOpts(descriptor,
                    com.ptc.pfc.pfcSession.pfcSession.RetrieveModelOptions_Create());
            genericOpened = instance != null;
        }
        if (instance != null) {
            if (!(model instanceof Solid)) {
                throw new Failures.Refusal("E_VALIDATION", name.fileName() + " is not a part or assembly");
            }
            // As File > Open asks which instance of a generic: the file is the generic's.
            try {
                model = Families.open(session, (Solid) model, instance);
            } catch (Exception failure) {
                if (!genericOpened) {
                    throw failure;
                }
                Failures.Stage stage = new Failures.Stage("instance", failure);
                try {
                    model.Erase();
                    stage.cleanup = "the generic put away again";
                } catch (Throwable left) {
                    stage.cleanup = "the generic left in session";
                }
                throw stage;
            }
        }
        boolean shown = Json.bool(request, "display", true) && Creo.show(session, model);
        Map<String, Object> described = summary(session, model);
        described.put("displayed", shown);
        if (instance != null) {
            described.put("generic_opened", genericOpened);
        }
        return described;
    }

    // ------------------------------------------------------------------ model.import

    /**
     * A part or assembly made from an exchange file -- STEP, IGES, Parasolid -- under a new
     * name, as File > Import > New Model does; for STEP and IGES Creo says which of the two
     * the file holds. It lives in session until saved into the working directory.
     */
    static Map<String, Object> importModel(Map<String, Object> request) throws Exception {
        File file = new File(Json.string(request, "path"));
        if (!file.isFile()) {
            throw new Failures.Refusal("E_NOT_FOUND", file + " does not exist");
        }
        String format = Json.string(request, "format");
        com.ptc.pfc.pfcImport.NewModelImportType kind;
        switch (format) {
            case "step":
                kind = com.ptc.pfc.pfcImport.NewModelImportType.IMPORT_NEW_STEP;
                break;
            case "iges":
                kind = com.ptc.pfc.pfcImport.NewModelImportType.IMPORT_NEW_IGES;
                break;
            case "parasolid":
                kind = com.ptc.pfc.pfcImport.NewModelImportType.IMPORT_NEW_PARASOLID;
                break;
            default:
                throw new Failures.Refusal("E_VALIDATION", "'format' is step, iges or parasolid");
        }
        String name = Json.string(request, "name");
        Session session = Creo.session();
        ModelType type;
        String asked = Json.string(request, "type", null);
        if ("part".equals(asked)) {
            type = ModelType.MDL_PART;
        } else if ("assembly".equals(asked)) {
            type = ModelType.MDL_ASSEMBLY;
        } else {
            type = session.GetImportSourceType(file.getPath(), kind);
        }
        if (type.getValue() != ModelType._MDL_PART && type.getValue() != ModelType._MDL_ASSEMBLY) {
            throw new Failures.Refusal("E_UNSUPPORTED", "the file holds a " + Creo.typeName(type)
                    + "; a part or an assembly is imported");
        }
        Creo.Name made = Creo.name(name + (type.getValue() == ModelType._MDL_ASSEMBLY ? ".asm" : ".prt"));
        if (Creo.find(session, made) != null) {
            throw new Failures.Refusal("E_CONFLICT", made.fileName() + " is already in session");
        }
        Model model = session.ImportNewModel(file.getPath(), kind, type, name, null);
        Creo.show(session, model);
        Map<String, Object> out = summary(session, model);
        out.put("imported", Json.map("path", file.getPath(), "format", format));
        return out;
    }

    // ------------------------------------------------------------------ model.save

    /**
     * Save, and report the file found on disk afterwards, looked for where the model came
     * from: Creo stores a model back into the directory it was retrieved from, not into
     * the working directory, and writes a new version on every save.
     */
    static Map<String, Object> save(Map<String, Object> request) throws Exception {
        Session session = Creo.session();
        Model model = Creo.model(session, Json.string(request, "model"));
        String generic = model instanceof Solid ? Families.genericOf((Solid) model) : null;
        if (generic != null) {
            throw new Failures.Refusal("E_VALIDATION", Creo.fileName(model) + " is an instance of " + generic
                    + "'s family table and has no file of its own; save " + generic);
        }
        model.Save();
        File directory = Creo.storeDirectory(model, session);
        File written = Creo.newestVersion(directory, Creo.fileName(model).toLowerCase(java.util.Locale.ROOT));
        return Json.map(
                "model", Creo.fileName(model),
                "directory", directory.getAbsolutePath(),
                "file", written == null ? null : written.getAbsolutePath(),
                "file_bytes", written == null ? null : written.length(),
                "on_disk", written != null,
                "origin", Creo.origin(model),
                "modified", Creo.modified(model));
    }

    // ------------------------------------------------------------------ model.set-common-name

    /** A model's common name, or null where Creo gives none. */
    static String commonName(Model model) throws jxthrowable {
        String name = model.GetCommonName();
        return name == null || name.isEmpty() ? null : name;
    }

    static Map<String, Object> commonNameState(Model model) {
        Map<String, Object> result = Json.map("readable", false, "value", null, "modifiable", null,
                "source", "Model.GetCommonName/IsCommonNameModifiable");
        try { result.put("value", commonName(model)); result.put("readable", true); }
        catch (Throwable unreadable) { result.put("name_error", Failures.error(unreadable)); }
        try { result.put("modifiable", model.IsCommonNameModifiable()); }
        catch (Throwable unreadable) { result.put("modifiable_error", Failures.error(unreadable)); }
        return result;
    }

    /**
     * The name a part or assembly goes by beside its file name -- what Creo's parts list
     * shows in its DESCRIPTION column (asm.mbr.ptc_common_name), as File > Prepare > Model
     * Properties sets it. Refused where Creo keeps it unchangeable.
     */
    static Map<String, Object> setCommonName(Map<String, Object> request) throws Exception {
        Model model = Creo.model(Creo.session(), Json.string(request, "model"));
        if (!(model instanceof Solid)) {
            throw new Failures.Refusal("E_VALIDATION", Creo.fileName(model) + " is not a part or assembly");
        }
        String name = Json.string(request, "name");
        Map<String, Object> nameState = commonNameState(model);
        if (!Boolean.TRUE.equals(nameState.get("readable")) || !(nameState.get("modifiable") instanceof Boolean))
            throw new Failures.Refusal("E_VERIFY_INCOMPLETE", "native common-name or modifiability getter failed; setter refused");
        if (!Boolean.TRUE.equals(nameState.get("modifiable"))) {
            throw new Failures.Refusal("E_CONFLICT", Creo.fileName(model) + "'s common name cannot be changed: "
                    + "Creo keeps it, as it does for a family instance or a model a PDM system owns");
        }
        String before = (String) nameState.get("value");
        model.SetCommonName(name);
        return Json.map("model", Creo.fileName(model), "common_name", commonName(model), "before", before,
                "modified", Creo.modified(model));
    }

    // ------------------------------------------------------------------ model.close / discard

    /**
     * Close the model's window and erase it from session, as a person closing a file does.
     * A model with unsaved changes is refused unless the caller discards them; a model
     * another model in session still uses cannot be erased, and Creo says so.
     */
    static Map<String, Object> close(Map<String, Object> request, boolean discard) throws Exception {
        Session session = Creo.session();
        Model model = Creo.model(session, Json.string(request, "model"));
        String fileName = Creo.fileName(model);
        Boolean modified = Creo.modified(model);
        if (modified == null) throw new Failures.Refusal("E_VERIFY_INCOMPLETE", "modified state is unknown; close/discard refused");
        boolean unsaved = modified;
        if (unsaved && !discard) {
            throw new Failures.Refusal("E_CONFLICT", fileName + " holds unsaved changes; save it first, or "
                    + "discard them");
        }
        boolean windowClosed = false;
        Object closeFailure = null;
        Window window;
        try { window = session.GetModelWindow(model); }
        catch (com.ptc.pfc.pfcExceptions.XToolkitNotFound absent) { window = null; }
        catch (Throwable unreadable) { throw new Failures.Refusal("E_VERIFY_INCOMPLETE", "target window could not be observed"); }
        if (!discard && window != null)
            throw new Failures.Refusal("E_UNSUPPORTED", "a model with a window must use the named deferred model.close lifecycle; Window.Close must return control to Creo before model erase");
        if (window != null) {
            try {
                window.Close();
                windowClosed = true;
            } catch (jxthrowable failure) {
                // Keep the actual diagnostic. It does not prove an absent/base window.
                closeFailure = Failures.error(failure);
            }
        }
        try { model.Erase(); }
        catch (Throwable failed) {
            throw new Failures.Stage("model_erase", failed,
                    Json.map("model", fileName, "window_close_reported", windowClosed,
                            "window_close_error", closeFailure, "erase_reported", false));
        }
        return Json.map("model", fileName, "window_closed", windowClosed, "erased", true,
                "window_close_error", closeFailure, "discarded_changes", unsaved && discard);
    }

    // ------------------------------------------------------------------ model.show

    static Map<String, Object> show(Map<String, Object> request) throws Exception {
        Session session = Creo.session();
        return summary(session, Creo.model(session, Json.string(request, "model")));
    }

    /** What a model holds, by type. */
    static Map<String, Object> summary(Session session, Model model) throws Exception {
        int type = model.GetType().getValue();
        if (type == ModelType._MDL_DRAWING) {
            return drawing(model);
        }
        Solid solid = (Solid) model;
        Map<String, Object> nameState = commonNameState(model);
        Map<String, Object> originState = Creo.originInfo(model);
        Set<Integer> visible = Creo.visibleFeatureIds(solid);
        Map<String, Object> out = Json.map(
                "model", Creo.fileName(model),
                "type", Creo.typeName(model.GetType()),
                "units", Creo.units(solid),
                "material", material(model),
                "mass_properties", Creo.massProperties(solid),
                "bbox", Creo.outline(solid),
                "bodies", Creo.bodies(solid),
                "datum_planes", Creo.datumPlaneNames(solid),
                "cross_sections", Views.crossSections(solid),
                "tolerance_standard", Dimensions.toleranceStandard(solid, null),
                "tolerance_class", Dimensions.modelClass(solid),
                "common_name", nameState.get("value"), "common_name_readback", nameState,
                "family", Families.info(solid),
                "feature_count", visible == null ? null : visible.size(),
                "origin", originState.get("value"), "origin_readback", originState,
                "modified", Creo.modified(model));
        if (type == ModelType._MDL_ASSEMBLY) {
            out.put("components", components(solid));
            out.put("exploded_states", Assemblies.explodedStates((com.ptc.pfc.pfcAssembly.Assembly) solid));
            out.put("explosion", Assemblies.explosion(session, (com.ptc.pfc.pfcAssembly.Assembly) solid));
        }
        return out;
    }

    private static Object material(Model model) {
        if (!(model instanceof com.ptc.pfc.pfcPart.Part)) {
            return null;
        }
        try {
            com.ptc.pfc.pfcPart.Material material = ((com.ptc.pfc.pfcPart.Part) model).GetCurrentMaterial();
            return material == null ? null : material.GetName();
        } catch (Throwable none) {
            return null;
        }
    }

    /** Top-level components: feature id and the model each one places. */
    static List<Object> components(Solid assembly) throws jxthrowable {
        List<Object> rows = new ArrayList<>();
        com.ptc.pfc.pfcFeature.Features found =
                assembly.ListFeaturesByType(Boolean.TRUE, com.ptc.pfc.pfcFeature.FeatureType.FEATTYPE_COMPONENT);
        for (int i = 0; found != null && i < found.getarraysize(); i++) {
            com.ptc.pfc.pfcComponentFeat.ComponentFeat component = (com.ptc.pfc.pfcComponentFeat.ComponentFeat) found.get(i);
            String placed = null;
            try {
                placed = Creo.fileName(component.GetModelDescr()).toLowerCase(java.util.Locale.ROOT);
            } catch (Throwable unreadable) {
                // Reported as null.
            }
            rows.add(Assemblies.row(component, placed));
        }
        return rows;
    }

    private static Map<String, Object> drawing(Model model) throws jxthrowable {
        return Drawings.summary((com.ptc.pfc.pfcModel2D.Model2D) model);
    }
}
