package com.fateforge.creocli.host;

import com.fateforge.creocli.host.core.HostError;
import com.fateforge.creocli.host.core.Json;
import com.ptc.cipjava.jxthrowable;
import com.ptc.pfc.pfcArgument.ArgValue;
import com.ptc.pfc.pfcArgument.ArgValueType;
import com.ptc.pfc.pfcArgument.Arguments;
import com.ptc.pfc.pfcArgument.pfcArgument;
import com.ptc.pfc.pfcProToolkit.Dll;
import com.ptc.pfc.pfcProToolkit.FunctionReturn;
import com.ptc.pfc.pfcSession.Session;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Arrays;
import java.util.Map;

/**
 * The host's C library (plugin/source/native): the few things Object TOOLKIT Java cannot do,
 * done with Creo TOOLKIT. plugin install builds it next to the host's JAR when the computer has
 * a C compiler, Creo TOOLKIT and its development license; without it the host still runs, and
 * only the commands that need the library are refused, with the reason.
 *
 * <p>Each library function takes named arguments and answers a JSON object as text, so the
 * Java side needs no knowledge of TOOLKIT's structures.
 */
final class Native {
    /** Must match CCN_VERSION in creo_cli_native.c: the two are built from the same sources. */
    static final String VERSION = "1";
    static final String DLL = "creo-cli-native.dll";
    private static final String APPLICATION = "creo_cli_native";

    private static Dll dll;
    private static String missing = "plugin install has not built it";

    private Native() {
    }

    /**
     * Loads the library from the folder of the host's JAR. {@code recorded} is what plugin install
     * wrote about it: {"installed": false, "reason": ...} when it could not build it.
     */
    static void load(Session session, Path folder, Map<String, Object> recorded) {
        Path file = folder.resolve(DLL);
        if (!Files.isRegularFile(file)) {
            String reason = recorded == null ? null : Json.string(recorded, "reason", null);
            missing = reason != null ? reason : "plugin install has not built it";
            return;
        }
        try {
            dll = session.LoadProToolkitDll(APPLICATION, file.toString(), folder.toString(), false);
            Object version = call("ccn_version", Json.map()).get("version");
            if (!VERSION.equals(version)) {
                missing = "its version is " + version + ", the host needs " + VERSION + "; run plugin install again";
                dll.Unload();
                dll = null;
            }
        } catch (Throwable failure) {
            dll = null;
            missing = "Creo did not load it: " + failure;
        }
    }

    static boolean available() {
        return dll != null;
    }

    static String missing() {
        return available() ? null : missing;
    }

    /** Calls one library function; a failure the library reports becomes E_NATIVE_FAILURE with its message. */
    static Map<String, Object> call(String function, Map<String, Object> inputs) throws jxthrowable {
        if (dll == null) {
            throw new HostError(HostError.UNSUPPORTED, "This needs creo-cli's C library, which this Creo has not loaded: "
                    + missing + ". It needs Visual Studio's C compiler, the Creo TOOLKIT component and a Creo TOOLKIT "
                    + "development license when plugin install runs; then restart Creo.")
                    .with("knowledge", Arrays.asList("creo-host-component-loading"));
        }
        Arguments args = Arguments.create();
        for (Map.Entry<String, Object> in : inputs.entrySet()) {
            args.append(pfcArgument.Argument_Create(in.getKey(), value(in.getValue())));
        }
        FunctionReturn answer = dll.ExecuteFunction(function, args);
        String text = null;
        Arguments out = answer.GetOutputArguments();
        for (int i = 0; out != null && i < out.getarraysize(); i++) {
            if ("result".equals(out.get(i).GetLabel())) {
                ArgValue v = out.get(i).GetValue();
                text = v.Getdiscr() == ArgValueType.ARG_V_ASCII_STRING ? v.GetASCIIStringValue() : v.GetStringValue();
            }
        }
        Object parsed = text == null ? null : Json.parse(text);
        @SuppressWarnings("unchecked")
        Map<String, Object> result = parsed instanceof Map ? (Map<String, Object>) parsed : Json.map();
        if (answer.GetFunctionReturn() != 0) {
            throw new HostError(HostError.NATIVE, Json.string(result, "message", "The C library's " + function + " failed.")
                    + " (Creo TOOLKIT status " + answer.GetFunctionReturn() + ")");
        }
        return result;
    }

    private static ArgValue value(Object v) throws jxthrowable {
        if (v instanceof Integer || v instanceof Long) {
            return pfcArgument.CreateIntArgValue(((Number) v).intValue());
        }
        if (v instanceof Number) {
            return pfcArgument.CreateDoubleArgValue(((Number) v).doubleValue());
        }
        if (v instanceof Boolean) {
            return pfcArgument.CreateBoolArgValue((Boolean) v);
        }
        return pfcArgument.CreateASCIIStringArgValue(String.valueOf(v));
    }
}
