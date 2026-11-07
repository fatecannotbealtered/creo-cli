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
#include <ProElement.h>
#include <ProElemId.h>
#include <ProElempath.h>
#include <ProFeature.h>
#include <ProModelitem.h>
#include <ProSecConstr.h>
#include <ProSecdim.h>
#include <ProSecerror.h>
#include <ProSection.h>
#include <ProSelection.h>
#include <ProSolid.h>
#include <math.h>
#include <stdlib.h>
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

/* ------------------------------------------------------------------ sketches */

/*
 * A sketch arrives as a program of lines, one item each, written by the host's Sketch class:
 *
 *   frame ox oy oz ux uy uz vx vy vz    the sketch's origin and x and y axes in model coordinates
 *   ref NAME SURFACE_ID                 a datum plane or planar face, projected into the sketch
 *   line NAME x1 y1 x2 y2               coordinates in the sketch frame, model units
 *   arc NAME cx cy r a1 a2              counterclockwise from a1 to a2, radians, in the sketch frame
 *   circle NAME cx cy r
 *   cline NAME x1 y1 x2 y2              a centerline (construction)
 *   point NAME x y
 *   con TYPE REF...                     a ProConstraintType and its references, NAME:whole|start|end|center
 *   dim NAME TYPE VALUE PX PY REF...    a ProSecdimType, its value, where its text goes, its references
 *
 * The section is built with Creo's intent manager, which needs every constraint stated: it
 * adds a weak dimension for each freedom left. A sketch the program does not fully define
 * therefore ends with weak dimensions; they are reported and the feature is left as it was.
 */


#define MAX_NAMES 512
#define PI_VALUE 3.14159265358979323846

typedef struct {
    char name[64];
    int id;
    int arc;
} Named;

static Named NAMES[MAX_NAMES];
static int NAME_COUNT;
static int OWN_DIMS[MAX_NAMES];
static char OWN_DIM_NAMES[MAX_NAMES][64];
static int OWN_DIM_COUNT;

static int name_find(const char *name)
{
    int i;
    for (i = 0; i < NAME_COUNT; i++) {
        if (strcmp(NAMES[i].name, name) == 0) return i;
    }
    return -1;
}

static void name_add(const char *name, int id, int arc)
{
    if (NAME_COUNT >= MAX_NAMES) return;
    strncpy(NAMES[NAME_COUNT].name, name, 63);
    NAMES[NAME_COUNT].name[63] = 0;
    NAMES[NAME_COUNT].id = id;
    NAMES[NAME_COUNT].arc = arc;
    NAME_COUNT++;
}

static const char *name_of(int id)
{
    int i;
    for (i = 0; i < NAME_COUNT; i++) {
        if (NAMES[i].id == id) return NAMES[i].name;
    }
    return "?";
}

/* The mapping from the sketch frame to Creo's section coordinates. */
typedef struct {
    double o[3], u[3], v[3];
    ProMatrix loc;
    int flip;
} Frame;

static void to_section(const Frame *f, double x, double y, double out[2])
{
    double p[3];
    int k;
    for (k = 0; k < 3; k++) p[k] = f->o[k] + x * f->u[k] + y * f->v[k] - f->loc[3][k];
    out[0] = p[0] * f->loc[0][0] + p[1] * f->loc[0][1] + p[2] * f->loc[0][2];
    out[1] = p[0] * f->loc[1][0] + p[1] * f->loc[1][1] + p[2] * f->loc[1][2];
}

static double angle_to_section(const Frame *f, double a)
{
    double d[3], s, t;
    int k;
    for (k = 0; k < 3; k++) d[k] = cos(a) * f->u[k] + sin(a) * f->v[k];
    s = d[0] * f->loc[0][0] + d[1] * f->loc[0][1] + d[2] * f->loc[0][2];
    t = d[0] * f->loc[1][0] + d[1] * f->loc[1][1] + d[2] * f->loc[1][2];
    return atan2(t, s);
}

static ProSectionPointType point_type(const char *text, int arc, int flip)
{
    if (strcmp(text, "start") == 0) return arc && flip ? PRO_ENT_END : PRO_ENT_START;
    if (strcmp(text, "end") == 0) return arc && flip ? PRO_ENT_START : PRO_ENT_END;
    if (strcmp(text, "center") == 0) return PRO_ENT_CENTER;
    return PRO_ENT_WHOLE;
}

/* "NAME:start" into the section entity ID and the point type. */
static int reference(const char *token, int flip, int *id, ProSectionPointType *type)
{
    char name[64];
    const char *colon = strchr(token, ':');
    size_t n = colon ? (size_t)(colon - token) : strlen(token);
    int at;
    if (n >= sizeof(name)) return 0;
    memcpy(name, token, n);
    name[n] = 0;
    at = name_find(name);
    if (at < 0) return 0;
    *id = NAMES[at].id;
    *type = point_type(colon ? colon + 1 : "whole", NAMES[at].arc, flip);
    return 1;
}

static void add_errors(ProWSecerror *errs, int *first)
{
    int n = 0, i;
    ProMsg msg;
    char text[PRO_LINE_SIZE * 2];
    if (ProSecerrorCount(errs, &n) != PRO_TK_NO_ERROR) return;
    for (i = 0; i < n; i++) {
        ProSecerrorMsgGet(*errs, i, msg);
        ProWstringToString(text, msg);
        if (!*first) out_add(", ");
        *first = 0;
        out_string(text);
    }
}

static ProError sketch_section(ProArgument *in, ProMdl *model, ProFeature *feature, ProElement *tree, ProSection *section)
{
    ProElement sketcher;
    ProElempath path;
    ProElempathItem items[2];
    ProError status = named_model(in, model);
    if (status != PRO_TK_NO_ERROR) return status;
    status = ProFeatureInit((ProSolid)*model, input_int(in, "feature", -1), feature);
    if (status != PRO_TK_NO_ERROR) return status;
    status = ProFeatureElemtreeExtract(feature, NULL, PRO_FEAT_EXTRACT_NO_OPTS, tree);
    if (status != PRO_TK_NO_ERROR) return status;
    items[0].type = PRO_ELEM_PATH_ITEM_TYPE_ID;
    items[0].path_item.elem_id = PRO_E_STD_SECTION;
    items[1].type = PRO_ELEM_PATH_ITEM_TYPE_ID;
    items[1].path_item.elem_id = PRO_E_SKETCHER;
    ProElempathAlloc(&path);
    ProElempathDataSet(path, items, 2);
    status = ProElemtreeElementGet(*tree, path, &sketcher);
    ProElempathFree(&path);
    if (status != PRO_TK_NO_ERROR) return status;
    return ProElementSpecialvalueGet(sketcher, NULL, (ProAppData *)section);
}

static char *next_line(char **cursor)
{
    char *line = *cursor, *end;
    if (line == NULL || *line == 0) return NULL;
    end = strchr(line, '\n');
    if (end) {
        *end = 0;
        *cursor = end + 1;
    } else {
        *cursor = line + strlen(line);
    }
    return line;
}

#define MAX_TOKENS 32

static int split(char *line, char **tokens)
{
    int n = 0;
    char *t = strtok(line, " \t\r");
    while (t != NULL && n < MAX_TOKENS) {
        tokens[n++] = t;
        t = strtok(NULL, " \t\r");
    }
    return n;
}

/*
 * Builds the sketch of an incomplete feature from the program, then redefines the feature
 * with it. Answers the section and solid IDs of each named dimension, and on a sketch that is
 * not fully defined the weak dimensions Creo added, without redefining the feature.
 */
PRO_TK_DLL_EXPORT ProError ccn_sketch(ProArgument *in, ProArgument **outputs)
{
    const char *program = input_text(in, "program");
    char *copy, *cursor, *line, *tokens[MAX_TOKENS];
    ProMdl model;
    ProFeature feature;
    ProElement tree = NULL;
    ProSection section = NULL;
    Frame frame;
    ProError status;
    ProIntlist dims = NULL;
    int ndims = 0, i, j, weak = 0, first = 1, line_no = 0;
    char failure[512];
    ProWSecerror errs;

    if (program == NULL) return fail(outputs, PRO_TK_BAD_INPUTS, "No sketch program was given.");
    status = sketch_section(in, &model, &feature, &tree, &section);
    if (status != PRO_TK_NO_ERROR) return fail(outputs, status, "The feature's sketch could not be opened.");
    memset(&frame, 0, sizeof(frame));
    status = ProSectionLocationGet(section, frame.loc);
    if (status != PRO_TK_NO_ERROR) {
        ProElementFree(&tree);
        return fail(outputs, status, "Creo did not give the sketch's location.");
    }
    status = ProSectionIntentManagerModeSet(section, PRO_B_TRUE);
    if (status != PRO_TK_NO_ERROR) {
        ProElementFree(&tree);
        return fail(outputs, status, "Creo did not switch the sketch to the intent manager.");
    }
    NAME_COUNT = 0;
    OWN_DIM_COUNT = 0;
    failure[0] = 0;
    copy = (char *)malloc(strlen(program) + 1);
    strcpy(copy, program);
    cursor = copy;
    while ((line = next_line(&cursor)) != NULL && failure[0] == 0) {
        int n = split(line, tokens);
        line_no++;
        if (n == 0) continue;
        if (strcmp(tokens[0], "frame") == 0 && n == 10) {
            double det;
            for (i = 0; i < 3; i++) {
                frame.o[i] = atof(tokens[1 + i]);
                frame.u[i] = atof(tokens[4 + i]);
                frame.v[i] = atof(tokens[7 + i]);
            }
            /* Does the sketch frame turn the other way than Creo's section? Then arcs run backwards. */
            {
                double us = frame.u[0] * frame.loc[0][0] + frame.u[1] * frame.loc[0][1] + frame.u[2] * frame.loc[0][2];
                double ut = frame.u[0] * frame.loc[1][0] + frame.u[1] * frame.loc[1][1] + frame.u[2] * frame.loc[1][2];
                double vs = frame.v[0] * frame.loc[0][0] + frame.v[1] * frame.loc[0][1] + frame.v[2] * frame.loc[0][2];
                double vt = frame.v[0] * frame.loc[1][0] + frame.v[1] * frame.loc[1][1] + frame.v[2] * frame.loc[1][2];
                det = us * vt - ut * vs;
            }
            frame.flip = det < 0;
        } else if (strcmp(tokens[0], "ref") == 0 && n == 3) {
            ProModelitem item;
            ProSelection sel;
            int id;
            status = ProModelitemInit(model, atoi(tokens[2]), PRO_SURFACE, &item);
            if (status == PRO_TK_NO_ERROR) status = ProSelectionAlloc(NULL, &item, &sel);
            if (status == PRO_TK_NO_ERROR) {
                status = ProSectionEntityFromProjection(section, sel, &id);
                ProSelectionFree(&sel);
            }
            if (status != PRO_TK_NO_ERROR) snprintf(failure, sizeof(failure), "Creo did not project %s into the sketch (status %d).", tokens[1], (int)status);
            else name_add(tokens[1], id, 0);
        } else if ((strcmp(tokens[0], "line") == 0 || strcmp(tokens[0], "cline") == 0) && n == 6) {
            Pro2dLinedef l;
            double a[2], b[2];
            int id;
            memset(&l, 0, sizeof(l));
            l.type = strcmp(tokens[0], "line") == 0 ? PRO_2D_LINE : PRO_2D_CENTER_LINE;
            to_section(&frame, atof(tokens[2]), atof(tokens[3]), a);
            to_section(&frame, atof(tokens[4]), atof(tokens[5]), b);
            l.end1[0] = a[0]; l.end1[1] = a[1]; l.end2[0] = b[0]; l.end2[1] = b[1];
            status = ProSectionEntityAdd(section, (Pro2dEntdef *)&l, &id);
            if (status != PRO_TK_NO_ERROR) snprintf(failure, sizeof(failure), "Creo did not add %s (status %d).", tokens[1], (int)status);
            else name_add(tokens[1], id, 0);
        } else if (strcmp(tokens[0], "arc") == 0 && n == 7) {
            Pro2dArcdef a;
            double c[2], s0 = angle_to_section(&frame, atof(tokens[5])), s1 = angle_to_section(&frame, atof(tokens[6]));
            int id;
            memset(&a, 0, sizeof(a));
            a.type = PRO_2D_ARC;
            to_section(&frame, atof(tokens[2]), atof(tokens[3]), c);
            a.center[0] = c[0]; a.center[1] = c[1];
            a.radius = atof(tokens[4]);
            if (frame.flip) {
                double t = s0;
                s0 = s1;
                s1 = t;
            }
            while (s1 <= s0) s1 += 2 * PI_VALUE;
            a.start_angle = s0;
            a.end_angle = s1;
            status = ProSectionEntityAdd(section, (Pro2dEntdef *)&a, &id);
            if (status != PRO_TK_NO_ERROR) snprintf(failure, sizeof(failure), "Creo did not add %s (status %d).", tokens[1], (int)status);
            else name_add(tokens[1], id, 1);
        } else if (strcmp(tokens[0], "circle") == 0 && n == 5) {
            Pro2dCircledef c;
            double p[2];
            int id;
            memset(&c, 0, sizeof(c));
            c.type = PRO_2D_CIRCLE;
            to_section(&frame, atof(tokens[2]), atof(tokens[3]), p);
            c.center[0] = p[0]; c.center[1] = p[1];
            c.radius = atof(tokens[4]);
            status = ProSectionEntityAdd(section, (Pro2dEntdef *)&c, &id);
            if (status != PRO_TK_NO_ERROR) snprintf(failure, sizeof(failure), "Creo did not add %s (status %d).", tokens[1], (int)status);
            else name_add(tokens[1], id, 0);
        } else if (strcmp(tokens[0], "point") == 0 && n == 4) {
            Pro2dPointdef pt;
            double p[2];
            int id;
            memset(&pt, 0, sizeof(pt));
            pt.type = PRO_2D_POINT;
            to_section(&frame, atof(tokens[2]), atof(tokens[3]), p);
            pt.pnt[0] = p[0]; pt.pnt[1] = p[1];
            status = ProSectionEntityAdd(section, (Pro2dEntdef *)&pt, &id);
            if (status != PRO_TK_NO_ERROR) snprintf(failure, sizeof(failure), "Creo did not add %s (status %d).", tokens[1], (int)status);
            else name_add(tokens[1], id, 0);
        } else if (strcmp(tokens[0], "con") == 0 && n >= 3) {
            ProSelection *refs = NULL;
            int cid;
            ProArrayAlloc(0, sizeof(ProSelection), 1, (ProArray *)&refs);
            for (i = 2; i < n && failure[0] == 0; i++) {
                int id;
                ProSectionPointType type;
                ProSelection one = NULL;
                if (!reference(tokens[i], frame.flip, &id, &type)) {
                    snprintf(failure, sizeof(failure), "Line %d names %s, which the sketch does not have.", line_no, tokens[i]);
                    break;
                }
                status = ProSectionEntityGetSelected(section, id, type, NULL, PRO_VALUE_UNUSED, &one);
                if (status != PRO_TK_NO_ERROR) {
                    snprintf(failure, sizeof(failure), "Creo did not select %s (status %d).", tokens[i], (int)status);
                    break;
                }
                ProArrayObjectAdd((ProArray *)&refs, PRO_VALUE_UNUSED, 1, &one);
            }
            if (failure[0] == 0) {
                status = ProSectionConstraintCreate(section, refs, n - 2, (ProConstraintType)atoi(tokens[1]), &cid);
                if (status != PRO_TK_NO_ERROR)
                    snprintf(failure, sizeof(failure), "Creo refused the constraint on line %d (type %s, status %d); it may contradict another one.", line_no, tokens[1], (int)status);
            }
            ProArrayFree((ProArray *)&refs);
        } else if (strcmp(tokens[0], "dim") == 0 && n >= 7) {
            int ids[4], dim;
            ProSectionPointType types[4];
            Pro2dPnt place;
            double p[2];
            int count = n - 6;
            if (count > 4) count = 4;
            for (i = 0; i < count; i++) {
                if (!reference(tokens[6 + i], frame.flip, &ids[i], &types[i])) {
                    snprintf(failure, sizeof(failure), "Line %d names %s, which the sketch does not have.", line_no, tokens[6 + i]);
                    break;
                }
            }
            if (failure[0] == 0) {
                to_section(&frame, atof(tokens[4]), atof(tokens[5]), p);
                place[0] = p[0];
                place[1] = p[1];
                status = ProSecdimCreate(section, ids, types, count, (ProSecdimType)atoi(tokens[2]), place, &dim);
                if (status == PRO_TK_NO_ERROR) status = ProSecdimValueSet(section, dim, atof(tokens[3]));
                if (status != PRO_TK_NO_ERROR)
                    snprintf(failure, sizeof(failure), "Creo refused the dimension %s (status %d); it may contradict a constraint or another dimension.", tokens[1], (int)status);
                else if (OWN_DIM_COUNT < MAX_NAMES) {
                    OWN_DIMS[OWN_DIM_COUNT] = dim;
                    strncpy(OWN_DIM_NAMES[OWN_DIM_COUNT], tokens[1], 63);
                    OWN_DIM_NAMES[OWN_DIM_COUNT][63] = 0;
                    OWN_DIM_COUNT++;
                }
            }
        } else {
            snprintf(failure, sizeof(failure), "Line %d of the sketch program is not understood.", line_no);
        }
    }
    free(copy);
    if (failure[0] != 0) {
        ProElementFree(&tree);
        return fail(outputs, PRO_TK_BAD_INPUTS, failure);
    }
    out_reset();
    out_add("{\"errors\": [");
    ProSecerrorAlloc(&errs);
    ProSectionSolve(section, &errs);
    add_errors(&errs, &first);
    ProSecerrorFree(&errs);
    out_add("], \"weak\": [");
    ProSecdimIdsGet(section, &dims, &ndims);
    for (i = 0; i < ndims; i++) {
        int own = 0, *refs = NULL, nr = 0;
        ProSectionPointType *senses = NULL;
        double value = 0;
        ProSecdimType type = 0;
        for (j = 0; j < OWN_DIM_COUNT; j++) {
            if (OWN_DIMS[j] == dims[i]) own = 1;
        }
        if (own) continue;
        ProSecdimValueGet(section, dims[i], &value);
        ProSecdimTypeGet(section, dims[i], &type);
        ProSecdimReferencesGet(section, dims[i], &refs, &senses, &nr);
        out_add("%s{\"type\": %d, \"value\": %.10g, \"refs\": [", weak ? ", " : "", (int)type, value);
        for (j = 0; j < nr; j++) out_add("%s\"%s:%d\"", j ? ", " : "", name_of(refs[j]), (int)senses[j]);
        out_add("]}");
        weak++;
        if (refs) ProArrayFree((ProArray *)&refs);
        if (senses) ProArrayFree((ProArray *)&senses);
    }
    if (dims) ProArrayFree((ProArray *)&dims);
    out_add("]");
    if (weak > 0) {
        ProElementFree(&tree);
        out_add(", \"redefined\": false}");
        return answer(outputs, PRO_TK_NO_ERROR);
    }
    {
        ProFeatureCreateOptions *opts = NULL;
        ProErrorlist redefine_errors;
        ProArrayAlloc(1, sizeof(ProFeatureCreateOptions), 1, (ProArray *)&opts);
        opts[0] = PRO_FEAT_CR_NO_OPTS;
        memset(&redefine_errors, 0, sizeof(redefine_errors));
        status = ProFeatureWithoptionsRedefine(NULL, &feature, tree, opts, PRO_REGEN_NO_FLAGS, &redefine_errors);
        ProArrayFree((ProArray *)&opts);
        ProElementFree(&tree);
        out_add(", \"redefined\": %s, \"status\": %d", status == PRO_TK_NO_ERROR ? "true" : "false", (int)status);
    }
    out_add(", \"dimensions\": [");
    if (status == PRO_TK_NO_ERROR) {
        ProElement tree2 = NULL;
        ProSection section2 = NULL;
        ProIntlist section_ids = NULL, solid_ids = NULL;
        int count = 0, k, written = 0;
        if (sketch_section(in, &model, &feature, &tree2, &section2) == PRO_TK_NO_ERROR
            && ProSectionDimensionIdsGet(section2, &section_ids, &solid_ids, &count) == PRO_TK_NO_ERROR) {
            for (k = 0; k < count; k++) {
                for (j = 0; j < OWN_DIM_COUNT; j++) {
                    if (OWN_DIMS[j] == section_ids[k]) {
                        out_add("%s{\"name\": ", written++ ? ", " : "");
                        out_string(OWN_DIM_NAMES[j]);
                        out_add(", \"section\": %d, \"solid\": %d}", section_ids[k], solid_ids[k]);
                    }
                }
            }
            if (section_ids) ProArrayFree((ProArray *)&section_ids);
            if (solid_ids) ProArrayFree((ProArray *)&solid_ids);
        }
        if (tree2) ProElementFree(&tree2);
    }
    out_add("]}");
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
