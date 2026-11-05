package com.fateforge.creocli.host;

import com.fateforge.creocli.host.core.HostError;
import com.ptc.cipjava.jxthrowable;
import com.ptc.pfc.pfcBase.UnitType;
import com.ptc.pfc.pfcModel.Model;
import com.ptc.pfc.pfcSolid.Solid;
import com.ptc.pfc.pfcUnits.Unit;

import java.util.Locale;
import java.util.Map;
import java.util.TreeMap;

/**
 * Millimetres and degrees on the CLI side, the model's own units inside Creo (DCLI-080,
 * DCLI-083). A model may be in inches; every length crosses this class on its way in or out.
 */
final class Units {
    private static final Map<String, Double> MM = new TreeMap<>(String.CASE_INSENSITIVE_ORDER);

    static {
        MM.put("mm", 1.0);
        MM.put("millimeter", 1.0);
        MM.put("cm", 10.0);
        MM.put("m", 1000.0);
        MM.put("meter", 1000.0);
        MM.put("in", 25.4);
        MM.put("inch", 25.4);
        MM.put("ft", 304.8);
        MM.put("foot", 304.8);
        MM.put("micron", 0.001);
        MM.put("um", 0.001);
        MM.put("mil", 0.0254);
    }

    private Units() {
    }

    /** How many millimetres one length unit of the model is. */
    static double mmPerUnit(Model model) throws jxthrowable {
        Unit unit = lengthUnit(model);
        double scale = 1.0;
        for (int depth = 0; unit != null && depth < 8; depth++) {
            Double known = MM.get(unit.GetName().trim().toLowerCase(Locale.ROOT));
            if (known != null) {
                return scale * known;
            }
            scale *= unit.GetConversionFactor().GetScale();
            unit = unit.GetReferenceUnit();
        }
        throw new HostError(HostError.UNSUPPORTED, "The model's length unit cannot be converted to millimetres.");
    }

    /** Millimetres per one of this length unit, or null when it is not a length unit creo-cli knows. */
    static Double mmPer(Unit unit) {
        try {
            double scale = 1.0;
            for (int depth = 0; unit != null && depth < 8; depth++) {
                Double known = MM.get(unit.GetName().trim().toLowerCase(Locale.ROOT));
                if (known != null) {
                    return scale * known;
                }
                scale *= unit.GetConversionFactor().GetScale();
                unit = unit.GetReferenceUnit();
            }
        } catch (Throwable unreadable) {
            return null;
        }
        return null;
    }

    /** Millimetres per one unit named in a value, such as the in of 0.5in, or null. */
    static Double mmPer(String name) {
        return MM.get(name.trim().toLowerCase(Locale.ROOT));
    }

    static String lengthName(Model model) {
        try {
            Unit unit = lengthUnit(model);
            return unit == null ? null : unit.GetName();
        } catch (Throwable unreadable) {
            return null;
        }
    }

    static String massName(Model model) {
        try {
            if (!(model instanceof Solid)) {
                return null;
            }
            Unit unit = ((Solid) model).GetPrincipalUnits().GetUnit(UnitType.UNIT_MASS);
            return unit == null ? null : unit.GetName();
        } catch (Throwable unreadable) {
            return null;
        }
    }

    /** How many kilograms one mass unit of the model is, or null when unknown. */
    static Double kgPerUnit(Model model) {
        String name = massName(model);
        if (name == null) {
            return null;
        }
        switch (name.trim().toLowerCase(Locale.ROOT)) {
            case "kg":
            case "kilogram":
                return 1.0;
            case "g":
            case "gram":
                return 0.001;
            case "tonne":
                return 1000.0;
            case "lbm":
            case "pound":
                return 0.45359237;
            default:
                return null;
        }
    }

    private static Unit lengthUnit(Model model) throws jxthrowable {
        if (!(model instanceof Solid)) {
            return null;
        }
        return ((Solid) model).GetPrincipalUnits().GetUnit(UnitType.UNIT_LENGTH);
    }
}
