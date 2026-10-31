package com.fateforge.creocli.service;

import com.ptc.pfc.pfcFeature.Feature;
import com.ptc.pfc.pfcGeometry.Contour;
import com.ptc.pfc.pfcGeometry.Contours;
import com.ptc.pfc.pfcGeometry.Edge;
import com.ptc.pfc.pfcGeometry.Edges;
import com.ptc.pfc.pfcGeometry.Surface;
import com.ptc.pfc.pfcGeometry.Surfaces;
import com.ptc.pfc.pfcGeometry.SurfaceOrientation;
import com.ptc.pfc.pfcGeometry.SurfaceType;
import com.ptc.pfc.pfcGeometry.TransformedSurface;
import com.ptc.pfc.pfcModel.Model;
import com.ptc.pfc.pfcModelItem.ModelItemType;
import com.ptc.pfc.pfcModelItem.ModelItems;
import com.ptc.pfc.pfcSelect.Selections;
import com.ptc.pfc.pfcSolid.Solid;
import com.ptc.pfc.pfcSolid.SolidBody;
import com.ptc.pfc.pfcSolid.SolidBodyState;
import com.ptc.wfc.wfcElementTree.Element;
import com.ptc.wfc.wfcElementTree.ElementTree;
import com.ptc.wfc.wfcElementTree.Elements;
import com.ptc.wfc.wfcFeature.FeatureElemTreeExtractOptions;
import com.ptc.wfc.wfcFeature.WFeature;
import java.lang.ref.Reference;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/** Read-only bounded shell definitions and complete planar body boundaries. */
final class PrismaticReadback {
    static final String PROFILE = "prismatic-shell-v1";
    private PrismaticReadback() { }

    static Map<String, Object> definition(Feature feature) {
        List<Object> owners = new ArrayList<>();
        owners.add(feature);
        try {
            if (!"FEATTYPE_SHELL".equals(Creo.enumName(feature.GetFeatType()))) return null;
            ElementTree tree = ((WFeature) feature).GetElementTree(null,
                    FeatureElemTreeExtractOptions.FEAT_EXTRACT_NO_OPTS);
            if (tree == null) throw incomplete("shell tree is unavailable");
            owners.add(tree);
            Elements elements = tree.ListTreeElements();
            owners.add(elements);
            double thickness = one(elements, Ptc.PRO_E_SHELL_THICK, owners).GetValue().GetDoubleValue();
            int flip = one(elements, Ptc.PRO_E_SHELL_FLIP, owners).GetValue().GetIntValue();
            Element removed = one(elements, Ptc.PRO_E_SHELL_SRF, owners);
            Selections selected = removed.GetSelections();
            owners.add(selected);
            if (selected == null || selected.getarraysize() != 1)
                throw unsupported("bounded shell needs one readable removed surface");
            List<Object> refs = new ArrayList<>();
            refs.add(Geometry.ref(selected.get(0).GetSelItem()));
            Elements body = one(elements, Ptc.PRO_E_BODY, owners).GetChildren();
            owners.add(body);
            int bodyId = one(body, Ptc.PRO_E_BODY_SELECT, owners).GetValue()
                    .GetSelectionValue().GetSelItem().GetId();
            Element locals = optional(elements, Ptc.PRO_E_ST_SHELL_LOCL_LIST, owners);
            Elements localValues = locals == null ? null : locals.GetChildren();
            owners.add(localValues);
            int localCount = localValues == null ? 0 : localValues.getarraysize();
            Element excluded = optional(elements, Ptc.PRO_E_STD_SURF_COLLECTION_APPL, owners);
            int excludedCount = 0;
            if (excluded != null) {
                com.ptc.wfc.wfcCollection.Collection collection = excluded.GetElemCollection();
                owners.add(collection);
                if (collection != null) {
                    com.ptc.wfc.wfcCollection.SurfaceCollection surfaces = collection.GetSurfCollection();
                    owners.add(surfaces);
                    if (surfaces != null) {
                        com.ptc.wfc.wfcCollection.SurfaceCollectionInstructions instructions = surfaces.GetInstructions();
                        owners.add(instructions);
                        excludedCount = instructions == null ? 0 : instructions.getarraysize();
                    }
                }
            }
            String side = flip == Ptc.PRO_SHELL_INSIDE ? "inside"
                    : flip == Ptc.PRO_SHELL_OUTSIDE ? "outside" : "unknown";
            return Json.map("complete", true, "kind", "shell", "thickness", thickness,
                    "side", side, "removed", refs, "body_id", bodyId,
                    "local_thickness_count", localCount, "excluded_instruction_count", excludedCount,
                    "source", "independent WFeature shell tree; no creation request used");
        } catch (Throwable failure) {
            return Json.map("complete", false, "kind", "shell", "source", "native shell tree",
                    "error", Failures.error(failure));
        } finally {
            Reference.reachabilityFence(owners);
        }
    }

    static Map<String, Object> geometry(Solid solid) {
        List<Object> owners = new ArrayList<>();
        List<Object> items = new ArrayList<>();
        owners.add(solid);
        String model = null;
        try {
            model = Creo.fileName((Model) solid);
            ModelItems bodies = solid.ListItems(ModelItemType.ITEM_BODY);
            owners.add(bodies);
            SolidBody body = solid.GetDefaultBody();
            owners.add(body);
            if (bodies == null || bodies.getarraysize() != 1 || body == null
                    || bodies.get(0).GetId() != body.GetId()
                    || body.GetBodyState().getValue() != SolidBodyState._BODY_STATE_ACTIVE)
                throw unsupported("bounded shell geometry requires exactly one active default body");
            Surfaces faces = body.ListSurfaces();
            owners.add(faces);
            if (faces == null || faces.getarraysize() == 0 || faces.getarraysize() > 32)
                throw unsupported("bounded shell geometry needs 1..32 physical planar faces");
            Set<String> physical = new HashSet<>();
            for (int i = 0; i < faces.getarraysize(); i++) physical.add(Geometry.ref(faces.get(i)));
            Map<String, Map<String, Object>> edges = new LinkedHashMap<>();
            for (int i = 0; i < faces.getarraysize(); i++) {
                Surface face = faces.get(i);
                owners.add(face);
                if (face.GetSurfaceType().getValue() != SurfaceType._SURFACE_PLANE
                        || !(face instanceof TransformedSurface))
                    throw unsupported("bounded shell proof does not cover curved surfaces");
                SurfaceOrientation orientation = face.GetOrientation();
                if (orientation == null || (orientation.getValue() != SurfaceOrientation._SURFACEORIENT_INWARD
                        && orientation.getValue() != SurfaceOrientation._SURFACEORIENT_OUTWARD))
                    throw incomplete("physical face orientation is unreadable");
                Map<String, Object> row = Geometry.surface(face, false);
                List<Object> normal = Geometry.vector(((TransformedSurface) face).GetCoordSys().GetZAxis());
                if (orientation.getValue() == SurfaceOrientation._SURFACEORIENT_INWARD)
                    for (int j = 0; j < normal.size(); j++) normal.set(j, -((Number) normal.get(j)).doubleValue());
                row.put("normal", normal);
                row.put("area", Geometry.round(face.EvalArea()));
                Contours contours = face.ListContours();
                owners.add(contours);
                if (contours == null || contours.getarraysize() == 0 || contours.getarraysize() > 8)
                    throw incomplete("complete physical face contours unavailable");
                List<Object> loops = new ArrayList<>();
                for (int c = 0; c < contours.getarraysize(); c++) {
                    Contour contour = contours.get(c);
                    owners.add(contour);
                    Edges boundary = contour.ListElements();
                    owners.add(boundary);
                    if (boundary == null || boundary.getarraysize() < 3 || boundary.getarraysize() > 64)
                        throw incomplete("closed bounded linear contour unavailable");
                    List<Object> refs = new ArrayList<>();
                    for (int k = 0; k < boundary.getarraysize(); k++) {
                        Edge edge = boundary.get(k);
                        owners.add(edge);
                        if (edge.IsArtificial()) throw unsupported("artificial edges are outside shell proof");
                        Map<String, Object> detail = Geometry.edge(edge);
                        if (!"line".equals(detail.get("type")))
                            throw unsupported("bounded shell proof needs straight physical edges");
                        @SuppressWarnings("unchecked")
                        List<Object> adjacent = (List<Object>) detail.get("surfaces");
                        if (adjacent.size() != 2 || adjacent.get(0).equals(adjacent.get(1))
                                || !physical.containsAll(adjacent))
                            throw incomplete("physical edge adjacency is incomplete");
                        String ref = (String) detail.get("ref");
                        refs.add(ref);
                        edges.putIfAbsent(ref, detail);
                    }
                    loops.add(refs);
                }
                row.put("boundary_loops", loops);
                items.add(row);
            }
            if (edges.size() > 64) throw unsupported("bounded shell edge inventory exceeds 64");
            items.addAll(edges.values());
            return Json.map("model", model, "units", Creo.units(solid), "complete", true,
                    "profile", PROFILE, "body", Json.map("id", body.GetId(), "state", "BODY_STATE_ACTIVE"),
                    "items", items, "source", "SolidBody.ListSurfaces; strict orientations; complete contours and physical edge adjacency");
        } catch (Throwable failure) {
            return Json.map("model", model, "complete", false, "profile", PROFILE,
                    "items", items, "source", "bounded native body/face/contour getters",
                    "error", Failures.error(failure));
        } finally {
            Reference.reachabilityFence(owners);
        }
    }

    private static Element optional(Elements elements, int id, List<Object> owners) throws Exception {
        if (elements == null) return null;
        owners.add(elements);
        if (elements.getarraysize() > 4096) throw incomplete("shell tree exceeds reader bound");
        Element found = null;
        for (int i = 0; i < elements.getarraysize(); i++) {
            Element element = elements.get(i);
            owners.add(element);
            if (element.GetId() == id) {
                if (found != null) throw incomplete("ambiguous shell tree element " + id);
                found = element;
            }
        }
        return found;
    }

    private static Element one(Elements elements, int id, List<Object> owners) throws Exception {
        Element result = optional(elements, id, owners);
        if (result == null) throw incomplete("missing shell tree element " + id);
        return result;
    }

    private static Failures.Refusal incomplete(String message) {
        return new Failures.Refusal("E_VERIFY_INCOMPLETE", message);
    }

    private static Failures.Refusal unsupported(String message) {
        return new Failures.Refusal("E_UNSUPPORTED", message);
    }
}
