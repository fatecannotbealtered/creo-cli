package com.fateforge.creocli.service;

import com.ptc.pfc.pfcBase.ColorRGB;
import com.ptc.pfc.pfcBase.pfcBase;
import com.ptc.pfc.pfcExceptions.XToolkitNotExist;
import com.ptc.pfc.pfcModel.Model;
import com.ptc.pfc.pfcSelect.Selection;
import com.ptc.pfc.pfcSelect.pfcSelect;
import com.ptc.wfc.wfcDisplay.Appearance;
import com.ptc.wfc.wfcDisplay.Textures;
import com.ptc.wfc.wfcDisplay.Texture;
import com.ptc.wfc.wfcDisplay.TexturePlacement;
import com.ptc.wfc.wfcDisplay.wfcDisplay;
import com.ptc.wfc.wfcSelect.WSelection;
import com.ptc.wfc.wfcSolid.ItemAppearanceAndTextures;
import com.ptc.wfc.wfcSolid.ItemAppearanceAndTexturesSeq;
import com.ptc.wfc.wfcSolid.WSolid;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;

/** Whole source-part cosmetic appearance. Never a material or occurrence override. */
final class AppearanceOps {
    private AppearanceOps() { }

    static Map<String, Object> get(Map<String, Object> request) throws Exception {
        Model model = (Model) Creo.part(Creo.session(), Json.string(request, "model"));
        WSelection selection = (WSelection) pfcSelect.CreateModelSelection(model);
        Model selectionModel = selection.GetSelModel();
        Appearance appearance = visible(selection);
        List<Object> assignments = new ArrayList<>();
        ItemAppearanceAndTexturesSeq applied = ((WSolid) model).GetAllAppearancesAndTextures();
        for (int i = 0; applied != null && i < applied.getarraysize(); i++) {
            ItemAppearanceAndTextures value = applied.get(i);
            Selection where = value.GetSelection();
            Model assignmentModel = where.GetSelModel();
            com.ptc.pfc.pfcModelItem.ModelItem item = where.GetSelItem();
            Textures textures = value.GetTextures();
            List<Object> textureRows = new ArrayList<>();
            for (int t = 0; textures != null && t < textures.getarraysize(); t++)
                textureRows.add(texture(textures.get(t)));
            assignments.add(Json.map("item_type", item == null ? "model" : Creo.enumName(item.GetType()),
                    "item_id", item == null ? null : String.valueOf(item.GetId()),
                    "selection_model", Creo.fileName(assignmentModel),
                    "selection_model_type", assignmentModel == null ? null : Creo.typeName(assignmentModel.GetType()),
                    "appearance", row(value.GetAppearance()),
                    "texture_count", textures == null ? 0 : textures.getarraysize(),
                    "texture_inventory_complete", true, "textures", textureRows));
        }
        return Json.map("complete", true, "model", Creo.fileName(model), "scope", "source_part",
                "selection_model", Creo.fileName(selectionModel),
                "selection_model_type", selectionModel == null ? null : Creo.typeName(selectionModel.GetType()),
                "appearance", row(appearance), "assignments", assignments,
                "modified", model.GetIsModified(),
                "source", "pfcSelect.CreateModelSelection/WSelection.GetVisibleAppearance/WSolid.GetAllAppearancesAndTextures");
    }

    private static Appearance visible(WSelection selection) throws com.ptc.cipjava.jxthrowable {
        try { return selection.GetVisibleAppearance(); }
        catch (XToolkitNotExist absent) { return null; }
    }

    static Map<String, Object> set(Map<String, Object> request) throws Exception {
        Model model = (Model) Creo.part(Creo.session(), Json.string(request, "model"));
        WSelection selection = (WSelection) pfcSelect.CreateModelSelection(model);
        Map<String, Object> before = get(request);
        Map<String, Object> context = Json.map("model", Creo.fileName(model), "origin", Creo.origin(model));
        requireExpected(request, before, context);
        List<?> assignments = (List<?>) before.get("assignments");
        if (assignments.size() > 1)
            throw new Failures.Refusal("E_UNSUPPORTED", "whole-part color requires one source assignment");
        for (Object raw : assignments) {
            Map<String, Object> applied = Json.object(raw, "appearance assignment");
            if (!"model".equals(applied.get("item_type")) || applied.get("item_id") != null
                    || !sameReadback(applied.get("appearance"), before.get("appearance")))
                throw new Failures.Refusal("E_UNSUPPORTED", "whole-part color refuses item overrides or textures");
            for (Object rawTexture : (List<?>) applied.get("textures")) {
                Map<String, Object> texture = Json.object(rawTexture, "texture");
                String path = (String) texture.get("file_path");
                if (path != null && !path.isEmpty())
                    throw new Failures.Refusal("E_UNSUPPORTED", "whole-part color refuses actual texture assets");
            }
        }
        String action = Json.string(request, "action", "set");
        if (!"set".equals(action) && !"restore".equals(action))
            throw new Failures.Refusal("E_VALIDATION", "unknown appearance action");
        String referenceAction = Json.string(request, "reference_action", "preserve");
        boolean replace = "create_and_bind".equals(referenceAction);
        if (!replace && !"preserve".equals(referenceAction))
            throw new Failures.Refusal("E_VALIDATION", "unknown appearance reference action");
        boolean authorized = Json.bool(request, "reference_replacement_authorized", false);
        if (replace != authorized)
            throw new Failures.Refusal("E_FORBIDDEN", "reference creation requires explicit create_and_bind authorization");
        if (replace && (!Objects.equals(before.get("model"), before.get("selection_model"))
                || !"part".equals(before.get("selection_model_type")) || assignments.size() != 1))
            throw new Failures.Refusal("E_VERIFY_INCOMPLETE", "one independently identified source-model reference binding is required");
        if (replace) for (Object raw : assignments) {
            Map<String, Object> applied = Json.object(raw, "appearance assignment");
            if (!Objects.equals(before.get("model"), applied.get("selection_model"))
                    || !"part".equals(applied.get("selection_model_type")))
                throw new Failures.Refusal("E_VERIFY_INCOMPLETE", "native assignment selection is not bound to this source part");
        }
        Map<String, Object> current = before.get("appearance") == null ? null
                : Json.object(before.get("appearance"), "current appearance");
        Map<String, Object> requested = "restore".equals(action)
                ? request.get("appearance") == null ? null
                    : Json.object(request.get("appearance"), "appearance")
                : current == null ? null : new java.util.LinkedHashMap<>(current);
        List<?> requestedRGB = "set".equals(action) ? (List<?>) request.get("rgb") : null;
        if ("set".equals(action)) colorValues(requestedRGB);
        if (requested != null && "set".equals(action)) requested.put("rgb", requestedRGB);
        if (replace && (current == null || requested == null))
            throw new Failures.Refusal("E_UNSUPPORTED", "create_and_bind requires existing and intended non-null appearances");
        if (!replace && current != null && requested != null && !sameReadback(current, requested))
            throw new Failures.Refusal("E_UNSUPPORTED", "changing an existing appearance requires authorized create_and_bind");
        boolean allocatesReference = replace || (current == null && !("restore".equals(action) && requested == null));
        if (allocatesReference && !"random_candidate_native_readback_v1".equals(
                Json.string(request, "reference_allocation_policy", "")))
            throw new Failures.Refusal("E_UNSUPPORTED", "reference creation requires the collision-resistant allocation policy");
        try {
            Appearance intended;
            if (replace) {
                // f29 and f176 both renamed an existing reference on RGB change.
                // This separately authorized path creates a property object with no
                // reusable fixed identifier. Only native readback supplies its actual ID.
                // Never mutate the old object: other sources can still reference it.
                intended = createAndBindProperties(requested);
            } else if ("restore".equals(action) && requested == null) {
                intended = null;
            } else if (current != null) {
                // Only a byte-equivalent appearance is allowed in preserve mode.
                // Reading a reference never grants authority to mutate its palette.
                intended = visible(selection);
                if (!sameReadback(row(intended), current))
                    throw new IllegalStateException("appearance changed after expected-before check");
            } else {
                intended = "restore".equals(action) ? createAndBindProperties(requested)
                        : wfcDisplay.Appearance_Create(0.3, 0.7, 0.0, 0.2, 0.0, color(requestedRGB),
                                pfcBase.ColorRGB_Create(1, 1, 1), 0, newReferenceCandidate(), "", "", "");
            }
            selection.SetVisibleAppearance(intended);
        }
        catch (Throwable failure) {
            throw new Failures.Stage("appearance_set", failure, Json.map("model", Creo.fileName(model),
                    "before", before, "modified", Creo.modified(model)));
        }
        Creo.repaint(Creo.session());
        return Json.map("model", Creo.fileName(model), "scope", "source_part", "setter_returned", true,
                "reference_action", referenceAction,
                "reference_replacement_authorized", replace,
                "old_reference", Json.map("source_context", context,
                        "native_id", current == null ? null : current.get("name")),
                "new_reference_status", allocatesReference ? "native_allocated_readback_pending" : "independent_readback_pending");
    }

    static Appearance createAndBindProperties(Map<String, Object> properties)
            throws com.ptc.cipjava.jxthrowable {
        Map<String, Object> value = new java.util.LinkedHashMap<>(properties);
        value.put("name", newReferenceCandidate());
        // This candidate prevents predictable reuse; Creo may still choose a different
        // actual identifier, which must be independently observed after the setter.
        return from(value);
    }

    static String newReferenceCandidate() {
        // 27 ASCII characters stay within the bounded profile; no model or user data
        // is embedded. The actual native ID is not inferred from this candidate.
        return "cc_" + UUID.randomUUID().toString().replace("-", "").substring(0, 24);
    }

    static void requireExpected(Map<String, Object> request, Map<String, Object> before,
            Map<String, Object> context) {
        if (!request.containsKey("expected_before") || !request.containsKey("expected_source_context"))
            throw new Failures.Refusal("E_VALIDATION", "complete expected-before appearance and source context are required");
        if (!sameReadback(request.get("expected_before"), before)
                || !sameReadback(request.get("expected_source_context"), context))
            throw new Failures.Refusal("E_CONFLICT", "appearance identity, attributes, assignment or source context changed before setter");
    }

    static boolean sameReadback(Object left, Object right) {
        if (left instanceof Number && right instanceof Number)
            return ((Number) left).doubleValue() == ((Number) right).doubleValue();
        if (left instanceof Map && right instanceof Map) {
            Map<?, ?> a = (Map<?, ?>) left, b = (Map<?, ?>) right;
            if (!a.keySet().equals(b.keySet())) return false;
            for (Object key : a.keySet()) if (!sameReadback(a.get(key), b.get(key))) return false;
            return true;
        }
        if (left instanceof List && right instanceof List) {
            List<?> a = (List<?>) left, b = (List<?>) right;
            if (a.size() != b.size()) return false;
            for (int i = 0; i < a.size(); i++) if (!sameReadback(a.get(i), b.get(i))) return false;
            return true;
        }
        return Objects.equals(left, right);
    }

    static Map<String, Object> row(Appearance appearance) throws com.ptc.cipjava.jxthrowable {
        if (appearance == null) return null;
        return Json.map("rgb", rgb(appearance.GetRGBColor()), "ambient", appearance.GetAmbient(),
                "diffuse", appearance.GetDiffuse(), "highlight", appearance.GetHighlight(),
                "shininess", appearance.GetShininess(), "transparency", appearance.GetTransparency(),
                "highlight_rgb", rgb(appearance.GetHighlightColor()), "reflection", appearance.GetReflection(),
                "name", appearance.GetName(), "label", appearance.GetLabel(),
                "description", appearance.GetDescription(), "keywords", appearance.GetKeywords());
    }

    static Appearance from(Map<String, Object> value) throws com.ptc.cipjava.jxthrowable {
        return wfcDisplay.Appearance_Create(Json.number(value, "ambient"), Json.number(value, "diffuse"),
                Json.number(value, "highlight"), Json.number(value, "shininess"), Json.number(value, "transparency"),
                color((List<?>) value.get("rgb")), color((List<?>) value.get("highlight_rgb")),
                Json.number(value, "reflection"), (String) value.get("name"), (String) value.get("label"),
                (String) value.get("description"), (String) value.get("keywords"));
    }

    private static ColorRGB color(List<?> values) throws com.ptc.cipjava.jxthrowable {
        double[] rgb = colorValues(values);
        return pfcBase.ColorRGB_Create(rgb[0], rgb[1], rgb[2]);
    }

    private static double[] colorValues(List<?> values) {
        if (values == null || values.size() != 3) throw new IllegalArgumentException("RGB needs three values");
        double[] rgb = new double[3];
        for (int i = 0; i < 3; i++) {
            if (!(values.get(i) instanceof Number))
                throw new IllegalArgumentException("RGB values must be numbers");
            rgb[i] = ((Number) values.get(i)).doubleValue();
            if (!Double.isFinite(rgb[i]) || rgb[i] < 0 || rgb[i] > 1)
                throw new IllegalArgumentException("RGB values must be finite and in 0..1");
        }
        return rgb;
    }

    private static List<Double> rgb(ColorRGB color) throws com.ptc.cipjava.jxthrowable {
        return Arrays.asList(color.GetRed(), color.GetGreen(), color.GetBlue());
    }

    private static Map<String, Object> texture(Texture value) throws com.ptc.cipjava.jxthrowable {
        TexturePlacement placement = value.GetPlacement();
        Map<String, Object> position = null;
        if (placement != null) {
            com.ptc.pfc.pfcBase.Transform3D local = placement.GetLocalSys();
            List<Object> matrix = null;
            if (local != null) {
                matrix = new ArrayList<>();
                com.ptc.pfc.pfcBase.Matrix3D raw = local.GetMatrix();
                for (int r = 0; r < 4; r++) {
                    List<Object> row = new ArrayList<>();
                    for (int c = 0; c < 4; c++) row.add(raw.get(r, c));
                    matrix.add(row);
                }
            }
            position = Json.map("complete", true,
                    "projection_type", Creo.enumName(placement.GetTextureProjectionType()),
                    "local_transform", matrix,
                    "horizontal_offset", placement.GetHorizontalOffset(),
                    "vertical_offset", placement.GetVerticalOffset(), "rotate", placement.GetRotate(),
                    "horizontal_scale", placement.GetHorizontalScale(), "vertical_scale", placement.GetVerticalScale(),
                    "bump_height", placement.GetBumpHeight(), "decal_intensity", placement.GetDecalIntensity(),
                    "horizontal_flip", placement.GetHorizontalFlip(), "vertical_flip", placement.GetVerticalFlip());
        }
        return Json.map("complete", true, "type", Creo.enumName(value.GetType()),
                "file_path", value.GetFilePath(), "placement", position);
    }
}
