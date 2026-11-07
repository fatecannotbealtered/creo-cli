/*
 * The C library of creo-cli's host component: the few things Creo's Object TOOLKIT Java
 * cannot do, done with Creo TOOLKIT. The host loads it with Session.LoadProToolkitDll and calls
 * its functions with Dll.ExecuteFunction, on Creo's main thread.
 *
 * Every function takes its inputs as named arguments and answers one output argument,
 * "result": a JSON object as text. A function that fails returns a ProError other than
 * PRO_TK_NO_ERROR and puts {"message": ...} in "result".
 *
 * plugin install compiles this file on the user's computer against the user's own Creo TOOLKIT
 * and unlocks the DLL with the user's own license; no binary of it is shipped.
 */
#include <windows.h>
#include <ProToolkit.h>
#include <ProToolkitDll.h>
#include <ProArray.h>
#include <ProCore.h>
#include <ProMdl.h>
#include <ProUtil.h>
#include <ProValue.h>
#include <ProView.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>

/* Must match Native.VERSION in the Java host: the two are built from the same sources. */
#define CCN_VERSION "1"
#define RESTORE_VIEW "CREO_CLI_RESTORE"

/* ------------------------------------------------------------------ the result text */

/* Not OUT: windows.h defines OUT and IN as empty markers. */
static char TEXT[262144];
static size_t TEXT_LEN;

static void out_reset(void)
{
    TEXT_LEN = 0;
    TEXT[0] = 0;
}

static void out_add(const char *fmt, ...)
{
    va_list ap;
    int n;
    if (TEXT_LEN >= sizeof(TEXT) - 1) return;
    va_start(ap, fmt);
    n = vsnprintf(TEXT + TEXT_LEN, sizeof(TEXT) - TEXT_LEN, fmt, ap);
    va_end(ap);
    if (n < 0) return;
    TEXT_LEN += (size_t)n;
    if (TEXT_LEN >= sizeof(TEXT)) TEXT_LEN = sizeof(TEXT) - 1;
}

/* A JSON string: quotes, backslashes and control characters escaped. */
static void out_string(const char *text)
{
    const unsigned char *p = (const unsigned char *)text;
    out_add("\"");
    for (; *p; p++) {
        if (*p == '"' || *p == '\\') out_add("\\%c", *p);
        else if (*p < 0x20) out_add("\\u%04x", *p);
        else out_add("%c", *p);
    }
    out_add("\"");
}

static ProError answer(ProArgument **outputs, ProError status)
{
    ProArgument arg;
    memset(&arg, 0, sizeof(arg));
    ProArrayAlloc(0, sizeof(ProArgument), 1, (ProArray *)outputs);
    ProStringToWstring(arg.label, "result");
    arg.value.type = PRO_VALUE_TYPE_STRING;
    ProValuedataStringSet(&arg.value, TEXT);
    ProArrayObjectAdd((ProArray *)outputs, PRO_VALUE_UNUSED, 1, &arg);
    return status;
}

static ProError fail(ProArgument **outputs, ProError status, const char *message)
{
    out_reset();
    out_add("{\"message\": ");
    out_string(message);
    out_add(", \"status\": %d}", (int)status);
    return answer(outputs, status == PRO_TK_NO_ERROR ? PRO_TK_GENERAL_ERROR : status);
}

/* ------------------------------------------------------------------ the inputs */

static ProValueData *input(ProArgument *in, const char *label)
{
    int n = 0, i;
    char name[PRO_NAME_SIZE];
    if (in == NULL || ProArraySizeGet((ProArray)in, &n) != PRO_TK_NO_ERROR) return NULL;
    for (i = 0; i < n; i++) {
        ProWstringToString(name, in[i].label);
        if (strcmp(name, label) == 0) return &in[i].value;
    }
    return NULL;
}

static int input_int(ProArgument *in, const char *label, int fallback)
{
    ProValueData *v = input(in, label);
    return v != NULL && v->type == PRO_VALUE_TYPE_INT ? v->v.i : fallback;
}

static const char *input_text(ProArgument *in, const char *label)
{
    ProValueData *v = input(in, label);
    return v != NULL && v->type == PRO_VALUE_TYPE_STRING ? v->v.s : NULL;
}

/* The model the host names by its file name and type: "PAD", part, assembly or drawing. */
static ProError named_model(ProArgument *in, ProMdl *model)
{
    const char *name = input_text(in, "model");
    const char *kind = input_text(in, "kind");
    ProMdlName wname;
    ProMdlfileType type = PRO_MDLFILE_PART;
    if (name == NULL) return PRO_TK_BAD_INPUTS;
    if (kind != NULL && strcmp(kind, "assembly") == 0) type = PRO_MDLFILE_ASSEMBLY;
    else if (kind != NULL && strcmp(kind, "drawing") == 0) type = PRO_MDLFILE_DRAWING;
    ProStringToWstring(wname, (char *)name);
    return ProMdlnameInit(wname, type, model);
}

/* ------------------------------------------------------------------ version */

PRO_TK_DLL_EXPORT ProError ccn_version(ProArgument *in, ProArgument **outputs)
{
    out_reset();
    out_add("{\"version\": ");
    out_string(CCN_VERSION);
    out_add("}");
    return answer(outputs, PRO_TK_NO_ERROR);
}

/* ------------------------------------------------------------------ ending Creo */

static void CALLBACK end_now(HWND window, UINT message, UINT_PTR timer, DWORD time)
{
    KillTimer(NULL, timer);
    ProEngineerEnd();
}

/*
 * Ends Creo the way File > Exit does, after the host's call has returned: ProEngineerEnd
 * called inside a call from the Java host crashes Creo, so a Windows timer on Creo's main
 * thread calls it once the call stack has unwound. The host has checked for unsaved changes.
 */
PRO_TK_DLL_EXPORT ProError ccn_end_later(ProArgument *in, ProArgument **outputs)
{
    int delay = input_int(in, "delay_ms", 1000);
    UINT_PTR timer = SetTimer(NULL, 0, (UINT)(delay < 100 ? 100 : delay), end_now);
    if (timer == 0) return fail(outputs, PRO_TK_GENERAL_ERROR, "Windows refused the timer that ends Creo.");
    out_reset();
    out_add("{\"delay_ms\": %d}", delay < 100 ? 100 : delay);
    return answer(outputs, PRO_TK_NO_ERROR);
}

/* ------------------------------------------------------------------ the view of a window */

/*
 * Keeps the model's current orientation as a named view, so that it can be put back after
 * images in other directions. Object TOOLKIT Java refuses to set a view transform.
 */
PRO_TK_DLL_EXPORT ProError ccn_view_keep(ProArgument *in, ProArgument **outputs)
{
    ProMdl model;
    ProView view;
    ProLine name;
    ProError status = named_model(in, &model);
    if (status != PRO_TK_NO_ERROR) return fail(outputs, status, "The model is not in session.");
    ProStringToWstring(name, RESTORE_VIEW);
    status = ProViewStore(model, name, &view);
    if (status != PRO_TK_NO_ERROR) return fail(outputs, status, "Creo did not keep the current view.");
    out_reset();
    out_add("{\"kept\": true}");
    return answer(outputs, PRO_TK_NO_ERROR);
}

/* Puts back the orientation ccn_view_keep kept, then deletes the named view it made. */
PRO_TK_DLL_EXPORT ProError ccn_view_restore(ProArgument *in, ProArgument **outputs)
{
    ProMdl model;
    ProView view;
    ProLine name;
    ProError status = named_model(in, &model);
    if (status != PRO_TK_NO_ERROR) return fail(outputs, status, "The model is not in session.");
    ProStringToWstring(name, RESTORE_VIEW);
    status = ProViewRetrieve(model, name, &view);
    if (status != PRO_TK_NO_ERROR) return fail(outputs, status, "Creo did not put the kept view back.");
    status = ProViewDelete(model, view);
    out_reset();
    out_add("{\"restored\": true, \"deleted\": %s}", status == PRO_TK_NO_ERROR ? "true" : "false");
    return answer(outputs, PRO_TK_NO_ERROR);
}

/* ------------------------------------------------------------------ entry points */

int user_initialize(int argc, char *argv[], char *version, char *build, wchar_t errbuf[80])
{
    return 0;
}

void user_terminate(void)
{
}
