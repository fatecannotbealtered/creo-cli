package com.fateforge.creocli.service;

import com.ptc.cipjava.jxthrowable;
import com.ptc.pfc.pfcModel.Model;
import com.ptc.pfc.pfcPart.Material;
import com.ptc.pfc.pfcPart.Part;
import com.ptc.pfc.pfcSession.Session;
import com.ptc.pfc.pfcSolid.Solid;

import java.io.File;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.nio.file.Files;
import java.security.MessageDigest;

/**
 * material.list and material.assign: Creo's material library, and giving a part one of its
 * materials the way the Materials dialog does, so the part has a density and a mass.
 */
final class Materials {

    /** The config option naming the material library; Creo's own library when unset. */
    private static final String LIBRARY_OPTION = "pro_material_dir";

    private Materials() {
    }

    static File library(Session session) throws jxthrowable {
        String configured = session.GetConfigOption(LIBRARY_OPTION);
        if (configured != null && !configured.trim().isEmpty()) {
            File dir = new File(ModelOps.expand(configured.trim()));
            if (dir.isDirectory()) {
                return dir;
            }
        }
        return new File(new File(ModelOps.creoCommonFiles(), "text"), "materials-library");
    }

    /** Every material file in the library, with the folder it sits in as its category. */
    static List<Map<String, Object>> entries(File root) {
        List<Map<String, Object>> out = new ArrayList<>();
        walk(root, root, out, 0);
        out.sort((a, b) -> String.valueOf(a.get("name")).compareToIgnoreCase(String.valueOf(b.get("name"))));
        return out;
    }

    private static void walk(File root, File dir, List<Map<String, Object>> out, int depth) {
        File[] children = dir.listFiles();
        if (children == null || depth > 6) {
            return;
        }
        for (File child : children) {
            if (child.isDirectory()) {
                walk(root, child, out, depth + 1);
            } else if (child.getName().toLowerCase(Locale.ROOT).endsWith(".mtl")) {
                String name = child.getName().substring(0, child.getName().length() - 4);
                String category = root.toPath().relativize(dir.toPath()).toString().replace('\\', '/');
                out.add(Json.map("name", name, "category", category.isEmpty() ? null : category,
                        "file", child.getPath()));
            }
        }
    }

    static Map<String, Object> list(Map<String, Object> request) throws Exception {
        Session session = Creo.session();
        File root = library(session);
        String filter = Json.string(request, "name", null);
        List<Object> rows = new ArrayList<>();
        for (Map<String, Object> entry : entries(root)) {
            if (filter == null || String.valueOf(entry.get("name")).toLowerCase(Locale.ROOT)
                    .contains(filter.toLowerCase(Locale.ROOT))) {
                rows.add(entry);
            }
        }
        Map<String, Object> out = Json.map("library", root.getPath(), "materials", rows,
                "configuration", Json.map("configured_directory", session.GetConfigOption(LIBRARY_OPTION),
                        "effective_library", root.getCanonicalPath(), "working_directory", session.GetCurrentDirectory()));
        String modelName = Json.string(request, "model", null);
        if (modelName != null) {
            out.put("model", state((Part) Creo.part(session, modelName)));
        }
        return out;
    }

    /** A part's current material, the materials loaded into it, and its mass properties. */
    private static Map<String, Object> observed(String source, Object value, String status) {
        return Json.map("source", source, "status", status, "value", value);
    }

    private static Map<String, Object> unknown(String source, Throwable failure) {
        if (failure instanceof VirtualMachineError) throw (VirtualMachineError) failure;
        if (failure instanceof ThreadDeath) throw (ThreadDeath) failure;
        NativeReadTrace.rethrowFatal(failure);
        return Json.map("source", source, "status", "unknown", "value", null,
                "exception_type", failure.getClass().getName());
    }

    private static Map<String, Object> materialIdentity(Material material) {
        if (material == null) return null;
        String name = PresentationOps.contextRead("Material.GetName(physical observation)", material::GetName);
        return materialIdentity(material, name);
    }

    private static Map<String, Object> materialIdentity(Material material, String name) {
        if (name == null || name.isEmpty()) throw new IllegalStateException("material name unavailable");
        int id = PresentationOps.contextRead("Material.GetId(physical observation)", material::GetId);
        return Json.map("id", id, "name", name);
    }

    private static Map<String, Object> bodyMaterials(Part part) {
        String source = "Solid.ListItems(ITEM_BODY)/WSolidBody.GetMaterial/Material.GetId/GetName";
        try {
            com.ptc.pfc.pfcModelItem.ModelItems bodies = PresentationOps.contextRead(
                    "Solid.ListItems(ITEM_BODY physical observation)",
                    () -> part.ListItems(com.ptc.pfc.pfcModelItem.ModelItemType.ITEM_BODY));
            if (bodies == null) return observed(source, null, "returned_null");
            int count = bodies.getarraysize();
            if (count != 1) return Json.map("source", source, "status", "unsupported_profile",
                    "value", null, "count", count);
            com.ptc.pfc.pfcSolid.SolidBody body = (com.ptc.pfc.pfcSolid.SolidBody) bodies.get(0);
            int id = PresentationOps.contextRead("SolidBody.GetId(physical observation)", body::GetId);
            Material bodyMaterial = PresentationOps.contextRead("WSolidBody.GetMaterial(physical observation)",
                    () -> ((com.ptc.wfc.wfcSolid.WSolidBody) body).GetMaterial());
            Map<String, Object> density;
            try {
                Double value = PresentationOps.contextRead("SolidBody.GetDensity(physical observation)", body::GetDensity);
                density = value == null ? observed("SolidBody.GetDensity", null, "returned_null")
                        : Double.isFinite(value) ? observed("SolidBody.GetDensity", value, "value")
                        : observed("SolidBody.GetDensity", null, "non_finite");
            } catch (Throwable failure) { density = unknown("SolidBody.GetDensity", failure); }
            return observed(source, java.util.List.of(Json.map("id", id,
                    "material", materialIdentity(bodyMaterial), "density", density)), "value");
        } catch (Throwable failure) { return unknown(source, failure); }
    }

    static Map<String, Object> state(Part part) throws jxthrowable {
        final String currentSource = "Part.GetCurrentMaterial/Material.GetId/GetName";
        final String loadedSource = "Part.ListMaterials/Material.GetName";
        final String assignedSource = "Material.GetPropertyValue(MTL_PROP_MASS_DENSITY)";
        Map<String, Object> identity;
        try { identity = observed("Model.GetFileName/GetType/GetOrigin/GetVersionStamp/GetRelationId",
                PresentationOps.targetIdentity(part), "value"); }
        catch (Throwable failure) {
            identity = unknown("Model.GetFileName/GetType/GetOrigin/GetVersionStamp/GetRelationId", failure);
        }
        Map<String, Object> modified;
        try { modified = observed("Model.GetIsModified",
                PresentationOps.contextRead("Model.GetIsModified(physical observation)", part::GetIsModified), "value"); }
        catch (Throwable failure) { modified = unknown("Model.GetIsModified", failure); }
        Material current = null;
        String materialName = null;
        Map<String, Object> currentReading = observed(currentSource, null, "not_read");
        try {
            current = PresentationOps.contextRead("Part.GetCurrentMaterial(physical observation)", part::GetCurrentMaterial);
            if (current == null) currentReading = observed(currentSource, null, "unset");
        } catch (Throwable failure) { currentReading = unknown(currentSource, failure); }
        if (current != null) {
            Material held = current;
            // The legacy name getter remains authoritative even when only the new ID read fails.
            // A name-getter failure retains its original read-failure semantics.
            materialName = PresentationOps.contextRead("Material.GetName(current material)", held::GetName);
            try {
                currentReading = observed(currentSource, materialIdentity(held, materialName), "value");
            } catch (Throwable failure) { currentReading = unknown(currentSource, failure); }
        }
        List<Object> loaded = new ArrayList<>();
        Map<String, Object> loadedReading;
        try {
            com.ptc.pfc.pfcPart.Materials all = PresentationOps.contextRead(
                    "Part.ListMaterials(physical observation)", part::ListMaterials);
            if (all == null) throw new IllegalStateException("native material inventory returned null");
            if (all.getarraysize() > 1000) throw new IllegalStateException("material inventory exceeds bounded profile");
            for (int i = 0; all != null && i < all.getarraysize(); i++) {
                Material member = all.get(i);
                String name = PresentationOps.contextRead("Material.GetName(loaded physical observation)", member::GetName);
                if (name == null || name.isEmpty() || loaded.contains(name))
                    throw new IllegalStateException("material inventory identity incomplete");
                loaded.add(name);
            }
            loaded.sort((a, b) -> ((String) a).compareTo((String) b));
            loadedReading = observed(loadedSource, loaded, "value");
        } catch (Throwable failure) { loadedReading = unknown(loadedSource, failure); }
        Map<String, Object> units = Creo.units((Solid) part);
        String densityUnits = units.get("mass") instanceof String && units.get("length") instanceof String
                ? units.get("mass") + "/" + units.get("length") + "^3" : null;
        Double density = null;
        Object assignedDensity = null;
        String description = null;
        Map<String, Object> densityReading = observed("Material.GetMassDensity", null, "not_read");
        Map<String, Object> assignedReading = observed(assignedSource, null, "not_read");
        if (current != null) {
            Material selected = current;
            try {
                double value = PresentationOps.contextRead("Material.GetMassDensity(physical observation)", selected::GetMassDensity);
                if (Double.isFinite(value)) {
                    density = value;
                    densityReading = observed("Material.GetMassDensity",
                            Json.map("value", value, "units", densityUnits), "value");
                } else densityReading = observed("Material.GetMassDensity", null, "non_finite");
            } catch (Throwable failure) { densityReading = unknown("Material.GetMassDensity", failure); }
            try {
                com.ptc.pfc.pfcPart.MaterialProperty property = PresentationOps.contextRead(
                        "Material.GetPropertyValue(MTL_PROP_MASS_DENSITY physical observation)",
                        () -> selected.GetPropertyValue(com.ptc.pfc.pfcPart.MaterialPropertyType.MTL_PROP_MASS_DENSITY));
                if (property != null) {
                    double value = PresentationOps.contextRead("MaterialProperty.GetValue(physical observation)", property::GetValue);
                    String propertyUnits = PresentationOps.contextRead("MaterialProperty.GetUnits(physical observation)", property::GetUnits);
                    if (Double.isFinite(value)) {
                        assignedDensity = Json.map("value", value, "units", propertyUnits);
                        assignedReading = observed(assignedSource, assignedDensity, "value");
                    } else assignedReading = observed(assignedSource, null, "non_finite");
                } else assignedReading = observed(assignedSource, null, "unset");
            } catch (Throwable failure) { assignedReading = unknown(assignedSource, failure); }
            try { description = selected.GetDescription(); }
            catch (com.ptc.pfc.pfcExceptions.XToolkitNotFound unavailable) { /* legacy optional field */ }
        } else if ("unset".equals(currentReading.get("status"))) {
            densityReading = observed("Material.GetMassDensity", null, "not_applicable");
            assignedReading = observed(assignedSource, null, "not_applicable");
        }
        Map<String, Object> physical = Json.map("schema", "part_material_physical.v1",
                "identity", identity, "modified", modified, "current_material", currentReading,
                "loaded_materials", loadedReading, "model_units", units,
                "body_materials", bodyMaterials(part),
                "density", densityReading, "assigned_density", assignedReading);
        return Json.map(
                "model", Creo.fileName(part),
                "material", materialName,
                "density", density == null ? null : Json.map("value", density,
                        "units", units.get("mass") + "/" + units.get("length") + "^3"),
                "loaded", loaded,
                "assigned_density", assignedDensity,
                "description", description,
                "physical_observation", physical,
                "mass_properties", Creo.massProperties((Solid) part));
    }

    static Map<String, Object> source(File file) throws Exception {
        if (!file.isFile() || !file.getName().toLowerCase(Locale.ROOT).endsWith(".mtl"))
            throw new Failures.Refusal("E_NOT_FOUND", "material source is not a modern .mtl file");
        if (file.length() > 1024 * 1024) throw new Failures.Refusal("E_VALIDATION", "material file exceeds 1 MiB");
        byte[] bytes = Files.readAllBytes(file.toPath());
        byte[] digest = MessageDigest.getInstance("SHA-256").digest(bytes);
        StringBuilder hex = new StringBuilder();
        for (byte value : digest) hex.append(String.format("%02x", value & 255));
        return Json.map("path", file.getCanonicalPath(), "size_bytes", bytes.length, "sha256", hex.toString());
    }

    /**
     * Assign a material from the library by name. Creo retrieves a material file only from
     * the working directory or the library directory itself, not from the library's
     * subfolders, so the library option is pointed at the file's own folder for the length
     * of the retrieval and put back afterwards.
     */
    static Map<String, Object> assign(Map<String, Object> request) throws Exception {
        Session session = Creo.session();
        Part part = (Part) Creo.part(session, Json.string(request, "model"));
        String wanted = Json.string(request, "material");
        File root = library(session);
        List<Map<String, Object>> matches = new ArrayList<>();
        for (Map<String, Object> entry : entries(root)) {
            if (wanted.equalsIgnoreCase(String.valueOf(entry.get("name")))) {
                matches.add(entry);
            }
        }
        String explicit = Json.string(request, "file", null);
        if (matches.isEmpty() && explicit == null) {
            throw new Failures.Refusal("E_NOT_FOUND", "no material named " + wanted + " in the library at " + root
                    + "; material list shows what there is");
        }
        if (matches.size() > 1 && explicit == null) {
            List<Object> where = new ArrayList<>();
            for (Map<String, Object> m : matches) {
                where.add(m.get("category"));
            }
            throw new Failures.Refusal("E_CONFLICT", "the library holds " + matches.size() + " materials named "
                    + wanted + ", in " + where + "; the name is ambiguous");
        }
        Map<String, Object> before = state(part);
        File file = new File(explicit == null ? String.valueOf(matches.get(0).get("file")) : explicit);
        String name = file.getName().replaceFirst("(?i)\\.mtl$", "");
        if (!name.equalsIgnoreCase(wanted)) throw new Failures.Refusal("E_VALIDATION", "material name does not match file");
        Map<String, Object> bound = source(file);
        if (!String.valueOf(bound.get("sha256")).equals(Json.string(request, "source_sha256")))
            throw new Failures.Refusal("E_CONFLICT", "material source differs from the authorized bytes");
        File shadow = new File(session.GetCurrentDirectory(), name + ".mtl");
        if (shadow.isFile() && !shadow.getCanonicalFile().equals(file.getCanonicalFile()))
            throw new Failures.Refusal("E_CONFLICT", "a working-directory material shadows the authorized source");
        // The OTK filename argument is a bounded name, not a long absolute path.
        // Scope retrieval to the exact parent; the existing helper reports restoration failures.
        String beforeDirectory = session.GetConfigOption(LIBRARY_OPTION);
        Material material = Creo.withConfig(session, LIBRARY_OPTION, file.getParent(), root.getPath(),
                () -> part.RetrieveMaterial(name));
        String afterDirectory = session.GetConfigOption(LIBRARY_OPTION);
        if (!library(session).getCanonicalFile().equals(root.getCanonicalFile()))
            throw new Failures.Refusal("E_VERIFY_INCOMPLETE", "material library directory was not restored");
        part.SetCurrentMaterial(material);
        Map<String, Object> afterSource = source(file);
        if (!bound.equals(afterSource)) throw new Failures.Refusal("E_VERIFY_INCOMPLETE", "material source changed during native retrieval");
        return Json.map("model", Creo.fileName((Model) part), "before", before, "after", state(part),
                "category", explicit == null ? matches.get(0).get("category") : null,
                "source", afterSource, "session_config_restored", true,
                "material_directory_before", beforeDirectory, "material_directory_after", afterDirectory);
    }
}
