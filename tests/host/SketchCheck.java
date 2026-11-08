import com.fateforge.creocli.host.core.HostError;
import com.fateforge.creocli.host.core.Json;
import com.fateforge.creocli.host.core.Sketch;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Checks a --sketch value as the host does, without Creo: the planes of a part made from the
 * metric template (TOP, RIGHT, FRONT through the origin) and TOP_22, a plane 22 mm above TOP.
 * Prints {"problems": [...], "program": "..."}, or {"error": code, "message": ...}.
 */
public final class SketchCheck {
    public static void main(String[] args) throws Exception {
        Object value = Json.parse(new String(Files.readAllBytes(Paths.get(args[0])), StandardCharsets.UTF_8));
        Map<String, Sketch.Plane> planes = new LinkedHashMap<>();
        planes.put("TOP", new Sketch.Plane("TOP", 5, new double[] {0, 0, 0}, new double[] {0, 1, 0}));
        planes.put("RIGHT", new Sketch.Plane("RIGHT", 1, new double[] {0, 0, 0}, new double[] {1, 0, 0}));
        planes.put("FRONT", new Sketch.Plane("FRONT", 3, new double[] {0, 0, 0}, new double[] {0, 0, 1}));
        planes.put("TOP_22", new Sketch.Plane("TOP_22", 9, new double[] {10, 22, -4}, new double[] {0, 1, 0}));
        Map<String, Object> out = new LinkedHashMap<>();
        try {
            Sketch sketch = Sketch.read(value, name -> {
                Sketch.Plane p = planes.get(name);
                if (p == null) {
                    throw new HostError(HostError.NOT_FOUND, "no plane " + name);
                }
                return p;
            }, 1.0);
            out.put("problems", sketch.problems);
            out.put("program", sketch.program());
            out.put("named", sketch.namedValues);
        } catch (HostError refused) {
            out.put("error", refused.code);
            out.put("message", refused.getMessage());
        }
        System.out.println(Json.write(out));
    }
}
