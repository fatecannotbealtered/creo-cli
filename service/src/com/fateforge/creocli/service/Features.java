package com.fateforge.creocli.service;

import com.ptc.cipjava.jxthrowable;
import com.ptc.pfc.pfcArgument.pfcArgument;
import com.ptc.pfc.pfcFeature.Feature;
import com.ptc.pfc.pfcModel.Model;
import com.ptc.pfc.pfcModelItem.ModelItemType;
import com.ptc.pfc.pfcModelItem.ModelItems;
import com.ptc.pfc.pfcSelect.Selection;
import com.ptc.pfc.pfcSelect.Selections;
import com.ptc.pfc.pfcSelect.pfcSelect;
import com.ptc.pfc.pfcSession.Session;
import com.ptc.pfc.pfcSolid.Solid;
import com.ptc.wfc.wfcCollection.CurveCollectionInstrType;
import com.ptc.wfc.wfcCollection.CurveCollectionInstructions;
import com.ptc.wfc.wfcCollection.wfcCollection;
import com.ptc.wfc.wfcElementTree.Element;
import com.ptc.wfc.wfcElementTree.Elements;
import com.ptc.wfc.wfcFeature.WFeature;
import com.ptc.wfc.wfcFeatureInstructions.FeatCreateOption;
import com.ptc.wfc.wfcSession.WSession;
import com.ptc.wfc.wfcSolid.WSolid;
import com.ptc.wfc.wfcSolidInstructions.wfcSolidInstructions;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * The features placed on existing geometry and the datums: feature.datum-plane,
 * feature.datum-axis, feature.round, feature.chamfer, feature.hole, feature.shell,
 * feature.draft. Each is one element tree, built as PTC's own examples build that kind of
 * feature, and created in one call; references are the strings {@link Geometry#item}
 * resolves, never a pick.
 */
final class Features {

    private Features() {
    }

    // ------------------------------------------------------------------ datums

    /** A datum plane offset from a plane or planar face, or through an axis at an angle to a plane. */
    static Map<String, Object> datumPlane(Map<String, Object> request) throws Exception {
        Session session = Creo.session();
        Solid solid = Creo.part(session, Json.string(request, "model"));
        Elements elements = start(Ptc.PRO_FEAT_DATUM, request);
        Creo.add(elements, Ptc.PRO_E_DTMPLN_CONSTRAINTS, null, 1);
        if (request.containsKey("offset")) {
            Map<String, Object> offset = Json.object(request.get("offset"), "'offset'");
            Creo.add(elements, Ptc.PRO_E_DTMPLN_CONSTRAINT, null, 2);
            Creo.add(elements, Ptc.PRO_E_DTMPLN_CONSTR_TYPE, pfcArgument.CreateIntArgValue(Ptc.PRO_DTMPLN_OFFS), 3);
            Creo.add(elements, Ptc.PRO_E_DTMPLN_CONSTR_REF,
                    pfcArgument.CreateSelectionArgValue(Geometry.select(solid, Json.string(offset, "from"))), 3);
            Creo.add(elements, Ptc.PRO_E_DTMPLN_CONSTR_REF_OFFSET,
                    pfcArgument.CreateDoubleArgValue(Json.number(offset, "distance")), 3);
        } else if (request.containsKey("angle")) {
            Map<String, Object> angle = Json.object(request.get("angle"), "'angle'");
            Creo.add(elements, Ptc.PRO_E_DTMPLN_CONSTRAINT, null, 2);
            Creo.add(elements, Ptc.PRO_E_DTMPLN_CONSTR_TYPE, pfcArgument.CreateIntArgValue(Ptc.PRO_DTMPLN_THRU), 3);
            Creo.add(elements, Ptc.PRO_E_DTMPLN_CONSTR_REF,
                    pfcArgument.CreateSelectionArgValue(Geometry.select(solid, Json.string(angle, "through"))), 3);
            Creo.add(elements, Ptc.PRO_E_DTMPLN_CONSTRAINT, null, 2);
            Creo.add(elements, Ptc.PRO_E_DTMPLN_CONSTR_TYPE, pfcArgument.CreateIntArgValue(Ptc.PRO_DTMPLN_ANG), 3);
            Creo.add(elements, Ptc.PRO_E_DTMPLN_CONSTR_REF,
                    pfcArgument.CreateSelectionArgValue(Geometry.select(solid, Json.string(angle, "from"))), 3);
            Creo.add(elements, Ptc.PRO_E_DTMPLN_CONSTR_REF_ANGLE,
                    pfcArgument.CreateDoubleArgValue(Json.number(angle, "degrees")), 3);
        } else {
            throw new Failures.Refusal("E_VALIDATION", "a datum plane needs 'offset' or 'angle'");
        }
        Map<String, Object> before = Creo.measure(solid);
        WFeature feature = create(session, solid, elements, FeatCreateOption.FEAT_CR_NO_OPTS);
        Map<String, Object> plane = null;
        ModelItems own = feature.ListSubItems(ModelItemType.ITEM_SURFACE);
        if (own != null && own.getarraysize() > 0) {
            plane = Geometry.surface((com.ptc.pfc.pfcGeometry.Surface) own.get(0), true);
        }
        return Extrude.built(solid, feature, before, Json.map("geometry", plane));
    }

    /** A datum axis where two planes meet, or through an edge or a cylinder's axis. */
    static Map<String, Object> datumAxis(Map<String, Object> request) throws Exception {
        Session session = Creo.session();
        Solid solid = Creo.part(session, Json.string(request, "model"));
        List<String> through = strings(request, "through", 1, 2);
        Elements elements = start(Ptc.PRO_FEAT_DATUM_AXIS, request);
        Creo.add(elements, Ptc.PRO_E_DTMAXIS_CONSTRAINTS, null, 1);
        for (String ref : through) {
            Creo.add(elements, Ptc.PRO_E_DTMAXIS_CONSTRAINT, null, 2);
            Creo.add(elements, Ptc.PRO_E_DTMAXIS_CONSTR_TYPE,
                    pfcArgument.CreateIntArgValue(Ptc.PRO_DTMAXIS_CONSTR_TYPE_THRU), 3);
            Creo.add(elements, Ptc.PRO_E_DTMAXIS_CONSTR_REF,
                    pfcArgument.CreateSelectionArgValue(Geometry.select(solid, ref)), 3);
        }
        Map<String, Object> before = Creo.measure(solid);
        WFeature feature = create(session, solid, elements, FeatCreateOption.FEAT_CR_NO_OPTS);
        Map<String, Object> axis = null;
        ModelItems own = feature.ListSubItems(ModelItemType.ITEM_AXIS);
        if (own != null && own.getarraysize() > 0) {
            axis = Geometry.axis((com.ptc.wfc.wfcGeometry.WAxis) own.get(0));
        }
        return Extrude.built(solid, feature, before, Json.map("geometry", axis));
    }

    // ------------------------------------------------------------------ edges

    /** A constant-radius round on edges, as ProRound.h's edge-round example builds one. */
    static Map<String, Object> round(Map<String, Object> request) throws Exception {
        return edgeFeature(request, true);
    }

    /**
     * An equal-distance chamfer on edges, as ProChamfer.h's edge-chamfer example builds one.
     * Where the edges' faces meet square it is made 45 x D, the scheme a drawing calls out as
     * 1 X 45 (or C1, by the drawing's default_chamfer_text); D x D, the same geometry there,
     * comes out as a bare length. Creo allows 45 x D only between faces at right angles, so
     * where it refuses the chamfer is made D x D.
     */
    static Map<String, Object> chamfer(Map<String, Object> request) throws Exception {
        try {
            Map<String, Object> made = edgeFeature(request, false, Ptc.PRO_CHM_45_X_D);
            made.put("scheme", "45_x_d");
            return made;
        } catch (Failures.Stage refused) {
            if (!"create".equals(refused.stage) && !"deleted".equals(refused.cleanup)) {
                throw refused;
            }
        }
        Map<String, Object> made = edgeFeature(request, false, Ptc.PRO_CHM_D_X_D);
        made.put("scheme", "d_x_d");
        return made;
    }

    private static Map<String, Object> edgeFeature(Map<String, Object> request, boolean round) throws Exception {
        return edgeFeature(request, round, Ptc.PRO_CHM_D_X_D);
    }

    private static Map<String, Object> edgeFeature(Map<String, Object> request, boolean round, int scheme)
            throws Exception {
        Session session = Creo.session();
        Solid solid = Creo.part(session, Json.string(request, "model"));
        List<String> edges = strings(request, "edges", 1, 200);
        double size = Json.number(request, round ? "radius" : "distance");
        if (size <= 0) {
            throw new Failures.Refusal("E_VALIDATION", round ? "'radius' must be positive" : "'distance' must be positive");
        }
        Elements elements = start(round ? Ptc.PRO_FEAT_ROUND : Ptc.PRO_FEAT_CHAMFER, request);
        Creo.add(elements, Ptc.PRO_E_RNDCH_SETS, null, 1);
        Creo.add(elements, Ptc.PRO_E_RNDCH_SET, null, 2);
        if (round) {
            Creo.add(elements, Ptc.PRO_E_RNDCH_SHAPE_OPTIONS, pfcArgument.CreateIntArgValue(Ptc.PRO_ROUND_TYPE_CONSTANT), 3);
            Creo.add(elements, Ptc.PRO_E_RNDCH_COMPOUND_CONIC, null, 3);
            Creo.add(elements, Ptc.PRO_E_RNDCH_CONIC_TYPE, pfcArgument.CreateIntArgValue(Ptc.PRO_ROUND_CONIC_DISABLE), 4);
        } else {
            Creo.add(elements, Ptc.PRO_E_RNDCH_DIMENSIONAL_SCHEMA, pfcArgument.CreateIntArgValue(scheme), 3);
        }
        Creo.add(elements, Ptc.PRO_E_RNDCH_REFERENCES, null, 3);
        if (round) {
            Creo.add(elements, Ptc.PRO_E_RNDCH_REFERENCE_TYPE, pfcArgument.CreateIntArgValue(Ptc.PRO_ROUND_REF_EDGE), 4);
        }
        Element collection = Creo.add(elements, Ptc.PRO_E_STD_CURVE_COLLECTION_APPL, null, 4);
        collection.SetElemCollection(edgeCollection(solid, edges));
        Creo.add(elements, Ptc.PRO_E_RNDCH_RADII, null, 3);
        Creo.add(elements, Ptc.PRO_E_RNDCH_RADIUS, null, 4);
        Creo.add(elements, Ptc.PRO_E_RNDCH_LEG1, null, 5);
        Creo.add(elements, Ptc.PRO_E_RNDCH_LEG_TYPE, pfcArgument.CreateIntArgValue(Ptc.PRO_ROUND_RADIUS_TYPE_VALUE), 6);
        Creo.add(elements, Ptc.PRO_E_RNDCH_LEG_VALUE, pfcArgument.CreateDoubleArgValue(size), 6);
        Creo.add(elements, Ptc.PRO_E_RNDCH_ATTACH_TYPE, pfcArgument.CreateIntArgValue(Ptc.PRO_ROUND_ATTACHED), 1);
        Map<String, Object> before = Creo.measure(solid);
        WFeature feature = create(session, solid, elements, FeatCreateOption.FEAT_CR_DEFINE_MISS_ELEMS);
        return Extrude.built(solid, feature, before, Json.map());
    }

    /** One "add one" instruction per edge, as PTC's example builds its chain. */
    private static com.ptc.wfc.wfcCollection.Collection edgeCollection(Solid solid, List<String> refs) throws jxthrowable {
        CurveCollectionInstructions instructions = CurveCollectionInstructions.create();
        for (String ref : refs) {
            com.ptc.pfc.pfcModelItem.ModelItem item = Geometry.item(solid, ref);
            if (item.GetType().getValue() != ModelItemType._ITEM_EDGE) {
                throw new Failures.Refusal("E_VALIDATION", ref + " is not an edge; geometry list --kind edge shows them");
            }
            Selections one = Selections.create();
            one.append(pfcSelect.CreateModelItemSelection(item, null));
            instructions.append(wfcCollection.CurveCollectionInstruction_Create(
                    CurveCollectionInstrType.CURVCOLL_ADD_ONE_INSTR, one));
        }
        com.ptc.wfc.wfcCollection.Collection collection = wfcCollection.Collection_Create();
        collection.SetCrvCollection(wfcCollection.CurveCollection_Create(instructions));
        return collection;
    }

    // ------------------------------------------------------------------ hole

    /**
     * A straight hole on a planar face, blind to a depth or through all, placed as the Hole
     * tool places one: by distances from two references, on a bolt circle, or on an axis
     * (Holes.place).
     */
    static Map<String, Object> hole(Map<String, Object> request) throws Exception {
        if (Holes.shaped(request)) {
            return Holes.hole(request);
        }
        Session session = Creo.session();
        Solid solid = Creo.part(session, Json.string(request, "model"));
        double diameter = Json.number(request, "diameter");
        if (diameter <= 0) {
            throw new Failures.Refusal("E_VALIDATION", "'diameter' must be positive");
        }
        Object depthValue = request.get("depth");
        boolean through = "through_all".equals(depthValue);
        if (!through && !(depthValue instanceof Double && (Double) depthValue > 0)) {
            throw new Failures.Refusal("E_VALIDATION", "'depth' is a positive number or \"through_all\"");
        }
        Map<String, Object> placement = Json.object(request.get("placement"), "'placement'");
        Elements elements = Elements.create();
        Creo.add(elements, Ptc.PRO_E_FEATURE_TREE, null, 0);
        Creo.add(elements, Ptc.PRO_E_FEATURE_TYPE, pfcArgument.CreateIntArgValue(Ptc.PRO_FEAT_HOLE), 1);
        Creo.add(elements, Ptc.PRO_E_FEATURE_FORM, pfcArgument.CreateIntArgValue(Ptc.PRO_HLE_TYPE_STRAIGHT), 1);
        Creo.add(elements, Ptc.PRO_E_HLE_COM, null, 1);
        Creo.add(elements, Ptc.PRO_E_HLE_TYPE_NEW, pfcArgument.CreateIntArgValue(Ptc.PRO_HLE_NEW_TYPE_STRAIGHT), 2);
        Creo.add(elements, Ptc.PRO_E_DIAMETER, pfcArgument.CreateDoubleArgValue(diameter), 2);
        Creo.add(elements, Ptc.PRO_E_HOLE_STD_DEPTH, null, 2);
        Creo.add(elements, Ptc.PRO_E_HOLE_DEPTH_TO, null, 3);
        Creo.add(elements, Ptc.PRO_E_HOLE_DEPTH_TO_TYPE, pfcArgument.CreateIntArgValue(
                through ? Ptc.PRO_HLE_STRGHT_THRU_ALL_DEPTH : Ptc.PRO_HLE_STRGHT_BLIND_DEPTH), 4);
        if (!through) {
            Creo.add(elements, Ptc.PRO_E_EXT_DEPTH_TO_VALUE, pfcArgument.CreateDoubleArgValue((Double) depthValue), 4);
        }
        Creo.add(elements, Ptc.PRO_E_HOLE_DEPTH_FROM, null, 3);
        Creo.add(elements, Ptc.PRO_E_HOLE_DEPTH_FROM_TYPE, pfcArgument.CreateIntArgValue(Ptc.PRO_HLE_STRGHT_NONE_DEPTH), 4);
        String placed = Holes.place(elements, solid, placement);
        String name = Json.string(request, "name", null);
        if (name != null) {
            Creo.add(elements, Ptc.PRO_E_STD_FEATURE_NAME, pfcArgument.CreateStringArgValue(name), 1);
        }
        Map<String, Object> before = Creo.measure(solid);
        WFeature feature = create(session, solid, elements, FeatCreateOption.FEAT_CR_DEFINE_MISS_ELEMS);
        return Extrude.built(solid, feature, before, Json.map("drill_diameter", diameter,
                "depth", through ? "through_all" : depthValue, "placement", placed,
                "surfaces", Holes.surfaces(feature)));
    }

    // ------------------------------------------------------------------ shell

    /**
     * Hollow the part to a wall thickness, removing the faces named, as the Shell tool does.
     * ProShell.h: the body is mandatory and must be the single body to shell.
     */
    static Map<String, Object> shell(Map<String, Object> request) throws Exception {
        Session session = Creo.session();
        Solid solid = Creo.part(session, Json.string(request, "model"));
        double thickness = Json.number(request, "thickness");
        if (thickness <= 0) {
            throw new Failures.Refusal("E_VALIDATION", "'thickness' must be positive");
        }
        List<String> remove = strings(request, "remove", 0, 200);
        com.ptc.pfc.pfcSolid.SolidBody body = solid.GetDefaultBody();
        if (body == null) {
            throw new Failures.Refusal("E_CONFLICT", "the part has no solid body to shell");
        }
        Elements elements = start(Ptc.PRO_FEAT_SHELL, request);
        Creo.add(elements, Ptc.PRO_E_BODY, null, 1);
        Creo.add(elements, Ptc.PRO_E_BODY_USE, pfcArgument.CreateIntArgValue(Ptc.PRO_BODY_USE_SELECTED), 2);
        Creo.add(elements, Ptc.PRO_E_BODY_SELECT,
                pfcArgument.CreateSelectionArgValue(pfcSelect.CreateModelItemSelection(body, null)), 2);
        if (!remove.isEmpty()) {
            Selections faces = Selections.create();
            for (String ref : remove) {
                com.ptc.pfc.pfcModelItem.ModelItem item = Geometry.item(solid, ref);
                if (item.GetType().getValue() != ModelItemType._ITEM_SURFACE) {
                    throw new Failures.Refusal("E_VALIDATION", ref + " is not a face of the part");
                }
                faces.append(pfcSelect.CreateModelItemSelection(item, null));
            }
            Element srf = Creo.add(elements, Ptc.PRO_E_SHELL_SRF, null, 1);
            srf.SetSelections(faces);
        }
        Creo.add(elements, Ptc.PRO_E_SHELL_THICK, pfcArgument.CreateDoubleArgValue(thickness), 1);
        Creo.add(elements, Ptc.PRO_E_SHELL_FLIP, pfcArgument.CreateIntArgValue(
                "outside".equals(Json.string(request, "side", "inside")) ? Ptc.PRO_SHELL_OUTSIDE : Ptc.PRO_SHELL_INSIDE), 1);
        Map<String, Object> before = Creo.measure(solid);
        WFeature feature = create(session, solid, elements, FeatCreateOption.FEAT_CR_DEFINE_MISS_ELEMS);
        int featureId = feature.GetId();
        // Native creation can round the thickness to the model's display precision.
        // Preserve the authorized value through the existing driving-dimension API;
        // never change session configuration or call creation again after a failure.
        Map<String, Object> definition = PrismaticReadback.definition(feature);
        if (definition == null || !Boolean.TRUE.equals(definition.get("complete")))
            throw new Failures.Stage("shell_thickness", new Failures.Refusal(
                    "E_VERIFY_INCOMPLETE", "created shell thickness definition is unreadable"));
        ModelItems dimensions = feature.ListSubItems(ModelItemType.ITEM_DIMENSION);
        if (dimensions == null || dimensions.getarraysize() != 1)
            throw new Failures.Stage("shell_thickness", new Failures.Refusal(
                    "E_VERIFY_INCOMPLETE", "one identified shell driving dimension is required"));
        com.ptc.pfc.pfcDimension.BaseDimension dimension =
                (com.ptc.pfc.pfcDimension.BaseDimension) dimensions.get(0);
        double createdThickness = ((Number) definition.get("thickness")).doubleValue();
        if (!"DIM_LINEAR".equals(Creo.enumName(dimension.GetDimType()))
                || Math.abs(dimension.GetDimValue() - createdThickness) > 1e-10)
            throw new Failures.Stage("shell_thickness", new Failures.Refusal(
                    "E_VERIFY_INCOMPLETE", "shell dimension and native tree disagree"));
        boolean corrected = Math.abs(createdThickness - thickness) > Math.max(1e-12, Math.abs(thickness) * 1e-12);
        if (corrected) {
            try {
                Dimensions.set(Json.map("model", Creo.fileName((Model) solid),
                        "dimension", String.valueOf(dimension.GetId()), "value", thickness));
            } catch (Exception failure) {
                throw new Failures.Stage("shell_thickness", failure);
            }
        }
        // Reacquire after regeneration rather than use a pre-regeneration feature proxy.
        feature = (WFeature) solid.GetFeatureById(featureId);
        return Extrude.built(solid, feature, before, Json.map(
                "requested_thickness", thickness, "created_thickness", createdThickness,
                "driving_dimension_corrected", corrected));
    }

    // ------------------------------------------------------------------ draft

    /**
     * Tilt faces by an angle about a hinge -- a datum plane or planar face, where the faces
     * keep their size -- as the Draft tool does with a plane for its hinge. The angle is
     * measured from the pull direction: the hinge's normal unless another reference is
     * named, flipped on request. ProDraft.h: one side, one constant angle, no split.
     */
    static Map<String, Object> draft(Map<String, Object> request) throws Exception {
        Session session = Creo.session();
        Solid solid = Creo.part(session, Json.string(request, "model"));
        List<String> faces = strings(request, "surfaces", 1, 200);
        double angle = Json.number(request, "angle");
        if (angle == 0 || Math.abs(angle) > 89) {
            throw new Failures.Refusal("E_VALIDATION", "'angle' is not zero and within 89 degrees either way");
        }
        String hinge = Json.string(request, "hinge");
        String pull = Json.string(request, "pull", hinge);
        boolean flip = Boolean.TRUE.equals(request.get("flip_pull"));
        Elements elements = start(Ptc.PRO_FEAT_DRAFT, request);
        Creo.add(elements, Ptc.PRO_E_DRAFT_SPLIT, pfcArgument.CreateIntArgValue(Ptc.PRO_DRAFT_UI_SPLIT_NONE), 1);
        Element collection = Creo.add(elements, Ptc.PRO_E_STD_SURF_COLLECTION_APPL, null, 1);
        collection.SetElemCollection(surfaceCollection(solid, faces));
        Creo.add(elements, Ptc.PRO_E_DIRECTION_COMPOUND, null, 1);
        Creo.add(elements, Ptc.PRO_E_DIRECTION_REFERENCE,
                pfcArgument.CreateSelectionArgValue(Geometry.select(solid, pull)), 2);
        Creo.add(elements, Ptc.PRO_E_DIRECTION_FLIP, pfcArgument.CreateIntArgValue(
                flip ? Ptc.PRO_DIRECTION_FLIP_AGAINST : Ptc.PRO_DIRECTION_FLIP_ALONG), 2);
        Creo.add(elements, Ptc.PRO_E_DRAFT_CONSTANT_OR_VARIABLE,
                pfcArgument.CreateIntArgValue(Ptc.PRO_DRAFT_UI_CONSTANT), 1);
        Creo.add(elements, Ptc.PRO_E_DRAFT_INCLUDE_TANGENT, pfcArgument.CreateIntArgValue(Ptc.PRO_DRAFT_UI_INC_TANG), 1);
        Creo.add(elements, Ptc.PRO_E_DRAFT_SIDE_1, null, 1);
        Creo.add(elements, Ptc.PRO_E_DRAFT_NEUTRAL_OBJECT_TYPE_1, pfcArgument.CreateIntArgValue(Ptc.PRO_DRAFT_UI_PLANE), 2);
        Creo.add(elements, Ptc.PRO_E_DRAFT_NEUTRAL_PLANE_1,
                pfcArgument.CreateSelectionArgValue(Geometry.select(solid, hinge)), 2);
        Creo.add(elements, Ptc.PRO_E_DRAFT_DEPENDENT_1, pfcArgument.CreateIntArgValue(Ptc.PRO_DRAFT_UI_INDEPENDENT), 2);
        Creo.add(elements, Ptc.PRO_E_DRAFT_ANGLE_1, pfcArgument.CreateDoubleArgValue(angle), 2);
        Map<String, Object> before = Creo.measure(solid);
        WFeature feature = create(session, solid, elements, FeatCreateOption.FEAT_CR_DEFINE_MISS_ELEMS);
        // The feature lists three surfaces per face drafted; only the tilted one is part of the
        // solid -- the others have no area and are not among the part's surfaces.
        java.util.Set<Integer> onPart = new java.util.HashSet<>();
        for (com.ptc.pfc.pfcGeometry.Surface face : Creo.surfaces(solid)) {
            onPart.add(face.GetId());
        }
        List<Object> drafted = new ArrayList<>();
        ModelItems own = feature.ListSubItems(ModelItemType.ITEM_SURFACE);
        for (int i = 0; own != null && i < own.getarraysize(); i++) {
            if (onPart.contains(own.get(i).GetId())) {
                drafted.add(Geometry.surface((com.ptc.pfc.pfcGeometry.Surface) own.get(i), false));
            }
        }
        return Extrude.built(solid, feature, before, Json.map("drafted", drafted));
    }

    /** One instruction naming each face, as ProSrfcollection.h's single-surface rule does. */
    private static com.ptc.wfc.wfcCollection.Collection surfaceCollection(Solid solid, List<String> refs)
            throws jxthrowable {
        com.ptc.wfc.wfcCollection.SurfaceCollectionReferences references =
                com.ptc.wfc.wfcCollection.SurfaceCollectionReferences.create();
        for (String ref : refs) {
            com.ptc.pfc.pfcModelItem.ModelItem item = Geometry.item(solid, ref);
            if (item.GetType().getValue() != ModelItemType._ITEM_SURFACE) {
                throw new Failures.Refusal("E_VALIDATION", ref + " is not a face of the part");
            }
            references.append(wfcCollection.SurfaceCollectionReference_Create(
                    com.ptc.wfc.wfcCollection.SurfaceCollectionRefType.SURFCOLL_REF_SINGLE,
                    pfcSelect.CreateModelItemSelection(item, null)));
        }
        com.ptc.wfc.wfcCollection.SurfaceCollectionInstructions instructions =
                com.ptc.wfc.wfcCollection.SurfaceCollectionInstructions.create();
        instructions.append(wfcCollection.SurfaceCollectionInstruction_Create(
                com.ptc.wfc.wfcCollection.SurfaceCollectionInstrType.SURFCOLL_SINGLE_SURF, true, references,
                com.ptc.wfc.wfcCollection.SurfaceCollectionRules.create()));
        com.ptc.wfc.wfcCollection.Collection collection = wfcCollection.Collection_Create();
        collection.SetSurfCollection(wfcCollection.SurfaceCollection_Create(instructions));
        return collection;
    }

    // ------------------------------------------------------------------ pattern

    /**
     * A pattern of one feature, as the Pattern tool's Direction and Axis types make one:
     * along one or two directions at a spacing, or about an axis at an angle increment. The
     * element tree is PTC's general pattern tree (ProPattern.h), not the legacy one.
     */
    static Map<String, Object> pattern(Map<String, Object> request) throws Exception {
        Session session = Creo.session();
        Solid solid = Creo.part(session, Json.string(request, "model"));
        Feature leader = Creo.feature(solid, Json.string(request, "feature"));
        Elements elements = Elements.create();
        Creo.add(elements, Ptc.PRO_E_PATTERN_ROOT, null, 0);
        if (request.containsKey("axis")) {
            Map<String, Object> axis = Json.object(request.get("axis"), "'axis'");
            int count = count(axis);
            double angle = Json.number(axis, "angle");
            Creo.add(elements, Ptc.PRO_E_GENPAT_TYPE, pfcArgument.CreateIntArgValue(Ptc.PRO_GENPAT_AXIS_DRIVEN), 1);
            Creo.add(elements, Ptc.PRO_E_GENPAT_AXIS, null, 1);
            Creo.add(elements, Ptc.PRO_E_GENPAT_AXIS_REF,
                    pfcArgument.CreateSelectionArgValue(Geometry.select(solid, Json.string(axis, "about"))), 2);
            Creo.add(elements, Ptc.PRO_E_GENPAT_AXIS1_INC, pfcArgument.CreateDoubleArgValue(Math.abs(angle)), 2);
            // ProPattern.h: a flip flag, 0 or 1 -- the angle's sign, not an enumeration.
            Creo.add(elements, Ptc.PRO_E_AXIS_PAT_DIR1_FLIP, pfcArgument.CreateIntArgValue(angle < 0 ? 1 : 0), 2);
            Creo.add(elements, Ptc.PRO_E_GENPAT_DIM_FIRST_DIR, null, 2);
            Creo.add(elements, Ptc.PRO_E_GENPAT_DIM_FIRST_DIR_NUM_INST, pfcArgument.CreateIntArgValue(count), 2);
            Creo.add(elements, Ptc.PRO_E_GENPAT_REGEN_METHOD, pfcArgument.CreateIntArgValue(Ptc.PRO_PAT_GENERAL), 1);
        } else if (request.containsKey("direction")) {
            Map<String, Object> direction = Json.object(request.get("direction"), "'direction'");
            int count = count(direction);
            double spacing = Json.number(direction, "spacing");
            Creo.add(elements, Ptc.PRO_E_GENPAT_TYPE, pfcArgument.CreateIntArgValue(Ptc.PRO_GENPAT_DIR_DRIVEN), 1);
            Creo.add(elements, Ptc.PRO_E_GENPAT_REGEN_METHOD, pfcArgument.CreateIntArgValue(Ptc.PRO_PAT_GENERAL), 1);
            Creo.add(elements, Ptc.PRO_E_GENPAT_DIR, null, 1);
            Creo.add(elements, Ptc.PRO_E_DIR_PAT_DIR1_OPT, pfcArgument.CreateIntArgValue(Ptc.PRO_GENPAT_TRANSLATIONAL), 2);
            Creo.add(elements, Ptc.PRO_E_GENPAT_DIR1, null, 2);
            Creo.add(elements, Ptc.PRO_E_DIRECTION_COMPOUND, null, 3);
            Creo.add(elements, Ptc.PRO_E_DIRECTION_REFERENCE,
                    pfcArgument.CreateSelectionArgValue(Geometry.select(solid, Json.string(direction, "along"))), 4);
            // ProPattern.h: PRO_E_DIRECTION_FLIP is ignored for patterns; the dir flip below is 0 or 1.
            Creo.add(elements, Ptc.PRO_E_DIRECTION_FLIP, pfcArgument.CreateIntArgValue(0), 4);
            Creo.add(elements, Ptc.PRO_E_DIR_PAT_DIR1_FLIP, pfcArgument.CreateIntArgValue(spacing < 0 ? 1 : 0), 2);
            Creo.add(elements, Ptc.PRO_E_GENPAT_DIR1_INC, pfcArgument.CreateDoubleArgValue(Math.abs(spacing)), 2);
            // A second direction makes a grid, rows by columns, as the Pattern tool's Direction 2.
            Map<String, Object> second = request.containsKey("direction2")
                    ? Json.object(request.get("direction2"), "'direction2'") : null;
            if (second != null) {
                double spacing2 = Json.number(second, "spacing");
                Creo.add(elements, Ptc.PRO_E_DIR_PAT_DIR2_OPT, pfcArgument.CreateIntArgValue(Ptc.PRO_GENPAT_TRANSLATIONAL), 2);
                Creo.add(elements, Ptc.PRO_E_GENPAT_DIR2, null, 2);
                Creo.add(elements, Ptc.PRO_E_DIRECTION_COMPOUND, null, 3);
                Creo.add(elements, Ptc.PRO_E_DIRECTION_REFERENCE,
                        pfcArgument.CreateSelectionArgValue(Geometry.select(solid, Json.string(second, "along"))), 4);
                Creo.add(elements, Ptc.PRO_E_DIRECTION_FLIP, pfcArgument.CreateIntArgValue(0), 4);
                Creo.add(elements, Ptc.PRO_E_DIR_PAT_DIR2_FLIP, pfcArgument.CreateIntArgValue(spacing2 < 0 ? 1 : 0), 2);
                Creo.add(elements, Ptc.PRO_E_GENPAT_DIR2_INC, pfcArgument.CreateDoubleArgValue(Math.abs(spacing2)), 2);
            }
            Creo.add(elements, Ptc.PRO_E_GENPAT_DIM_FIRST_DIR, null, 2);
            Creo.add(elements, Ptc.PRO_E_GENPAT_DIM_FIRST_DIR_NUM_INST, pfcArgument.CreateIntArgValue(count), 2);
            if (second != null) {
                Creo.add(elements, Ptc.PRO_E_GENPAT_DIM_SECOND_DIR, null, 2);
                Creo.add(elements, Ptc.PRO_E_GENPAT_DIM_SECOND_DIR_NUM_INST,
                        pfcArgument.CreateIntArgValue(count(second)), 2);
            }
        } else {
            throw new Failures.Refusal("E_VALIDATION", "a pattern needs 'direction' or 'axis'");
        }
        String name = Json.string(request, "name", null);
        if (name != null) {
            Creo.add(elements, Ptc.PRO_E_STD_FEATURE_NAME, pfcArgument.CreateStringArgValue(name), 1);
        }
        Map<String, Object> before = Creo.measure(solid);
        java.util.Set<Integer> existing = new java.util.HashSet<>();
        com.ptc.pfc.pfcFeature.Features old = solid.ListFeaturesByType(Boolean.FALSE, null);
        for (int i = 0; old != null && i < old.getarraysize(); i++) {
            existing.add(old.get(i).GetId());
        }
        try {
            ((WFeature) leader).CreatePattern(((WSession) session).CreateElementTree(elements),
                    com.ptc.wfc.wfcFeature.PatternType.FEAT_PATTERN);
        } catch (Exception failure) {
            throw new Failures.Stage("create", failure);
        }
        Creo.repaint(session);
        List<Object> members = new ArrayList<>();
        try {
            com.ptc.pfc.pfcFeature.FeaturePattern made = solid.GetFeatureById(leader.GetId()).GetPattern();
            com.ptc.pfc.pfcFeature.Features all = made == null ? null : made.ListMembers();
            for (int i = 0; all != null && i < all.getarraysize(); i++) {
                members.add(Json.map("id", all.get(i).GetId(), "name", all.get(i).GetName()));
            }
        } catch (Throwable unreadable) {
            // Reported as an empty list; the CLI checks the count.
        }
        // CreatePattern hands back the leader on Creo 13.4, not the pattern; the pattern is the
        // new feature of type FEATTYPE_PATTERN_HEAD, which carries the name.
        Feature reported = null;
        com.ptc.pfc.pfcFeature.Features now = solid.ListFeaturesByType(Boolean.FALSE, null);
        for (int i = 0; reported == null && now != null && i < now.getarraysize(); i++) {
            Feature f = now.get(i);
            if (!existing.contains(f.GetId())
                    && f.GetFeatType().getValue() == com.ptc.pfc.pfcFeature.FeatureType._FEATTYPE_PATTERN_HEAD) {
                reported = f;
            }
        }
        return Extrude.built(solid, reported != null ? reported : leader, before, Json.map("members", members));
    }

    private static int count(Map<String, Object> from) {
        int count = Json.integer(from, "count");
        if (count < 2 || count > 500) {
            throw new Failures.Refusal("E_VALIDATION", "'count' is the number of instances, the original included: "
                    + "2 to 500");
        }
        return count;
    }

    // ------------------------------------------------------------------ mirror

    /**
     * Mirror the whole part about a plane and merge the copy, as Mirror does with the part
     * selected -- for a part modelled as one half. ProMirror.h: mirroring features by
     * element tree is not supported, the part is.
     */
    static Map<String, Object> mirror(Map<String, Object> request) throws Exception {
        Session session = Creo.session();
        Solid solid = Creo.part(session, Json.string(request, "model"));
        Elements elements = start(Ptc.PRO_FEAT_GEN_MERGE, request);
        Creo.add(elements, Ptc.PRO_E_SRF_TRANS_TYPE, pfcArgument.CreateIntArgValue(Ptc.PRO_SURF_TRANS_TYPE_PART_MIRROR), 1);
        Selections items = Selections.create();
        items.append(pfcSelect.CreateModelSelection((com.ptc.pfc.pfcModel.Model) solid));
        Element refs = Creo.add(elements, Ptc.PRO_E_MIRROR_REF_ITEMS, null, 1);
        refs.SetSelections(items);
        Creo.add(elements, Ptc.PRO_E_MIRROR_REF_PLANE,
                pfcArgument.CreateSelectionArgValue(Geometry.select(solid, Json.string(request, "plane"))), 1);
        Creo.add(elements, Ptc.PRO_E_COPY_NO_COPY, pfcArgument.CreateIntArgValue(Ptc.PRO_MIRROR_KEEP_ORIGINAL), 1);
        Map<String, Object> before = Creo.measure(solid);
        WFeature feature = create(session, solid, elements, FeatCreateOption.FEAT_CR_DEFINE_MISS_ELEMS);
        return Extrude.built(solid, feature, before, Json.map());
    }

    // ------------------------------------------------------------------ common

    /** The root, the feature type and, when given, the name every tree here starts with. */
    private static Elements start(int featureType, Map<String, Object> request) throws jxthrowable {
        Elements elements = Elements.create();
        Creo.add(elements, Ptc.PRO_E_FEATURE_TREE, null, 0);
        Creo.add(elements, Ptc.PRO_E_FEATURE_TYPE, pfcArgument.CreateIntArgValue(featureType), 1);
        String name = Json.string(request, "name", null);
        if (name != null) {
            Creo.add(elements, Ptc.PRO_E_STD_FEATURE_NAME, pfcArgument.CreateStringArgValue(name), 1);
        }
        return elements;
    }

    /** Create the feature; a failure is a refusal by Creo, and nothing is left behind. */
    static WFeature create(Session session, Solid solid, Elements elements, FeatCreateOption option)
            throws Exception {
        WFeature feature;
        try {
            feature = ((WSolid) solid).WCreateFeature(((WSession) session).CreateElementTree(elements),
                    Creo.options(option), wfcSolidInstructions.WRegenInstructions_Create());
        } catch (Exception failure) {
            throw new Failures.Stage("create", failure);
        }
        // A tree Creo accepts but cannot regenerate -- a draft of a face the hinge never
        // meets -- comes back as a feature that failed, not as an exception. It goes, so
        // nothing is left behind on this path either.
        com.ptc.pfc.pfcFeature.FeatureStatus status = solid.GetFeatureById(feature.GetId()).GetStatus();
        if (status.getValue() != com.ptc.pfc.pfcFeature.FeatureStatus._FEAT_ACTIVE) {
            Failures.Stage failed = new Failures.Stage("regenerate", new Failures.Refusal("E_CREO",
                    "Creo made the feature but could not regenerate it (" + Creo.enumName(status) + ")"));
            failed.cleanup = Extrude.deleteFeature(solid, feature);
            Creo.repaint(session);
            throw failed;
        }
        Creo.repaint(session);
        return feature;
    }

    private static List<String> strings(Map<String, Object> request, String key, int min, int max) {
        Object raw = request.get(key);
        if (raw == null && min == 0) {
            return new ArrayList<>();
        }
        if (!(raw instanceof List) || ((List<?>) raw).size() < min || ((List<?>) raw).size() > max) {
            throw new Failures.Refusal("E_VALIDATION", "'" + key + "' must list " + min + " to " + max + " references");
        }
        List<String> out = new ArrayList<>();
        for (Object item : (List<?>) raw) {
            if (!(item instanceof String) || ((String) item).isEmpty()) {
                throw new Failures.Refusal("E_VALIDATION", "'" + key + "' holds reference strings");
            }
            out.add((String) item);
        }
        return out;
    }
}
