package com.fateforge.creocli.service;

import com.ptc.pfc.pfcSession.Session;
import com.ptc.pfc.pfcView.ViewOwner;
import com.ptc.pfc.pfcWindow.Window;
import java.lang.reflect.Proxy;
import java.util.*;

/** SDK-interface substitutes exercise actual compiled cleanup, not native rendering. */
public final class RenderRestoreTest {
    static <T> T fake(Class<T> type, String label, List<String> calls, Set<String> faults) {
        return type.cast(Proxy.newProxyInstance(type.getClassLoader(), new Class<?>[]{type}, (p, m, args) -> {
            if (m.getName().equals("GetId")) return label.equals("previous") ? 2 : 1;
            if (m.getName().equals("GetScreenTransform")) return null;
            String action = label + "." + m.getName();
            if (m.getName().equals("SetConfigOption")) action += ":" + args[0];
            calls.add(action);
            if (faults.contains(action)) throw new IllegalStateException("injected " + action);
            return null;
        }));
    }
    public static void main(String[] args) throws Exception {
        Map<String, Object> configs = new LinkedHashMap<>();
        for (String key : List.of("display_planes", "display_axes", "display_points", "display_coord_sys"))
            configs.put(key, "yes");
        List<String> expected = List.of("session.SetConfigOption:display_planes", "session.SetConfigOption:display_axes",
                "session.SetConfigOption:display_points", "session.SetConfigOption:display_coord_sys",
                "owner.CurrentViewRotate", "window.SetScreenTransform", "window.Repaint", "previous.Activate");
        List<Set<String>> faults = List.of(Set.of(), Set.of(expected.get(0)),
                Set.of(expected.get(4)), Set.of(expected.get(5)), Set.of(expected.get(7)), new HashSet<>(expected));
        for (Set<String> injected : faults) {
            List<String> calls = new ArrayList<>();
            List<Object> errors = Output.restore(fake(Session.class, "session", calls, injected),
                    fake(ViewOwner.class, "owner", calls, injected), fake(Window.class, "window", calls, injected),
                    fake(Window.class, "previous", calls, injected), List.of(new Output.Rotation(com.ptc.pfc.pfcBase.CoordAxis.COORD_AXIS_X, 30)), null, configs);
            if (!calls.equals(expected) || errors.size() != injected.size())
                throw new AssertionError("cleanup skipped or swallowed: " + calls + " / " + errors);
        }
        for (boolean restoreFails : List.of(false, true)) {
            int[] sets = {0};
            Session session = (Session) Proxy.newProxyInstance(Session.class.getClassLoader(),
                    new Class<?>[]{Session.class}, (proxy, method, values) -> {
                        if (method.getName().equals("GetConfigOption")) return "yes";
                        if (method.getName().equals("SetConfigOption") && ++sets[0] == 2 && restoreFails)
                            throw new IllegalStateException("restore failure");
                        return null;
                    });
            IllegalStateException work = new IllegalStateException("work failure");
            try {
                Creo.withConfig(session, "display_planes", "no", () -> { throw work; });
                throw new AssertionError("work/restore exception swallowed");
            } catch (Exception caught) {
                if (sets[0] != 2) throw new AssertionError("restoration not attempted");
                if (!restoreFails && caught != work) throw new AssertionError("original failure lost");
                if (restoreFails && (!(caught instanceof Failures.Stage)
                        || caught.getCause().getSuppressed().length != 1
                        || caught.getCause().getSuppressed()[0] != work))
                    throw new AssertionError("cleanup/original failure lost");
            }
        }
        System.out.println("{\"passed\":8,\"scope\":\"compiled Java cleanup with SDK interface substitutes; not native\"}");
    }
}
