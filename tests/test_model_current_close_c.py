"""Exercise the real fixed close C section against fake SDK calls, never Creo."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts import build_native_sketch

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "service/native/creo_cli_sketch.c"
TICKET = "0123456789abcdef0123456789abcdef"
HARNESS = r"""
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <wchar.h>
#include <stddef.h>
typedef int ProError;
typedef int ProMdlType;
typedef int ProBoolean;
typedef void *ProMdl;
typedef void *ProArray;
typedef void *ProAppData;
typedef wchar_t ProMdlName[180];
#define PRO_MDLNAME_SIZE 180
typedef char *ProWVerstamp;
typedef struct { int type; union { int i; double d; void *p; wchar_t *w; } v; } ProValueData;
typedef struct { wchar_t label[32]; ProValueData value; } ProArgument;
_Static_assert(sizeof(ProValueData)==16,"fake value ABI");
_Static_assert(offsetof(ProValueData,v)==8,"fake union ABI");
_Static_assert(sizeof(ProArgument)==80,"fake argument ABI");
_Static_assert(offsetof(ProArgument,value)==64,"fake argument offset ABI");
typedef void *uiCmdCmdId;
typedef int uiCmdValue;
typedef int uiCmdAccessMode;
typedef int uiCmdAccessState;
typedef int (*uiCmdCmdActFn)(uiCmdCmdId,uiCmdValue*,void*);
typedef int (*uiCmdAccessFn)(uiCmdAccessMode);
#define uiProeImmediate 2
#define PRO_B_TRUE 1
#define PRO_B_FALSE 0
#define ACCESS_AVAILABLE 4
#define ACCESS_DISALLOW 3
#define PRO_TK_DLL_EXPORT
#define PRO_TK_NO_ERROR 0
#define PRO_TK_GENERAL_ERROR -1
#define PRO_TK_BAD_INPUTS -2
#define PRO_TK_USER_ABORT -3
#define PRO_TK_E_NOT_FOUND -4
#define PRO_TK_E_IN_USE -39
#define PRO_VALUE_TYPE_INT 1
#define PRO_VALUE_TYPE_WSTRING 5
#define OWNED_EXIT_MAX_WAIT_MS 30000ULL
enum {PRO_MDL_PART=2,PRO_MDL_ASSEMBLY=1,PRO_MDL_DRAWING=4,PRO_MDL_3DSECTION=7,
 PRO_MDL_2DSECTION=11,PRO_MDL_LAYOUT=19,PRO_MDL_DWGFORM=33,PRO_MDL_MFG=37,
 PRO_MDL_REPORT=105,PRO_MDL_MARKUP=116,PRO_MDL_DIAGRAM=121};
static int mode, phase, sdk_calls, close_calls, sdk_after_close, wrong_context, allocated;
static int macro_calls, inputs_count=10, flush_count, callback_sdk_calls, after_close_flush;
static int callback_flushes;
static int macro_returned, io_stage, postqueue_flush_failed;
static wchar_t test_runtime[32768];
static ULONGLONG tick=10000;
static ProMdl original=(ProMdl)0x3333;
static uiCmdCmdId command_id=(uiCmdCmdId)0x1234;
static uiCmdCmdActFn callback;
static int sdk(void) { ++sdk_calls;if(close_calls)++sdk_after_close;return 0; }
static ULONGLONG test_tick(void) { return tick; }
static BOOL test_flush(HANDLE file) {
    ++flush_count;
    if((mode==52 && flush_count==2) || (mode==53 && phase==1 && ++callback_flushes==2))tick+=2000;
    if((mode==54 && flush_count==2) || (mode==55 && phase==1 && ++callback_flushes==2)) {
        wchar_t path[32768];FILE *cancel;
        _snwprintf(path,32767,L"%ls\\model-close-0123456789abcdef0123456789abcdef.cancelled.json",test_runtime);
        cancel=_wfopen(path,L"w");if(cancel){fputs("{}",cancel);fclose(cancel);}
    }
    if(mode==12 || (mode==13 && phase==1))return FALSE;
    if(close_calls && mode==47 && ++after_close_flush==2)return FALSE;
    if(close_calls && mode==48 && ++after_close_flush==1)return FALSE;
    if(mode==67 && macro_returned && !phase && !io_stage && !postqueue_flush_failed++)return FALSE;
    if(mode==68 && io_stage==1)return FALSE;
    return FlushFileBuffers(file);
}
static ProError ProCmdActionAdd(char *name,uiCmdCmdActFn fn,int priority,
 uiCmdAccessFn access,int nonactive,int accessory,uiCmdCmdId *id) {
    if(strcmp(name,"CreoCliModelCurrentCloseDeferred") || priority!=2
       || nonactive || accessory)return -2;
    callback=fn;*id=mode==30?NULL:command_id;return mode==30?-7:0;
}
static ProError ProMacroLoad(wchar_t *macro) {
    sdk();++macro_calls;
    if(wcscmp(macro,L"~ Command `CreoCliModelCurrentCloseDeferred`;"))return -2;
    if(mode==14)callback(command_id,NULL,NULL);
    macro_returned=1;
    return mode==15?-7:0;
}
static ProError ProArrayAlloc(int n,int size,int grow,ProArray *out) {
    sdk();*out=calloc(1,(size_t)size);return *out?0:-1;
}
static ProError ProArraySizeGet(ProArray input,int *count) { *count=inputs_count;return 0; }
static ProError ProArrayFree(ProArray *input) {
    sdk();free(*input);*input=NULL;--allocated;return 0;
}
static ProError arg_value(ProArgument *inputs,const wchar_t *label,ProValueData *out) {
    int i;for(i=0;i<inputs_count;i++)
        if(!wcscmp(inputs[i].label,label)){*out=inputs[i].value;return 0;}
    return -4;
}
static ProError arg_int(ProArgument *inputs,const wchar_t *label,int *out) {
    ProValueData v;if(arg_value(inputs,label,&v)||v.type!=1)return -2;*out=v.v.i;return 0;
}
static ProError ProMdlCurrentGet(ProMdl *out) {
    sdk();*out=mode==72?NULL:(mode==8&&phase==1?(ProMdl)0x4444:original);
    return mode==10||(mode==44&&phase==1)?-7:0;
}
static ProError ProMdlMdlnameGet(ProMdl mdl,ProMdlName name) {
    const wchar_t *actual=L"midframe";
    sdk();
    if(mode==1||(mode==45&&phase==1))actual=L"other";
    if(mode==56)actual=L"MIDFRAME";
    if(mode==57)actual=L"MidFrame";
    if(mode==58)actual=L"midframe.prt";
    if(mode==59)actual=L"midframe.prt.12";
    if(mode==60)actual=L"midframe<generic>";
    if(mode==61)actual=L"midframe ";
    if(mode==62)actual=L"midframe\"\\\n";
    if(mode==63)actual=L"m\x0131 dframe";
    wcscpy(name,actual);
    if(mode==64){wmemset(name,L'A',180);}
    return 0;
}
static ProError ProMdlTypeGet(ProMdl mdl,ProMdlType *type) {
    sdk();*type=mode==2||(mode==46&&phase==1)?PRO_MDL_ASSEMBLY:PRO_MDL_PART;return 0;
}
static ProError ProMdlWindowGet(ProMdl mdl,int *window) {
    sdk();*window=mode==73?1008:1003;return 0;
}
static ProError ProWindowCurrentGet(int *window) {
    sdk();*window=mode==3||(mode==40&&phase==1)?1001:1003;return 0;
}
static ProError ProWindowMdlGet(int window,ProMdl *out) {
    sdk();*out=window==1003?original:(mode==5||(mode==42&&phase==1)?original:NULL);
    if(mode==74 && window==1003)*out=(ProMdl)0x4444;
    if(mode==80 && window==1001){*out=(ProMdl)0xdead;return -7;}
    return mode==9&&window==1001?-4:0;
}
static ProError ProMdlModificationVerify(ProMdl mdl,ProBoolean *modified) {
    sdk();*modified=mode==39||(mode==6&&phase==1);return 0;
}
static ProError ProMdlVerstampGet(ProMdl mdl,ProWVerstamp *stamp) {
    if(mode==81){sdk();*stamp=NULL;return 0;}
    sdk();*stamp=_strdup(mode==7&&phase==1?"changed-stamp":"saved-stamp");++allocated;return 0;
}
static ProError ProVerstampStringGet(ProWVerstamp stamp,char **text) {
    if(mode==82){sdk();*text=NULL;return 0;}
    sdk();*text=_strdup(stamp);++allocated;return mode==28?-7:0;
}
static ProError ProVerstampStringFree(char **text) {
    sdk();free(*text);*text=NULL;--allocated;return 0;
}
static ProError ProVerstampFree(ProWVerstamp *stamp) {
    sdk();free(*stamp);*stamp=NULL;--allocated;return 0;
}
static ProError ProSessionMdlList(ProMdlType type,ProMdl **out,int *count) {
    sdk();*out=NULL;*count=0;
    if(mode==29 && type==PRO_MDL_REPORT)return -7;
    if(type==PRO_MDL_PART || ((mode==16||(mode==43&&phase==1)) && type==PRO_MDL_2DSECTION)) {
        if(mode==75){*count=0;return -4;}
        *out=(ProMdl *)malloc(sizeof(ProMdl));++allocated;
        (*out)[0]=mode==76?(ProMdl)0x4444:original;*count=1;return 0;
    }
    return -4;
}
static ProError ProWindowsVisit(ProError (*visit)(int,ProAppData),ProAppData data) {
    sdk();visit(1003,data);if(mode!=77)visit(1001,data);
    if(mode==4||(mode==41&&phase==1))visit(1007,data);return 0;
}
static ProError ProWindowCurrentClose(void) {
    if(phase!=1)++wrong_context;++close_calls;return mode==17?-7:0;
}
#define GetTickCount64 test_tick
#define FlushFileBuffers test_flush
static HANDLE test_create(LPCWSTR path,DWORD access,DWORD share,LPSECURITY_ATTRIBUTES security,
                         DWORD disposition,DWORD flags,HANDLE template_file) {
    io_stage=wcsstr(path,L".dispatch.json")!=NULL;
    if(mode==69 && io_stage){SetLastError(ERROR_DISK_FULL);return INVALID_HANDLE_VALUE;}
    return CreateFileW(path,access,share,security,disposition,flags,template_file);
}
#define CreateFileW test_create
/*SHARED_READ_HELPERS*/
/*REAL_CLOSE_SECTION*/
static void text(ProArgument *a,const wchar_t *name,wchar_t *value) {
    wcscpy(a->label,name);a->value.type=PRO_VALUE_TYPE_WSTRING;a->value.v.w=value;
}
static void number(ProArgument *a,const wchar_t *name,int value) {
    wcscpy(a->label,name);a->value.type=1;a->value.v.i=value;
}
int wmain(int argc,wchar_t **argv) {
    ProArgument a[11],*out=NULL;
    wchar_t path[32768];FILE *cancel;
    int first,replay=999,before_callback,queued_close;
    if(argc<3)return 2;mode=_wtoi(argv[2]);
    wcscpy(test_runtime,argv[1]);
    _wputenv_s(L"CREO_CLI_CONFIG_DIR",argv[1]);
    model_close_registration_status=model_close_register();
    model_close_registration_reported=model_close_registration_witness(argv[1]);
    memset(a,0,sizeof a);
    number(&a[0],L"target_window",1003);number(&a[1],L"empty_window",1001);
    text(&a[2],L"model",L"midframe");
    text(&a[3],L"close_ticket_id",L"0123456789abcdef0123456789abcdef");
    text(&a[4],L"service_instance_id",L"01234567-89ab-cdef-0123-456789abcdef");
    text(&a[5],L"request_sha256",L"0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef");
    number(&a[6],L"ttl_ms",1000);text(&a[7],L"runtime_directory",argv[1]);
    text(&a[8],L"callback_proof",L"feedfeedfeedfeedfeedfeedfeedfeedfeedfeedfeedfeedfeedfeedfeedfeed");
    text(&a[9],L"dispatch_refusal_proof",L"cafecafecafecafecafecafecafecafecafecafecafecafecafecafecafecafe");
    if(mode==31)a[3].value.v.w=L"../bad";
    if(mode==32)wcscpy(a[6].label,L"target_window");
    if(mode==33)a[6].value.v.i=30001;
    if(mode==34)a[2].value.v.w=L"midframe.prt";
    if(mode==35){inputs_count=11;number(&a[10],L"unknown",1);}
    if(mode==36)a[1].value.v.i=1003;
    if(mode==50)inputs_count=8;
    if(mode==51)a[8].value.v.w=L"bad-proof";
    if(mode==65)inputs_count=9;
    if(mode==66)a[9].value.v.w=L"bad-refusal-proof";
    if(mode==70)a[9].value.v.w=a[8].value.v.w;
    if(mode==71)a[2].value.v.w=L"MIDFRAME";
    first=creo_cli_model_current_close(a,&out);free(out);out=NULL;
    queued_close=close_calls;before_callback=sdk_calls;
    if(first==0&&mode!=20) {
        phase=1;
        if(mode==21)tick+=2000;
        if(mode==22){_snwprintf(path,32767,L"%ls\\model-close-0123456789abcdef0123456789abcdef.cancelled.json",argv[1]);cancel=_wfopen(path,L"w");if(cancel){fputs("{}",cancel);fclose(cancel);}}
        if(mode==11)_wputenv_s(L"CREO_CLI_CONFIG_DIR",L"C:\\foreign-runtime");
        if(mode==37)++model_close_pending.pid;
        if(mode==38)++model_close_pending.birth;
        callback(mode==25?(uiCmdCmdId)0x9999:command_id,NULL,NULL);
        if(mode==24)callback(command_id,NULL,NULL);
    }
    callback_sdk_calls=sdk_calls-before_callback;
    if(mode==23){phase=0;replay=creo_cli_model_current_close(a,&out);free(out);}
    printf("{\"status\":%d,\"replay_status\":%d,\"close_calls\":%d,\"queued_close_calls\":%d,"
        "\"sdk_calls\":%d,\"callback_sdk_calls\":%d,\"sdk_after_close\":%d,\"wrong_context\":%d,"
        "\"allocated\":%d,\"macro_calls\":%d}\n",first,replay,close_calls,queued_close,sdk_calls,
        callback_sdk_calls,sdk_after_close,wrong_context,allocated,macro_calls);
    return 0;
}
"""


@unittest.skipUnless(os.name == "nt", "Windows C fake Toolkit harness")
class ModelCurrentCloseNativeC(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="model-close-c-")
        cls.root = Path(cls.temp.name)
        source = SOURCE.read_text(encoding="utf-8")
        helpers = source.split("static int owned_exit_wstring", 1)[1].split(
            "static int owned_exit_witness", 1
        )[0]
        section = source.split(
            "/* ------------------------------------------------ fixed current model close */", 1
        )[1].split(
            "/* -------------------------------------------------- current close section end */", 1
        )[0]
        code = cls.root / "harness.c"
        code.write_text(
            HARNESS.replace(
                "/*SHARED_READ_HELPERS*/", "static int owned_exit_wstring" + helpers
            ).replace("/*REAL_CLOSE_SECTION*/", section),
            encoding="utf-8",
        )
        cls.binary = cls.root / "harness.exe"
        batch = cls.root / "compile.bat"
        batch.write_text(
            f'@echo off\r\ncall "{build_native_sketch.vcvars()}" >nul || exit /b 1\r\n'
            f'cl /nologo /W3 /utf-8 /std:c11 /Fe"{cls.binary}" "{code}" '
            f'>"{cls.root / "compile.log"}" 2>&1\r\n',
            encoding="ascii",
        )
        result = subprocess.run(
            ["cmd.exe", "/c", str(batch)], capture_output=True, timeout=60, cwd=cls.root
        )
        if result.returncode:
            raise AssertionError((cls.root / "compile.log").read_text(errors="replace"))

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def run_case(self, mode):
        folder = self.root / f"case-{mode}-{self.id().rsplit('.', 1)[-1]}"
        folder.mkdir()
        result = subprocess.run(
            [str(self.binary), str(folder), str(mode)],
            capture_output=True,
            check=True,
            timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        marker = folder / f"model-close-{TICKET}.callback-return.json"
        journal = folder / f"model-close-{TICKET}.native.jsonl"
        return (
            json.loads(result.stdout),
            json.loads(marker.read_text()) if marker.exists() else None,
            [json.loads(line) for line in journal.read_text().splitlines()]
            if journal.exists()
            else [],
            folder,
        )

    def test_exact_part_is_queued_then_closes_once_with_durable_call_boundaries(self):
        data, marker, journal, folder = self.run_case(0)
        self.assertEqual(data["status"], 0)
        self.assertEqual(data["queued_close_calls"], 0)
        self.assertEqual(data["close_calls"], 1)
        self.assertEqual(data["sdk_after_close"], 0)
        self.assertEqual(data["wrong_context"], 0)
        self.assertEqual(data["allocated"], 0)
        self.assertTrue(marker["api_called"])
        self.assertTrue(marker["normal_callback_return_ready"])
        self.assertEqual(marker["status"], 0)
        self.assertEqual(marker["callback_proof"], "feed" * 16)
        self.assertTrue(all("callback_proof" not in line for line in journal))
        self.assertNotIn("feed" * 16, json.dumps(journal))
        for line in journal:
            self.assertEqual(line["close_ticket_id"], TICKET)
            self.assertEqual(line["target_window"], 1003)
            self.assertEqual(line["model"], "midframe")
            self.assertEqual(line["native_pid"], marker["native_pid"])
        calls = [(line["event"], line["api"]) for line in journal]
        self.assertIn(("begin", "ProMacroLoad(fixed model close)"), calls)
        self.assertIn(("end", "ProMacroLoad(fixed model close)"), calls)
        self.assertLess(
            calls.index(("begin", "ProWindowCurrentClose")),
            calls.index(("end", "ProWindowCurrentClose")),
        )
        self.assertEqual(calls[-1][0], "normal-callback-return-ready")
        registration = json.loads((folder / "native-model-close-dispatch.json").read_text())
        self.assertEqual(registration["dispatch_contract"], "model_current_close_v2")
        self.assertEqual(registration["input_argument_count"], 10)
        self.assertEqual(registration["priority"], "uiProeImmediate")
        dispatch = self.dispatch(folder)
        self.assertEqual(dispatch["state"], "queue_acknowledged")
        self.assertEqual(dispatch["status"], 0)
        self.assertTrue(dispatch["queue_api_entered"])
        self.assertTrue(dispatch["queue_acknowledged"])
        self.assertNotIn("callback_proof", dispatch)
        self.assertNotIn("dispatch_refusal_proof", dispatch)

    def dispatch(self, folder):
        path = folder / f"model-close-{TICKET}.dispatch.json"
        return json.loads(path.read_text()) if path.exists() else None

    def test_real_sdk_headers_confirm_fake_argument_layout_and_enum(self):
        sdk = Path("D:/PTC/Creo13.4/Creo 13.4.1.0/Common Files/protoolkit/includes")
        if not (sdk / "ProToolkitDll.h").is_file():
            self.skipTest("installed SDK headers unavailable")
        code = self.root / "sdk-layout.c"
        code.write_text(
            "#include <stddef.h>\n#include <ProToolkitDll.h>\n#include <ProMdl.h>\n"
            '_Static_assert(sizeof(ProArgument)==80,"argument size");\n'
            '_Static_assert(offsetof(ProArgument,value)==64,"value offset");\n'
            '_Static_assert(sizeof(((ProArgument*)0)->label)==64,"label size");\n'
            '_Static_assert(sizeof(ProValueData)==16,"value size");\n'
            '_Static_assert(offsetof(ProValueData,v)==8,"union offset");\n'
            '_Static_assert(PRO_VALUE_TYPE_WSTRING==5,"wstring tag");\n'
            '_Static_assert(PRO_VALUE_TYPE_INT==1,"integer tag");\n'
            '_Static_assert(PRO_MDL_PART==2 && PRO_MDL_ASSEMBLY==1,"solid type enums");\n'
            '_Static_assert(PRO_MDL_2DSECTION==11,"section type enum");\n',
            encoding="ascii",
        )
        batch = self.root / "sdk-layout-compile.bat"
        log = self.root / "sdk-layout-compile.log"
        batch.write_text(
            f'@echo off\r\ncall "{build_native_sketch.vcvars()}" >nul || exit /b 1\r\n'
            f"cl /nologo /c /std:c11 /DPRO_MACHINE=36 /DPRO_OS=4 /D_WSTDIO_DEFINED "
            f'/I"{sdk}" /Fo"{self.root / "sdk-layout.obj"}" "{code}" >"{log}" 2>&1\r\n',
            encoding="ascii",
        )
        result = subprocess.run(
            ["cmd.exe", "/c", str(batch)], capture_output=True, timeout=60, cwd=self.root
        )
        self.assertEqual(result.returncode, 0, log.read_text(errors="replace"))

    def test_ascii_case_only_names_pass_and_record_actual_native_name(self):
        for mode, native, expected in (
            (56, "MIDFRAME", "midframe"),
            (57, "MidFrame", "midframe"),
            (71, "midframe", "MIDFRAME"),
        ):
            with self.subTest(mode=mode):
                data, marker, journal, folder = self.run_case(mode)
                self.assertEqual(data["status"], 0)
                self.assertEqual(data["close_calls"], 1)
                self.assertTrue(marker["api_called"])
                names = [line for line in journal if line["event"] == "name-identity"]
                self.assertEqual(len(names), 2)
                self.assertTrue(all(line["native_name"] == native for line in names))
                self.assertTrue(all(line["expected_name"] == expected for line in names))
                self.assertTrue(all(line["ascii_fold_equal"] for line in names))
                self.assertTrue(all(not line["ordinal_equal"] for line in names))
                self.assertTrue(all(line["change_class"] == "ascii_case_only" for line in names))
                self.assertEqual(self.dispatch(folder)["state"], "queue_acknowledged")

    def test_native_suffix_version_instance_whitespace_and_non_ascii_never_normalize(self):
        for mode in (1, 58, 59, 60, 61, 62, 63, 64):
            with self.subTest(mode=mode):
                data, marker, journal, folder = self.run_case(mode)
                self.assertNotEqual(data["status"], 0)
                self.assertEqual(data["macro_calls"], 0)
                self.assertEqual(data["close_calls"], 0)
                self.assertIsNone(marker)
                name = next(line for line in journal if line["event"] == "name-identity")
                self.assertFalse(name["ascii_fold_equal"])
                if mode == 62:
                    self.assertEqual(name["native_name"], 'midframe"\\\n')
                if mode == 64:
                    self.assertEqual(name["native_length"], 180)
                    self.assertFalse(name["native_terminated"])
                dispatch = self.dispatch(folder)
                self.assertEqual(dispatch["state"], "refused_before_queue")
                self.assertEqual(dispatch["reason"], "target_name_mismatch")
                self.assertEqual(dispatch["status"], data["status"])
                self.assertEqual(dispatch["dispatch_refusal_proof"], "cafe" * 16)
                self.assertNotIn("callback_proof", dispatch)
                self.assertFalse(dispatch["queue_api_entered"])
                self.assertFalse(dispatch["queue_acknowledged"])
                self.assertNotIn("feed" * 16, json.dumps(journal))
                self.assertNotIn("cafe" * 16, json.dumps(journal))

    def test_dispatch_unknown_after_macro_entry_never_discloses_either_proof(self):
        for mode in (14, 15, 67):
            with self.subTest(mode=mode):
                data, _, journal, folder = self.run_case(mode)
                self.assertNotEqual(data["status"], 0)
                self.assertEqual(data["close_calls"], 0)
                dispatch = self.dispatch(folder)
                self.assertEqual(dispatch["state"], "queue_outcome_unknown")
                self.assertTrue(dispatch["queue_api_entered"])
                self.assertEqual(dispatch["queue_acknowledged"], mode != 15)
                self.assertNotIn("callback_proof", dispatch)
                self.assertNotIn("dispatch_refusal_proof", dispatch)
                self.assertNotIn("feed" * 16, json.dumps(dispatch) + json.dumps(journal))
                self.assertNotIn("cafe" * 16, json.dumps(dispatch) + json.dumps(journal))

    def test_dispatch_write_or_flush_failure_leaves_no_ack_file_and_no_close(self):
        for mode in (68, 69):
            with self.subTest(mode=mode):
                data, marker, _, folder = self.run_case(mode)
                self.assertNotEqual(data["status"], 0)
                self.assertIsNone(self.dispatch(folder))
                self.assertIsNone(marker)
                self.assertEqual(data["close_calls"], 0)

    def test_refused_guards_record_safe_expected_actual_and_category(self):
        cases = (
            (72, "current_model_present", True, False),
            (8, "current_model_handle_match", True, False),
            (2, "target_type", 2, 1),
            (73, "model_window", 1003, 1008),
            (3, "current_window", 1003, 1001),
            (74, "target_window_owner_match", True, False),
            (39, "target_modified", False, True),
            (7, "stamp_match", True, False),
            (16, "inventory_count", 0, 1),
            (75, "inventory_count", 1, 0),
            (76, "inventory_target_handle_match", True, False),
            (4, "window_count", 2, 3),
            (77, "window_count", 2, 1),
            (5, "empty_window_owner_present", False, True),
            (80, "api_status", 0, -7),
            (10, "api_status", 0, -7),
            (29, "inventory_api_status", 0, -7),
            (81, "stamp_allocated", True, False),
            (82, "stamp_text_allocated", True, False),
            (11, "runtime_environment_match", True, False),
            (21, "deadline_live", True, False),
            (22, "cancel_file_absent", True, False),
            (37, "native_pid_match", True, False),
            (38, "native_birth_match", True, False),
            (14, "outside_export_transport", True, False),
            (15, "queue_api_status", 0, -7),
        )
        for mode, category, expected, actual in cases:
            with self.subTest(mode=mode):
                data, _, journal, _ = self.run_case(mode)
                guard = next(line for line in journal if line.get("category") == category)
                self.assertEqual(guard["expected"], expected)
                self.assertEqual(guard["actual"], actual)
                self.assertEqual(data["close_calls"], 0)
                self.assertNotIn("0x4444", json.dumps(journal))
                self.assertNotIn("0xdead", json.dumps(journal))
                self.assertNotIn("feed" * 16, json.dumps(journal))
                self.assertNotIn("cafe" * 16, json.dumps(journal))
                if mode == 4:
                    self.assertEqual(guard["actual_window_ids"], [1003, 1001, 1007])
                if mode == 16:
                    self.assertEqual(guard["model_type"], 11)
                if mode == 80:
                    self.assertFalse(
                        any(
                            line.get("category") == "empty_window_owner_present" for line in journal
                        )
                    )

    def test_export_refuses_wrong_name_type_current_window_empty_owner_extra_window(self):
        for mode in (1, 2, 3, 4, 5, 9, 16, 29, 39):
            with self.subTest(mode=mode):
                data, marker, _, _ = self.run_case(mode)
                self.assertNotEqual(data["status"], 0)
                self.assertEqual(data["macro_calls"], 0)
                self.assertEqual(data["close_calls"], 0)
                self.assertEqual(data["allocated"], 0)
                self.assertIsNone(marker)

    def test_callback_rechecks_dirty_stamp_and_fresh_opaque_identity(self):
        for mode in (6, 7, 8, 40, 41, 42, 43, 44, 45, 46):
            with self.subTest(mode=mode):
                data, marker, _, _ = self.run_case(mode)
                self.assertEqual(data["status"], 0)
                self.assertEqual(data["close_calls"], 0)
                self.assertFalse(marker["api_called"])
                self.assertNotEqual(marker["status"], 0)
                self.assertEqual(data["allocated"], 0)

    def test_first_api_failure_stops_validation(self):
        data, _, journal, _ = self.run_case(10)
        self.assertEqual(data["sdk_calls"], 1)
        self.assertEqual(data["close_calls"], 0)
        self.assertEqual(
            [line["api"] for line in journal if line["event"] == "begin"], ["ProMdlCurrentGet"]
        )

    def test_expiry_or_cancel_during_begin_flush_blocks_first_export_and_callback_sdk(self):
        for mode in (52, 53, 54, 55):
            with self.subTest(mode=mode):
                data, marker, _, _ = self.run_case(mode)
                self.assertEqual(data["close_calls"], 0)
                self.assertEqual(data["allocated"], 0)
                if mode in (52, 54):
                    self.assertEqual(data["sdk_calls"], 0)
                    self.assertIsNone(marker)
                else:
                    self.assertEqual(data["callback_sdk_calls"], 0)
                    self.assertFalse(marker["api_called"])

    def test_cancel_deadline_and_foreign_runtime_run_no_callback_sdk(self):
        for mode in (11, 21, 22, 37, 38):
            with self.subTest(mode=mode):
                data, marker, _, _ = self.run_case(mode)
                self.assertEqual(data["callback_sdk_calls"], 0)
                self.assertEqual(data["close_calls"], 0)
                self.assertFalse(marker["api_called"])

    def test_close_log_and_return_ready_flush_failure_never_claim_success(self):
        for mode in (47, 48):
            with self.subTest(mode=mode):
                data, marker, _, _ = self.run_case(mode)
                self.assertEqual(data["close_calls"], 1)
                self.assertNotEqual(marker["status"], 0)
                self.assertEqual(data["sdk_after_close"], 0)

    def test_inline_command_is_refused_and_never_closes(self):
        data, marker, _, _ = self.run_case(14)
        self.assertNotEqual(data["status"], 0)
        self.assertEqual(data["close_calls"], 0)
        self.assertFalse(marker["api_called"])

    def test_missing_or_wrong_callback_has_no_completion_marker(self):
        for mode in (20, 25):
            with self.subTest(mode=mode):
                data, marker, _, _ = self.run_case(mode)
                self.assertEqual(data["status"], 0)
                self.assertEqual(data["close_calls"], 0)
                self.assertIsNone(marker)

    def test_io_flush_failure_blocks_export_or_callback(self):
        for mode in (12, 13):
            with self.subTest(mode=mode):
                data, _, _, _ = self.run_case(mode)
                self.assertEqual(data["close_calls"], 0)
                if mode == 12:
                    self.assertEqual(data["sdk_calls"], 0)
                else:
                    self.assertEqual(data["callback_sdk_calls"], 0)

    def test_queue_and_close_errors_are_not_success(self):
        data, marker, _, _ = self.run_case(15)
        self.assertNotEqual(data["status"], 0)
        self.assertIsNone(marker)
        data, marker, _, _ = self.run_case(17)
        self.assertEqual(data["close_calls"], 1)
        self.assertEqual(marker["status"], -7)
        self.assertEqual(data["sdk_after_close"], 0)

    def test_ticket_replay_and_duplicate_callback_cannot_repeat_close(self):
        data, _, _, _ = self.run_case(23)
        self.assertNotEqual(data["replay_status"], 0)
        self.assertEqual(data["close_calls"], 1)
        data, _, _, _ = self.run_case(24)
        self.assertEqual(data["close_calls"], 1)
        self.assertEqual(data["sdk_after_close"], 0)

    def test_allocated_stamp_is_cleaned_on_first_failure(self):
        data, _, _, _ = self.run_case(28)
        self.assertEqual(data["allocated"], 0)
        self.assertEqual(data["close_calls"], 0)

    def test_registration_and_exact_ten_field_contract_fail_closed(self):
        for mode in (30, 31, 32, 33, 34, 35, 36, 50, 51, 65, 66, 70):
            with self.subTest(mode=mode):
                data, marker, _, _ = self.run_case(mode)
                self.assertNotEqual(data["status"], 0)
                self.assertEqual(data["close_calls"], 0)
                self.assertEqual(data["macro_calls"], 0)
                self.assertIsNone(marker)
