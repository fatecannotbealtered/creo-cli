/*
 * creo_cli_sketch -- the one piece of sketching Object TOOLKIT Java cannot do.
 *
 * A sketch made of several entities -- a rectangle, a polygon -- has to be
 * dimensioned to references projected from the model into the sketch. A person's
 * sketch gets them automatically; the section a toolkit application receives has
 * none, and the Java toolkit has no call that creates them. The C toolkit does:
 * ProSectionEntityFromProjection. That is the reason this file exists: the Java
 * service still builds the feature, chooses the body, the depth and the plane, and
 * reads back the result. This DLL is handed an incomplete feature and finishes its
 * sketch. Its one other job is the drawing's: placing a dimension's text, and reading
 * it back, where a drawing shows it (see "drawing dimensions" below).
 *
 * The work after projecting and drawing is a sequence of section and feature
 * calls whose required order PTC documents only partly, and this library is not
 * cheap to change: Creo asks the user before loading any rebuilt, unsigned toolkit
 * DLL. So the sequence is an input -- a list of named steps -- and trying another
 * order is a change on the Java side, not a rebuild and another prompt.
 *
 * It runs inside Creo's own process. A crash here is a crash of the user's CAD
 * session, so every call is checked, nothing is dereferenced unchecked, and
 * nothing is left allocated on any path.
 *
 * Called from Java through Dll.ExecuteFunction:
 *
 *   inputs   model        wstring  part name without extension
 *            feature_id   int      the incomplete feature
 *            refs         wstring  datum names to project, ';'-separated (two)
 *            entities     wstring  ';'-separated: "L x0 y0 x1 y1", "C cx cy r",
 *                                  "A cx cy r a0 a1" (radians), "S n x0 y0 ..." (a spline
 *                                  through n points), "K x0 y0 x1 y1" (a
 *                                  centerline, a revolve's axis), in the sketch's own
 *                                  axes, measured from where the references cross
 *            dims         wstring  optional, ';'-separated: the dimensions the "plan" step
 *                                  gives the sketch before auto-dimensioning does the rest,
 *                                  each "<type> <d|-> <x> <y> <ref> [<ref>]" -- a ProSecdimType,
 *                                  d for a diameter across a centerline, where its text goes,
 *                                  and what it measures: rv or rh, the reference projected
 *                                  upright or level, or e<index>.<w|s|e|c>, an entity of
 *                                  "entities" (counted from 0) whole or its start, end or centre
 *            direction    int      PRO_E_STD_DIRECTION, set by the "direction" step
 *            steps        wstring  optional, ','-separated, run in order; default
 *                                  im_on,refs,entities,im_off,regenerate,direction,redefine
 *            sketcher_path wstring optional, '/'-separated element ids leading to
 *                                  the sketch; default "447/458", PRO_E_STD_SECTION /
 *                                  PRO_E_SKETCHER, which every standard-section
 *                                  feature (extrude, revolve, ...) shares
 *            cleanup      int      optional, default 1: on failure, delete the
 *                                  incomplete feature here, where the context to do
 *                                  so still exists (Java's delete is refused after)
 *
 *   outputs  failed_step  wstring  the step that failed, or "" on success
 *            steps_done   wstring  the steps that completed, in order
 *            origin_x/_y  double   where the references cross, section coordinates
 *            vertical_ref int      which of refs projected upright (0 or 1), -1 if neither
 *            planned      wstring  after "plan": per planned dimension, ','-separated, the
 *                                  section dimension it became, or x<status> if it failed;
 *                                  empty when the plan over-constrained the sketch and was dropped
 *            plan_dropped wstring  why the plan was dropped -- the solver's messages
 *            dim_ids      wstring  after "readback": "<section dim>:<model dim>," pairs
 *            dims_read    wstring  after "readback": per section dimension, ';'-separated,
 *                                  "<id> <type> <diameter 0|1> <value> <ref>.<point>..." with
 *                                  refs named as in dims (r<index> for a reference)
 *            entities_read wstring after "describe": every entity of the sketch, ';'-separated,
 *                                  "#<id> <L|K|A|C|S|R|?> <numbers>" in the section's own
 *                                  coordinates -- R a reference projected into it, followed by
 *                                  its name, S a spline by its two ends only
 *            constraints  wstring  after "readback": the sketch's constraints other than
 *                                  shared points and level or upright lines, ';'-separated,
 *                                  "<ProConstraintType> <ref>.<point>..."
 *            location     wstring  after the "locate" step: the section's x, y and z axes
 *                                  and origin in the model, twelve numbers, spaces between
 *            projection_refs wstring after "projection_refs": independent projected selections,
 *                                  ';'-separated "#entity item_id surface|other owner_name
 *                                  part|other item_name owner_model_id same_owner path_depth";
 *                                  an empty item name is represented explicitly by '-'
 *            projection_refs_complete int 1 only after every section entity and projection
 *                                  selection was read without failure or truncation
 *            projection_ref_count int projected selections read by that independent step
 *            section_entity_count int total native section entity IDs enumerated by that step
 *            section_entity_roles wstring ';'-separated "#entity projection0|1 construction0|1"
 *                                  with the two flags encoded as separate numeric tokens
 *            section_entity_roles_complete int 1 only after every native entity role was read
 *            section_entity_role_count int complete role entries independently read
 *            projections  int      references projected
 *            entities     int      entities added
 *            messages     wstring  the section solver's own messages, if any
 *            feature_errors wstring  "element_id:error;..." from the redefine
 *            cleanup      wstring  "deleted", "kept", or why deleting failed
 *            status       int      the toolkit status of the failing step, or 0
 *
 *   returns  PRO_TK_NO_ERROR, or the status of the step that failed.
 *
 * Steps: im_on, im_off (ProSectionIntentManagerModeSet); refetch (read the section
 * pointer from the tree again -- switching intent manager may replace it); refs;
 * entities; solve; regenerate; autodim; plan (the planned dimensions, then autodim and
 * regenerate -- and if the plan over-constrains the sketch, its dimensions deleted and
 * autodim and regenerate again: a sketch dimensioned by Creo alone rather than none);
 * readback (after the redefine: what each dimension measures and became in the model, and
 * what Creo holds equal); describe (an existing feature's sketch read as "readback" reads
 * one, with every entity -- for dimension list; it changes nothing and never fails, and is
 * called with cleanup 0); locate (where the section lies in the model,
 * ProSectionLocationGet); set_section (store the section pointer back
 * in the tree); direction; set_int:<path>:<value> (set any integer element, by
 * '/'-separated id path, once the sketch exists -- ProExtrude.h note 3 lists the
 * elements that must wait for it); set_ref:<path>:<axis|edge>:<id> (set a reference
 * element the same way: a revolve's external axis, which Creo drops from a feature
 * whose sketch is still empty); redefine.
 */

#include <ProToolkit.h>
#include <ProToolkitDll.h>
#include <ProCore.h>
#include <ProArray.h>
#include <ProAsmcomp.h>
#include <ProBomballoon.h>
#include <ProDimension.h>
#include <ProDrawing.h>
#include <ProElement.h>
#include <ProElempath.h>
#include <ProElemId.h>
#include <ProFeature.h>
#include <ProFeatType.h>
#include <ProHole.h>
#include <ProItemerr.h>
#include <ProMdl.h>
#include <ProMenu.h>
#include <ProModelitem.h>
#include <ProReference.h>
#include <ProSection.h>
#include <ProSecerror.h>
#include <ProSelection.h>
#include <ProSolid.h>
#include <ProSurface.h>
#include <ProUtil.h>
#include <ProUICmd.h>
#include <ProValue.h>
#include <ProWindows.h>
#include <ProVerstamp.h>
#include <Pro2dEntdef.h>

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <windows.h>
#include <string.h>
#include <wchar.h>

#define MAX_TEXT 8192
#define MAX_REFS 4
#define MAX_SPLINE_POINTS 64
#define MAX_ENTITIES 256
#define MAX_PLAN 128
#define DEFAULT_STEPS "im_on,refs,entities,im_off,regenerate,direction,redefine"

/* ------------------------------------------------------------------ outputs */

static void put(ProArgument **out, const wchar_t *label, ProValueData value)
{
    ProArgument arg;
    memset(&arg, 0, sizeof arg);
    wcsncpy(arg.label, label, PRO_NAME_SIZE - 1);
    arg.value = value;
    ProArrayObjectAdd((ProArray *)out, PRO_VALUE_UNUSED, 1, &arg);
}

static void put_int(ProArgument **out, const wchar_t *label, int v)
{
    ProValueData value;
    memset(&value, 0, sizeof value);
    value.type = PRO_VALUE_TYPE_INT;
    value.v.i = v;
    put(out, label, value);
}

static void put_double(ProArgument **out, const wchar_t *label, double v)
{
    ProValueData value;
    memset(&value, 0, sizeof value);
    value.type = PRO_VALUE_TYPE_DOUBLE;
    value.v.d = v;
    put(out, label, value);
}

/* The caller frees output strings, so they must be the toolkit's own copies. */
static void put_text(ProArgument **out, const wchar_t *label, const wchar_t *text)
{
    ProValueData value;
    memset(&value, 0, sizeof value);
    value.type = PRO_VALUE_TYPE_WSTRING;
    if (ProValuedataWstringSet(&value, (wchar_t *)text) == PRO_TK_NO_ERROR)
        put(out, label, value);
}

static void put_ascii(ProArgument **out, const wchar_t *label, const char *text)
{
    wchar_t wide[MAX_TEXT];
    size_t i;
    for (i = 0; i + 1 < MAX_TEXT && text[i] != 0; i++)
        wide[i] = (wchar_t)(unsigned char)text[i];
    wide[i] = 0;
    put_text(out, label, wide);
}

/* ------------------------------------------------------------------- inputs */

static ProError arg_value(ProArgument *inputs, const wchar_t *label, ProValueData *data)
{
    int size = 0, i;
    if (inputs == NULL || ProArraySizeGet((ProArray)inputs, &size) != PRO_TK_NO_ERROR)
        return PRO_TK_BAD_INPUTS;
    for (i = 0; i < size; i++)
        if (wcscmp(inputs[i].label, label) == 0) {
            *data = inputs[i].value;
            return PRO_TK_NO_ERROR;
        }
    return PRO_TK_E_NOT_FOUND;
}

/* A wide-string input copied to ASCII; everything this DLL is sent is ASCII. */
static ProError arg_text(ProArgument *inputs, const wchar_t *label, char *buffer, size_t size)
{
    ProValueData data;
    size_t i;
    ProError status = arg_value(inputs, label, &data);
    if (status != PRO_TK_NO_ERROR)
        return status;
    if (data.type == PRO_VALUE_TYPE_WSTRING && data.v.w != NULL) {
        for (i = 0; i + 1 < size && data.v.w[i] != 0; i++)
            buffer[i] = data.v.w[i] < 128 ? (char)data.v.w[i] : '?';
        buffer[i] = 0;
        return PRO_TK_NO_ERROR;
    }
    if (data.type == PRO_VALUE_TYPE_STRING && data.v.s != NULL) {
        strncpy(buffer, data.v.s, size - 1);
        buffer[size - 1] = 0;
        return PRO_TK_NO_ERROR;
    }
    return PRO_TK_BAD_INPUTS;
}

/* A model name, kept wide: Creo's names need not be ASCII. */
static ProError arg_name(ProArgument *inputs, const wchar_t *label, ProMdlName name)
{
    ProValueData data;
    ProError status = arg_value(inputs, label, &data);
    if (status != PRO_TK_NO_ERROR)
        return status;
    if (data.type == PRO_VALUE_TYPE_WSTRING && data.v.w != NULL && wcslen(data.v.w) < PRO_MDLNAME_SIZE) {
        wcsncpy(name, data.v.w, PRO_MDLNAME_SIZE - 1);
        name[PRO_MDLNAME_SIZE - 1] = 0;
        return PRO_TK_NO_ERROR;
    }
    if (data.type == PRO_VALUE_TYPE_STRING && data.v.s != NULL && strlen(data.v.s) < PRO_MDLNAME_SIZE) {
        ProStringToWstring(name, data.v.s);
        return PRO_TK_NO_ERROR;
    }
    return PRO_TK_BAD_INPUTS;
}

static ProError arg_int(ProArgument *inputs, const wchar_t *label, int *v)
{
    ProValueData data;
    ProError status = arg_value(inputs, label, &data);
    if (status != PRO_TK_NO_ERROR)
        return status;
    if (data.type != PRO_VALUE_TYPE_INT)
        return PRO_TK_BAD_INPUTS;
    *v = data.v.i;
    return PRO_TK_NO_ERROR;
}

static ProError arg_double(ProArgument *inputs, const wchar_t *label, double *v)
{
    ProValueData data;
    ProError status = arg_value(inputs, label, &data);
    if (status != PRO_TK_NO_ERROR)
        return status;
    if (data.type != PRO_VALUE_TYPE_DOUBLE)
        return PRO_TK_BAD_INPUTS;
    *v = data.v.d;
    return PRO_TK_NO_ERROR;
}

/* --------------------------------------------------------------- geometry */

/* Where two projected reference lines cross, in section coordinates. */
static int intersect(Pro2dLinedef *a, Pro2dLinedef *b, double *x, double *y)
{
    double ax = a->end2[0] - a->end1[0], ay = a->end2[1] - a->end1[1];
    double bx = b->end2[0] - b->end1[0], by = b->end2[1] - b->end1[1];
    double det = ax * by - ay * bx;
    double t;
    if (fabs(det) < 1e-12)
        return 0; /* parallel: they fix no point */
    t = ((b->end1[0] - a->end1[0]) * by - (b->end1[1] - a->end1[1]) * bx) / det;
    *x = a->end1[0] + t * ax;
    *y = a->end1[1] + t * ay;
    return 1;
}

/* Add one "L x0 y0 x1 y1" / "K x0 y0 x1 y1" (centerline) / "C cx cy r" /
   "A cx cy r a0 a1" entity. A revolve takes its axis from the section's centerline. */
/* "S n x0 y0 ... " -- a spline through n points, its ends free: Creo's own interpolation. */
static ProError add_spline(ProSection section, const char *spec, double ox, double oy, int *id)
{
    Pro2dPnt points[MAX_SPLINE_POINTS];
    Pro2dSplinedef spline;
    const char *cursor = spec;
    char *end = NULL;
    long count;
    int i;

    while (*cursor == ' ')
        cursor++;
    if (*cursor != 'S')
        return PRO_TK_BAD_INPUTS;
    cursor++;
    count = strtol(cursor, &end, 10);
    if (end == cursor || count < 2 || count > MAX_SPLINE_POINTS)
        return PRO_TK_BAD_INPUTS;
    cursor = end;
    for (i = 0; i < count; i++) {
        double x = strtod(cursor, &end);
        if (end == cursor)
            return PRO_TK_BAD_INPUTS;
        cursor = end;
        double y = strtod(cursor, &end);
        if (end == cursor)
            return PRO_TK_BAD_INPUTS;
        cursor = end;
        points[i][0] = ox + x;
        points[i][1] = oy + y;
    }
    memset(&spline, 0, sizeof spline);
    spline.type = PRO_2D_SPLINE;
    spline.tangency_type = PRO_2D_SPLINE_TAN_NONE;
    spline.n_points = (unsigned int)count;
    spline.point_arr = points;
    return ProSectionEntityAdd(section, (Pro2dEntdef *)&spline, id);
}

/* One entity of "entities"; its section id comes back in *id. */
static ProError add_entity(ProSection section, const char *spec, double ox, double oy, int *id)
{
    double v[6];
    char kind = 0;
    int n = sscanf(spec, " %c %lf %lf %lf %lf %lf %lf", &kind, &v[0], &v[1], &v[2], &v[3], &v[4], &v[5]);

    *id = -1;
    if (kind == 'S')
        return add_spline(section, spec, ox, oy, id);

    if ((kind == 'L' || kind == 'K') && n == 5) {
        Pro2dLinedef line;
        memset(&line, 0, sizeof line);
        line.type = kind == 'K' ? PRO_2D_CENTER_LINE : PRO_2D_LINE;
        line.end1[0] = ox + v[0];
        line.end1[1] = oy + v[1];
        line.end2[0] = ox + v[2];
        line.end2[1] = oy + v[3];
        return ProSectionEntityAdd(section, (Pro2dEntdef *)&line, id);
    }
    if (kind == 'C' && n == 4 && v[2] > 0) {
        Pro2dCircledef circle;
        memset(&circle, 0, sizeof circle);
        circle.type = PRO_2D_CIRCLE;
        circle.center[0] = ox + v[0];
        circle.center[1] = oy + v[1];
        circle.radius = v[2];
        return ProSectionEntityAdd(section, (Pro2dEntdef *)&circle, id);
    }
    if (kind == 'A' && n == 6 && v[2] > 0) {
        Pro2dArcdef arc;
        memset(&arc, 0, sizeof arc);
        arc.type = PRO_2D_ARC;
        arc.center[0] = ox + v[0];
        arc.center[1] = oy + v[1];
        arc.radius = v[2];
        arc.start_angle = v[3];
        arc.end_angle = v[4];
        return ProSectionEntityAdd(section, (Pro2dEntdef *)&arc, id);
    }
    return PRO_TK_BAD_INPUTS;
}

/* ------------------------------------------------------------ dimensioning */

static void append(char *text, size_t size, const char *more)
{
    size_t used = strlen(text);
    if (used + strlen(more) + 1 < size)
        strcat(text, more);
}

/* What a planned dimension measures, by the names "dims" uses. */
static int plan_ref(const char *text, const int *entity_ids, int entities, const int *ref_ids,
                    const Pro2dLinedef *projected, int projections, int *id, ProSectionPointType *point)
{
    if (text[0] == 'r' && (text[1] == 'v' || text[1] == 'h') && text[2] == 0) {
        int k;
        for (k = 0; k < projections; k++) {
            double dx = fabs(projected[k].end2[0] - projected[k].end1[0]);
            double dy = fabs(projected[k].end2[1] - projected[k].end1[1]);
            if ((dy > dx) == (text[1] == 'v')) {
                *id = ref_ids[k];
                *point = PRO_ENT_WHOLE;
                return 1;
            }
        }
        return 0;
    }
    if (text[0] == 'e') {
        char *end = NULL;
        long index = strtol(text + 1, &end, 10);
        if (end == text + 1 || index < 0 || index >= entities || entity_ids[index] < 0)
            return 0;
        *id = entity_ids[index];
        if (*end == 0 || strcmp(end, ".w") == 0)
            *point = PRO_ENT_WHOLE;
        else if (strcmp(end, ".s") == 0)
            *point = PRO_ENT_START;
        else if (strcmp(end, ".e") == 0)
            *point = PRO_ENT_END;
        else if (strcmp(end, ".c") == 0)
            *point = PRO_ENT_CENTER;
        else
            return 0;
        return 1;
    }
    return 0;
}

/* One planned dimension, "<type> <d|-> <x> <y> <ref> [<ref>]"; its id comes back in *made,
   -1 when Creo refused it. A diameter Creo will not make one is deleted again. */
static ProError plan_dimension(ProSection section, const char *spec, double ox, double oy, const int *entity_ids,
                               int entities, const int *ref_ids, const Pro2dLinedef *projected, int projections,
                               int *made)
{
    int type = 0, ids[2], count = 0, r, read;
    ProSectionPointType points[2];
    char flag[4] = "", refs[2][24];
    double x = 0.0, y = 0.0;
    Pro2dPnt place;
    ProError status;

    *made = -1;
    refs[0][0] = refs[1][0] = 0;
    read = sscanf(spec, " %d %3s %lf %lf %23s %23s", &type, flag, &x, &y, refs[0], refs[1]);
    if (read < 5)
        return PRO_TK_BAD_INPUTS;
    for (r = 0; r < read - 4; r++) {
        if (!plan_ref(refs[r], entity_ids, entities, ref_ids, projected, projections, &ids[count], &points[count]))
            return PRO_TK_BAD_INPUTS;
        count++;
    }
    place[0] = ox + x;
    place[1] = oy + y;
    status = ProSecdimCreate(section, ids, points, count, (ProSecdimType)type, place, made);
    if (status != PRO_TK_NO_ERROR) {
        *made = -1;
        return status;
    }
    if (flag[0] == 'd') {
        status = ProSecdimDiameterSet(section, *made);
        if (status != PRO_TK_NO_ERROR) {
            ProSecdimDelete(section, *made);
            *made = -1;
        }
    }
    return status;
}

/* An entity as the read-back names it: e<index> for one "entities" added, r<index> for a
   projected reference, #<id> for anything else. */
static void entity_name(int id, const int *entity_ids, int entities, const int *ref_ids, int projections,
                        char *out, size_t size)
{
    int k;
    for (k = 0; k < entities; k++) {
        if (entity_ids[k] == id) {
            snprintf(out, size, "e%d", k);
            return;
        }
    }
    for (k = 0; k < projections; k++) {
        if (ref_ids[k] == id) {
            snprintf(out, size, "r%d", k);
            return;
        }
    }
    snprintf(out, size, "#%d", id);
}

/* After the redefine, from the feature's own section: which model dimension each sketch
   dimension became, what each measures, and the constraints that tie entities together. */
static void read_back(ProSection section, const int *entity_ids, int entities, const int *ref_ids, int projections,
                      char *ids_text, size_t ids_size, char *dims_text, size_t dims_size, char *constraints_text,
                      size_t constraints_size)
{
    ProIntlist sec_ids = NULL, solid_ids = NULL, dims = NULL, constraints = NULL;
    int count = 0, k, r;
    char one[160], name[24];

    if (ProSectionDimensionIdsGet(section, &sec_ids, &solid_ids, &count) == PRO_TK_NO_ERROR) {
        for (k = 0; k < count && sec_ids != NULL && solid_ids != NULL; k++) {
            snprintf(one, sizeof one, "%s%d:%d", k ? "," : "", sec_ids[k], solid_ids[k]);
            append(ids_text, ids_size, one);
        }
    }
    if (sec_ids != NULL)
        ProArrayFree((ProArray *)&sec_ids);
    if (solid_ids != NULL)
        ProArrayFree((ProArray *)&solid_ids);

    count = 0;
    if (ProSecdimIdsGet(section, &dims, &count) == PRO_TK_NO_ERROR) {
        for (k = 0; k < count && dims != NULL; k++) {
            ProSecdimType type = PRO_TK_DIM_NONE;
            ProBoolean diameter = PRO_B_FALSE;
            double value = 0.0;
            int *refs = NULL, refs_count = 0;
            ProSectionPointType *points = NULL;
            ProSecdimTypeGet(section, dims[k], &type);
            ProSecdimDiameterInquire(section, dims[k], &diameter);
            ProSecdimValueGet(section, dims[k], &value);
            snprintf(one, sizeof one, "%s%d %d %d %.15g", k ? ";" : "", dims[k], (int)type, diameter ? 1 : 0, value);
            append(dims_text, dims_size, one);
            if (ProSecdimReferencesGet(section, dims[k], &refs, &points, &refs_count) == PRO_TK_NO_ERROR) {
                for (r = 0; r < refs_count && refs != NULL; r++) {
                    entity_name(refs[r], entity_ids, entities, ref_ids, projections, name, sizeof name);
                    snprintf(one, sizeof one, " %s.%d", name, points != NULL ? (int)points[r] : 0);
                    append(dims_text, dims_size, one);
                }
            }
            if (refs != NULL)
                ProArrayFree((ProArray *)&refs);
            if (points != NULL)
                ProArrayFree((ProArray *)&points);
        }
    }
    if (dims != NULL)
        ProArrayFree((ProArray *)&dims);

    count = 0;
    if (ProSectionConstraintsIdsGet(section, &constraints, &count) == PRO_TK_NO_ERROR) {
        for (k = 0; k < count && constraints != NULL; k++) {
            ProConstraintType type;
            ProConstraintStatus how;
            int refs_count = 0, *refs = NULL;
            ProSectionPointType *senses = NULL;
            if (ProSectionConstraintsGet(section, constraints[k], &type, &how, &refs_count, &refs, &senses) !=
                PRO_TK_NO_ERROR)
                continue;
            /* Shared points and level or upright lines are the drawing itself. */
            if (type != PRO_CONSTRAINT_SAME_POINT && type != PRO_CONSTRAINT_HORIZONTAL_ENT &&
                type != PRO_CONSTRAINT_VERTICAL_ENT) {
                snprintf(one, sizeof one, "%s%d", constraints_text[0] ? ";" : "", (int)type);
                append(constraints_text, constraints_size, one);
                for (r = 0; r < refs_count && refs != NULL; r++) {
                    entity_name(refs[r], entity_ids, entities, ref_ids, projections, name, sizeof name);
                    snprintf(one, sizeof one, " %s.%d", name, senses != NULL ? (int)senses[r] : 0);
                    append(constraints_text, constraints_size, one);
                }
            }
            if (refs != NULL)
                ProArrayFree((ProArray *)&refs);
            if (senses != NULL)
                ProArrayFree((ProArray *)&senses);
        }
    }
    if (constraints != NULL)
        ProArrayFree((ProArray *)&constraints);
}

/* Every entity of a section, in its own coordinates, and what each projection projects. */
static void describe_entities(ProSection section, char *text, size_t size)
{
    ProIntlist ids = NULL;
    int count = 0, k;
    char one[256];

    if (ProSectionEntityIdsGet(section, &ids, &count) != PRO_TK_NO_ERROR)
        return;
    for (k = 0; k < count && ids != NULL; k++) {
        Pro2dEntdef *entity = NULL;
        ProBoolean projected = PRO_B_FALSE;
        const char *sep = text[0] ? ";" : "";
        if (ProSectionEntityGet(section, ids[k], &entity) != PRO_TK_NO_ERROR || entity == NULL)
            continue;
        if (ProSectionEntityIsProjection(section, ids[k], &projected) != PRO_TK_NO_ERROR)
            projected = PRO_B_FALSE;
        switch (entity->type) {
        case PRO_2D_LINE:
        case PRO_2D_CENTER_LINE: {
            Pro2dLinedef *line = (Pro2dLinedef *)entity;
            snprintf(one, sizeof one, "%s#%d %c %.15g %.15g %.15g %.15g", sep, ids[k],
                     projected ? 'R' : entity->type == PRO_2D_LINE ? 'L' : 'K', line->end1[0], line->end1[1],
                     line->end2[0], line->end2[1]);
            break;
        }
        case PRO_2D_ARC: {
            Pro2dArcdef *arc = (Pro2dArcdef *)entity;
            snprintf(one, sizeof one, "%s#%d A %.15g %.15g %.15g %.15g %.15g", sep, ids[k], arc->center[0],
                     arc->center[1], arc->radius, arc->start_angle, arc->end_angle);
            break;
        }
        case PRO_2D_CIRCLE: {
            Pro2dCircledef *circle = (Pro2dCircledef *)entity;
            snprintf(one, sizeof one, "%s#%d C %.15g %.15g %.15g", sep, ids[k], circle->center[0], circle->center[1],
                     circle->radius);
            break;
        }
        case PRO_2D_SPLINE: {
            Pro2dSplinedef *spline = (Pro2dSplinedef *)entity;
            if (spline->n_points < 2 || spline->point_arr == NULL)
                continue;
            snprintf(one, sizeof one, "%s#%d S 2 %.15g %.15g %.15g %.15g", sep, ids[k], spline->point_arr[0][0],
                     spline->point_arr[0][1], spline->point_arr[spline->n_points - 1][0],
                     spline->point_arr[spline->n_points - 1][1]);
            break;
        }
        default:
            snprintf(one, sizeof one, "%s#%d ?", sep, ids[k]);
        }
        append(text, size, one);
        if (projected) {
            ProSelection reference = NULL;
            ProModelitem item;
            ProName name;
            if (ProSectionEntityReferenceGet(section, ids[k], &reference) == PRO_TK_NO_ERROR && reference != NULL &&
                ProSelectionModelitemGet(reference, &item) == PRO_TK_NO_ERROR &&
                ProModelitemNameGet(&item, name) == PRO_TK_NO_ERROR) {
                char narrow[PRO_NAME_SIZE * 2];
                ProWstringToString(narrow, name);
                snprintf(one, sizeof one, " %s", narrow);
                append(text, size, one);
            }
            if (reference != NULL)
                ProSelectionFree(&reference);
        }
    }
    if (ids != NULL)
        ProArrayFree((ProArray *)&ids);
}

/* Bounded ASCII wire tokens: never replace or truncate a native identity to make it fit. */
static ProError projection_token(const wchar_t *wide, char *text, size_t size, int allow_empty)
{
    size_t i;
    if (wide == NULL || size < 2)
        return PRO_TK_BAD_INPUTS;
    if (wide[0] == 0) {
        if (!allow_empty)
            return PRO_TK_BAD_INPUTS;
        strcpy(text, "-");
        return PRO_TK_NO_ERROR;
    }
    for (i = 0; wide[i] != 0; i++) {
        if (i + 1 >= size || wide[i] <= 32 || wide[i] >= 127 || wide[i] == L';')
            return PRO_TK_BAD_INPUTS;
        text[i] = (char)wide[i];
    }
    text[i] = 0;
    return PRO_TK_NO_ERROR;
}

/* Actual projection selections, independent of the request's refs and display names.
   All getters must succeed, even for non-projected entities whose classification matters.
   This step reads an existing section and never changes it or cleans up its feature. */
static ProError projection_references(ProSection section, ProMdl target, char *text, size_t size,
                                      int *count_read, int *entity_count, char *roles, size_t roles_size,
                                      int *role_count, int *roles_complete)
{
    ProIntlist ids = NULL;
    int count = 0, i;
    ProError status;
    *count_read = 0;
    *entity_count = 0;
    *role_count = 0;
    *roles_complete = 0;
    text[0] = 0;
    roles[0] = 0;
    status = ProSectionEntityIdsGet(section, &ids, &count);
    if (status != PRO_TK_NO_ERROR)
        goto finish;
    if (count < 0 || count > MAX_ENTITIES || (count > 0 && ids == NULL)) {
        status = PRO_TK_BAD_INPUTS;
        goto finish;
    }
    *entity_count = count;
    /* Classify the complete section first, retaining roles even if a later selection fails. */
    for (i = 0; i < count; i++) {
        ProBoolean projected = PRO_B_FALSE, construction = PRO_B_FALSE;
        char role[80];
        int written;
        size_t used = strlen(roles);
        status = ProSectionEntityIsProjection(section, ids[i], &projected);
        if (status == PRO_TK_NO_ERROR)
            status = ProSectionEntityIsConstruction(section, ids[i], &construction);
        if (status != PRO_TK_NO_ERROR)
            goto finish;
        if ((projected != PRO_B_FALSE && projected != PRO_B_TRUE) ||
            (construction != PRO_B_FALSE && construction != PRO_B_TRUE)) {
            status = PRO_TK_BAD_INPUTS;
            goto finish;
        }
        written = snprintf(role, sizeof role, "%s#%d %d %d", used ? ";" : "", ids[i],
                           projected == PRO_B_TRUE ? 1 : 0, construction == PRO_B_TRUE ? 1 : 0);
        if (written < 0 || (size_t)written >= sizeof role || (size_t)written >= roles_size - used) {
            status = PRO_TK_BAD_INPUTS;
            goto finish;
        }
        memcpy(roles + used, role, (size_t)written + 1);
        (*role_count)++;
    }
    *roles_complete = 1;
    for (i = 0; i < count; i++) {
        ProBoolean projected = PRO_B_FALSE;
        ProSelection reference = NULL;
        ProModelitem item;
        ProMdl owner = NULL;
        ProMdlType owner_type;
        ProMdlName owner_name;
        ProName item_name;
        ProAsmcomppath path;
        int owner_id = -1, written;
        char owner_ascii[PRO_MDLNAME_SIZE], item_ascii[PRO_NAME_SIZE], one[1024];
        size_t used;
        memset(&item, 0, sizeof item);
        memset(&path, 0, sizeof path);
        status = ProSectionEntityIsProjection(section, ids[i], &projected);
        if (status != PRO_TK_NO_ERROR)
            goto finish;
        if (!projected)
            continue;
        status = ProSectionEntityReferenceGet(section, ids[i], &reference);
        if (status == PRO_TK_NO_ERROR && reference == NULL)
            status = PRO_TK_E_NOT_FOUND;
        if (status == PRO_TK_NO_ERROR)
            status = ProSelectionModelitemGet(reference, &item);
        if (status == PRO_TK_NO_ERROR)
            status = ProModelitemMdlGet(&item, &owner);
        if (status == PRO_TK_NO_ERROR && (owner == NULL || owner != item.owner))
            status = PRO_TK_E_NOT_FOUND;
        if (status == PRO_TK_NO_ERROR)
            status = ProMdlMdlnameGet(owner, owner_name);
        if (status == PRO_TK_NO_ERROR)
            status = ProMdlTypeGet(owner, &owner_type);
        if (status == PRO_TK_NO_ERROR)
            status = ProMdlIdGet(owner, &owner_id);
        if (status == PRO_TK_NO_ERROR && item.type == PRO_SURFACE) {
            ProSurface surface = NULL;
            status = ProSurfaceInit(owner, item.id, &surface);
            if (status == PRO_TK_NO_ERROR && surface == NULL)
                status = PRO_TK_E_NOT_FOUND;
        }
        if (status == PRO_TK_NO_ERROR) {
            status = ProModelitemNameGet(&item, item_name);
            /* An actual unnamed surface is a successful identity observation. Other
               errors remain incomplete; never substitute an owner-feature name or ID. */
            if (status == PRO_TK_E_NOT_FOUND) {
                item_name[0] = 0;
                status = PRO_TK_NO_ERROR;
            }
        }
        if (status == PRO_TK_NO_ERROR)
            status = ProSelectionAsmcomppathGet(reference, &path);
        if (reference != NULL)
            ProSelectionFree(&reference);
        if (status != PRO_TK_NO_ERROR)
            goto finish;
        if (owner_id < 0 || path.table_num < 0 || path.table_num > PRO_MAX_ASSEM_LEVEL) {
            status = PRO_TK_BAD_INPUTS;
            goto finish;
        }
        status = projection_token(owner_name, owner_ascii, sizeof owner_ascii, 0);
        if (status == PRO_TK_NO_ERROR)
            status = projection_token(item_name, item_ascii, sizeof item_ascii, 1);
        if (status != PRO_TK_NO_ERROR)
            goto finish;
        used = strlen(text);
        written = snprintf(one, sizeof one, "%s#%d %d %s %s %s %s %d %d %d",
                           used ? ";" : "", ids[i], item.id,
                           item.type == PRO_SURFACE ? "surface" : "other", owner_ascii,
                           owner_type == PRO_MDL_PART ? "part" : "other", item_ascii,
                           owner_id, owner == target ? 1 : 0, path.table_num);
        if (written < 0 || (size_t)written >= sizeof one || (size_t)written >= size - used) {
            status = PRO_TK_BAD_INPUTS;
            goto finish;
        }
        memcpy(text + used, one, (size_t)written + 1);
        (*count_read)++;
    }
finish:
    if (ids != NULL)
        ProArrayFree((ProArray *)&ids);
    return status;
}

/* The section solver's messages, appended; nothing when it had nothing to say. */
static void solver_messages(ProWSecerror errors, wchar_t *out, size_t size)
{
    int count = 0, i;
    if (errors == NULL || ProSecerrorCount(&errors, &count) != PRO_TK_NO_ERROR)
        return;
    for (i = 0; i < count; i++) {
        ProMsg msg;
        if (ProSecerrorMsgGet(errors, i, msg) != PRO_TK_NO_ERROR)
            continue;
        if (wcslen(out) + wcslen(msg) + 3 >= size)
            break;
        if (out[0] != 0)
            wcscat(out, L" | ");
        wcscat(out, msg);
    }
}

static ProError element_at(ProElement tree, int *ids, int depth, ProElement *element)
{
    ProElempath path = NULL;
    ProElempathItem items[4];
    ProError status;
    int i;
    memset(items, 0, sizeof items);
    for (i = 0; i < depth; i++) {
        items[i].type = PRO_ELEM_PATH_ITEM_TYPE_ID;
        items[i].path_item.elem_id = ids[i];
    }
    status = ProElempathAlloc(&path);
    if (status != PRO_TK_NO_ERROR)
        return status;
    status = ProElempathDataSet(path, items, depth);
    if (status == PRO_TK_NO_ERROR)
        status = ProElemtreeElementGet(tree, path, element);
    ProElempathFree(&path);
    return status;
}

/* "447/458" -> {447, 458}; at most four levels, every level a positive id. */
static int parse_path(const char *text, int *ids)
{
    int depth = 0;
    const char *p = text;
    while (*p != 0 && depth < 4) {
        char *end = NULL;
        long id = strtol(p, &end, 10);
        if (end == p || id <= 0)
            return 0;
        ids[depth++] = (int)id;
        if (*end == '/')
            p = end + 1;
        else if (*end == 0 || *end == ':')
            return depth;
        else
            return 0;
    }
    return *p == 0 ? depth : 0;
}

/* ------------------------------------------------------------------ the task */

PRO_TK_DLL_EXPORT ProError creo_cli_sketch(ProArgument *inputs, ProArgument **outputs)
{
    char model_a[PRO_MDLNAME_SIZE], refs_a[MAX_TEXT], entities_a[MAX_TEXT], steps_a[MAX_TEXT];
    char sketcher_path_a[64] = "";
    int sketcher_depth = 2;
    char failed[64] = "", done[MAX_TEXT] = "";
    ProMdlName model_w;
    ProMdl mdl = NULL;
    ProFeature feature;
    ProElement tree = NULL, sketcher = NULL, direction_elem = NULL;
    ProSection section = NULL;
    ProWSecerror sec_errors = NULL;
    ProFeatureCreateOptions *options = NULL;
    ProErrorlist feature_errors;
    Pro2dLinedef projected[MAX_REFS];
    int feature_id = 0, direction = 0, projections = 0, added = 0, cleanup_wanted = 1, i;
    int sketcher_path[4] = {PRO_E_STD_SECTION, PRO_E_SKETCHER, 0, 0};
    int direction_path[1] = {PRO_E_STD_DIRECTION};
    double origin_x = 0.0, origin_y = 0.0;
    wchar_t messages[MAX_TEXT] = L"";
    wchar_t location_text[MAX_TEXT] = L"";
    wchar_t plan_dropped[1024] = L"";
    char dims_a[MAX_TEXT] = "", planned[2048] = "", dim_ids[2048] = "", dims_read[MAX_TEXT] = "";
    char constraints_read[4096] = "", entities_read[MAX_TEXT] = "";
    char projection_refs[MAX_TEXT] = "", section_entity_roles[MAX_TEXT] = "";
    int projection_refs_requested = 0, projection_refs_complete = 0, projection_ref_count = 0;
    int section_entity_count = 0;
    int section_entity_role_count = 0, section_entity_roles_complete = 0;
    int entity_ids[MAX_ENTITIES], ref_ids[MAX_REFS], vertical_ref = -1;
    wchar_t errors_text[MAX_TEXT] = L"";
    const wchar_t *cleanup = L"not needed";
    char *step_cursor, *step, *cursor, *token;
    ProError status;

    memset(&feature, 0, sizeof feature);
    memset(&feature_errors, 0, sizeof feature_errors);
    if (outputs == NULL)
        return PRO_TK_BAD_INPUTS;
    status = ProArrayAlloc(0, sizeof(ProArgument), 8, (ProArray *)outputs);
    if (status != PRO_TK_NO_ERROR)
        return status;

    strcpy(failed, "inputs");
    if ((status = arg_text(inputs, L"model", model_a, sizeof model_a)) != PRO_TK_NO_ERROR ||
        (status = arg_int(inputs, L"feature_id", &feature_id)) != PRO_TK_NO_ERROR ||
        (status = arg_text(inputs, L"refs", refs_a, sizeof refs_a)) != PRO_TK_NO_ERROR ||
        (status = arg_text(inputs, L"entities", entities_a, sizeof entities_a)) != PRO_TK_NO_ERROR ||
        (status = arg_int(inputs, L"direction", &direction)) != PRO_TK_NO_ERROR)
        goto finish;
    if (arg_text(inputs, L"steps", steps_a, sizeof steps_a) != PRO_TK_NO_ERROR || steps_a[0] == 0)
        strcpy(steps_a, DEFAULT_STEPS);
    if (arg_text(inputs, L"dims", dims_a, sizeof dims_a) != PRO_TK_NO_ERROR)
        dims_a[0] = 0;
    if (arg_int(inputs, L"cleanup", &cleanup_wanted) != PRO_TK_NO_ERROR)
        cleanup_wanted = 1;
    if (arg_text(inputs, L"sketcher_path", sketcher_path_a, sizeof sketcher_path_a) == PRO_TK_NO_ERROR &&
        sketcher_path_a[0] != 0) {
        sketcher_depth = parse_path(sketcher_path_a, sketcher_path);
        if (sketcher_depth < 1) {
            status = PRO_TK_BAD_INPUTS;
            goto finish;
        }
    }

    strcpy(failed, "model");
    ProStringToWstring(model_w, model_a);
    if ((status = ProMdlnameInit(model_w, PRO_MDLFILE_PART, &mdl)) != PRO_TK_NO_ERROR)
        goto finish;
    strcpy(failed, "feature");
    if ((status = ProFeatureInit((ProSolid)mdl, feature_id, &feature)) != PRO_TK_NO_ERROR)
        goto finish;
    strcpy(failed, "extract");
    status = ProFeatureElemtreeExtract(&feature, NULL, PRO_FEAT_EXTRACT_NO_OPTS, &tree);
    if (status != PRO_TK_NO_ERROR)
        goto finish;
    strcpy(failed, "section");
    if ((status = element_at(tree, sketcher_path, sketcher_depth, &sketcher)) != PRO_TK_NO_ERROR)
        goto finish;
    status = ProElementSpecialvalueGet(sketcher, NULL, (ProAppData *)&section);
    if (status != PRO_TK_NO_ERROR || section == NULL) {
        if (status == PRO_TK_NO_ERROR)
            status = PRO_TK_E_NOT_FOUND;
        goto finish;
    }
    if ((status = ProSecerrorAlloc(&sec_errors)) != PRO_TK_NO_ERROR)
        goto finish;

    for (step = strtok_s(steps_a, ",", &step_cursor); step != NULL; step = strtok_s(NULL, ",", &step_cursor)) {
        while (*step == ' ')
            step++;
        strncpy(failed, step, sizeof failed - 1);
        failed[sizeof failed - 1] = 0;

        if (strcmp(step, "im_on") == 0) {
            status = ProSectionIntentManagerModeSet(section, PRO_B_TRUE);
        } else if (strcmp(step, "im_off") == 0) {
            status = ProSectionIntentManagerModeSet(section, PRO_B_FALSE);
        } else if (strcmp(step, "refetch") == 0) {
            status = ProElementSpecialvalueGet(sketcher, NULL, (ProAppData *)&section);
            if (status == PRO_TK_NO_ERROR && section == NULL)
                status = PRO_TK_E_NOT_FOUND;
        } else if (strcmp(step, "refs") == 0) {
            /* The references a person's sketch would have: projections of datum planes. */
            char refs_copy[MAX_TEXT];
            strncpy(refs_copy, refs_a, sizeof refs_copy - 1);
            refs_copy[sizeof refs_copy - 1] = 0;
            status = PRO_TK_NO_ERROR;
            for (token = strtok_s(refs_copy, ";", &cursor); token != NULL && status == PRO_TK_NO_ERROR;
                 token = strtok_s(NULL, ";", &cursor)) {
                ProName ref_name;
                ProModelitem item;
                ProSelection selection = NULL;
                Pro2dEntdef *entity = NULL;
                int ent_id = 0;
                while (*token == ' ')
                    token++;
                if (*token == 0)
                    continue;
                if (projections >= MAX_REFS) {
                    status = PRO_TK_BAD_INPUTS;
                    break;
                }
                ProStringToWstring(ref_name, token);
                if ((status = ProModelitemByNameInit(mdl, PRO_SURFACE, ref_name, &item)) != PRO_TK_NO_ERROR)
                    break;
                if ((status = ProSelectionAlloc(NULL, &item, &selection)) != PRO_TK_NO_ERROR)
                    break;
                status = ProSectionEntityFromProjection(section, selection, &ent_id);
                ProSelectionFree(&selection);
                if (status != PRO_TK_NO_ERROR)
                    break;
                if ((status = ProSectionEntityGet(section, ent_id, &entity)) != PRO_TK_NO_ERROR)
                    break;
                if (entity == NULL || entity->type != PRO_2D_LINE) {
                    /* A plane parallel to the sketch plane projects to no line at all. */
                    status = PRO_TK_BAD_INPUTS;
                    break;
                }
                if (fabs(((Pro2dLinedef *)entity)->end2[1] - ((Pro2dLinedef *)entity)->end1[1]) >
                    fabs(((Pro2dLinedef *)entity)->end2[0] - ((Pro2dLinedef *)entity)->end1[0]))
                    vertical_ref = projections;
                ref_ids[projections] = ent_id;
                projected[projections++] = *(Pro2dLinedef *)entity;
            }
            if (status == PRO_TK_NO_ERROR &&
                (projections < 2 || !intersect(&projected[0], &projected[1], &origin_x, &origin_y)))
                status = PRO_TK_BAD_INPUTS;
        } else if (strcmp(step, "entities") == 0) {
            char entities_copy[MAX_TEXT];
            strncpy(entities_copy, entities_a, sizeof entities_copy - 1);
            entities_copy[sizeof entities_copy - 1] = 0;
            status = PRO_TK_NO_ERROR;
            for (token = strtok_s(entities_copy, ";", &cursor); token != NULL && status == PRO_TK_NO_ERROR;
                 token = strtok_s(NULL, ";", &cursor)) {
                while (*token == ' ')
                    token++;
                if (*token == 0)
                    continue;
                if (added >= MAX_ENTITIES) {
                    status = PRO_TK_BAD_INPUTS;
                    break;
                }
                status = add_entity(section, token, origin_x, origin_y, &entity_ids[added]);
                if (status == PRO_TK_NO_ERROR)
                    added++;
            }
            if (status == PRO_TK_NO_ERROR && added == 0)
                status = PRO_TK_BAD_INPUTS;
        } else if (strcmp(step, "solve") == 0) {
            status = ProSectionSolve(section, &sec_errors);
            if (status != PRO_TK_NO_ERROR)
                solver_messages(sec_errors, messages, MAX_TEXT);
        } else if (strcmp(step, "regenerate") == 0) {
            status = ProSectionRegenerate(section, &sec_errors);
            if (status != PRO_TK_NO_ERROR)
                solver_messages(sec_errors, messages, MAX_TEXT);
        } else if (strcmp(step, "plan") == 0) {
            /* Dimensioned as a drafter would, before Creo fills in whatever is left: given
               first, a dimension is one auto-dimensioning does not replace with an equality
               it infers from two numbers that merely coincide. */
            int made[MAX_PLAN], count = 0, k;
            char dims_copy[MAX_TEXT], one[32];
            strncpy(dims_copy, dims_a, sizeof dims_copy - 1);
            dims_copy[sizeof dims_copy - 1] = 0;
            for (token = strtok_s(dims_copy, ";", &cursor); token != NULL && count < MAX_PLAN;
                 token = strtok_s(NULL, ";", &cursor)) {
                ProError one_status = plan_dimension(section, token, origin_x, origin_y, entity_ids, added, ref_ids,
                                                     projected, projections, &made[count]);
                if (made[count] >= 0)
                    snprintf(one, sizeof one, "%s%d", count ? "," : "", made[count]);
                else
                    snprintf(one, sizeof one, "%sx%d", count ? "," : "", (int)one_status);
                append(planned, sizeof planned, one);
                count++;
            }
            status = ProSectionAutodim(section, &sec_errors);
            if (status == PRO_TK_NO_ERROR)
                status = ProSectionRegenerate(section, &sec_errors);
            if (status != PRO_TK_NO_ERROR && count > 0) {
                /* The plan over-constrained it: Creo dimensions it alone. */
                solver_messages(sec_errors, plan_dropped, 1024);
                if (plan_dropped[0] == 0)
                    swprintf(plan_dropped, 1024, L"toolkit error %d", (int)status);
                for (k = 0; k < count; k++)
                    if (made[k] >= 0)
                        ProSecdimDelete(section, made[k]);
                planned[0] = 0;
                ProSecerrorFree(&sec_errors);
                sec_errors = NULL;
                status = ProSecerrorAlloc(&sec_errors);
                if (status == PRO_TK_NO_ERROR)
                    status = ProSectionAutodim(section, &sec_errors);
                if (status == PRO_TK_NO_ERROR)
                    status = ProSectionRegenerate(section, &sec_errors);
            }
            if (status != PRO_TK_NO_ERROR)
                solver_messages(sec_errors, messages, MAX_TEXT);
        } else if (strcmp(step, "readback") == 0) {
            /* From the feature as the redefine left it. Costs the description, never the
               feature, if it fails. */
            ProElement read_tree = NULL, read_sketcher = NULL;
            ProSection read_section = NULL;
            if (ProFeatureElemtreeExtract(&feature, NULL, PRO_FEAT_EXTRACT_NO_OPTS, &read_tree) == PRO_TK_NO_ERROR &&
                element_at(read_tree, sketcher_path, sketcher_depth, &read_sketcher) == PRO_TK_NO_ERROR &&
                read_sketcher != NULL &&
                ProElementSpecialvalueGet(read_sketcher, NULL, (ProAppData *)&read_section) == PRO_TK_NO_ERROR &&
                read_section != NULL)
                read_back(read_section, entity_ids, added, ref_ids, projections, dim_ids, sizeof dim_ids, dims_read,
                          sizeof dims_read, constraints_read, sizeof constraints_read);
            if (read_tree != NULL)
                ProFeatureElemtreeFree(&feature, read_tree);
            status = PRO_TK_NO_ERROR;
        } else if (strcmp(step, "describe") == 0) {
            /* An existing feature's sketch, read and nothing else. */
            describe_entities(section, entities_read, sizeof entities_read);
            read_back(section, entity_ids, 0, ref_ids, 0, dim_ids, sizeof dim_ids, dims_read, sizeof dims_read,
                      constraints_read, sizeof constraints_read);
            status = PRO_TK_NO_ERROR;
        } else if (strcmp(step, "locate") == 0) {
            ProMatrix location;
            status = ProSectionLocationGet(section, location);
            if (status == PRO_TK_NO_ERROR)
                swprintf(location_text, MAX_TEXT,
                         L"%.15g %.15g %.15g %.15g %.15g %.15g %.15g %.15g %.15g %.15g %.15g %.15g",
                         location[0][0], location[0][1], location[0][2], location[1][0], location[1][1],
                         location[1][2], location[2][0], location[2][1], location[2][2], location[3][0],
                         location[3][1], location[3][2]);
        } else if (strcmp(step, "projection_refs") == 0) {
            projection_refs_requested = 1;
            status = projection_references(section, mdl, projection_refs, sizeof projection_refs,
                                           &projection_ref_count, &section_entity_count,
                                           section_entity_roles, sizeof section_entity_roles,
                                           &section_entity_role_count, &section_entity_roles_complete);
            projection_refs_complete = status == PRO_TK_NO_ERROR ? 1 : 0;
        } else if (strcmp(step, "autodim") == 0) {
            status = ProSectionAutodim(section, &sec_errors);
            if (status != PRO_TK_NO_ERROR)
                solver_messages(sec_errors, messages, MAX_TEXT);
        } else if (strcmp(step, "set_section") == 0) {
            status = ProElementSpecialvalueSet(sketcher, (ProAppData)section);
        } else if (strcmp(step, "direction") == 0) {
            /* ProExtrude.h note 3: ignored until the section is complete. */
            status = element_at(tree, direction_path, 1, &direction_elem);
            if (status == PRO_TK_NO_ERROR && direction_elem != NULL)
                status = ProElementIntegerSet(direction_elem, direction);
        } else if (strncmp(step, "set_int:", 8) == 0) {
            int path[4], depth, value;
            const char *value_text;
            ProElement target = NULL;
            depth = parse_path(step + 8, path);
            value_text = strchr(step + 8, ':');
            if (depth < 1 || value_text == NULL || sscanf(value_text + 1, "%d", &value) != 1) {
                status = PRO_TK_BAD_INPUTS;
            } else {
                status = element_at(tree, path, depth, &target);
                if (status == PRO_TK_NO_ERROR && target != NULL)
                    status = ProElementIntegerSet(target, value);
            }
        } else if (strncmp(step, "set_ref:", 8) == 0) {
            int path[4], depth, item_id = 0;
            char kind[8] = "";
            const char *spec;
            ProType type = PRO_TYPE_INVALID;
            ProElement target = NULL;
            ProModelitem item;
            ProSelection selection = NULL;
            ProReference reference = NULL;
            depth = parse_path(step + 8, path);
            spec = strchr(step + 8, ':');
            if (depth >= 1 && spec != NULL && sscanf(spec + 1, "%7[a-z]:%d", kind, &item_id) == 2)
                type = strcmp(kind, "axis") == 0 ? PRO_AXIS : strcmp(kind, "edge") == 0 ? PRO_EDGE
                                                                                   : PRO_TYPE_INVALID;
            if (type == PRO_TYPE_INVALID || item_id <= 0) {
                status = PRO_TK_BAD_INPUTS;
            } else {
                status = element_at(tree, path, depth, &target);
                if (status == PRO_TK_NO_ERROR && target == NULL)
                    status = PRO_TK_E_NOT_FOUND;
                if (status == PRO_TK_NO_ERROR)
                    status = ProModelitemInit(mdl, item_id, type, &item);
                if (status == PRO_TK_NO_ERROR)
                    status = ProSelectionAlloc(NULL, &item, &selection);
                if (status == PRO_TK_NO_ERROR)
                    status = ProSelectionToReference(selection, &reference);
                if (status == PRO_TK_NO_ERROR)
                    status = ProElementReferenceSet(target, reference);
                if (reference != NULL)
                    ProReferenceFree(reference);
                if (selection != NULL)
                    ProSelectionFree(&selection);
            }
        } else if (strcmp(step, "redefine") == 0) {
            if (options == NULL) {
                status = ProArrayAlloc(1, sizeof(ProFeatureCreateOptions), 1, (ProArray *)&options);
                if (status != PRO_TK_NO_ERROR)
                    goto finish;
                options[0] = PRO_FEAT_CR_NO_OPTS;
            }
            status = ProFeatureWithoptionsRedefine(NULL, &feature, tree, options, PRO_REGEN_NO_FLAGS,
                                                   &feature_errors);
            if (status != PRO_TK_NO_ERROR) {
                for (i = 0; i < feature_errors.error_number && feature_errors.error_list != NULL; i++) {
                    wchar_t one[64];
                    swprintf(one, 64, L"%d:%d;", feature_errors.error_list[i].err_item_id,
                             (int)feature_errors.error_list[i].error);
                    if (wcslen(errors_text) + wcslen(one) + 1 < MAX_TEXT)
                        wcscat(errors_text, one);
                }
            }
        } else {
            status = PRO_TK_BAD_INPUTS; /* not a step this library knows */
        }

        if (status != PRO_TK_NO_ERROR)
            goto finish;
        if (strlen(done) + strlen(step) + 2 < sizeof done) {
            if (done[0] != 0)
                strcat(done, ",");
            strcat(done, step);
        }
    }
    failed[0] = 0;

finish:
    /* A tree from ProFeatureElemtreeExtract has its own release, as PTC's template shows. */
    if (tree != NULL) {
        ProFeatureElemtreeFree(&feature, tree);
        tree = NULL;
    }
    if (status != PRO_TK_NO_ERROR && mdl != NULL && feature_id > 0) {
        if (!cleanup_wanted) {
            cleanup = L"kept";
        } else {
            ProFeatureDeleteOptions delete_options[1] = {PRO_FEAT_DELETE_NO_OPTS};
            int ids[1];
            ids[0] = feature_id;
            cleanup = ProFeatureDelete((ProSolid)mdl, ids, 1, delete_options, 1) == PRO_TK_NO_ERROR
                          ? L"deleted" : L"delete failed";
        }
    }
    put_ascii(outputs, L"failed_step", failed);
    put_ascii(outputs, L"steps_done", done);
    put_double(outputs, L"origin_x", origin_x);
    put_double(outputs, L"origin_y", origin_y);
    put_int(outputs, L"projections", projections);
    put_int(outputs, L"vertical_ref", vertical_ref);
    put_int(outputs, L"entities", added);
    if (dims_a[0] != 0)
        put_ascii(outputs, L"planned", planned);
    if (plan_dropped[0] != 0)
        put_text(outputs, L"plan_dropped", plan_dropped);
    if (dim_ids[0] != 0)
        put_ascii(outputs, L"dim_ids", dim_ids);
    if (dims_read[0] != 0)
        put_ascii(outputs, L"dims_read", dims_read);
    if (constraints_read[0] != 0)
        put_ascii(outputs, L"constraints", constraints_read);
    if (entities_read[0] != 0)
        put_ascii(outputs, L"entities_read", entities_read);
    if (projection_refs_requested) {
        put_ascii(outputs, L"projection_refs", projection_refs);
        put_int(outputs, L"projection_refs_complete", projection_refs_complete);
        put_int(outputs, L"projection_ref_count", projection_ref_count);
        put_int(outputs, L"section_entity_count", section_entity_count);
        put_ascii(outputs, L"section_entity_roles", section_entity_roles);
        put_int(outputs, L"section_entity_roles_complete", section_entity_roles_complete);
        put_int(outputs, L"section_entity_role_count", section_entity_role_count);
    }
    put_int(outputs, L"status", (int)status);
    put_text(outputs, L"cleanup", cleanup);
    if (messages[0] != 0)
        put_text(outputs, L"messages", messages);
    if (location_text[0] != 0)
        put_text(outputs, L"location", location_text);
    if (errors_text[0] != 0)
        put_text(outputs, L"feature_errors", errors_text);
    if (options != NULL)
        ProArrayFree((ProArray *)&options);
    if (sec_errors != NULL)
        ProSecerrorFree(&sec_errors);
    return status;
}

/* ------------------------------------------------------- drawing dimensions */

/*
 * The other thing Object TOOLKIT Java cannot do that a drawing needs: place a dimension's
 * text where a drawing shows it, and read back where it went by the same measure.
 * WDimension.Move is ProDimensionMove, which moves a dimension in its owner model and
 * answers NOT_DISPLAYED for a drawing; Dimension2D.SetLocation, deprecated since Creo 4,
 * reads back through a getter that ProDrawing.h says is offset from where the text was put
 * (ProDrawingDimensionPosGet, the text box's centre). ProDrawingDimensionMove and
 * ProDimlocationTextGet are the pair PTC documents together: the second reads the first.
 *
 * A dimension is named by:
 *            drawing     wstring  the drawing's name, without extension
 *            owner       wstring  the model that owns it, without extension: a part, an
 *                                 assembly, or the drawing itself for one made on it
 *            owner_type  wstring  "prt", "asm" or "drw"
 *            dimension   int      its id in its owner
 *            reference   int      1 for a reference dimension, 0 for a driving one
 */
static ProError named_dimension(ProArgument *inputs, ProMdl *drawing, ProModelitem *dimension)
{
    ProMdlName drawing_w, owner_w;
    char type_a[8];
    ProMdl owner = NULL;
    ProMdlfileType owner_file;
    int dim_id = 0, reference = 0;
    ProError status;

    if ((status = arg_name(inputs, L"drawing", drawing_w)) != PRO_TK_NO_ERROR ||
        (status = arg_name(inputs, L"owner", owner_w)) != PRO_TK_NO_ERROR ||
        (status = arg_text(inputs, L"owner_type", type_a, sizeof type_a)) != PRO_TK_NO_ERROR ||
        (status = arg_int(inputs, L"dimension", &dim_id)) != PRO_TK_NO_ERROR ||
        (status = arg_int(inputs, L"reference", &reference)) != PRO_TK_NO_ERROR)
        return status;
    if (strcmp(type_a, "prt") == 0)
        owner_file = PRO_MDLFILE_PART;
    else if (strcmp(type_a, "asm") == 0)
        owner_file = PRO_MDLFILE_ASSEMBLY;
    else if (strcmp(type_a, "drw") == 0)
        owner_file = PRO_MDLFILE_DRAWING;
    else
        return PRO_TK_BAD_INPUTS;
    if ((status = ProMdlnameInit(drawing_w, PRO_MDLFILE_DRAWING, drawing)) != PRO_TK_NO_ERROR ||
        (status = ProMdlnameInit(owner_w, owner_file, &owner)) != PRO_TK_NO_ERROR)
        return status;
    return ProModelitemInit(owner, dim_id, reference ? PRO_REF_DIMENSION : PRO_DIMENSION, dimension);
}

/*
 *   inputs   the dimension, as above, and
 *            x, y        double   where its text goes, in the drawing's screen coordinates
 *   outputs  status      int      the toolkit status, 0 when it moved
 */
PRO_TK_DLL_EXPORT ProError creo_cli_dimension_move(ProArgument *inputs, ProArgument **outputs)
{
    ProMdl drawing = NULL;
    ProModelitem dimension;
    ProVector location;
    double x = 0.0, y = 0.0;
    ProError status;

    if (outputs == NULL)
        return PRO_TK_BAD_INPUTS;
    status = ProArrayAlloc(0, sizeof(ProArgument), 2, (ProArray *)outputs);
    if (status != PRO_TK_NO_ERROR)
        return status;
    if ((status = named_dimension(inputs, &drawing, &dimension)) == PRO_TK_NO_ERROR &&
        (status = arg_double(inputs, L"x", &x)) == PRO_TK_NO_ERROR &&
        (status = arg_double(inputs, L"y", &y)) == PRO_TK_NO_ERROR) {
        location[0] = x;
        location[1] = y;
        location[2] = 0.0;
        status = ProDrawingDimensionMove((ProDrawing)drawing, (ProDimension *)&dimension, location);
    }
    put_int(outputs, L"status", (int)status);
    return status;
}

/*
 *   inputs   the dimension, as above
 *   outputs  status      int      the toolkit status, 0 when read
 *            x, y        double   where its text is, in the drawing's screen coordinates
 */
PRO_TK_DLL_EXPORT ProError creo_cli_dimension_place(ProArgument *inputs, ProArgument **outputs)
{
    ProMdl drawing = NULL;
    ProModelitem dimension;
    ProDimlocation place = NULL;
    ProBoolean elbow = PRO_B_FALSE;
    ProPoint3d text;
    double elbow_length = 0.0;
    ProError status;

    if (outputs == NULL)
        return PRO_TK_BAD_INPUTS;
    status = ProArrayAlloc(0, sizeof(ProArgument), 3, (ProArray *)outputs);
    if (status != PRO_TK_NO_ERROR)
        return status;
    if ((status = named_dimension(inputs, &drawing, &dimension)) == PRO_TK_NO_ERROR &&
        (status = ProDimensionLocationGet((ProDimension *)&dimension, NULL, (ProDrawing)drawing, &place)) ==
            PRO_TK_NO_ERROR) {
        status = ProDimlocationTextGet(place, &elbow, text, &elbow_length);
        if (status == PRO_TK_NO_ERROR) {
            put_double(outputs, L"x", text[0]);
            put_double(outputs, L"y", text[1]);
        }
    }
    if (place != NULL)
        ProDimlocationFree(place);
    put_int(outputs, L"status", (int)status);
    return status;
}

/*
 * A dimension made on the drawing, deleted. Dimension2D.EraseFromModel2D answers without
 * error and leaves the dimension in the drawing (measured on Creo 13.4); ProDimensionDelete
 * deletes a reference or driven dimension. PTC lists it under the TOOLKIT for 3D Drawings
 * licence; without it the status says so.
 *
 *   inputs   the dimension, as above
 *   outputs  status      int      the toolkit status, 0 when deleted
 */
PRO_TK_DLL_EXPORT ProError creo_cli_dimension_delete(ProArgument *inputs, ProArgument **outputs)
{
    ProMdl drawing = NULL;
    ProModelitem dimension;
    ProError status;

    if (outputs == NULL)
        return PRO_TK_BAD_INPUTS;
    status = ProArrayAlloc(0, sizeof(ProArgument), 1, (ProArray *)outputs);
    if (status != PRO_TK_NO_ERROR)
        return status;
    if ((status = named_dimension(inputs, &drawing, &dimension)) == PRO_TK_NO_ERROR)
        status = ProDimensionDelete((ProDimension *)&dimension);
    put_int(outputs, L"status", (int)status);
    return status;
}

/* ------------------------------------------------------------- parts lists */

/*
 * BOM balloons, which Java cannot make: one per component of a parts list, numbered by its
 * row, in a view -- or in the drawing's first view -- as Creo's own Create Balloons places
 * them (ProBomballoonCreate). The drawing must be on screen.
 *
 *   inputs   drawing  wstring  the drawing's name, without extension
 *            table    int      the parts list's table id
 *            view     wstring  the view's name; empty for the drawing's first view
 *   outputs  status   int      the toolkit status, 0 when they were made
 */
PRO_TK_DLL_EXPORT ProError creo_cli_bom_balloons(ProArgument *inputs, ProArgument **outputs)
{
    ProMdlName drawing_w;
    ProName wanted, name;
    char view_a[PRO_NAME_SIZE * 2];
    ProMdl drawing = NULL;
    ProDwgtable table;
    ProView *views = NULL, view = NULL;
    int table_id = 0, count = 0, i;
    ProError status;

    if (outputs == NULL)
        return PRO_TK_BAD_INPUTS;
    status = ProArrayAlloc(0, sizeof(ProArgument), 1, (ProArray *)outputs);
    if (status != PRO_TK_NO_ERROR)
        return status;
    if ((status = arg_name(inputs, L"drawing", drawing_w)) == PRO_TK_NO_ERROR &&
        (status = arg_int(inputs, L"table", &table_id)) == PRO_TK_NO_ERROR &&
        (status = arg_text(inputs, L"view", view_a, sizeof view_a)) == PRO_TK_NO_ERROR &&
        (status = ProMdlnameInit(drawing_w, PRO_MDLFILE_DRAWING, &drawing)) == PRO_TK_NO_ERROR &&
        (status = ProModelitemInit(drawing, table_id, PRO_DRAW_TABLE, (ProModelitem *)&table)) ==
            PRO_TK_NO_ERROR) {
        if (view_a[0] != 0) {
            ProStringToWstring(wanted, view_a);
            status = ProDrawingViewsCollect((ProDrawing)drawing, &views);
            if (status == PRO_TK_NO_ERROR && ProArraySizeGet((ProArray)views, &count) == PRO_TK_NO_ERROR) {
                for (i = 0; i < count && view == NULL; i++)
                    if (ProDrawingViewNameGet((ProDrawing)drawing, views[i], name) == PRO_TK_NO_ERROR &&
                        wcscmp(name, wanted) == 0)
                        view = views[i];
            }
            if (status == PRO_TK_NO_ERROR && view == NULL)
                status = PRO_TK_E_NOT_FOUND;
        }
        if (status == PRO_TK_NO_ERROR)
            status = view != NULL ? ProBomballoonCreate((ProDrawing)drawing, &table, -1, view)
                                  : ProBomballoonAllCreate((ProDrawing)drawing, &table, -1);
    }
    if (views != NULL)
        ProArrayFree((ProArray *)&views);
    put_int(outputs, L"status", (int)status);
    return status;
}

/* Read only: model/assembly and repeat-region identity for every actual BOM cell.
 * C is used because Creo 13's Java GetCellTopModel can throw XTypeMismatch. */
PRO_TK_DLL_EXPORT ProError creo_cli_bom_references(ProArgument *inputs, ProArgument **outputs)
{
    ProMdlName name;
    ProMdl drawing = NULL, model = NULL;
    ProAssembly assembly = NULL;
    ProDwgtable table;
    ProMdlFileName model_w, assembly_w;
    char model_a[PRO_PATH_SIZE * 2], assembly_a[PRO_PATH_SIZE * 2];
    char rows[MAX_TEXT] = "", one[2048];
    int id = 0, nr = 0, nc = 0, r, c, region;
    ProError status;
    if (outputs == NULL) return PRO_TK_BAD_INPUTS;
    status = ProArrayAlloc(0, sizeof(ProArgument), 2, (ProArray *)outputs);
    if (status != PRO_TK_NO_ERROR) return status;
    if ((status = arg_name(inputs, L"drawing", name)) != PRO_TK_NO_ERROR ||
        (status = arg_int(inputs, L"table", &id)) != PRO_TK_NO_ERROR ||
        (status = ProMdlnameInit(name, PRO_MDLFILE_DRAWING, &drawing)) != PRO_TK_NO_ERROR ||
        (status = ProModelitemInit(drawing, id, PRO_DRAW_TABLE, (ProModelitem *)&table)) != PRO_TK_NO_ERROR ||
        (status = ProDwgtableRowsCount(&table, &nr)) != PRO_TK_NO_ERROR ||
        (status = ProDwgtableColumnsCount(&table, &nc)) != PRO_TK_NO_ERROR) goto finish_bom_read;
    if (nr > 100 || nc > 20) { status = PRO_TK_BAD_INPUTS; goto finish_bom_read; }
    for (r = 1; r <= nr; r++) for (c = 1; c <= nc; c++) {
        status = ProDwgtableCellRefmodelGet(&table, c, r, &assembly, &model);
        if (status == PRO_TK_E_NOT_FOUND) { status = PRO_TK_NO_ERROR; continue; }
        if (status != PRO_TK_NO_ERROR) goto finish_bom_read;
        if ((status = ProDwgtableCellRegionGet((ProDrawing)drawing, &table, c - 1, r - 1, &region)) != PRO_TK_NO_ERROR ||
            (status = ProMdlDisplaynameGet(model, PRO_B_TRUE, model_w)) != PRO_TK_NO_ERROR ||
            (status = ProMdlDisplaynameGet((ProMdl)assembly, PRO_B_TRUE, assembly_w)) != PRO_TK_NO_ERROR) goto finish_bom_read;
        ProWstringToString(model_a, model_w);
        ProWstringToString(assembly_a, assembly_w);
        if (strpbrk(model_a, ",;\r\n") || strpbrk(assembly_a, ",;\r\n")) { status = PRO_TK_BAD_INPUTS; goto finish_bom_read; }
        snprintf(one, sizeof one, "%d,%d,%d,%s,%s;", r, c, region, model_a, assembly_a);
        if (strlen(rows) + strlen(one) + 1 >= sizeof rows) { status = PRO_TK_BAD_INPUTS; goto finish_bom_read; }
        strcat(rows, one);
    }
finish_bom_read:
    put_ascii(outputs, L"cells", rows);
    put_int(outputs, L"status", (int)status);
    return status;
}

/* ----------------------------------------------------------- tolerance standard */

/*
 * A part or assembly is named by:
 *            model       wstring  the model's name, without extension
 *            model_type  wstring  "prt" or "asm"
 */
static ProError named_model(ProArgument *inputs, ProMdl *model)
{
    ProMdlName model_w;
    char type_a[8];
    ProError status;

    if ((status = arg_name(inputs, L"model", model_w)) != PRO_TK_NO_ERROR ||
        (status = arg_text(inputs, L"model_type", type_a, sizeof type_a)) != PRO_TK_NO_ERROR)
        return status;
    if (strcmp(type_a, "prt") == 0)
        return ProMdlnameInit(model_w, PRO_MDLFILE_PART, model);
    if (strcmp(type_a, "asm") == 0)
        return ProMdlnameInit(model_w, PRO_MDLFILE_ASSEMBLY, model);
    return PRO_TK_BAD_INPUTS;
}

/*
 * A model's tolerance standard, which ISO fits need: File > Prepare > Model Properties >
 * Tolerance. The Java toolkit has no call for it. Setting it does not regenerate; the Java
 * side does that.
 *
 *   inputs   the model, as above, and
 *            set         int      optional: 1 ANSI, 2 ISO/DIN; absent, it is only read
 *   outputs  standard    int      1 ANSI or 2 ISO/DIN, as the model has it afterwards
 *            status      int      the toolkit status, 0 when it worked
 */
PRO_TK_DLL_EXPORT ProError creo_cli_tolerance_standard(ProArgument *inputs, ProArgument **outputs)
{
    ProMdl model = NULL;
    ProStandard standard = PROSTANDARD_ANSI;
    int wanted = 0;
    ProError status;

    if (outputs == NULL)
        return PRO_TK_BAD_INPUTS;
    status = ProArrayAlloc(0, sizeof(ProArgument), 2, (ProArray *)outputs);
    if (status != PRO_TK_NO_ERROR)
        return status;
    status = named_model(inputs, &model);
    if (status == PRO_TK_NO_ERROR && arg_int(inputs, L"set", &wanted) == PRO_TK_NO_ERROR && wanted != 0) {
        if (wanted == PROSTANDARD_ANSI || wanted == PROSTANDARD_ISO)
            status = ProSolidToleranceStandardSet((ProSolid)model, (ProStandard)wanted);
        else
            status = PRO_TK_BAD_INPUTS;
    }
    if (status == PRO_TK_NO_ERROR)
        status = ProSolidToleranceStandardGet((ProSolid)model, &standard);
    put_int(outputs, L"standard", status == PRO_TK_NO_ERROR ? (int)standard : 0);
    put_int(outputs, L"status", (int)status);
    return status;
}

/*
 * How many decimal places a model dimension's tolerance shows. Java cannot set it, and Creo
 * otherwise shows a tolerance to the dimension's own places: +0.021 came out as +0,02 and
 * +-0.005 as +-0,01.
 *
 *   inputs   the model, as above, and
 *            dimension           int  the dimension's id
 *            tolerance_decimals  int  the places to show
 *   outputs  tolerance_decimals  int  as read back
 *            status              int  the toolkit status, 0 when it worked
 */
/* Observe ISO table ownership, or detach it for an explicit numeric tolerance.
   The Java enum has no TOLTABLE_NONE. Read-only mode never changes the model. */
PRO_TK_DLL_EXPORT ProError creo_cli_numeric_tolerance_table(ProArgument *inputs, ProArgument **outputs)
{
    ProMdl model = NULL;
    ProModelitem dimension;
    ProStandard standard = PROSTANDARD_ANSI;
    ProToleranceTable type = PROTOLTABLE_NONE;
    ProName table = L"";
    int dim_id = 0, detach = 0, column = 0, before = -1;
    ProError status, read;
    HMODULE module = NULL;
    wchar_t image[1024] = L"";
    if (outputs == NULL) return PRO_TK_BAD_INPUTS;
    status = ProArrayAlloc(0, sizeof(ProArgument), 8, (ProArray *)outputs);
    if (status != PRO_TK_NO_ERROR) return status;
    if ((status = named_model(inputs, &model)) == PRO_TK_NO_ERROR &&
        (status = arg_int(inputs, L"dimension", &dim_id)) == PRO_TK_NO_ERROR &&
        (status = arg_int(inputs, L"detach", &detach)) == PRO_TK_NO_ERROR &&
        (status = ProModelitemInit(model, dim_id, PRO_DIMENSION, &dimension)) == PRO_TK_NO_ERROR &&
        (status = ProSolidToleranceStandardGet((ProSolid)model, &standard)) == PRO_TK_NO_ERROR) {
        if (detach != 0 && detach != 1) status = PRO_TK_BAD_INPUTS;
        else if (standard == PROSTANDARD_ISO) {
            read = ProDimensionTollabelGet((ProDimension *)&dimension, &type, table, &column);
            if (read == PRO_TK_E_NOT_FOUND) type = PROTOLTABLE_NONE;
            else if (read != PRO_TK_NO_ERROR) status = read;
            if (status == PRO_TK_NO_ERROR) {
                before = (int)type;
                if (detach && type != PROTOLTABLE_NONE) {
                    status = ProDimensionTollabelSet((ProDimension *)&dimension, PROTOLTABLE_NONE, L"", 0);
                    if (status == PRO_TK_NO_ERROR) {
                        read = ProDimensionTollabelGet((ProDimension *)&dimension, &type, table, &column);
                        if (read == PRO_TK_E_NOT_FOUND) type = PROTOLTABLE_NONE;
                        else if (read != PRO_TK_NO_ERROR) status = read;
                        if (status == PRO_TK_NO_ERROR && type != PROTOLTABLE_NONE) status = PRO_TK_GENERAL_ERROR;
                    }
                }
            }
        } else if (standard == PROSTANDARD_ANSI) before = PROTOLTABLE_NONE;
        else status = PRO_TK_BAD_CONTEXT;
    }
    if (GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
        (LPCWSTR)&creo_cli_numeric_tolerance_table, &module)) GetModuleFileNameW(module, image, 1024);
    put_int(outputs, L"contract_version", 1);
    put_int(outputs, L"standard", (int)standard);
    put_int(outputs, L"before_table_type", before);
    put_int(outputs, L"table_type", status == PRO_TK_NO_ERROR ? (int)type : -1);
    put_int(outputs, L"assigned", status == PRO_TK_NO_ERROR && type != PROTOLTABLE_NONE);
    put_int(outputs, L"status", (int)status);
    put_text(outputs, L"native_image", image);
    return status;
}

PRO_TK_DLL_EXPORT ProError creo_cli_tolerance_decimals(ProArgument *inputs, ProArgument **outputs)
{
    ProMdl model = NULL;
    ProModelitem dimension;
    int dim_id = 0, places = 0, read = -1;
    ProError status;

    if (outputs == NULL)
        return PRO_TK_BAD_INPUTS;
    status = ProArrayAlloc(0, sizeof(ProArgument), 2, (ProArray *)outputs);
    if (status != PRO_TK_NO_ERROR)
        return status;
    if ((status = named_model(inputs, &model)) == PRO_TK_NO_ERROR &&
        (status = arg_int(inputs, L"dimension", &dim_id)) == PRO_TK_NO_ERROR &&
        (status = arg_int(inputs, L"tolerance_decimals", &places)) == PRO_TK_NO_ERROR &&
        (status = ProModelitemInit(model, dim_id, PRO_DIMENSION, &dimension)) == PRO_TK_NO_ERROR &&
        (status = ProDimensionTolerancedecimalsSet((ProDimension *)&dimension, places)) == PRO_TK_NO_ERROR &&
        ProDimensionTolerancedecimalsGet((ProDimension *)&dimension, &read) != PRO_TK_NO_ERROR)
        read = -1;
    put_int(outputs, L"tolerance_decimals", read);
    put_int(outputs, L"status", (int)status);
    return status;
}

/* ----------------------------------------------------------- hole charts */

/* One integer element under a parent; the tree owns it once added. */
static ProError add_int(ProElement parent, ProElemId id, int value, ProElement *made)
{
    ProElement element = NULL;
    ProError status = ProElementAlloc(id, &element);
    if (status == PRO_TK_NO_ERROR)
        status = ProElementIntegerSet(element, value);
    if (status == PRO_TK_NO_ERROR)
        status = ProElemtreeElementAdd(parent, NULL, element);
    if (status != PRO_TK_NO_ERROR) {
        if (element != NULL)
            ProElementFree(&element);
        return status;
    }
    if (made != NULL)
        *made = element;
    return status;
}

/*
 * A standard hole's thread series and screw size as Creo indexes them. The hole's element
 * tree holds both as integers -- positions in lists Creo builds from the .hol files it
 * finds (ProHole.h note 1) -- and only C turns "ISO" and "M6x1" into them, with
 * ProElementHoleThreadSeriesSet and ProElementHoleScrewSizeSet, here on a tree made only
 * for them. The Java side builds the hole.
 *
 *   inputs   model         wstring  the part's name, without extension
 *            series        wstring  the thread series, as a .hol file names it: ISO, UNC
 *            screw         wstring  the fastener id in that file: M6x1
 *   outputs  series_index  int      what PRO_E_HLE_THRDSERIS takes
 *            screw_index   int      what PRO_E_HLE_SCREWSIZE takes
 *            failed_step   wstring  "series" or "screw" when Creo does not know it, else ""
 *            status        int      the toolkit status, 0 when both were found
 */
PRO_TK_DLL_EXPORT ProError creo_cli_hole_indexes(ProArgument *inputs, ProArgument **outputs)
{
    ProMdlName model_w;
    char series_a[PRO_NAME_SIZE], screw_a[PRO_NAME_SIZE];
    wchar_t series_w[PRO_NAME_SIZE], screw_w[PRO_NAME_SIZE];
    ProMdl model = NULL;
    ProElement tree = NULL, com = NULL, series_e = NULL, screw_e = NULL;
    int series_index = -1, screw_index = -1;
    const char *failed = "inputs";
    ProError status;

    if (outputs == NULL)
        return PRO_TK_BAD_INPUTS;
    status = ProArrayAlloc(0, sizeof(ProArgument), 4, (ProArray *)outputs);
    if (status != PRO_TK_NO_ERROR)
        return status;
    if ((status = arg_name(inputs, L"model", model_w)) == PRO_TK_NO_ERROR &&
        (status = arg_text(inputs, L"series", series_a, sizeof series_a)) == PRO_TK_NO_ERROR &&
        (status = arg_text(inputs, L"screw", screw_a, sizeof screw_a)) == PRO_TK_NO_ERROR &&
        (status = ProMdlnameInit(model_w, PRO_MDLFILE_PART, &model)) == PRO_TK_NO_ERROR) {
        failed = "tree";
        ProStringToWstring(series_w, series_a);
        ProStringToWstring(screw_w, screw_a);
        status = ProElementAlloc(PRO_E_FEATURE_TREE, &tree);
        if (status == PRO_TK_NO_ERROR)
            status = add_int(tree, PRO_E_FEATURE_TYPE, PRO_FEAT_HOLE, NULL);
        if (status == PRO_TK_NO_ERROR)
            status = ProElementAlloc(PRO_E_HLE_COM, &com);
        if (status == PRO_TK_NO_ERROR) {
            status = ProElemtreeElementAdd(tree, NULL, com);
            if (status != PRO_TK_NO_ERROR)
                ProElementFree(&com);
        }
        if (status == PRO_TK_NO_ERROR)
            status = add_int(com, PRO_E_HLE_TYPE_NEW, PRO_HLE_NEW_TYPE_STANDARD, NULL);
        if (status == PRO_TK_NO_ERROR)
            status = add_int(com, PRO_E_HLE_STAN_TYPE, PRO_HLE_TAPPED_TYPE, NULL);
        if (status == PRO_TK_NO_ERROR)
            status = add_int(com, PRO_E_HLE_THRDSERIS, 0, &series_e);
        if (status == PRO_TK_NO_ERROR)
            status = add_int(com, PRO_E_HLE_SCREWSIZE, 0, &screw_e);
        if (status == PRO_TK_NO_ERROR) {
            failed = "series";
            status = ProElementHoleThreadSeriesSet(tree, model, series_w);
        }
        if (status == PRO_TK_NO_ERROR) {
            failed = "screw";
            status = ProElementHoleScrewSizeSet(tree, model, screw_w);
        }
        if (status == PRO_TK_NO_ERROR) {
            failed = "read";
            status = ProElementIntegerGet(series_e, NULL, &series_index);
        }
        if (status == PRO_TK_NO_ERROR)
            status = ProElementIntegerGet(screw_e, NULL, &screw_index);
        if (status == PRO_TK_NO_ERROR)
            failed = "";
    }
    if (tree != NULL)
        ProElementFree(&tree);
    put_int(outputs, L"series_index", series_index);
    put_int(outputs, L"screw_index", screw_index);
    put_ascii(outputs, L"failed_step", failed);
    put_int(outputs, L"status", (int)status);
    return status;
}

/* ------------------------------------------------------- component replace */

/*
 * Put another model where an assembly component is, keeping its constraints -- what
 * Component > Replace does. The Java route, ComponentFeat.CreateReplaceOp run by
 * Solid.ExecuteFeatureOps, answers XToolkitBadContext on Creo 13.4, as it does for every
 * feature operation. So, as PTC's own TestAsm example replaces a component: the component's
 * tree extracted, PRO_E_COMPONENT_MODEL (a pointer, which Java cannot set) pointed at the
 * new model, each constraint's component reference pointed at the item of the same id and
 * type in the new model, and the feature redefined. Another instance of the same family
 * has every item its generic has, under the same ids.
 *
 *   inputs   model        wstring  the assembly, without extension
 *            feature_id   int      the component
 *            with         wstring  the new model, without extension
 *            with_type    wstring  prt or asm
 *   outputs  failed_step  wstring  the step that failed, or "" on success
 *            references   int      component references pointed at the new model
 *            status       int      the toolkit status, 0 when it worked
 */
PRO_TK_DLL_EXPORT ProError creo_cli_component_replace(ProArgument *inputs, ProArgument **outputs)
{
    ProMdlName asm_w, with_w;
    char type_a[8];
    ProMdl assembly = NULL, with = NULL;
    ProFeature feature;
    ProElement tree = NULL, model_elem = NULL;
    ProElement *constraints = NULL;
    ProElempath path = NULL;
    ProElempathItem items[1];
    ProFeatureCreateOptions *options = NULL;
    ProErrorlist errors;
    int feature_id = 0, count = 0, moved = 0, i;
    const char *failed = "inputs";
    ProError status;

    memset(&feature, 0, sizeof feature);
    memset(&errors, 0, sizeof errors);
    if (outputs == NULL)
        return PRO_TK_BAD_INPUTS;
    status = ProArrayAlloc(0, sizeof(ProArgument), 3, (ProArray *)outputs);
    if (status != PRO_TK_NO_ERROR)
        return status;
    if ((status = arg_name(inputs, L"model", asm_w)) != PRO_TK_NO_ERROR ||
        (status = arg_int(inputs, L"feature_id", &feature_id)) != PRO_TK_NO_ERROR ||
        (status = arg_name(inputs, L"with", with_w)) != PRO_TK_NO_ERROR ||
        (status = arg_text(inputs, L"with_type", type_a, sizeof type_a)) != PRO_TK_NO_ERROR)
        goto finish;
    failed = "model";
    if ((status = ProMdlnameInit(asm_w, PRO_MDLFILE_ASSEMBLY, &assembly)) != PRO_TK_NO_ERROR)
        goto finish;
    failed = "with";
    if (strcmp(type_a, "prt") == 0)
        status = ProMdlnameInit(with_w, PRO_MDLFILE_PART, &with);
    else if (strcmp(type_a, "asm") == 0)
        status = ProMdlnameInit(with_w, PRO_MDLFILE_ASSEMBLY, &with);
    else
        status = PRO_TK_BAD_INPUTS;
    if (status != PRO_TK_NO_ERROR)
        goto finish;
    failed = "feature";
    if ((status = ProFeatureInit((ProSolid)assembly, feature_id, &feature)) != PRO_TK_NO_ERROR)
        goto finish;
    failed = "extract";
    if ((status = ProFeatureElemtreeExtract(&feature, NULL, PRO_FEAT_EXTRACT_NO_OPTS, &tree)) != PRO_TK_NO_ERROR)
        goto finish;
    failed = "component_model";
    {
        int model_path[1] = {PRO_E_COMPONENT_MODEL};
        if ((status = element_at(tree, model_path, 1, &model_elem)) != PRO_TK_NO_ERROR)
            goto finish;
    }
    if ((status = ProElementSpecialvalueSet(model_elem, (ProAppData)with)) != PRO_TK_NO_ERROR)
        goto finish;
    failed = "constraints";
    memset(items, 0, sizeof items);
    items[0].type = PRO_ELEM_PATH_ITEM_TYPE_ID;
    items[0].path_item.elem_id = PRO_E_COMPONENT_CONSTRAINTS;
    if ((status = ProElempathAlloc(&path)) != PRO_TK_NO_ERROR ||
        (status = ProElempathDataSet(path, items, 1)) != PRO_TK_NO_ERROR)
        goto finish;
    /* Both calls fill an array the caller has allocated (ProElement.h). */
    if ((status = ProArrayAlloc(0, sizeof(ProElement), 4, (ProArray *)&constraints)) != PRO_TK_NO_ERROR)
        goto finish;
    status = ProElementArrayGet(tree, path, &constraints);
    if (status == PRO_TK_NO_ERROR)
        status = ProArraySizeGet((ProArray)constraints, &count);
    if (status != PRO_TK_NO_ERROR)
        goto finish;
    for (i = 0; i < count; i++) {
        ProElement *children = NULL;
        int n = 0, j;
        if (ProArrayAlloc(0, sizeof(ProElement), 8, (ProArray *)&children) != PRO_TK_NO_ERROR)
            continue;
        if (ProElementChildrenGet(constraints[i], NULL, &children) != PRO_TK_NO_ERROR) {
            ProArrayFree((ProArray *)&children);
            continue;
        }
        ProArraySizeGet((ProArray)children, &n);
        for (j = 0; j < n; j++) {
            ProElemId id;
            ProReference old_ref = NULL, new_ref = NULL;
            ProType type;
            int item_id;
            ProModelitem item;
            if (ProElementIdGet(children[j], &id) != PRO_TK_NO_ERROR || id != PRO_E_COMPONENT_COMP_CONSTR_REF)
                continue;
            if (ProElementReferenceGet(children[j], NULL, &old_ref) != PRO_TK_NO_ERROR || old_ref == NULL)
                continue;
            if (ProReferenceTypeGet(old_ref, &type) == PRO_TK_NO_ERROR &&
                ProReferenceIdGet(old_ref, &item_id) == PRO_TK_NO_ERROR &&
                ProModelitemInit(with, item_id, type, &item) == PRO_TK_NO_ERROR &&
                ProReferenceAlloc(&new_ref) == PRO_TK_NO_ERROR) {
                if (ProReferenceSet(new_ref, NULL, &item) == PRO_TK_NO_ERROR &&
                    ProElementReferenceSet(children[j], new_ref) == PRO_TK_NO_ERROR)
                    moved++;
                ProReferenceFree(new_ref);
            }
            ProReferenceFree(old_ref);
        }
        ProArrayFree((ProArray *)&children);
    }
    failed = "redefine";
    if ((status = ProArrayAlloc(1, sizeof(ProFeatureCreateOptions), 1, (ProArray *)&options)) != PRO_TK_NO_ERROR)
        goto finish;
    options[0] = PRO_FEAT_CR_NO_OPTS;
    status = ProFeatureWithoptionsRedefine(NULL, &feature, tree, options, PRO_REGEN_NO_FLAGS, &errors);
    if (status == PRO_TK_NO_ERROR)
        failed = "";

finish:
    if (constraints != NULL)
        ProArrayFree((ProArray *)&constraints);
    if (path != NULL)
        ProElempathFree(&path);
    if (options != NULL)
        ProArrayFree((ProArray *)&options);
    if (tree != NULL)
        ProFeatureElemtreeFree(&feature, tree);
    put_ascii(outputs, L"failed_step", failed);
    put_int(outputs, L"references", moved);
    put_int(outputs, L"status", (int)status);
    return status;
}

/* ----------------------------------------------------------- section edges */

/*
 * Whether a section view shows the model's edges beyond the cut (Total, Creo's default) or
 * the cut face alone (Area), as a shaft's section through a keyway is drawn: a drawing
 * view setting Java has no call for (ProDrawingView2DSectionAreaSet / TotalSet).
 *
 *   inputs   drawing   wstring  the drawing's name, without extension
 *            view      wstring  the section view's name
 *            edges     wstring  "area" or "total"
 *   outputs  status    int      PRO_TK_NO_CHANGE, already so, counts as done
 */
PRO_TK_DLL_EXPORT ProError creo_cli_section_edges(ProArgument *inputs, ProArgument **outputs)
{
    ProMdlName drawing_w, view_w;
    ProName name;
    char edges_a[16] = "";
    ProMdl drawing = NULL;
    ProView *views = NULL, view = NULL;
    int count = 0, i;
    ProError status;

    if (outputs == NULL)
        return PRO_TK_BAD_INPUTS;
    status = ProArrayAlloc(0, sizeof(ProArgument), 1, (ProArray *)outputs);
    if (status != PRO_TK_NO_ERROR)
        return status;
    if ((status = arg_name(inputs, L"drawing", drawing_w)) == PRO_TK_NO_ERROR &&
        (status = arg_name(inputs, L"view", view_w)) == PRO_TK_NO_ERROR &&
        (status = arg_text(inputs, L"edges", edges_a, sizeof edges_a)) == PRO_TK_NO_ERROR &&
        (status = ProMdlnameInit(drawing_w, PRO_MDLFILE_DRAWING, &drawing)) == PRO_TK_NO_ERROR &&
        (status = ProDrawingViewsCollect((ProDrawing)drawing, &views)) == PRO_TK_NO_ERROR &&
        (status = ProArraySizeGet((ProArray)views, &count)) == PRO_TK_NO_ERROR) {
        for (i = 0; i < count && view == NULL; i++)
            if (ProDrawingViewNameGet((ProDrawing)drawing, views[i], name) == PRO_TK_NO_ERROR &&
                wcscmp(name, view_w) == 0)
                view = views[i];
        if (view == NULL)
            status = PRO_TK_E_NOT_FOUND;
        else if (strcmp(edges_a, "area") == 0)
            status = ProDrawingView2DSectionAreaSet((ProDrawing)drawing, view);
        else if (strcmp(edges_a, "total") == 0)
            status = ProDrawingView2DSectionTotalSet((ProDrawing)drawing, view);
        else
            status = PRO_TK_BAD_INPUTS;
        if (status == PRO_TK_NO_CHANGE)
            status = PRO_TK_NO_ERROR;
    }
    if (views != NULL)
        ProArrayFree((ProArray *)&views);
    put_int(outputs, L"status", (int)status);
    return status;
}

/* ----------------------------------------------------------------- ray */

/*
 * Where a line through a part meets its faces: ProSolidRayIntersectionCompute, which Java
 * lacks. A rib's chain is carried along to the faces it joins by it.
 *
 *   inputs   model     wstring  the part's name, without extension
 *            from      wstring  "x y z", the ray's start, in the part's coordinates
 *            along     wstring  "dx dy dz", its direction
 *            aperture  wstring  optional: how near the ray a face or edge counts as hit, in
 *                               the part's units; Creo's own default -- wide enough to pick
 *                               an edge a millimetre off the ray, measured -- when absent
 *   outputs  hits      wstring  "distance x y z;" per face or edge hit, sorted by distance
 *                               along the ray, negative behind its start
 *            status    int
 */
PRO_TK_DLL_EXPORT ProError creo_cli_ray(ProArgument *inputs, ProArgument **outputs)
{
    ProMdlName model_w;
    char from_a[128] = "", along_a[128] = "", aperture_a[64] = "", hits[MAX_TEXT] = "", one[128];
    ProMdl model = NULL;
    ProRay ray;
    ProSelection *found = NULL;
    double length, aperture = -1.0;
    int count = 0, i;
    ProError status;

    if (outputs == NULL)
        return PRO_TK_BAD_INPUTS;
    status = ProArrayAlloc(0, sizeof(ProArgument), 1, (ProArray *)outputs);
    if (status != PRO_TK_NO_ERROR)
        return status;
    memset(&ray, 0, sizeof ray);
    if ((status = arg_name(inputs, L"model", model_w)) == PRO_TK_NO_ERROR &&
        (status = arg_text(inputs, L"from", from_a, sizeof from_a)) == PRO_TK_NO_ERROR &&
        (status = arg_text(inputs, L"along", along_a, sizeof along_a)) == PRO_TK_NO_ERROR) {
        if (sscanf(from_a, "%lf %lf %lf", &ray.start_point[0], &ray.start_point[1], &ray.start_point[2]) != 3 ||
            sscanf(along_a, "%lf %lf %lf", &ray.dir_vector[0], &ray.dir_vector[1], &ray.dir_vector[2]) != 3)
            status = PRO_TK_BAD_INPUTS;
    }
    if (status == PRO_TK_NO_ERROR && arg_text(inputs, L"aperture", aperture_a, sizeof aperture_a) == PRO_TK_NO_ERROR &&
        (sscanf(aperture_a, "%lf", &aperture) != 1 || !(aperture > 0)))
        status = PRO_TK_BAD_INPUTS;
    length = sqrt(ray.dir_vector[0] * ray.dir_vector[0] + ray.dir_vector[1] * ray.dir_vector[1] +
                  ray.dir_vector[2] * ray.dir_vector[2]);
    if (status == PRO_TK_NO_ERROR && !(length > 0))
        status = PRO_TK_BAD_INPUTS;
    if (status == PRO_TK_NO_ERROR)
        status = ProMdlnameInit(model_w, PRO_MDLFILE_PART, &model);
    if (status == PRO_TK_NO_ERROR)
        status = ProSolidRayIntersectionCompute(model, aperture, &ray, &found, &count);
    if (status == PRO_TK_E_NOT_FOUND) {
        status = PRO_TK_NO_ERROR;
        count = 0;
    }
    /* The selections are the toolkit's own, reused on the next call: read, not freed. */
    for (i = 0; status == PRO_TK_NO_ERROR && found != NULL && i < count; i++) {
        Pro3dPnt point;
        double distance;
        if (ProSelectionPoint3dGet(found[i], point) != PRO_TK_NO_ERROR)
            continue;
        distance = ((point[0] - ray.start_point[0]) * ray.dir_vector[0] +
                    (point[1] - ray.start_point[1]) * ray.dir_vector[1] +
                    (point[2] - ray.start_point[2]) * ray.dir_vector[2]) / length;
        snprintf(one, sizeof one, "%.15g %.15g %.15g %.15g;", distance, point[0], point[1], point[2]);
        append(hits, sizeof hits, one);
    }
    put_ascii(outputs, L"hits", hits);
    put_int(outputs, L"status", (int)status);
    return status;
}

/* --------------------------------------------------------- owned empty exit */

/* Fixed lifecycle operation, not an arbitrary process terminator. Java separately
   checks the raw Session.ListModels() inventory (including section models), source
   identity, generation, deadline and explicit owned-launch/dangerous authorization.
   ProSessionMdlList documents valid model types, not PRO_MDL_UNUSED as an all-type
   sentinel, so this side checks all eleven public model types and does not invent
   coverage of reserved types. No model is saved, erased or otherwise edited here. */
#define OWNED_EXIT_MAX_WAIT_MS 30000ULL
#define OWNED_EXIT_DISPATCH_CONTRACT L"queued_native_command_v1"
#define OWNED_EXIT_COMMAND_NAME "CreoCliOwnedExitDeferred"
static volatile LONG owned_exit_claimed = 0;
static volatile LONG owned_exit_export_active = 0;
static int owned_exit_registration_reported = 0;
static ProError owned_exit_registration_status = PRO_TK_E_NOT_FOUND;
static uiCmdCmdId owned_exit_command_id = NULL;
typedef struct {
    DWORD pid;
    ULONGLONG birth, deadline;
    wchar_t operation[40], instance[40], runtime[32768];
    HANDLE directory;
} OwnedExitTicket;
static OwnedExitTicket owned_exit_pending;

static int owned_exit_wstring(ProArgument *inputs, const wchar_t *label,
                              wchar_t *out, size_t capacity)
{
    ProValueData value;
    size_t length;
    if (arg_value(inputs, label, &value) != PRO_TK_NO_ERROR ||
        value.type != PRO_VALUE_TYPE_WSTRING || value.v.w == NULL)
        return 0;
    length = wcsnlen(value.v.w, capacity);
    if (length == 0 || length >= capacity) return 0;
    wmemcpy(out, value.v.w, length + 1);
    return 1;
}

static int owned_exit_decimal(const wchar_t *text, ULONGLONG *value)
{
    ULONGLONG number = 0, digit;
    const wchar_t *at = text;
    if (at == NULL || *at == 0) return 0;
    while (*at != 0) {
        if (*at < L'0' || *at > L'9') return 0;
        digit = (ULONGLONG)(*at++ - L'0');
        if (number > (0xffffffffffffffffULL - digit) / 10ULL) return 0;
        number = number * 10ULL + digit;
    }
    *value = number;
    return 1;
}

static int owned_exit_id(const wchar_t *text, int uuid)
{
    size_t i, wanted = uuid ? 36 : 32;
    if (wcslen(text) != wanted) return 0;
    for (i = 0; i < wanted; ++i) {
        if (uuid && (i == 8 || i == 13 || i == 18 || i == 23)) {
            if (text[i] != L'-') return 0;
        } else if (!((text[i] >= L'0' && text[i] <= L'9') ||
                     (text[i] >= L'a' && text[i] <= L'f'))) return 0;
    }
    return 1;
}

static int owned_exit_deadline(ULONGLONG deadline)
{
    ULONGLONG now = GetTickCount64();
    return deadline > now && deadline - now <= OWNED_EXIT_MAX_WAIT_MS;
}

static int owned_exit_birth(ULONGLONG expected)
{
    FILETIME created, exited, kernel, user;
    ULARGE_INTEGER actual;
    if (!GetProcessTimes(GetCurrentProcess(), &created, &exited, &kernel, &user)) return 0;
    actual.LowPart = created.dwLowDateTime;
    actual.HighPart = created.dwHighDateTime;
    return expected != 0 && actual.QuadPart == expected;
}

/* Hold the actual local runtime directory without delete sharing until exit. The
   final resolved DOS path must match both explicit input and this process's env;
   reparse points and UNC/device paths are refused. No directory is created. */
static HANDLE owned_exit_runtime(const wchar_t *requested, wchar_t full[32768])
{
    const wchar_t *environment = _wgetenv(L"CREO_CLI_CONFIG_DIR");
    wchar_t env_full[32768], resolved[32768];
    BY_HANDLE_FILE_INFORMATION info;
    DWORD length;
    HANDLE directory;
    if (environment == NULL || wcslen(requested) < 4 || wcslen(environment) < 4 ||
        requested[1] != L':' || environment[1] != L':' ||
        (requested[2] != L'\\' && requested[2] != L'/') ||
        (environment[2] != L'\\' && environment[2] != L'/')) return INVALID_HANDLE_VALUE;
    length = GetFullPathNameW(requested, 32768, full, NULL);
    if (length < 4 || length >= 32720) return INVALID_HANDLE_VALUE;
    length = GetFullPathNameW(environment, 32768, env_full, NULL);
    if (length < 4 || length >= 32720 || _wcsicmp(full, env_full) != 0) return INVALID_HANDLE_VALUE;
    directory = CreateFileW(full, FILE_READ_ATTRIBUTES, FILE_SHARE_READ | FILE_SHARE_WRITE,
                            NULL, OPEN_EXISTING,
                            FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT, NULL);
    if (directory == INVALID_HANDLE_VALUE) return directory;
    if (!GetFileInformationByHandle(directory, &info) ||
        (info.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) == 0 ||
        (info.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT) != 0) {
        CloseHandle(directory); return INVALID_HANDLE_VALUE;
    }
    length = GetFinalPathNameByHandleW(directory, resolved, 32768, FILE_NAME_NORMALIZED | VOLUME_NAME_DOS);
    if (length < 8 || length >= 32768 || wcsncmp(resolved, L"\\\\?\\", 4) != 0 ||
        _wcsicmp(resolved + 4, full) != 0) {
        CloseHandle(directory); return INVALID_HANDLE_VALUE;
    }
    return directory;
}

static int owned_exit_witness(const wchar_t *runtime, const wchar_t *operation,
                              const wchar_t *instance, ULONGLONG birth, ULONGLONG deadline,
                              int returned, int status, int api_called)
{
    wchar_t path[32768];
    char body[1536], operation_ascii[33], instance_ascii[37];
    HANDLE file;
    DWORD written = 0;
    int i, size, ok;
    for (i = 0; i < 32; ++i) operation_ascii[i] = (char)operation[i];
    operation_ascii[32] = 0;
    for (i = 0; i < 36; ++i) instance_ascii[i] = (char)instance[i];
    instance_ascii[36] = 0;
    if (_snwprintf(path, 32767, L"%ls\\owned-exit-%ls.%ls.json", runtime, operation,
                    returned ? L"returned" : L"entered") < 0) return 0;
    path[32767] = 0;
    size = snprintf(body, sizeof body,
        "{\"status\":\"%s\",\"entrypoint\":\"ProEngineerEnd\","
        "\"native_pid\":%lu,\"native_creation_filetime\":\"%llu\","
        "\"operation_id\":\"%s\",\"service_instance_id\":\"%s\","
        "\"deadline_tick_ms\":\"%llu\",\"raw_java_empty_checked\":true,"
        "\"native_known_types_empty\":true,\"native_type_count\":11,\"empty_models\":true,"
        "\"dispatch_contract\":\"queued_native_command_v1\","
        "\"dispatch_context\":\"registered_native_command\"%s}\n",
        returned ? "native_returned" : "native_entered", (unsigned long)GetCurrentProcessId(),
        birth, operation_ascii, instance_ascii, deadline,
        returned ? (api_called ? ",\"api_called\":true" : ",\"api_called\":false") : "");
    if (size <= 0 || size >= (int)sizeof body) return 0;
    if (returned) {
        /* Insert native_return_code before the closing brace, keeping JSON bounded. */
        size -= 2;
        size += snprintf(body + size, sizeof body - (size_t)size,
                            ",\"native_return_code\":%d}\n", status);
        if (size <= 0 || size >= (int)sizeof body) return 0;
    }
    file = CreateFileW(path, GENERIC_WRITE, FILE_SHARE_READ, NULL, CREATE_NEW,
                        FILE_ATTRIBUTE_NORMAL | FILE_FLAG_OPEN_REPARSE_POINT | FILE_FLAG_WRITE_THROUGH, NULL);
    if (file == INVALID_HANDLE_VALUE) return 0;
    ok = WriteFile(file, body, (DWORD)size, &written, NULL) && written == (DWORD)size && FlushFileBuffers(file);
    if (!CloseHandle(file)) ok = 0;
    return ok;
}

static void owned_exit_close_ticket(void)
{
    if (owned_exit_pending.directory != INVALID_HANDLE_VALUE && owned_exit_pending.directory != NULL)
        CloseHandle(owned_exit_pending.directory);
    owned_exit_pending.directory = INVALID_HANDLE_VALUE;
    InterlockedExchange(&owned_exit_claimed, 3);
}

static int owned_exit_notice(const wchar_t *kind, ProError status, const char *reason,
                              int api_called, int returned_recorded)
{
    wchar_t path[32768];
    char body[1024], operation[33], instance[37];
    int i, size, ok;
    DWORD written = 0;
    HANDLE file;
    for (i = 0; i < 32; ++i) operation[i] = (char)owned_exit_pending.operation[i];
    operation[32] = 0;
    for (i = 0; i < 36; ++i) instance[i] = (char)owned_exit_pending.instance[i];
    instance[36] = 0;
    if (_snwprintf(path, 32767, L"%ls\\owned-exit-%ls.%ls.json", owned_exit_pending.runtime,
                    owned_exit_pending.operation, kind) < 0) return 0;
    path[32767] = 0;
    size = snprintf(body, sizeof body,
        "{\"status\":\"%s\",\"entrypoint\":\"ProEngineerEnd\","
        "\"operation_id\":\"%s\",\"service_instance_id\":\"%s\",\"native_pid\":%lu,"
        "\"native_creation_filetime\":\"%llu\",\"api_called\":%s,\"native_return_code\":%d,"
        "\"returned_witness_recorded\":%s,"
        "\"dispatch_contract\":\"queued_native_command_v1\",\"reason\":\"%s\"}\n",
        api_called ? "native_exit_failed_after_entry" : "native_command_refused_before_entry",
        operation, instance, (unsigned long)GetCurrentProcessId(), owned_exit_pending.birth,
        api_called ? "true" : "false", (int)status, returned_recorded ? "true" : "false", reason);
    if (size <= 0 || size >= (int)sizeof body) return 0;
    file = CreateFileW(path, GENERIC_WRITE, FILE_SHARE_READ, NULL, CREATE_NEW,
                        FILE_ATTRIBUTE_NORMAL | FILE_FLAG_OPEN_REPARSE_POINT | FILE_FLAG_WRITE_THROUGH, NULL);
    if (file == INVALID_HANDLE_VALUE) return 0;
    ok = WriteFile(file, body, (DWORD)size, &written, NULL) && written == (DWORD)size && FlushFileBuffers(file);
    if (!CloseHandle(file)) ok = 0;
    return ok;
}

/* Only this registered native command may enter End. In particular the exported
   Dll.ExecuteFunction call below must return to the OTK transport first. */
static int owned_exit_command(uiCmdCmdId command, uiCmdValue *value, void *data)
{
    const ProMdlType types[] = { PRO_MDL_PART, PRO_MDL_ASSEMBLY, PRO_MDL_DRAWING,
        PRO_MDL_3DSECTION, PRO_MDL_2DSECTION, PRO_MDL_LAYOUT, PRO_MDL_DWGFORM,
        PRO_MDL_MFG, PRO_MDL_REPORT, PRO_MDL_MARKUP, PRO_MDL_DIAGRAM };
    wchar_t full[32768];
    ProMdl *models = NULL;
    ProError status = PRO_TK_BAD_INPUTS, freed;
    HANDLE rechecked = INVALID_HANDLE_VALUE;
    int count = 0, i, returned_recorded;
    const char *reason = "native_command_identity_or_runtime_changed";
    if (command != owned_exit_command_id || owned_exit_command_id == NULL) return 0;
    if (InterlockedCompareExchange(&owned_exit_claimed, 2, 1) != 1) return 0;
    if (InterlockedCompareExchange(&owned_exit_export_active, 0, 0) != 0) {
        reason = "native_command_attempted_inside_export"; goto refused;
    }
    if (owned_exit_pending.pid != GetCurrentProcessId() || !owned_exit_birth(owned_exit_pending.birth)) goto refused;
    if (!owned_exit_deadline(owned_exit_pending.deadline)) {
        status = PRO_TK_USER_ABORT; reason = "native_command_expired"; goto refused;
    }
    rechecked = owned_exit_runtime(owned_exit_pending.runtime, full);
    if (rechecked == INVALID_HANDLE_VALUE || _wcsicmp(full, owned_exit_pending.runtime) != 0) goto refused;
    CloseHandle(rechecked); rechecked = INVALID_HANDLE_VALUE;
    for (i = 0; i < (int)(sizeof types / sizeof types[0]); ++i) {
        if (!owned_exit_deadline(owned_exit_pending.deadline)) {
            status = PRO_TK_USER_ABORT; reason = "native_inventory_deadline_elapsed"; goto refused;
        }
        models = NULL; count = 0;
        status = ProSessionMdlList(types[i], &models, &count);
        freed = models == NULL ? PRO_TK_NO_ERROR : ProArrayFree((ProArray *)&models);
        if (freed != PRO_TK_NO_ERROR) { status = freed; reason = "native_inventory_cleanup_failed"; goto refused; }
        if (!owned_exit_deadline(owned_exit_pending.deadline)) {
            status = PRO_TK_USER_ABORT; reason = "native_inventory_deadline_elapsed"; goto refused;
        }
        if (status != PRO_TK_NO_ERROR && status != PRO_TK_E_NOT_FOUND) {
            reason = "native_inventory_unavailable"; goto refused;
        }
        if (count != 0) { status = PRO_TK_E_IN_USE; reason = "native_model_appeared"; goto refused; }
    }
    if (!owned_exit_deadline(owned_exit_pending.deadline)) {
        status = PRO_TK_USER_ABORT; reason = "native_command_expired"; goto refused;
    }
    if (!owned_exit_witness(full, owned_exit_pending.operation, owned_exit_pending.instance,
                            owned_exit_pending.birth, owned_exit_pending.deadline, 0, 0, 0)) {
        status = PRO_TK_GENERAL_ERROR; reason = "native_entered_witness_unavailable"; goto refused;
    }
    if (!owned_exit_deadline(owned_exit_pending.deadline)) {
        status = PRO_TK_USER_ABORT;
        owned_exit_witness(full, owned_exit_pending.operation, owned_exit_pending.instance,
                            owned_exit_pending.birth, owned_exit_pending.deadline, 1, status, 0);
        owned_exit_close_ticket(); return 0;
    }
    /* May terminate this process/JVM before returning. No SDK call follows End. */
    status = ProEngineerEnd();
    returned_recorded = owned_exit_witness(full, owned_exit_pending.operation, owned_exit_pending.instance,
                                            owned_exit_pending.birth, owned_exit_pending.deadline, 1, status, 1);
    /* Deferred Java has already returned. Preserve a known native failure as an
       independent veto even if its returned witness cannot be created/flushed.
       If all OS/file writes fail, no durable veto can be claimed; never retry End. */
    if (status != PRO_TK_NO_ERROR || !returned_recorded)
        owned_exit_notice(L"failed", status,
            status != PRO_TK_NO_ERROR
                ? (returned_recorded ? "native_api_returned_error" : "native_error_and_return_witness_unavailable")
                : "native_return_witness_unavailable", 1, returned_recorded);
    owned_exit_close_ticket();
    return 0;
refused:
    if (rechecked != INVALID_HANDLE_VALUE) CloseHandle(rechecked);
    owned_exit_notice(status == PRO_TK_USER_ABORT ? L"cancelled" : L"failed", status, reason, 0, 0);
    owned_exit_close_ticket();
    return 0;
}

static uiCmdAccessState owned_exit_access(uiCmdAccessMode mode)
{
    return owned_exit_command_id != NULL && InterlockedCompareExchange(&owned_exit_claimed, 0, 0) == 1
        ? ACCESS_AVAILABLE : ACCESS_DISALLOW;
}

static ProError owned_exit_register(void)
{
    ProError status;
    if (owned_exit_command_id != NULL) return PRO_TK_E_IN_USE;
    status = ProCmdActionAdd(OWNED_EXIT_COMMAND_NAME, owned_exit_command, uiProeImmediate,
                            owned_exit_access, PRO_B_TRUE, PRO_B_TRUE, &owned_exit_command_id);
    if (status != PRO_TK_NO_ERROR) owned_exit_command_id = NULL;
    if (status == PRO_TK_NO_ERROR && owned_exit_command_id == NULL) status = PRO_TK_GENERAL_ERROR;
    return status;
}

/* Registration availability is process-private, not a new global configuration.
   The existing resolver requires the explicit Native child's runtime env. */
static int owned_exit_registration_witness(const wchar_t *runtime)
{
    wchar_t full[32768], path[32768];
    HANDLE directory, file;
    FILETIME created, exited, kernel, user;
    ULARGE_INTEGER birth;
    char body[768];
    int size, ok;
    DWORD written = 0;
    directory = owned_exit_runtime(runtime, full);
    if (directory == INVALID_HANDLE_VALUE) return 0;
    if (!GetProcessTimes(GetCurrentProcess(), &created, &exited, &kernel, &user)) {
        CloseHandle(directory); return 0;
    }
    birth.LowPart = created.dwLowDateTime; birth.HighPart = created.dwHighDateTime;
    if (_snwprintf(path, 32767, L"%ls\\native-owned-exit-dispatch.json", full) < 0) {
        CloseHandle(directory); return 0;
    }
    path[32767] = 0;
    size = snprintf(body, sizeof body,
        "{\"schema_version\":\"1.0\",\"dispatch_contract\":\"queued_native_command_v1\","
        "\"command\":\"CreoCliOwnedExitDeferred\",\"priority\":\"uiProeImmediate\","
        "\"registered\":%s,\"registration_status\":%d,\"native_pid\":%lu,"
        "\"native_creation_filetime\":\"%llu\"}\n",
        owned_exit_registration_status == PRO_TK_NO_ERROR && owned_exit_command_id != NULL ? "true" : "false",
        (int)owned_exit_registration_status, (unsigned long)GetCurrentProcessId(), birth.QuadPart);
    if (size <= 0 || size >= (int)sizeof body) { CloseHandle(directory); return 0; }
    file = CreateFileW(path, GENERIC_WRITE, FILE_SHARE_READ, NULL, CREATE_NEW,
                        FILE_ATTRIBUTE_NORMAL | FILE_FLAG_OPEN_REPARSE_POINT | FILE_FLAG_WRITE_THROUGH, NULL);
    if (file == INVALID_HANDLE_VALUE) { CloseHandle(directory); return 0; }
    ok = WriteFile(file, body, (DWORD)size, &written, NULL) && written == (DWORD)size && FlushFileBuffers(file);
    if (!CloseHandle(file)) ok = 0;
    CloseHandle(directory);
    return ok;
}

/* New contract is deliberately an eighth argument: an old inline DLL rejects it
   before End, and this DLL rejects an old seven-argument Java caller. Return 0
   only acknowledges queuing; no native-entered/returned witness is written here. */
PRO_TK_DLL_EXPORT ProError creo_cli_session_exit(ProArgument *inputs, ProArgument **outputs)
{
    const wchar_t *labels[] = { L"expected_pid", L"expected_creation_filetime", L"operation_id",
        L"service_instance_id", L"runtime_directory", L"deadline_tick_ms", L"raw_java_model_count", L"dispatch_contract" };
    wchar_t creation[32], deadline_text[32], operation[40], instance[40], runtime[32768], full[32768], contract[40];
    ULONGLONG birth = 0, deadline = 0;
    ProError status = PRO_TK_BAD_INPUTS;
    HANDLE directory = INVALID_HANDLE_VALUE;
    int expected_pid = 0, java_count = -1, input_count = 0, i, j, found;
    if (outputs == NULL) return PRO_TK_BAD_INPUTS;
    *outputs = NULL;
    if (InterlockedCompareExchange(&owned_exit_claimed, 0, 0) != 0) return PRO_TK_E_IN_USE;
    if (owned_exit_command_id == NULL || !owned_exit_registration_reported) return PRO_TK_E_NOT_FOUND;
    if (inputs == NULL || ProArraySizeGet((ProArray)inputs, &input_count) != PRO_TK_NO_ERROR || input_count != 8)
        goto done;
    for (i = 0; i < input_count; ++i) {
        found = 0;
        for (j = 0; j < 8; ++j) if (wcscmp(inputs[i].label, labels[j]) == 0) ++found;
        if (found != 1) goto done;
        for (j = 0; j < i; ++j) if (wcscmp(inputs[i].label, inputs[j].label) == 0) goto done;
    }
    if (arg_int(inputs, L"expected_pid", &expected_pid) != PRO_TK_NO_ERROR || expected_pid <= 0 ||
        arg_int(inputs, L"raw_java_model_count", &java_count) != PRO_TK_NO_ERROR || java_count != 0 ||
        !owned_exit_wstring(inputs, L"expected_creation_filetime", creation, 32) ||
        !owned_exit_wstring(inputs, L"deadline_tick_ms", deadline_text, 32) ||
        !owned_exit_wstring(inputs, L"operation_id", operation, 40) ||
        !owned_exit_wstring(inputs, L"service_instance_id", instance, 40) ||
        !owned_exit_wstring(inputs, L"runtime_directory", runtime, 32768) ||
        !owned_exit_wstring(inputs, L"dispatch_contract", contract, 40) || wcscmp(contract, OWNED_EXIT_DISPATCH_CONTRACT) != 0 ||
        !owned_exit_decimal(creation, &birth) || !owned_exit_decimal(deadline_text, &deadline) ||
        !owned_exit_id(operation, 0) || !owned_exit_id(instance, 1)) goto done;
    if ((DWORD)expected_pid != GetCurrentProcessId() || !owned_exit_birth(birth)) goto done;
    directory = owned_exit_runtime(runtime, full);
    if (directory == INVALID_HANDLE_VALUE) goto done;
    if (InterlockedCompareExchange(&owned_exit_claimed, 0, 0) != 0) {
        status = PRO_TK_E_IN_USE; goto done;
    }
    if (!owned_exit_deadline(deadline)) { status = PRO_TK_USER_ABORT; goto done; }
    /* All Toolkit output preparation precedes the final queueing API. */
    status = ProArrayAlloc(0, sizeof(ProArgument), 4, (ProArray *)outputs);
    if (status != PRO_TK_NO_ERROR) goto done;
    if (!owned_exit_deadline(deadline)) { status = PRO_TK_USER_ABORT; goto done; }
    if (InterlockedCompareExchange(&owned_exit_claimed, -1, 0) != 0) { status = PRO_TK_E_IN_USE; goto done; }
    owned_exit_pending.pid = (DWORD)expected_pid;
    owned_exit_pending.birth = birth; owned_exit_pending.deadline = deadline;
    wcscpy(owned_exit_pending.operation, operation); wcscpy(owned_exit_pending.instance, instance);
    wcscpy(owned_exit_pending.runtime, full);
    owned_exit_pending.directory = directory; directory = INVALID_HANDLE_VALUE;
    InterlockedExchange(&owned_exit_export_active, 1);
    InterlockedExchange(&owned_exit_claimed, 1);
    /* PTC: executes once control returns to Creo. Never use ProMacroExecute here. */
    status = ProMacroLoad(L"~ Command `CreoCliOwnedExitDeferred`;");
    InterlockedExchange(&owned_exit_export_active, 0);
    if (status != PRO_TK_NO_ERROR) {
        owned_exit_notice(L"failed", status, "native_command_queue_failed", 0, 0);
        owned_exit_close_ticket();
    }
done:
    if (directory != INVALID_HANDLE_VALUE) CloseHandle(directory);
    return status;
}

/* ----------------------------------------------------------- DLL lifecycle */

/* ------------------------------------------------ fixed current model close */

/* This narrow command handles a clean, last part plus one empty window. The
   export only queues this fixed command; the callback returns immediately after
   CurrentClose. Java independently observes the later UI tick before erasing.
   ProMdl is retained only as an opaque comparison value, never dereferenced. */
#define MODEL_CLOSE_COMMAND "CreoCliModelCurrentCloseDeferred"
#define MODEL_CLOSE_CONTRACT "model_current_close_v2"
typedef struct {
    DWORD pid;
    ULONGLONG birth, deadline;
    int target_window, empty_window;
    wchar_t ticket[33], instance[37], request[65], proof[65], refusal_proof[65], model[81], runtime[32768];
    char stamp[1024];
    const char *stage;
    const char *name_change;
    const char *refusal_category;
    int observed_window_ids[3], observed_window_count;
    ProMdl model_handle;
    HANDLE directory, journal;
} ModelCloseTicket;
static ModelCloseTicket model_close_pending;
static volatile LONG model_close_claimed = 0, model_close_export_active = 0;
static uiCmdCmdId model_close_command_id = NULL;
static ProError model_close_registration_status = PRO_TK_E_NOT_FOUND;
static int model_close_registration_reported = 0;

static int model_close_hex(const wchar_t *text, size_t length)
{
    size_t i;
    if (wcslen(text) != length) return 0;
    for (i = 0; i < length; ++i)
        if (!((text[i] >= L'0' && text[i] <= L'9') || (text[i] >= L'a' && text[i] <= L'f'))) return 0;
    return 1;
}

static int model_close_stem_chars(const wchar_t *text, size_t n)
{
    size_t i;
    if (n == 0 || n > 80) return 0;
    for (i = 0; i < n; ++i)
        if (!((text[i] >= L'a' && text[i] <= L'z') || (text[i] >= L'A' && text[i] <= L'Z') ||
              (text[i] >= L'0' && text[i] <= L'9') || text[i] == L'_')) return 0;
    return 1;
}

static int model_close_stem(const wchar_t *text)
{
    return model_close_stem_chars(text, wcsnlen(text, 81));
}

static int model_close_path(wchar_t path[32768], const wchar_t *suffix)
{
    return _snwprintf(path, 32767, L"%ls\\model-close-%ls.%ls", model_close_pending.runtime,
                      model_close_pending.ticket, suffix) >= 0;
}

static int model_close_guard(const char *category, long long expected, long long actual,
                            int boolean_values, int model_type);

static int model_close_live(void)
{
    wchar_t cancelled[32768];
    const wchar_t *environment = _wgetenv(L"CREO_CLI_CONFIG_DIR");
    DWORD attributes, error;
    if (model_close_pending.pid != GetCurrentProcessId()) {
        model_close_guard("native_pid_match", 1, 0, 1, -1); return 0;
    }
    if (!owned_exit_birth(model_close_pending.birth)) {
        model_close_guard("native_birth_match", 1, 0, 1, -1); return 0;
    }
    if (environment == NULL || _wcsicmp(environment, model_close_pending.runtime) != 0) {
        model_close_guard("runtime_environment_match", 1, 0, 1, -1); return 0;
    }
    if (GetTickCount64() >= model_close_pending.deadline) {
        model_close_guard("deadline_live", 1, 0, 1, -1); return 0;
    }
    if (!model_close_path(cancelled, L"cancelled.json")) {
        model_close_guard("cancel_path_bounded", 1, 0, 1, -1); return 0;
    }
    attributes = GetFileAttributesW(cancelled); error = GetLastError();
    if (attributes != INVALID_FILE_ATTRIBUTES || error != ERROR_FILE_NOT_FOUND) {
        model_close_guard("cancel_file_absent", 1, 0, 1, -1); return 0;
    }
    return 1;
}

static int model_close_write_journal(const char *body, int n)
{
    DWORD written = 0;
    return n > 0 && model_close_pending.journal != NULL && model_close_pending.journal != INVALID_HANDLE_VALUE &&
        WriteFile(model_close_pending.journal, body, (DWORD)n, &written, NULL) && written == (DWORD)n &&
        FlushFileBuffers(model_close_pending.journal);
}

/* One fixed diagnostic shape for this close command's guards. Values are only
   bounded integers/booleans from successful reads; no native addresses, stamps,
   paths, transport inputs or proofs are included. */
static int model_close_guard(const char *category, long long expected, long long actual,
                            int boolean_values, int model_type)
{
    char body[2048], expected_json[32], actual_json[32], windows[80];
    int n, i, at = 0, count = model_close_pending.observed_window_count;
    model_close_pending.refusal_category = category;
    if (boolean_values) {
        strcpy(expected_json, expected ? "true" : "false");
        strcpy(actual_json, actual ? "true" : "false");
    } else {
        snprintf(expected_json, sizeof expected_json, "%lld", expected);
        snprintf(actual_json, sizeof actual_json, "%lld", actual);
    }
    windows[at++] = '[';
    for (i = 0; i < count && i < 3; ++i)
        at += snprintf(windows + at, sizeof windows - (size_t)at, "%s%d", i == 0 ? "" : ",",
                       model_close_pending.observed_window_ids[i]);
    windows[at++] = ']'; windows[at] = 0;
    n = snprintf(body, sizeof body,
        "{\"event\":\"guard-refused\",\"category\":\"%s\",\"api\":\"%s\",\"expected\":%s,\"actual\":%s,"
        "\"model_type\":%d,\"close_ticket_id\":\"%ls\",\"service_instance_id\":\"%ls\","
        "\"request_sha256\":\"%ls\",\"target_window\":%d,\"empty_window\":%d,\"model\":\"%ls\","
        "\"native_pid\":%lu,\"native_creation_filetime\":\"%llu\",\"actual_window_ids\":%s,"
        "\"actual_window_count\":%d,\"window_ids_complete\":%s}\n",
        category, model_close_pending.stage == NULL ? "none" : model_close_pending.stage,
        expected_json, actual_json, model_type, model_close_pending.ticket, model_close_pending.instance,
        model_close_pending.request, model_close_pending.target_window, model_close_pending.empty_window,
        model_close_pending.model, (unsigned long)model_close_pending.pid, model_close_pending.birth,
        windows, count, count <= 3 ? "true" : "false");
    return n > 0 && n < (int)sizeof body && model_close_write_journal(body, n);
}

static ProError model_close_refuse(const char *category, long long expected, long long actual,
                                 int boolean_values, int model_type, ProError status)
{
    return model_close_guard(category, expected, actual, boolean_values, model_type)
        ? status : PRO_TK_GENERAL_ERROR;
}

static int model_close_record(const char *event, const char *api, int status)
{
    char body[2048];
    int n;
    n = snprintf(body, sizeof body,
        "{\"event\":\"%s\",\"api\":\"%s\",\"status\":%d,\"close_ticket_id\":\"%ls\","
        "\"service_instance_id\":\"%ls\",\"request_sha256\":\"%ls\",\"target_window\":%d,"
        "\"empty_window\":%d,\"model\":\"%ls\",\"native_pid\":%lu,"
        "\"native_creation_filetime\":\"%llu\"}\n", event, api, status,
        model_close_pending.ticket, model_close_pending.instance, model_close_pending.request,
        model_close_pending.target_window, model_close_pending.empty_window, model_close_pending.model,
        (unsigned long)model_close_pending.pid, model_close_pending.birth);
    return n > 0 && n < (int)sizeof body && model_close_write_journal(body, n);
}

/* Escaping is bounded by the actual SDK name array, including invalid names.
   Non-ASCII UTF-16 units are journaled as escapes, never normalized or accepted. */
static void model_close_name_json(const wchar_t *text, size_t n, char *out)
{
    size_t i, at = 0;
    for (i = 0; i < n; ++i) {
        unsigned int unit = (unsigned int)text[i] & 0xffff;
        if (unit >= 32 && unit < 127 && unit != '"' && unit != '\\') out[at++] = (char)unit;
        else { snprintf(out + at, 7, "\\u%04x", unit); at += 6; }
    }
    out[at] = 0;
}

static int model_close_name_check(const wchar_t *native_name, size_t capacity)
{
    size_t native_n = wcsnlen(native_name, capacity), expected_n = wcslen(model_close_pending.model), i;
    int native_valid = native_n < capacity && model_close_stem_chars(native_name, native_n);
    int expected_valid = model_close_stem_chars(model_close_pending.model, expected_n);
    int ordinal = native_n == expected_n && wmemcmp(native_name, model_close_pending.model, native_n) == 0;
    int folded = native_valid && expected_valid && native_n == expected_n;
    char expected_json[81 * 6 + 1], native_json[PRO_MDLNAME_SIZE * 6 + 1], body[4096];
    const char *change;
    int n;
    if (folded) for (i = 0; i < native_n; ++i) {
        wchar_t a = native_name[i], b = model_close_pending.model[i];
        if (a >= L'A' && a <= L'Z') a += L'a' - L'A';
        if (b >= L'A' && b <= L'Z') b += L'a' - L'A';
        if (a != b) { folded = 0; break; }
    }
    change = !native_valid ? "native_invalid_stem" : !expected_valid ? "expected_invalid_stem" :
        native_n != expected_n ? "length_mismatch" : ordinal ? "ordinal_equal" :
        folded ? "ascii_case_only" : "ascii_character_mismatch";
    model_close_name_json(model_close_pending.model, expected_n, expected_json);
    model_close_name_json(native_name, native_n, native_json);
    n = snprintf(body, sizeof body,
        "{\"event\":\"name-identity\",\"api\":\"ProMdlMdlnameGet\",\"close_ticket_id\":\"%ls\","
        "\"service_instance_id\":\"%ls\",\"request_sha256\":\"%ls\",\"target_window\":%d,"
        "\"empty_window\":%d,\"model\":\"%ls\",\"native_pid\":%lu,\"native_creation_filetime\":\"%llu\","
        "\"expected_name\":\"%s\",\"native_name\":\"%s\",\"expected_length\":%llu,\"native_length\":%llu,"
        "\"expected_valid_charset\":%s,\"native_valid_charset\":%s,\"native_terminated\":%s,"
        "\"ordinal_equal\":%s,\"ascii_fold_equal\":%s,\"change_class\":\"%s\"}\n",
        model_close_pending.ticket, model_close_pending.instance, model_close_pending.request,
        model_close_pending.target_window, model_close_pending.empty_window, model_close_pending.model,
        (unsigned long)model_close_pending.pid, model_close_pending.birth, expected_json, native_json,
        (unsigned long long)expected_n, (unsigned long long)native_n, expected_valid ? "true" : "false",
        native_valid ? "true" : "false", native_n < capacity ? "true" : "false", ordinal ? "true" : "false",
        folded ? "true" : "false", change);
    model_close_pending.stage = change;
    model_close_pending.name_change = change;
    if (n <= 0 || n >= (int)sizeof body || !model_close_write_journal(body, n)) return -1;
    return folded;
}

static int model_close_begin(const char *api)
{
    model_close_pending.stage = api;
    return model_close_live() && model_close_record("begin", api, 0) && model_close_live();
}

/* Each validation stops at its first failure. Cleanup of already allocated SDK
   memory is the sole exception; all of it finishes before CurrentClose. */
#define MODEL_CLOSE_CALL(api, expression) do { \
    if (!model_close_begin(api)) { status = PRO_TK_USER_ABORT; goto done; } \
    status = (expression); \
    if (!model_close_record("end", api, (int)status)) { status = PRO_TK_GENERAL_ERROR; goto done; } \
    if (status != PRO_TK_NO_ERROR) { \
        status = model_close_refuse("api_status", 0, (long long)status, 0, -1, status); goto done; \
    } \
} while (0)

static ProError model_close_stamp(ProMdl live, char copy[1024])
{
    ProWVerstamp stamp = NULL;
    char *text = NULL;
    ProError status = PRO_TK_NO_ERROR, cleanup;
    MODEL_CLOSE_CALL("ProMdlVerstampGet", ProMdlVerstampGet(live, &stamp));
    if (stamp == NULL) { status = model_close_refuse("stamp_allocated", 1, 0, 1, -1, PRO_TK_BAD_INPUTS); goto done; }
    MODEL_CLOSE_CALL("ProVerstampStringGet", ProVerstampStringGet(stamp, &text));
    if (text == NULL) { status = model_close_refuse("stamp_text_allocated", 1, 0, 1, -1, PRO_TK_BAD_INPUTS); goto done; }
    if (strlen(text) == 0 || strlen(text) >= 1024) {
        model_close_guard("stamp_text_length", 1023, (long long)strlen(text), 0, -1);
        status = model_close_refuse("stamp_text_length_bounded", 1, 0, 1, -1, PRO_TK_BAD_INPUTS); goto done;
    }
    strcpy(copy, text);
done:
    if (text != NULL) {
        int begin = model_close_record("begin", "ProVerstampStringFree", 0);
        cleanup = ProVerstampStringFree(&text);
        if (cleanup != PRO_TK_NO_ERROR) model_close_guard("cleanup_api_status", 0, cleanup, 0, -1);
        if (!model_close_record("end", "ProVerstampStringFree", (int)cleanup) || !begin || cleanup != PRO_TK_NO_ERROR)
            status = PRO_TK_GENERAL_ERROR;
    }
    if (stamp != NULL) {
        int begin = model_close_record("begin", "ProVerstampFree", 0);
        cleanup = ProVerstampFree(&stamp);
        if (cleanup != PRO_TK_NO_ERROR) model_close_guard("cleanup_api_status", 0, cleanup, 0, -1);
        if (!model_close_record("end", "ProVerstampFree", (int)cleanup) || !begin || cleanup != PRO_TK_NO_ERROR)
            status = PRO_TK_GENERAL_ERROR;
    }
    return status;
}

typedef struct { int count, target, empty, other; } ModelCloseWindows;
static ProError model_close_visit(int id, ProAppData data)
{
    ModelCloseWindows *windows = (ModelCloseWindows *)data;
    if (model_close_pending.observed_window_count < 3)
        model_close_pending.observed_window_ids[model_close_pending.observed_window_count] = id;
    ++model_close_pending.observed_window_count;
    ++windows->count;
    if (id == model_close_pending.target_window) ++windows->target;
    else if (id == model_close_pending.empty_window) ++windows->empty;
    else ++windows->other;
    return PRO_TK_NO_ERROR;
}

static ProError model_close_validate(int initial)
{
    const ProMdlType types[] = { PRO_MDL_PART, PRO_MDL_ASSEMBLY, PRO_MDL_DRAWING,
        PRO_MDL_3DSECTION, PRO_MDL_2DSECTION, PRO_MDL_LAYOUT, PRO_MDL_DWGFORM,
        PRO_MDL_MFG, PRO_MDL_REPORT, PRO_MDL_MARKUP, PRO_MDL_DIAGRAM };
    ProMdl live = NULL, owner = NULL, *models = NULL;
    ProMdlName name;
    ProMdlType type;
    ProBoolean modified = PRO_B_TRUE;
    ModelCloseWindows windows = { 0, 0, 0, 0 };
    char stamp[1024];
    ProError status = PRO_TK_NO_ERROR, cleanup;
    int current = -1, window = -1, count = 0, i, name_matches;
    model_close_pending.observed_window_count = 0;
    MODEL_CLOSE_CALL("ProMdlCurrentGet", ProMdlCurrentGet(&live));
    if (live == NULL) { status = model_close_refuse("current_model_present", 1, 0, 1, -1, PRO_TK_BAD_INPUTS); goto done; }
    if (!initial && live != model_close_pending.model_handle) {
        status = model_close_refuse("current_model_handle_match", 1, 0, 1, -1, PRO_TK_BAD_INPUTS); goto done;
    }
    wmemset(name, 0, PRO_MDLNAME_SIZE);
    MODEL_CLOSE_CALL("ProMdlMdlnameGet", ProMdlMdlnameGet(live, name));
    name_matches = model_close_name_check(name, PRO_MDLNAME_SIZE);
    if (name_matches <= 0) {
        status = model_close_refuse(name_matches == 0 ? "target_name_match" : "name_metadata_durable",
            1, 0, 1, -1, name_matches == 0 ? PRO_TK_BAD_INPUTS : PRO_TK_GENERAL_ERROR); goto done;
    }
    MODEL_CLOSE_CALL("ProMdlTypeGet", ProMdlTypeGet(live, &type));
    if (type != PRO_MDL_PART) { status = model_close_refuse("target_type", PRO_MDL_PART, type, 0, type, PRO_TK_BAD_INPUTS); goto done; }
    MODEL_CLOSE_CALL("ProMdlWindowGet", ProMdlWindowGet(live, &window));
    if (window != model_close_pending.target_window) {
        status = model_close_refuse("model_window", model_close_pending.target_window, window, 0, type, PRO_TK_BAD_INPUTS); goto done;
    }
    MODEL_CLOSE_CALL("ProWindowCurrentGet", ProWindowCurrentGet(&current));
    if (current != window) { status = model_close_refuse("current_window", window, current, 0, type, PRO_TK_BAD_INPUTS); goto done; }
    MODEL_CLOSE_CALL("ProWindowMdlGet(target)", ProWindowMdlGet(window, &owner));
    if (owner != live) { status = model_close_refuse("target_window_owner_match", 1, 0, 1, type, PRO_TK_BAD_INPUTS); goto done; }
    MODEL_CLOSE_CALL("ProMdlModificationVerify", ProMdlModificationVerify(live, &modified));
    if (modified != PRO_B_FALSE) { status = model_close_refuse("target_modified", 0, 1, 1, type, PRO_TK_E_IN_USE); goto done; }
    status = model_close_stamp(live, stamp);
    if (status != PRO_TK_NO_ERROR) goto done;
    if (!initial && strcmp(stamp, model_close_pending.stamp) != 0) {
        model_close_guard("stamp_length", (long long)strlen(model_close_pending.stamp), (long long)strlen(stamp), 0, type);
        status = model_close_refuse("stamp_match", 1, 0, 1, type, PRO_TK_BAD_INPUTS); goto done;
    }
    for (i = 0; i < (int)(sizeof types / sizeof types[0]); ++i) {
        models = NULL; count = 0;
        if (!model_close_begin("ProSessionMdlList")) { status = PRO_TK_USER_ABORT; goto done; }
        status = ProSessionMdlList(types[i], &models, &count);
        if (!model_close_record("end", "ProSessionMdlList", (int)status)) { status = PRO_TK_GENERAL_ERROR; goto done; }
        if (status != PRO_TK_NO_ERROR && status != PRO_TK_E_NOT_FOUND) {
            status = model_close_refuse("inventory_api_status", 0, status, 0, types[i], status); goto done;
        }
        if (count != (types[i] == PRO_MDL_PART ? 1 : 0)) {
            status = model_close_refuse("inventory_count", types[i] == PRO_MDL_PART ? 1 : 0, count, 0, types[i], PRO_TK_E_IN_USE); goto done;
        }
        if (types[i] == PRO_MDL_PART && (status != PRO_TK_NO_ERROR || models == NULL || models[0] != live)) {
            status = model_close_refuse("inventory_target_handle_match", 1, 0, 1, types[i], PRO_TK_E_IN_USE); goto done;
        }
        if (models != NULL) {
            MODEL_CLOSE_CALL("ProArrayFree(model inventory)", ProArrayFree((ProArray *)&models));
        }
    }
    MODEL_CLOSE_CALL("ProWindowsVisit", ProWindowsVisit(model_close_visit, &windows));
    if (windows.count != 2 || windows.target != 1 || windows.empty != 1 || windows.other != 0) {
        model_close_guard("target_window_count", 1, windows.target, 0, type);
        model_close_guard("empty_window_count", 1, windows.empty, 0, type);
        model_close_guard("other_window_count", 0, windows.other, 0, type);
        status = model_close_refuse("window_count", 2, windows.count, 0, type, PRO_TK_BAD_INPUTS); goto done;
    }
    owner = NULL;
    MODEL_CLOSE_CALL("ProWindowMdlGet(empty)", ProWindowMdlGet(model_close_pending.empty_window, &owner));
    /* Header does not define NOT_FOUND as empty. PTC's TestDbms.c checks NULL
       after NO_ERROR; only that exact successful no-owner result is admitted. */
    if (owner != NULL) { status = model_close_refuse("empty_window_owner_present", 0, 1, 1, type, PRO_TK_E_IN_USE); goto done; }
    if (initial) { model_close_pending.model_handle = live; strcpy(model_close_pending.stamp, stamp); }
done:
    if (models != NULL) {
        int begin = model_close_record("begin", "ProArrayFree(model inventory cleanup)", 0);
        cleanup = ProArrayFree((ProArray *)&models);
        if (cleanup != PRO_TK_NO_ERROR) model_close_guard("cleanup_api_status", 0, cleanup, 0, -1);
        if (!model_close_record("end", "ProArrayFree(model inventory cleanup)", (int)cleanup) || !begin || cleanup != PRO_TK_NO_ERROR)
            status = PRO_TK_GENERAL_ERROR;
    }
    return status;
}

static void model_close_release(void)
{
    if (model_close_pending.journal != NULL && model_close_pending.journal != INVALID_HANDLE_VALUE)
        CloseHandle(model_close_pending.journal);
    if (model_close_pending.directory != NULL && model_close_pending.directory != INVALID_HANDLE_VALUE)
        CloseHandle(model_close_pending.directory);
    model_close_pending.journal = model_close_pending.directory = INVALID_HANDLE_VALUE;
    InterlockedExchange(&model_close_claimed, 0);
}

static int model_close_return_marker(ProError status, int api_called)
{
    wchar_t path[32768];
    char body[2048];
    HANDLE file;
    DWORD written = 0;
    int n, ok;
    if (!model_close_path(path, L"callback-return.json")) return 0;
    n = snprintf(body, sizeof body,
        "{\"close_ticket_id\":\"%ls\",\"service_instance_id\":\"%ls\",\"request_sha256\":\"%ls\","
        "\"target_window\":%d,\"empty_window\":%d,\"model\":\"%ls\",\"native_pid\":%lu,"
        "\"native_creation_filetime\":\"%llu\",\"api_called\":%s,\"status\":%d,"
        "\"normal_callback_return_ready\":true,\"callback_proof\":\"%ls\"}\n", model_close_pending.ticket, model_close_pending.instance,
        model_close_pending.request, model_close_pending.target_window, model_close_pending.empty_window,
        model_close_pending.model, (unsigned long)model_close_pending.pid, model_close_pending.birth,
        api_called ? "true" : "false", (int)status, model_close_pending.proof);
    if (n <= 0 || n >= (int)sizeof body) return 0;
    file = CreateFileW(path, GENERIC_WRITE, FILE_SHARE_READ, NULL, CREATE_NEW,
        FILE_ATTRIBUTE_NORMAL | FILE_FLAG_OPEN_REPARSE_POINT | FILE_FLAG_WRITE_THROUGH, NULL);
    if (file == INVALID_HANDLE_VALUE) return 0;
    ok = WriteFile(file, body, (DWORD)n, &written, NULL) && written == (DWORD)n && FlushFileBuffers(file);
    if (!CloseHandle(file)) ok = 0;
    return ok;
}

/* This OS-only file tells Java whether entering a transport return getter is
   safe. Only a proved refusal before ProMacroLoad carries the independent
   refusal proof. Queue acknowledgement and ambiguity disclose neither proof. */
static int model_close_dispatch_marker(ProError status, int entered, int acknowledged,
                                       const char *state, const char *reason)
{
    wchar_t path[32768];
    char body[2560], proof_field[128] = "";
    HANDLE file;
    DWORD written = 0;
    int n, ok;
    if (!model_close_path(path, L"dispatch.json")) return 0;
    if (!entered && status != PRO_TK_NO_ERROR && strcmp(state, "refused_before_queue") == 0)
        snprintf(proof_field, sizeof proof_field, ",\"dispatch_refusal_proof\":\"%ls\"", model_close_pending.refusal_proof);
    n = snprintf(body, sizeof body,
        "{\"close_ticket_id\":\"%ls\",\"service_instance_id\":\"%ls\",\"request_sha256\":\"%ls\","
        "\"target_window\":%d,\"empty_window\":%d,\"model\":\"%ls\",\"native_pid\":%lu,"
        "\"native_creation_filetime\":\"%llu\",\"dispatch_contract\":\"model_current_close_v2\","
        "\"status\":%d,\"queue_api_entered\":%s,\"queue_acknowledged\":%s,\"state\":\"%s\","
        "\"reason\":\"%s\",\"prequeue_stage\":\"%s\",\"name_change_class\":\"%s\","
        "\"refusal_category\":\"%s\"%s}\n",
        model_close_pending.ticket, model_close_pending.instance, model_close_pending.request,
        model_close_pending.target_window, model_close_pending.empty_window, model_close_pending.model,
        (unsigned long)model_close_pending.pid, model_close_pending.birth, (int)status,
        entered ? "true" : "false", acknowledged ? "true" : "false", state, reason,
        model_close_pending.stage == NULL ? "none" : model_close_pending.stage,
        model_close_pending.name_change == NULL ? "not_read" : model_close_pending.name_change,
        model_close_pending.refusal_category == NULL ? "none" : model_close_pending.refusal_category, proof_field);
    if (n <= 0 || n >= (int)sizeof body) return 0;
    file = CreateFileW(path, GENERIC_WRITE, FILE_SHARE_READ, NULL, CREATE_NEW,
        FILE_ATTRIBUTE_NORMAL | FILE_FLAG_OPEN_REPARSE_POINT | FILE_FLAG_WRITE_THROUGH, NULL);
    if (file == INVALID_HANDLE_VALUE) return 0;
    ok = WriteFile(file, body, (DWORD)n, &written, NULL) && written == (DWORD)n && FlushFileBuffers(file);
    if (!CloseHandle(file)) ok = 0;
    if (!ok) DeleteFileW(path); /* Never leave a known unflushed dispatch as evidence. */
    return ok;
}

static int model_close_command(uiCmdCmdId command, uiCmdValue *value, void *data)
{
    ProError status = PRO_TK_USER_ABORT;
    wchar_t full[32768];
    HANDLE checked = INVALID_HANDLE_VALUE;
    int called = 0;
    if (command != model_close_command_id || model_close_command_id == NULL) {
        model_close_guard("registered_command_match", 1, 0, 1, -1); return 0;
    }
    if (InterlockedCompareExchange(&model_close_claimed, 2, 1) != 1) {
        model_close_guard("pending_ticket_claimed", 1, 0, 1, -1); return 0;
    }
    if (InterlockedCompareExchange(&model_close_export_active, 0, 0) != 0) {
        model_close_guard("outside_export_transport", 1, 0, 1, -1); goto done;
    }
    if (!model_close_live()) goto done;
    checked = owned_exit_runtime(model_close_pending.runtime, full);
    if (checked == INVALID_HANDLE_VALUE || _wcsicmp(full, model_close_pending.runtime) != 0) {
        model_close_guard("runtime_directory_match", 1, 0, 1, -1); goto done;
    }
    CloseHandle(checked); checked = INVALID_HANDLE_VALUE;
    if (!model_close_record("callback-enter", MODEL_CLOSE_COMMAND, 0)) goto done;
    status = model_close_validate(0);
    if (status != PRO_TK_NO_ERROR) goto done;
    if (!model_close_begin("ProWindowCurrentClose")) { status = PRO_TK_USER_ABORT; goto done; }
    called = 1;
    status = ProWindowCurrentClose();
    /* No SDK call follows: only durable OS markers and an immediate return. */
    if (!model_close_record("end", "ProWindowCurrentClose", (int)status)) status = PRO_TK_GENERAL_ERROR;
    if (status != PRO_TK_NO_ERROR)
        model_close_guard("close_api_status", 0, status, 0, PRO_MDL_PART);
done:
    if (checked != INVALID_HANDLE_VALUE) CloseHandle(checked);
    if (!model_close_record("normal-callback-return-ready", MODEL_CLOSE_COMMAND, (int)status))
        status = PRO_TK_GENERAL_ERROR;
    model_close_return_marker(status, called);
    model_close_release();
    return 0;
}

static uiCmdAccessState model_close_access(uiCmdAccessMode mode)
{
    return model_close_command_id != NULL && InterlockedCompareExchange(&model_close_claimed, 0, 0) == 1
        ? ACCESS_AVAILABLE : ACCESS_DISALLOW;
}

static ProError model_close_register(void)
{
    ProError status = ProCmdActionAdd(MODEL_CLOSE_COMMAND, model_close_command, uiProeImmediate,
        model_close_access, PRO_B_FALSE, PRO_B_FALSE, &model_close_command_id);
    if (status != PRO_TK_NO_ERROR) model_close_command_id = NULL;
    return status == PRO_TK_NO_ERROR && model_close_command_id == NULL ? PRO_TK_GENERAL_ERROR : status;
}

static int model_close_registration_witness(const wchar_t *runtime)
{
    wchar_t full[32768], path[32768];
    HANDLE directory, file;
    FILETIME created, exited, kernel, user;
    ULARGE_INTEGER birth;
    DWORD written = 0;
    char body[768];
    int n, ok;
    directory = owned_exit_runtime(runtime, full);
    if (directory == INVALID_HANDLE_VALUE) return 0;
    if (!GetProcessTimes(GetCurrentProcess(), &created, &exited, &kernel, &user)) { CloseHandle(directory); return 0; }
    birth.LowPart = created.dwLowDateTime; birth.HighPart = created.dwHighDateTime;
    n = _snwprintf(path, 32767, L"%ls\\native-model-close-dispatch.json", full);
    if (n < 0) { CloseHandle(directory); return 0; }
    n = snprintf(body, sizeof body,
        "{\"schema_version\":\"1.0\",\"dispatch_contract\":\"model_current_close_v2\","
        "\"command\":\"CreoCliModelCurrentCloseDeferred\",\"priority\":\"uiProeImmediate\","
        "\"input_argument_count\":10,"
        "\"registered\":%s,\"registration_status\":%d,\"native_pid\":%lu,\"native_creation_filetime\":\"%llu\"}\n",
        model_close_registration_status == PRO_TK_NO_ERROR && model_close_command_id != NULL ? "true" : "false",
        (int)model_close_registration_status, (unsigned long)GetCurrentProcessId(), birth.QuadPart);
    file = CreateFileW(path, GENERIC_WRITE, FILE_SHARE_READ, NULL, CREATE_NEW,
        FILE_ATTRIBUTE_NORMAL | FILE_FLAG_OPEN_REPARSE_POINT | FILE_FLAG_WRITE_THROUGH, NULL);
    if (file == INVALID_HANDLE_VALUE) { CloseHandle(directory); return 0; }
    ok = n > 0 && n < (int)sizeof body && WriteFile(file, body, (DWORD)n, &written, NULL) &&
        written == (DWORD)n && FlushFileBuffers(file);
    if (!CloseHandle(file)) ok = 0;
    CloseHandle(directory);
    return ok;
}

PRO_TK_DLL_EXPORT ProError creo_cli_model_current_close(ProArgument *inputs, ProArgument **outputs)
{
    const wchar_t *labels[] = { L"target_window", L"empty_window", L"model", L"close_ticket_id",
        L"service_instance_id", L"request_sha256", L"ttl_ms", L"runtime_directory", L"callback_proof", L"dispatch_refusal_proof" };
    ModelCloseTicket ticket;
    FILETIME created, exited, kernel, user;
    ULARGE_INTEGER birth;
    wchar_t runtime[32768], journal[32768];
    int n = 0, i, j, ttl = 0, found, queue_entered = 0, queue_acknowledged = 0, journal_opened = 0;
    const char *reason = "export_prequeue_refused";
    ProError status = PRO_TK_BAD_INPUTS;
    if (outputs == NULL) return status;
    *outputs = NULL;
    if (!model_close_registration_reported || model_close_command_id == NULL) return PRO_TK_E_NOT_FOUND;
    if (InterlockedCompareExchange(&model_close_claimed, -1, 0) != 0) return PRO_TK_E_IN_USE;
    memset(&ticket, 0, sizeof ticket);
    ticket.directory = ticket.journal = INVALID_HANDLE_VALUE;
    if (inputs == NULL || ProArraySizeGet((ProArray)inputs, &n) != PRO_TK_NO_ERROR || n != 10) goto bad;
    for (i = 0; i < n; ++i) {
        found = 0;
        for (j = 0; j < 10; ++j) if (wcscmp(inputs[i].label, labels[j]) == 0) ++found;
        if (found != 1) goto bad;
        for (j = 0; j < i; ++j) if (wcscmp(inputs[i].label, inputs[j].label) == 0) goto bad;
    }
    if (arg_int(inputs, L"target_window", &ticket.target_window) != PRO_TK_NO_ERROR || ticket.target_window < 0 ||
        arg_int(inputs, L"empty_window", &ticket.empty_window) != PRO_TK_NO_ERROR || ticket.empty_window < 0 ||
        ticket.target_window == ticket.empty_window || arg_int(inputs, L"ttl_ms", &ttl) != PRO_TK_NO_ERROR || ttl < 1 || ttl > 30000 ||
        !owned_exit_wstring(inputs, L"model", ticket.model, 81) || !model_close_stem(ticket.model) ||
        !owned_exit_wstring(inputs, L"close_ticket_id", ticket.ticket, 33) || !model_close_hex(ticket.ticket, 32) ||
        !owned_exit_wstring(inputs, L"service_instance_id", ticket.instance, 37) || !owned_exit_id(ticket.instance, 1) ||
        !owned_exit_wstring(inputs, L"request_sha256", ticket.request, 65) || !model_close_hex(ticket.request, 64) ||
        !owned_exit_wstring(inputs, L"callback_proof", ticket.proof, 65) || !model_close_hex(ticket.proof, 64) ||
        !owned_exit_wstring(inputs, L"dispatch_refusal_proof", ticket.refusal_proof, 65) || !model_close_hex(ticket.refusal_proof, 64) ||
        wcscmp(ticket.proof, ticket.refusal_proof) == 0 ||
        !owned_exit_wstring(inputs, L"runtime_directory", runtime, 32768)) goto bad;
    ticket.directory = owned_exit_runtime(runtime, ticket.runtime);
    if (ticket.directory == INVALID_HANDLE_VALUE || !GetProcessTimes(GetCurrentProcess(), &created, &exited, &kernel, &user)) goto bad;
    ticket.pid = GetCurrentProcessId();
    birth.LowPart = created.dwLowDateTime; birth.HighPart = created.dwHighDateTime;
    ticket.birth = birth.QuadPart; ticket.deadline = GetTickCount64() + (ULONGLONG)ttl;
    model_close_pending = ticket;
    if (!model_close_path(journal, L"native.jsonl")) goto failed;
    model_close_pending.journal = CreateFileW(journal, GENERIC_WRITE, FILE_SHARE_READ, NULL, CREATE_NEW,
        FILE_ATTRIBUTE_NORMAL | FILE_FLAG_OPEN_REPARSE_POINT | FILE_FLAG_WRITE_THROUGH, NULL);
    if (model_close_pending.journal == INVALID_HANDLE_VALUE) goto failed;
    journal_opened = 1;
    status = model_close_validate(1);
    if (status != PRO_TK_NO_ERROR) {
        reason = model_close_pending.name_change != NULL &&
            strcmp(model_close_pending.name_change, "ordinal_equal") != 0 &&
            strcmp(model_close_pending.name_change, "ascii_case_only") != 0
            ? "target_name_mismatch" : "native_validation_refused";
        goto failed;
    }
    if (!model_close_begin("ProArrayAlloc(outputs)")) { status = PRO_TK_USER_ABORT; goto failed; }
    status = ProArrayAlloc(0, sizeof(ProArgument), 4, (ProArray *)outputs);
    if (!model_close_record("end", "ProArrayAlloc(outputs)", (int)status)) status = PRO_TK_GENERAL_ERROR;
    if (status != PRO_TK_NO_ERROR) goto failed;
    if (!model_close_begin("ProMacroLoad(fixed model close)")) { status = PRO_TK_USER_ABORT; goto failed; }
    InterlockedExchange(&model_close_export_active, 1);
    InterlockedExchange(&model_close_claimed, 1);
    queue_entered = 1;
    status = ProMacroLoad(L"~ Command `CreoCliModelCurrentCloseDeferred`;");
    queue_acknowledged = status == PRO_TK_NO_ERROR;
    InterlockedExchange(&model_close_export_active, 0);
    if (InterlockedCompareExchange(&model_close_claimed, 0, 0) != 1) {
        status = PRO_TK_GENERAL_ERROR; reason = "inline_callback_refused"; goto failed;
    }
    reason = "queue_api_error";
    if (status != PRO_TK_NO_ERROR) model_close_guard("queue_api_status", 0, status, 0, -1);
    if (!model_close_record("end", "ProMacroLoad(fixed model close)", (int)status)) {
        status = PRO_TK_GENERAL_ERROR; reason = "postqueue_journal_failed";
    }
    if (status != PRO_TK_NO_ERROR) goto failed;
    if (!model_close_dispatch_marker(status, 1, 1, "queue_acknowledged", "queue_acknowledged")) {
        status = PRO_TK_GENERAL_ERROR; goto dispatch_failed;
    }
    return PRO_TK_NO_ERROR;
failed:
    model_close_record("export-refused", MODEL_CLOSE_COMMAND, (int)status);
    if (status == PRO_TK_NO_ERROR) status = PRO_TK_GENERAL_ERROR;
    if (journal_opened && !model_close_dispatch_marker(status, queue_entered, queue_acknowledged,
            queue_entered ? "queue_outcome_unknown" : "refused_before_queue", reason))
        status = PRO_TK_GENERAL_ERROR;
dispatch_failed:
    model_close_release();
    return status;
bad:
    if (ticket.directory != INVALID_HANDLE_VALUE) CloseHandle(ticket.directory);
    InterlockedExchange(&model_close_claimed, 0);
    return status;
}

#undef MODEL_CLOSE_CALL

/* -------------------------------------------------- current close section end */

/* Tell the Java service which id Creo gave this library, since PTC documents the id
   only as "an identifying string". Written on every start; never fails the start --
   a non-zero return here would make Creo treat the application as failed. */
static void write_runtime_handshake(const wchar_t *directory, const char *id,
                                    const char *image_utf8)
{
    wchar_t path[32768];
    FILE *file;
    if (directory == NULL || wcslen(directory) + 32 >= 32768) return;
    _snwprintf(path, 32767, L"%ls\\native-sketch-id", directory);
    path[32767] = 0;
    file = _wfopen(path, L"wb");
    if (file != NULL) { fputs(id, file); fclose(file); }
    if (image_utf8 != NULL) {
        _snwprintf(path, 32767, L"%ls\\native-loaded-image.txt", directory);
        path[32767] = 0;
        file = _wfopen(path, L"wb");
        if (file != NULL) {
            fprintf(file, "%lu\n%s\n", (unsigned long)GetCurrentProcessId(), image_utf8);
            fclose(file);
        }
    }
}

int user_initialize(int argc, char *argv[], char *version, char *build, wchar_t errbuf[80])
{
    ProName id;
    char id_utf8[PRO_NAME_SIZE * 4];
    wchar_t image[32768], fallback[32768], *slash;
    char image_utf8[32768 * 4];
    const wchar_t *state = _wgetenv(L"CREO_CLI_CONFIG_DIR");
    const wchar_t *home = _wgetenv(L"USERPROFILE");
    HMODULE module = NULL;
    DWORD length;
    int has_image = 0;
    owned_exit_registration_status = owned_exit_register();
    if (state != NULL && state[0] != 0)
        owned_exit_registration_reported = owned_exit_registration_witness(state);
    model_close_registration_status = model_close_register();
    if (state != NULL && state[0] != 0)
        model_close_registration_reported = model_close_registration_witness(state);
    if (ProToolkitDllIdGet(NULL, id) != PRO_TK_NO_ERROR) return 0;
    if (!WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, id, -1,
                             id_utf8, (int)sizeof id_utf8, NULL, NULL)) return 0;
    if (GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS |
                          GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                          (LPCWSTR)&user_initialize, &module)) {
        length = GetModuleFileNameW(module, image, 32768);
        if (length > 0 && length < 32768)
            has_image = WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, image, -1,
                                            image_utf8, (int)sizeof image_utf8, NULL, NULL) > 0;
    }
    if ((state == NULL || state[0] == 0) && home != NULL && wcslen(home) + 16 < 32768) {
        _snwprintf(fallback, 32767, L"%ls\\.creo-cli", home);
        fallback[32767] = 0;
        state = fallback;
    }
    if (state != NULL && state[0] != 0)
        write_runtime_handshake(state, id_utf8, has_image ? image_utf8 : NULL);
    /* A live registered DLL also provides a UTF-8 identity beside its actual image.
       Windows paths are handled as UTF-16 throughout; no ANSI code-page conversion. */
    if (has_image) {
        slash = wcsrchr(image, L'\\');
        if (slash != NULL) {
            *slash = 0;
            write_runtime_handshake(image, id_utf8, image_utf8);
        }
    }
    return 0;
}

void user_terminate(void)
{
}
