package com.fateforge.creocli.service;

/**
 * PTC's element-tree vocabulary, under PTC's own names.
 *
 * <p>The Java toolkit exposes element ids ({@code wfcElemIds}) but none of the values
 * those elements take: {@code PRO_EXT_FEAT_TYPE_SOLID}, {@code PRO_EXT_DEPTH_TO_BLIND}
 * and the rest exist only in the C headers, and PTC's own Java examples write them as
 * bare integers. A bare integer is exactly the thing that goes wrong silently, so every
 * value used anywhere in this service is declared here, once, by the name PTC gives it.
 *
 * <p>These were generated from {@code contract/feature-trees.json}, which is derived
 * from the headers, and {@code tests/test_feature_trees.py} holds them to it: a name
 * that is not PTC's fails, a value that differs from the header fails, and an element
 * id on which the headers and {@code wfcElemIds} disagree fails -- the two sources
 * disagree on sixteen ids in Creo 13.4, and a modelling command must not depend on
 * which of them is right. Add a constant here and the test checks it; do not write an
 * element id or value as a literal anywhere else.
 */
final class Ptc {

    private Ptc() {
    }

    // element ids -- ProElemId.h
    static final int PRO_E_FEATURE_TREE = 386;
    static final int PRO_E_FEATURE_TYPE = 387;
    static final int PRO_E_FEATURE_FORM = 388;
    static final int PRO_E_STD_FEATURE_NAME = 1964;
    static final int PRO_E_EXT_SURF_CUT_SOLID_TYPE = 1956;
    static final int PRO_E_REMOVE_MATERIAL = 2023;
    static final int PRO_E_FEAT_FORM_IS_THIN = 3176;
    static final int PRO_E_STD_SECTION = 447;
    static final int PRO_E_STD_SEC_SETUP_PLANE = 450;
    static final int PRO_E_STD_SEC_PLANE = 451;
    static final int PRO_E_STD_SEC_PLANE_VIEW_DIR = 452;
    static final int PRO_E_STD_SEC_PLANE_ORIENT_DIR = 454;
    static final int PRO_E_STD_SEC_PLANE_ORIENT_REF = 455;
    static final int PRO_E_SKETCHER = 458;
    static final int PRO_E_STD_DIRECTION = 436;
    static final int PRO_E_STD_EXT_DEPTH = 515;
    static final int PRO_E_EXT_DEPTH_TO = 429;
    static final int PRO_E_EXT_DEPTH_TO_TYPE = 433;
    static final int PRO_E_EXT_DEPTH_TO_VALUE = 434;
    static final int PRO_E_BODY = 6314;
    static final int PRO_E_BODY_USE = 6315;
    static final int PRO_E_BODY_SELECT = 6316;
    static final int PRO_E_REVOLVE_AXIS = 3279;
    static final int PRO_E_REVOLVE_AXIS_OPT = 3280;
    static final int PRO_E_REV_ANGLE = 6;
    static final int PRO_E_REV_ANGLE_FROM = 437;
    static final int PRO_E_REV_ANGLE_FROM_TYPE = 439;
    static final int PRO_E_REV_ANGLE_TO = 438;
    static final int PRO_E_REV_ANGLE_TO_TYPE = 440;
    static final int PRO_E_REV_ANGLE_TO_VAL = 442;
    static final int PRO_E_DTMPLN_CONSTRAINTS = 410;
    static final int PRO_E_DTMPLN_CONSTRAINT = 411;
    static final int PRO_E_DTMPLN_CONSTR_TYPE = 412;
    static final int PRO_E_DTMPLN_CONSTR_REF = 413;
    static final int PRO_E_DTMPLN_CONSTR_REF_OFFSET = 414;
    static final int PRO_E_DTMPLN_CONSTR_REF_ANGLE = 415;
    static final int PRO_E_DTMAXIS_CONSTRAINTS = 2015;
    static final int PRO_E_DTMAXIS_CONSTRAINT = 2016;
    static final int PRO_E_DTMAXIS_CONSTR_TYPE = 2017;
    static final int PRO_E_DTMAXIS_CONSTR_REF = 2018;
    static final int PRO_E_RNDCH_SETS = 2101;
    static final int PRO_E_RNDCH_SET = 2102;
    static final int PRO_E_RNDCH_SHAPE_OPTIONS = 2178;
    static final int PRO_E_RNDCH_COMPOUND_CONIC = 2177;
    static final int PRO_E_RNDCH_CONIC_TYPE = 2119;
    static final int PRO_E_RNDCH_REFERENCES = 2121;
    static final int PRO_E_RNDCH_REFERENCE_TYPE = 2179;
    static final int PRO_E_STD_CURVE_COLLECTION_APPL = 2124;
    static final int PRO_E_RNDCH_RADII = 2123;
    static final int PRO_E_RNDCH_RADIUS = 2122;
    static final int PRO_E_RNDCH_LEG1 = 2106;
    static final int PRO_E_RNDCH_LEG_TYPE = 2108;
    static final int PRO_E_RNDCH_LEG_VALUE = 2109;
    static final int PRO_E_RNDCH_ATTACH_TYPE = 3042;
    static final int PRO_E_RNDCH_DIMENSIONAL_SCHEMA = 2103;
    static final int PRO_E_SHELL_SRF = 73;
    static final int PRO_E_SHELL_THICK = 74;
    static final int PRO_E_SHELL_FLIP = 2194;
    static final int PRO_E_ST_SHELL_LOCL_LIST = 556;
    static final int PRO_E_HLE_COM = 1671;
    static final int PRO_E_HLE_TYPE_NEW = 1672;
    static final int PRO_E_DIAMETER = 82;
    static final int PRO_E_HOLE_STD_DEPTH = 1684;
    static final int PRO_E_HOLE_DEPTH_TO = 1686;
    static final int PRO_E_HOLE_DEPTH_TO_TYPE = 1688;
    static final int PRO_E_HOLE_DEPTH_FROM = 1685;
    static final int PRO_E_HOLE_DEPTH_FROM_TYPE = 1687;
    static final int PRO_E_HLE_PLACEMENT = 1340;
    static final int PRO_E_HLE_PRIM_REF = 1341;
    static final int PRO_E_HLE_PL_TYPE = 696;
    static final int PRO_E_HLE_DIM_REF1 = 704;
    static final int PRO_E_HLE_DIM_DIST1 = 706;
    static final int PRO_E_HLE_DIM_REF2 = 707;
    static final int PRO_E_HLE_DIM_DIST2 = 708;
    static final int PRO_E_HLE_AXIS = 698;
    static final int PRO_E_HLE_DIM_DIA = 709;
    static final int PRO_E_HLE_PLCMNT_PLANE = 1677;
    static final int PRO_E_HLE_REF_PLANE_1 = 1678;
    static final int PRO_E_HLE_REF_ANG_1 = 1679;
    static final int PRO_E_HLE_STAN_TYPE = 1673;
    static final int PRO_E_HLE_THRDSERIS = 1356;
    static final int PRO_E_HLE_FITTYPE = 1661;
    static final int PRO_E_HLE_SCREWSIZE = 1358;
    static final int PRO_E_HLE_ADD_THREAD = 1674;
    static final int PRO_E_HLE_ADD_CBORE = 1675;
    static final int PRO_E_HLE_ADD_CSINK = 1676;
    static final int PRO_E_HLE_HOLEDIAM = 1347;
    static final int PRO_E_HLE_DEPTH = 1662;
    static final int PRO_E_HLE_CSINKANGLE = 1352;
    static final int PRO_E_HLE_CBOREDEPTH = 1349;
    static final int PRO_E_HLE_CBOREDIAM = 1350;
    static final int PRO_E_HLE_CSINKDIAM = 1351;
    static final int PRO_E_HLE_DEPTH_DIM_TYPE = 3741;
    static final int PRO_E_HLE_THRD_DEPTH = 1680;
    static final int PRO_E_HLE_THRDDEPTH = 1354;
    static final int PRO_E_HLE_DRILLANGLE = 1348;
    static final int PRO_E_HLE_DRILLDEPTH = 1663;
    static final int PRO_E_HLE_CRDIR_FLIP = 1689;
    static final int PRO_E_HLE_ADD_EXIT_CSINK = 3110;
    static final int PRO_E_HLE_ADD_PARAMETERS = 6900;
    static final int PRO_E_HLE_ADD_NOTE = 3750;
    static final int PRO_E_HLE_TOP_CLEARANCE = 6053;
    static final int PRO_E_THRD_TYPE_OPT_NEW = 4974;
    static final int PRO_E_THRD_SURF_NEW = 4902;
    static final int PRO_E_THRD_DIAM_NEW = 4900;
    static final int PRO_E_THRD_START_REF_NEW = 4901;
    static final int PRO_E_PATTERN_ROOT = 604;
    static final int PRO_E_GENPAT_TYPE = 3124;
    static final int PRO_E_GENPAT_REGEN_METHOD = 3131;
    static final int PRO_E_GENPAT_AXIS = 3130;
    static final int PRO_E_GENPAT_AXIS_REF = 3273;
    static final int PRO_E_GENPAT_AXIS1_INC = 3276;
    static final int PRO_E_AXIS_PAT_DIR1_FLIP = 3309;
    static final int PRO_E_GENPAT_DIM_FIRST_DIR = 3133;
    static final int PRO_E_GENPAT_DIM_FIRST_DIR_NUM_INST = 3134;
    static final int PRO_E_GENPAT_DIR = 3129;
    static final int PRO_E_GENPAT_DIR1 = 3291;
    static final int PRO_E_DIRECTION_COMPOUND = 3252;
    static final int PRO_E_DIRECTION_REFERENCE = 3253;
    static final int PRO_E_DIRECTION_FLIP = 3254;
    static final int PRO_E_GENPAT_DIR1_INC = 3274;
    static final int PRO_E_DIR_PAT_DIR1_FLIP = 3307;
    static final int PRO_E_DIR_PAT_DIR1_OPT = 4026;
    static final int PRO_E_GENPAT_DIR2 = 3292;
    static final int PRO_E_GENPAT_DIR2_INC = 3275;
    static final int PRO_E_DIR_PAT_DIR2_FLIP = 3308;
    static final int PRO_E_DIR_PAT_DIR2_OPT = 4027;
    static final int PRO_E_GENPAT_DIM_SECOND_DIR = 3135;
    static final int PRO_E_GENPAT_DIM_SECOND_DIR_NUM_INST = 3136;
    static final int PRO_E_SRF_TRANS_TYPE = 3182;
    static final int PRO_E_MIRROR_REF_ITEMS = 3161;
    static final int PRO_E_MIRROR_REF_PLANE = 3162;
    static final int PRO_E_COPY_NO_COPY = 3163;
    static final int PRO_E_STD_SURF_COLLECTION_APPL = 2213;
    static final int PRO_E_DRAFT_SPLIT = 2154;
    static final int PRO_E_DRAFT_CONSTANT_OR_VARIABLE = 2150;
    static final int PRO_E_DRAFT_INCLUDE_TANGENT = 3177;
    static final int PRO_E_DRAFT_SIDE_1 = 2164;
    static final int PRO_E_DRAFT_NEUTRAL_OBJECT_TYPE_1 = 2167;
    static final int PRO_E_DRAFT_NEUTRAL_PLANE_1 = 2169;
    static final int PRO_E_DRAFT_DEPENDENT_1 = 2171;
    static final int PRO_E_DRAFT_ANGLE_1 = 2168;
    static final int PRO_E_RIB_SECTION_COMP = 3109;
    static final int PRO_E_STD_MATRLSIDE = 499;
    static final int PRO_E_RIB_THICKNESS = 1965;
    static final int PRO_E_RIB_SIDE_OPTS = 2196;
    static final int PRO_E_CURVE_TYPE = 511;
    static final int PRO_E_SWEEP_TYPE = 5528;
    static final int PRO_E_SWEEP_FRAME_COMP = 3165;
    static final int PRO_E_FRM_OPT_TRAJ = 1176;
    static final int PRO_E_OPT_TRAJ = 15;
    static final int PRO_E_STD_SEC_METHOD = 725;
    static final int PRO_E_STD_SEC_SELECT = 726;
    static final int PRO_E_FRAME_SETUP = 1159;
    static final int PRO_E_FRM_NORMAL = 1170;
    static final int PRO_E_FRM_ORIENT = 1171;
    static final int PRO_E_FRM_PIVOT_DIR = 1172;
    static final int PRO_E_SWP_ATTR = 1651;
    static final int PRO_E_SWEEP_PROF_COMP = 3164;
    static final int PRO_E_SWEEP_SECTION = 897;

    // feature types -- ProFeatType.h
    static final int PRO_FEAT_PROTRUSION = 917;
    static final int PRO_FEAT_CUT = 916;
    static final int PRO_FEAT_DATUM = 923;
    static final int PRO_FEAT_DATUM_AXIS = 926;
    static final int PRO_FEAT_ROUND = 913;
    static final int PRO_FEAT_CHAMFER = 914;
    static final int PRO_FEAT_SHELL = 928;
    static final int PRO_FEAT_HOLE = 911;
    static final int PRO_FEAT_GEN_MERGE = 1238;
    static final int PRO_FEAT_DRAFT = 927;
    static final int PRO_FEAT_RIB = 920;
    static final int PRO_FEAT_THREAD = 1070;
    static final int PRO_FEAT_CURVE = 949;

    // ProFeatFormType -- ProFeatForm.h
    static final int PRO_EXTRUDE = 1;
    static final int PRO_REVOLVE = 2;

    // ProRevolve.h
    static final int PRO_REV_FEAT_TYPE_SOLID = 917;
    static final int PRO_REV_MATERIAL_ADD = -1;
    static final int PRO_REV_MATERIAL_REMOVE = 916;
    static final int PRO_REV_FEAT_FORM_NO_THIN = 0;
    static final int PRO_REV_ANG_FROM_NONE = 262144;
    static final int PRO_REV_ANG_TO_ANGLE = 4194304;
    static final int PRO_REV_ANG_SYMMETRIC = 536870912;
    static final int PRO_REV_AXIS_EXT_REF = -1;
    static final int PRO_REV_AXIS_INT_REF = 1;
    static final int PRO_REV_CR_IN_SIDE_ONE = -1;
    static final int PRO_REV_CR_IN_SIDE_TWO = 1;

    // ProDtmPln.h, ProDtmAxis.h
    static final int PRO_DTMPLN_THRU = 0;
    static final int PRO_DTMPLN_OFFS = 3;
    static final int PRO_DTMPLN_ANG = 4;
    // These default datum-plane constraints do not require a selection reference.
    static final int PRO_DTMPLN_DEF_X = 7;
    static final int PRO_DTMPLN_DEF_Y = 8;
    static final int PRO_DTMPLN_DEF_Z = 9;
    // ProDtmplnFlipDir / ProDtmplnFitType -- ProDtmPln.h (explicit read values, never absence defaults)
    static final int PRO_DTMPLN_FLIP_DIR_NO = 0;
    static final int PRO_DTMPLN_FLIP_DIR_YES = 1;
    static final int PRO_DTMPLN_FIT_DEFAULT = -1;
    static final int PRO_DTMAXIS_CONSTR_TYPE_THRU = 1;

    // ProRound.h, ProChamfer.h
    static final int PRO_ROUND_TYPE_CONSTANT = 0;
    static final int PRO_ROUND_CONIC_DISABLE = 2;
    static final int PRO_ROUND_REF_EDGE = 1;
    static final int PRO_ROUND_RADIUS_TYPE_VALUE = 1;
    static final int PRO_ROUND_ATTACHED = 0;
    static final int PRO_CHM_D_X_D = 602;
    static final int PRO_CHM_45_X_D = 601;

    // ProShell.h
    static final int PRO_SHELL_INSIDE = 1;
    static final int PRO_SHELL_OUTSIDE = -1;

    // ProDraft.h, ProDirection.h
    static final int PRO_DRAFT_UI_SPLIT_NONE = 0;
    static final int PRO_DRAFT_UI_CONSTANT = 1;
    static final int PRO_DRAFT_UI_INC_TANG = 1;
    static final int PRO_DRAFT_UI_PLANE = 1;
    static final int PRO_DRAFT_UI_INDEPENDENT = 0;
    static final int PRO_DIRECTION_FLIP_ALONG = 1;
    static final int PRO_DIRECTION_FLIP_AGAINST = -1;

    // ProDtmCrv.h, ProSweep.h, ProStdSection.h
    static final int PRO_CURVE_TYPE_SKETCHED = 0;
    static final int PRO_SWEEP = 4;
    static final int PRO_SWEEP_TYPE_MULTI_TRAJ = 128;
    static final int PRO_FRAME_CONSTANT = 3;
    static final int PRO_FRAME_PIVOT_DIR = 1 << 9;
    static final int PRO_SEC_SELECT = 26;
    static final int PRO_SWEEP_FEAT_TYPE_SOLID = 917;
    static final int PRO_SWEEP_MATERIAL_ADD = -1;
    static final int PRO_SWEEP_MATERIAL_REMOVE = 916;
    static final int PRO_SWEEP_FEAT_FORM_NO_THIN = 0;

    // ProRib.h
    static final int PRO_RIB_SYMMETRIC = 1;
    static final int PRO_RIB_SIDE_ONE = 2;
    static final int PRO_RIB_SIDE_TWO = 3;
    static final int PRO_RIB_SEC_SIDE_ONE = 1;
    static final int PRO_RIB_SEC_SIDE_TWO = 2;

    // ProPattern.h
    static final int PRO_GENPAT_DIR_DRIVEN = 5;
    static final int PRO_GENPAT_AXIS_DRIVEN = 6;
    static final int PRO_PAT_GENERAL = 4;
    static final int PRO_GENPAT_TRANSLATIONAL = -1;

    // ProMirror.h, ProSrfcollection.h
    static final int PRO_SURF_TRANS_TYPE_PART_MIRROR = 4;
    static final int PRO_MIRROR_KEEP_ORIGINAL = 0;

    // ProHole.h
    static final int PRO_HLE_TYPE_STRAIGHT = 1;
    static final int PRO_HLE_NEW_TYPE_STRAIGHT = 16;
    static final int PRO_HLE_STRGHT_BLIND_DEPTH = 1;
    static final int PRO_HLE_STRGHT_THRU_ALL_DEPTH = 3;
    static final int PRO_HLE_STRGHT_NONE_DEPTH = 6;
    static final int PRO_HLE_PL_TYPE_LIN = 1;
    static final int PRO_HLE_PL_TYPE_RAD_DIA_DIM = 3;
    static final int PRO_HLE_PL_TYPE_COAX = 5;
    static final int PRO_HLE_TYPE_SKETCHED = 2;
    static final int PRO_HLE_CUSTOM_TYPE = 7;
    static final int PRO_HLE_NEW_TYPE_STANDARD = 24;
    static final int PRO_HLE_TAPPED_TYPE = 14;
    static final int PRO_HLE_CLEARANCE_TYPE = 15;
    static final int PRO_HLE_CLOSE_FIT = 0;
    static final int PRO_HLE_FREE_FIT = 1;
    static final int PRO_HLE_MEDIUM_FIT = 2;
    static final int PRO_HLE_NO_THREAD = -1;
    static final int PRO_HLE_ADD_THREAD = 26;
    static final int PRO_HLE_NO_CBORE = -1;
    static final int PRO_HLE_ADD_CBORE = 27;
    static final int PRO_HLE_NO_CSINK = -1;
    static final int PRO_HLE_ADD_CSINK = 28;
    static final int PRO_HLE_THRU_THREAD = 32;
    static final int PRO_HLE_VARIABLE_THREAD = 33;
    static final int PRO_HLE_STD_VAR_DEPTH = 29;
    static final int PRO_HLE_STD_THRU_ALL_DEPTH = 31;
    static final int PRO_HLE_DEP_SHOULDER_DIM_SCHEME = -1;
    static final int PRO_HLE_CR_IN_SIDE_ONE = -1;
    static final int PRO_HLE_NO_EXIT_CSINK = -1;
    static final int PRO_HOLE_ADD_NOTE_FLAG = -1;
    static final int PRO_HOLE_GEN_CLRNCE = -1;

    // ProExtFeatType -- ProExtrude.h
    static final int PRO_EXT_FEAT_TYPE_SOLID = 917;

    // ProExtRemMaterial -- ProExtrude.h
    static final int PRO_EXT_MATERIAL_ADD = -1;
    static final int PRO_EXT_MATERIAL_REMOVE = 916;

    // ProExtFeatForm -- ProExtrude.h
    static final int PRO_EXT_FEAT_FORM_NO_THIN = 0;

    // ProSecViewDirType -- ProStdSection.h
    static final int PRO_SEC_VIEW_DIR_SIDE_ONE = 1;
    static final int PRO_SEC_VIEW_DIR_SIDE_TWO = -1;

    // ProSecOrientDirType -- ProStdSection.h
    static final int PRO_SEC_ORIENT_DIR_UP = 1;
    static final int PRO_SEC_ORIENT_DIR_DOWN = 2;
    static final int PRO_SEC_ORIENT_DIR_LEFT = 3;
    static final int PRO_SEC_ORIENT_DIR_RIGHT = 4;

    // ProExtDirection -- ProExtrude.h
    static final int PRO_EXT_CR_IN_SIDE_ONE = -1;
    static final int PRO_EXT_CR_IN_SIDE_TWO = 1;

    // ProBodyUseOpts -- ProBodyOpts.h
    static final int PRO_BODY_USE_NEW = 0;
    static final int PRO_BODY_USE_ALL = 1;
    static final int PRO_BODY_USE_SELECTED = 2;

    // ProExtDepthToType -- ProExtrude.h
    static final int PRO_EXT_DEPTH_TO_BLIND = 262144;
    static final int PRO_EXT_DEPTH_SYMMETRIC = 268435456;

    // ProAsmcompSetType / IntfcPlaceType -- ProAsmcomp.h
    static final int PRO_ASM_SET_TYPE_FIXED = 0;
    static final int PRO_ASM_SET_USER_DEFINED_TYPE = 5200;
    static final int PRO_ASM_INTFC_NONE = 0;
}
