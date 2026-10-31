package com.fateforge.creocli.service;

import com.ptc.cipjava.jxthrowable;
import com.ptc.cipjava.stringseq;
import com.ptc.pfc.pfcModel.Model;
import com.ptc.pfc.pfcModelItem.RelationOwner;
import com.ptc.pfc.pfcSession.Session;
import com.ptc.pfc.pfcSolid.Solid;
import com.ptc.wfc.wfcSolid.WSolid;
import com.ptc.wfc.wfcSolidInstructions.WRegenInstructions;
import com.ptc.wfc.wfcSolidInstructions.wfcSolidInstructions;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * A model's relations: the equations that tie its dimensions and parameters together --
 * d2 = d1 / 2, a hole kept centred as the block grows -- as a person writes them in Tools >
 * Relations. Setting them replaces the model's own list and regenerates; if the model will
 * not regenerate, the old list goes back.
 */
final class Relations {
    private Relations() {
    }

    static Map<String, Object> list(Map<String, Object> request) throws Exception {
        Solid solid = Creo.solid(Creo.session(), Json.string(request, "model"));
        return Json.map("model", Creo.fileName((Model) solid), "relations", lines((RelationOwner) solid));
    }

    static Map<String, Object> set(Map<String, Object> request) throws Exception {
        Session session = Creo.session();
        Solid solid = Creo.solid(session, Json.string(request, "model"));
        RelationOwner owner = (RelationOwner) solid;
        Object raw = request.get("relations");
        if (!(raw instanceof List)) {
            throw new Failures.Refusal("E_VALIDATION", "'relations' lists the model's relations, one per line");
        }
        stringseq wanted = stringseq.create();
        for (Object line : (List<?>) raw) {
            wanted.append(String.valueOf(line));
        }
        List<Object> before = lines(owner);
        stringseq old = owner.GetRelations();
        Double volumeBefore = Creo.volumeOf(Creo.measure(solid));
        owner.SetRelations(wanted);
        WRegenInstructions regen = wfcSolidInstructions.WRegenInstructions_Create();
        try {
            owner.RegenerateRelations();
        } catch (Throwable failure) {
            Failures.Stage failed = new Failures.Stage("relations", failure);
            failed.cleanup = restore(solid, owner, old);
            throw failed;
        }
        regen.SetUndoIfFail(true);
        regen.SetNoResolveMode(true);
        try {
            ((WSolid) solid).WRegenerate(regen);
        } catch (Throwable failure) {
            Failures.Stage failed = new Failures.Stage("regenerate", failure);
            failed.cleanup = restore(solid, owner, old);
            throw failed;
        }
        List<Object> broken = Dimensions.failedFeatures(solid);
        if (!broken.isEmpty()) {
            Failures.Stage failed = new Failures.Stage("regenerate",
                    new Failures.Refusal("E_CREO", "features failed to regenerate: " + broken));
            failed.cleanup = restore(solid, owner, old);
            throw failed;
        }
        Creo.repaint(session);
        Double volumeAfter = Creo.volumeOf(Creo.measure(solid));
        Map<String, Object> out = Json.map("model", Creo.fileName((Model) solid), "relations", lines(owner),
                "relations_before", before,
                "volume", Json.map("before", volumeBefore, "after", volumeAfter,
                        "change", volumeBefore == null || volumeAfter == null ? null : volumeAfter - volumeBefore));
        out.put("dimensions", Dimensions.list(Json.map("model", Creo.fileName((Model) solid))).get("dimensions"));
        return out;
    }

    private static String restore(Solid solid, RelationOwner owner, stringseq old) {
        try {
            owner.SetRelations(old);
            WRegenInstructions regen = wfcSolidInstructions.WRegenInstructions_Create();
            regen.SetNoResolveMode(true);
            ((WSolid) solid).WRegenerate(regen);
            return "the old relations restored and regenerated";
        } catch (Throwable failure) {
            return "restoring the old relations failed: " + failure.getClass().getSimpleName();
        }
    }

    private static List<Object> lines(RelationOwner owner) throws jxthrowable {
        List<Object> out = new ArrayList<>();
        stringseq all = owner.GetRelations();
        for (int i = 0; all != null && i < all.getarraysize(); i++) {
            out.add(all.get(i));
        }
        return out;
    }
}
