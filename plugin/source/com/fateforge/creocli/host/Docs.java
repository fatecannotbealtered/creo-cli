package com.fateforge.creocli.host;

import com.fateforge.creocli.host.core.HostError;
import com.fateforge.creocli.host.core.Json;
import com.fateforge.creocli.host.core.MainThread;
import com.ptc.cipjava.jxthrowable;
import com.ptc.pfc.pfcFeature.Feature;
import com.ptc.pfc.pfcModel.DefaultModelActionListener;
import com.ptc.pfc.pfcModel.Model;
import com.ptc.pfc.pfcModel.ModelDescriptor;
import com.ptc.pfc.pfcModel.ModelType;
import com.ptc.pfc.pfcModel.Models;
import com.ptc.pfc.pfcModel.pfcModel;
import com.ptc.pfc.pfcModelItem.ParamValue;
import com.ptc.pfc.pfcModelItem.Parameter;
import com.ptc.pfc.pfcSession.Session;
import com.ptc.pfc.pfcSolid.DefaultSolidActionListener;
import com.ptc.pfc.pfcSolid.Solid;
import com.ptc.pfc.pfcWindow.Window;

import java.io.File;
import java.io.InputStream;
import java.nio.file.Files;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/**
 * The documents of the session (DCLI-210, DCLI-211, DCLI-277): every part, assembly and
 * drawing in session, with a revision that moves on every change and every save, and the
 * changes made since the last save -- the tool's own, and a mark when someone else changed
 * the model. Creo's model events move the revision; while the tool itself writes, the events
 * are the tool's, at any other time they are a person's.
 */
final class Docs {
    private final String sessionId;
    private final Map<String, Long> revisions = new HashMap<>();
    private final Map<String, List<Map<String, Object>>> toolChanges = new HashMap<>();
    private final Map<String, Boolean> external = new HashMap<>();
    private final Map<String, Integer> untitled = new HashMap<>();
    /** The version file each model's last save wrote, and the newest version on disk before it. */
    private final Map<String, int[]> lastSave = new HashMap<>();
    private final Map<String, String> lastSaveFile = new HashMap<>();
    private boolean toolWriting;

    Docs(String sessionId) {
        this.sessionId = sessionId;
    }

    // ------------------------------------------------------------------ events

    /** Listen to Creo's model events. Called once, on the main thread. */
    void listen(Session session) throws jxthrowable {
        session.AddActionListener(new DefaultSolidActionListener() {
            @Override
            public void OnAfterRegen(Solid solid, Feature feature, boolean ok) {
                changed(solid);
            }

            @Override
            public void OnAfterFeatureCreate(Solid solid, Feature feature) {
                changed(solid);
            }

            @Override
            public void OnAfterFeatureDelete(Solid solid, int id) {
                changed(solid);
            }
        });
        session.AddActionListener(new DefaultModelActionListener() {
            @Override
            public void OnAfterModelSave(ModelDescriptor descriptor) {
                try {
                    saved(descriptor.GetFileName().replaceFirst("<[^>]*>", "").toLowerCase(Locale.ROOT));
                } catch (Throwable ignored) {
                    // The next documents call still reads the modified flag.
                }
            }

            @Override
            public void OnBeforeParameterModify(Parameter parameter, ParamValue value) {
                try {
                    Object owner = parameter.GetDBParent();
                    if (owner instanceof Model) {
                        changed((Model) owner);
                    }
                } catch (Throwable ignored) {
                    // A parameter of a feature or an item; its model regenerates later.
                }
            }
        });
    }

    private synchronized void changed(Model model) {
        try {
            String id = Creo.fileName(model);
            revisions.merge(id, 1L, Long::sum);
            if (!toolWriting) {
                external.put(id, true);
            }
        } catch (Throwable ignored) {
            // An event about a model we cannot name changes nothing we report.
        }
    }

    private synchronized void saved(String id) {
        revisions.merge(id, 1L, Long::sum);
        toolChanges.remove(id);
        external.remove(id);
    }

    /** Run a write of the tool: the model events it causes are the tool's. */
    synchronized void writing(boolean on) {
        toolWriting = on;
    }

    synchronized void recordToolChanges(String id, List<Map<String, Object>> changes) {
        revisions.merge(id, 1L, Long::sum);
        toolChanges.computeIfAbsent(id, k -> new ArrayList<>()).addAll(changes);
    }

    synchronized List<Map<String, Object>> toolChangesSinceSave(String id) {
        return new ArrayList<>(toolChanges.getOrDefault(id, new ArrayList<>()));
    }

    synchronized boolean changedOutside(String id) {
        return external.getOrDefault(id, false);
    }

    // ------------------------------------------------------------------ the documents

    List<Map<String, Object>> list() throws jxthrowable {
        List<Map<String, Object>> out = new ArrayList<>();
        Models all = Creo.session().ListModels();
        for (int i = 0; all != null && i < all.getarraysize(); i++) {
            Model model = all.get(i);
            if (isDocument(model)) {
                out.add(describe(model));
            }
        }
        return out;
    }

    static boolean isDocument(Model model) {
        try {
            int type = model.GetType().getValue();
            return type == ModelType._MDL_PART || type == ModelType._MDL_ASSEMBLY || type == ModelType._MDL_DRAWING;
        } catch (Throwable unreadable) {
            return false;
        }
    }

    /** The model a request names by document ID. */
    Model model(String id) throws jxthrowable {
        if (id == null) {
            throw new HostError(HostError.VALIDATION, "The call names no document.");
        }
        Models all = Creo.session().ListModels();
        for (int i = 0; all != null && i < all.getarraysize(); i++) {
            Model model = all.get(i);
            if (isDocument(model) && id.equalsIgnoreCase(Creo.fileName(model))) {
                return model;
            }
        }
        throw new HostError(HostError.NOT_FOUND, "No document " + id + " is open in this session.");
    }

    synchronized Map<String, Object> describe(Model model) throws jxthrowable {
        String id = Creo.fileName(model);
        String path = path(model);
        Map<String, Object> doc = new LinkedHashMap<>();
        doc.put("id", id);
        doc.put("path", path);
        if (path == null) {
            doc.put("key", "untitled:" + sessionId + "/" + untitled.computeIfAbsent(id, k -> untitled.size() + 1));
        }
        doc.put("session", sessionId);
        doc.put("kind", Creo.kind(model));
        doc.put("revision", "r" + revisions.getOrDefault(id, 0L));
        Boolean modified;
        try {
            modified = model.GetIsModified();
        } catch (Throwable unreadable) {
            modified = Boolean.TRUE;
        }
        doc.put("dirty", modified);
        doc.put("readonly", false);
        if (path != null) {
            doc.put("disk", disk(model, path));
        }
        return doc;
    }

    /** The target key of a document: file:///<path>, or its untitled: key (DCLI-028). */
    String key(Model model) throws jxthrowable {
        Map<String, Object> doc = describe(model);
        Object path = doc.get("path");
        return path != null ? fileKey((String) path) : (String) doc.get("key");
    }

    static String fileKey(String path) {
        String absolute = new File(path).getAbsolutePath().replace('\\', '/');
        while (absolute.startsWith("/")) {
            absolute = absolute.substring(1);
        }
        return "file:///" + absolute;
    }

    /**
     * Where the model's file is, without Creo's version number: D:\work\bracket.prt. Creo 13.4
     * reports the origin as the full path of the version file it was retrieved from. A model
     * never saved has no origin.
     */
    static String path(Model model) throws jxthrowable {
        String origin;
        try {
            origin = model.GetOrigin();
        } catch (Throwable unreadable) {
            origin = null;
        }
        if (origin == null || origin.trim().isEmpty()) {
            return null;
        }
        String name = Creo.fileName(model);
        File from = new File(origin.trim());
        File dir = from.isDirectory() ? from : from.getParentFile();
        return dir == null ? null : new File(dir, name).getAbsolutePath();
    }

    /** in_sync, changed (someone saved a newer version) or missing (no version is left). */
    static String disk(Model model, String path) {
        File file = new File(path);
        int newest = newestVersion(file);
        if (newest < 0) {
            return "missing";
        }
        Integer loaded = loadedVersion(model);
        return loaded != null && newest > loaded ? "changed" : "in_sync";
    }

    /**
     * The number of the file version the model came from or was last saved to (bracket.prt.3
     * is 3). Model.GetVersion is the PDM version, empty for a plain file (measured on Creo
     * 13.4); the descriptor's file version is the one, and the origin's suffix the fallback.
     */
    static Integer loadedVersion(Model model) {
        try {
            Integer version = model.GetDescr().GetFileVersion();
            if (version != null && version > 0) {
                return version;
            }
        } catch (Throwable unreadable) {
            // Try the origin.
        }
        try {
            String origin = model.GetOrigin();
            java.util.regex.Matcher suffix = java.util.regex.Pattern.compile("\\.([0-9]+)$").matcher(origin == null ? "" : origin.trim());
            if (suffix.find()) {
                return Integer.parseInt(suffix.group(1));
            }
        } catch (Throwable unreadable) {
            // Unknown: treated as in sync, since the file is there.
        }
        return null;
    }

    /** The highest version number of bracket.prt on disk (bracket.prt.3), 0 for an unnumbered file, -1 for none. */
    static int newestVersion(File file) {
        File dir = file.getParentFile();
        String name = file.getName().toLowerCase(Locale.ROOT);
        File[] found = dir == null ? null : dir.listFiles();
        int best = -1;
        for (int i = 0; found != null && i < found.length; i++) {
            String other = found[i].getName().toLowerCase(Locale.ROOT);
            if (!found[i].isFile()) {
                continue;
            }
            if (other.equals(name)) {
                best = Math.max(best, 0);
            } else if (other.startsWith(name + ".") && other.substring(name.length() + 1).matches("[0-9]+")) {
                best = Math.max(best, Integer.parseInt(other.substring(name.length() + 1)));
            }
        }
        return best;
    }

    static File newestFile(File file) {
        int version = newestVersion(file);
        if (version < 0) {
            return null;
        }
        return version == 0 ? file : new File(file.getParentFile(), file.getName() + "." + version);
    }

    // ------------------------------------------------------------------ open, save, close

    Object open(String path) throws jxthrowable {
        File file = new File(path).getAbsoluteFile();
        String name = file.getName().replaceFirst("\\.[0-9]+$", "");
        String lower = name.toLowerCase(Locale.ROOT);
        ModelType type;
        if (lower.endsWith(".prt")) {
            type = ModelType.MDL_PART;
        } else if (lower.endsWith(".asm")) {
            type = ModelType.MDL_ASSEMBLY;
        } else if (lower.endsWith(".drw")) {
            type = ModelType.MDL_DRAWING;
        } else {
            throw new HostError(HostError.UNSUPPORTED, "creo-cli opens .prt, .asm and .drw files; " + file.getName() + " is none of them.");
        }
        File plain = new File(file.getParentFile(), name);
        if (newestVersion(plain) < 0) {
            throw new HostError(HostError.NOT_FOUND, "There is no " + name + " in " + file.getParent() + ".");
        }
        String base = name.substring(0, name.length() - 4);
        Session session = Creo.session();
        Model found = Creo.inSession(session, base, type);
        if (found != null) {
            String there = path(found);
            if (there != null && new File(there).getAbsolutePath().equalsIgnoreCase(plain.getAbsolutePath())) {
                // Open already; it gets a window again if it lost its own (a model an open
                // assembly uses can be in session without one).
                try {
                    if (session.GetModelWindow(found) == null) {
                        session.CreateModelWindow(found);
                        found.Display();
                    }
                } catch (Throwable noWindow) {
                    // The model is open; a window is only for the person.
                }
                return facts("dispatched", "not_applicable", Json.map("document", describe(found)));
            }
            throw HostError.conflict("application_state", "A model named " + name + " from another folder ("
                    + there + ") is already in session; Creo holds one model of a name at a time.").with("knowledge", java.util.List.of("creo-basics"));
        }
        ModelDescriptor descriptor = pfcModel.ModelDescriptor_Create(type, base, null);
        descriptor.SetPath(plain.getParent());
        Model model;
        try {
            model = session.RetrieveModelWithOpts(descriptor, com.ptc.pfc.pfcSession.pfcSession.RetrieveModelOptions_Create());
        } catch (jxthrowable refused) {
            throw new HostError(HostError.NATIVE, "Creo could not open " + plain + ".").nativeMessage(refused.toString());
        }
        try {
            session.CreateModelWindow(model);
            model.Display();
        } catch (Throwable noWindow) {
            // The model is open; a window is only for the person.
            return facts("dispatched", "applied", Json.map("document", describe(model)));
        }
        // Creo builds the new window after this task returns -- in a Creo just started that
        // takes it seconds (measured on Creo 13.4) -- and runs no timer meanwhile. The reply
        // waits for the next tick, so the read-back that follows finds Creo free.
        final Model opened = model;
        return new MainThread.Later(() -> facts("dispatched", "applied", Json.map("document", describe(opened))));
    }

    Map<String, Object> save(Model model) throws Exception {
        String id = Creo.fileName(model);
        String path = path(model);
        if (String.valueOf(model.GetFileName()).contains("<")) {
            throw new HostError(HostError.VALIDATION, id + " is an instance of a family table and has no file of its own; save its generic.");
        }
        int before = path == null ? -1 : newestVersion(new File(path));
        try {
            model.Save();
        } catch (jxthrowable refused) {
            throw new HostError(HostError.NATIVE, "Creo did not save " + id + ".").nativeMessage(refused.toString());
        }
        saved(id);
        String now = path(model);
        if (now != null) {
            int after = newestVersion(new File(now));
            synchronized (this) {
                lastSave.put(id, new int[] {before, after});
                lastSaveFile.put(id, now);
            }
        }
        Map<String, Object> out = facts("dispatched", "not_applicable", Json.map("document", describe(model)));
        out.put("persistence", "saved");
        File written = now == null ? null : newestFile(new File(now));
        if (written != null) {
            List<Object> files = new ArrayList<>();
            files.add(Json.map("path", written.getAbsolutePath(), "bytes", written.length(), "sha256", sha256(written)));
            out.put("files", files);
        }
        if (path == null && now == null) {
            throw new HostError(HostError.NATIVE, "Creo reported no file for " + id + " after the save.", "dispatched");
        }
        return out;
    }

    /**
     * Whether the model's last save reached the disk: it wrote a version newer than the newest
     * before it, the model is tied to that version, and the file is still there.
     */
    synchronized boolean savedToDisk(Model model) throws jxthrowable {
        String id = Creo.fileName(model);
        int[] versions = lastSave.get(id);
        String path = lastSaveFile.get(id);
        if (versions == null || path == null || versions[1] <= versions[0]) {
            return false;
        }
        File plain = new File(path);
        File written = versions[1] == 0 ? plain : new File(plain.getParentFile(), plain.getName() + "." + versions[1]);
        Integer loaded = loadedVersion(model);
        return written.isFile() && (loaded == null || loaded == versions[1]);
    }

    /** Close a model's window, then -- on a later tick, as Creo requires -- erase it from session. */
    Object close(Model model, boolean discard) throws jxthrowable {
        String id = Creo.fileName(model);
        boolean modified;
        try {
            modified = model.GetIsModified();
        } catch (Throwable unreadable) {
            modified = true;
        }
        if (modified && !discard) {
            throw HostError.conflict("unsaved_changes", id + " has unsaved changes; save it, or close it with --discard.");
        }
        Session session = Creo.session();
        // Creo erases no model another model in session uses; refuse before the window closes,
        // so a refused close changes nothing.
        List<String> users = usersOf(session, model);
        if (!users.isEmpty()) {
            throw HostError.conflict("application_state", id + " is used by " + String.join(", ", users)
                    + ", open in Creo; close " + (users.size() == 1 ? "it" : "them") + " first.").with("knowledge", java.util.List.of("creo-basics"));
        }
        Window window = null;
        try {
            window = session.GetModelWindow(model);
        } catch (Throwable none) {
            // No window of its own.
        }
        if (window != null) {
            try {
                window.Close();
            } catch (jxthrowable refused) {
                throw new HostError(HostError.NATIVE, "Creo did not close the window of " + id + ".").nativeMessage(refused.toString());
            }
            return new MainThread.Later(() -> erase(id));
        }
        return erase(id);
    }

    /** The other models in session that use this one: assemblies of it, drawings of it. */
    static List<String> usersOf(Session session, Model model) throws jxthrowable {
        String id = Creo.fileName(model);
        List<String> users = new ArrayList<>();
        com.ptc.pfc.pfcModel.Models all = session.ListModels();
        for (int i = 0; all != null && i < all.getarraysize(); i++) {
            Model other = all.get(i);
            String otherId = Creo.fileName(other);
            if (otherId == null || otherId.equals(id)) {
                continue;
            }
            com.ptc.pfc.pfcModel.Dependencies uses;
            try {
                uses = other.ListDependencies();
            } catch (Throwable unreadable) {
                continue;
            }
            for (int j = 0; uses != null && j < uses.getarraysize(); j++) {
                ModelDescriptor used = uses.get(j).GetDepModel();
                String name = used == null ? null : used.GetFileName();
                if (name != null && id.equalsIgnoreCase(name.replaceFirst("<[^>]*>", ""))) {
                    users.add(otherId);
                    break;
                }
            }
        }
        return users;
    }

    private Map<String, Object> erase(String id) throws jxthrowable {
        Model model;
        try {
            model = model(id);
        } catch (HostError gone) {
            return facts("dispatched", "applied", Json.map());
        }
        try {
            model.Erase();
        } catch (jxthrowable refused) {
            throw new HostError(HostError.NATIVE, id + " stays in session: Creo did not erase it, for example because an open "
                    + "assembly or drawing uses it. Its window is closed.", "dispatched").nativeMessage(refused.toString());
        }
        synchronized (this) {
            toolChanges.remove(id);
            external.remove(id);
            lastSave.remove(id);
            lastSaveFile.remove(id);
        }
        return facts("dispatched", "applied", Json.map());
    }

    static Map<String, Object> facts(String dispatch, String change, Map<String, Object> more) {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("dispatch_state", dispatch);
        out.put("change", change);
        out.put("delivery", "not_applicable");
        out.put("persistence", "unchanged");
        out.putAll(more);
        return out;
    }

    static String sha256(File file) throws Exception {
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        try (InputStream in = Files.newInputStream(file.toPath())) {
            byte[] buffer = new byte[1 << 16];
            int n;
            while ((n = in.read(buffer)) > 0) {
                digest.update(buffer, 0, n);
            }
        }
        StringBuilder hex = new StringBuilder();
        for (byte b : digest.digest()) {
            hex.append(String.format("%02x", b));
        }
        return hex.toString();
    }
}
