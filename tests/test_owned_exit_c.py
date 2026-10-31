"""Compile the real fixed C exit section with fake Toolkit calls, never Creo."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from creo_cli import owned_exit
from scripts import build_native_sketch

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "service/native/creo_cli_sketch.c"
HARNESS = r"""
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <wchar.h>
typedef int ProError;
typedef int ProMdlType;
typedef void *ProMdl;
typedef void *ProArray;
typedef struct { int type; union { int i; wchar_t *w; } v; } ProValueData;
typedef struct { wchar_t label[80]; ProValueData value; } ProArgument;
typedef void *uiCmdCmdId;
typedef int uiCmdValue;
typedef int uiCmdAccessMode;
typedef int uiCmdAccessState;
typedef int (*uiCmdCmdActFn)(uiCmdCmdId,uiCmdValue*,void*);
typedef int (*uiCmdAccessFn)(uiCmdAccessMode);
#define uiProeImmediate 2
#define PRO_B_TRUE 1
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
#define PRO_VALUE_TYPE_WSTRING 2
enum {PRO_MDL_PART,PRO_MDL_ASSEMBLY,PRO_MDL_DRAWING,PRO_MDL_3DSECTION,
 PRO_MDL_2DSECTION,PRO_MDL_LAYOUT,PRO_MDL_DWGFORM,PRO_MDL_MFG,
 PRO_MDL_REPORT,PRO_MDL_MARKUP,PRO_MDL_DIAGRAM};
static int inputs_count=8, end_calls=0, list_calls=0, fail_type=-1, nonempty_type=-1;
static int toolkit_after_end=0;
static int end_status=0, expire_in_list=0, flush_fail=0, expire_in_flush=0;
static int returned_create_fail=0, all_after_end_io_fail=0;
static int registration_status=0, macro_status=0, macro_calls=0, inline_command=0;
static int callback_context=0, wrong_end_context=0;
static uiCmdCmdActFn registered_callback;
static uiCmdCmdId registered_id=(uiCmdCmdId)0x1234;
static ProError ProCmdActionAdd(char *name,uiCmdCmdActFn callback,int priority,
                               uiCmdAccessFn access,int nonactive,int accessory,uiCmdCmdId *id) {
    if(strcmp(name,"CreoCliOwnedExitDeferred")||priority!=uiProeImmediate
       ||!nonactive||!accessory)return -2;
    registered_callback=callback;*id=registration_status?NULL:registered_id;
    return registration_status;
}
static ProError ProMacroLoad(wchar_t *macro) {
    if(wcscmp(macro,L"~ Command `CreoCliOwnedExitDeferred`;"))return -2;
    ++macro_calls;
    if(inline_command)registered_callback(registered_id,NULL,NULL);
    return macro_status;
}
static ULONGLONG tick=10000;
static ULONGLONG test_tick(void) { return tick; }
static BOOL test_flush(HANDLE file) {
    if (flush_fail) return FALSE;
    if (expire_in_flush) tick+=2000;
    return FlushFileBuffers(file);
}
static ProError ProArrayAlloc(int n,int size,int grow,ProArray *out) {
    if(end_calls)++toolkit_after_end;
    *out=calloc(16,(size_t)size);return *out?0:-1;
}
static ProError ProArraySizeGet(ProArray input,int *count) {
    if(end_calls)++toolkit_after_end;*count=inputs_count;return 0;
}
static ProError ProArrayFree(ProArray *input) {
    if(end_calls)++toolkit_after_end;free(*input);*input=NULL;return 0;
}
static ProError arg_value(ProArgument *inputs,const wchar_t *label,ProValueData *out) {
    int i;
    for(i=0;i<inputs_count;i++)
        if(!wcscmp(inputs[i].label,label)){*out=inputs[i].value;return 0;}
    return -4;
}
static ProError arg_int(ProArgument *inputs,const wchar_t *label,int *out) {
    ProValueData v;
    if(arg_value(inputs,label,&v)||v.type!=PRO_VALUE_TYPE_INT)return -2;
    *out=v.v.i;return 0;
}
static void put_text(ProArgument **out,const wchar_t *label,const wchar_t *text) {
    if(end_calls)++toolkit_after_end;
}
static void put_int(ProArgument **out,const wchar_t *label,int value) {
    if(end_calls)++toolkit_after_end;
}
static ProError ProSessionMdlList(ProMdlType type,ProMdl **out,int *count) {
    ++list_calls;*count=(type==nonempty_type)?1:0;*out=NULL;
    if(expire_in_list)tick+=2000;
    return type==fail_type?-2:(*count==0?-4:0);
}
static ProError ProEngineerEnd(void) {
    if(!callback_context)++wrong_end_context;
    ++end_calls;return end_status;
}
static HANDLE test_create(LPCWSTR name,DWORD access,DWORD share,LPSECURITY_ATTRIBUTES security,
                         DWORD creation,DWORD flags,HANDLE template_file) {
    if(end_calls&&(all_after_end_io_fail
       ||(returned_create_fail&&wcsstr(name,L".returned.json")))) {
        SetLastError(ERROR_DISK_FULL);return INVALID_HANDLE_VALUE;
    }
    return CreateFileW(name,access,share,security,creation,flags,template_file);
}
#define GetTickCount64 test_tick
#define FlushFileBuffers test_flush
#define CreateFileW test_create
/*REAL_EXIT_SECTION*/
static void text(ProArgument *a,const wchar_t *name,wchar_t *value) {
    wcscpy(a->label,name);a->value.type=2;a->value.v.w=value;
}
static void number(ProArgument *a,const wchar_t *name,int value) {
    wcscpy(a->label,name);a->value.type=1;a->value.v.i=value;
}
int wmain(int argc,wchar_t **argv) {
    ProArgument a[9],*out=NULL;
    FILETIME c,e,k,u;ULARGE_INTEGER born;
    wchar_t creation[32],deadline[32],operation[40]=L"0123456789abcdef0123456789abcdef";
    wchar_t instance[40]=L"01234567-89ab-cdef-0123-456789abcdef",other[32768];
    int mode=argc>2?_wtoi(argv[2]):0,first,result,queued_end,queued_lists;
    if(argc<2)return 2;
    _wputenv_s(L"CREO_CLI_CONFIG_DIR",argv[1]);
    GetProcessTimes(GetCurrentProcess(),&c,&e,&k,&u);
    born.LowPart=c.dwLowDateTime;born.HighPart=c.dwHighDateTime;
    _snwprintf(creation,31,L"%llu",born.QuadPart);
    _snwprintf(deadline,31,L"%llu",tick+1000);
    memset(a,0,sizeof a);
    number(&a[0],L"expected_pid",(int)GetCurrentProcessId());
    text(&a[1],L"expected_creation_filetime",creation);
    text(&a[2],L"operation_id",operation);
    text(&a[3],L"service_instance_id",instance);
    text(&a[4],L"runtime_directory",argv[1]);
    text(&a[5],L"deadline_tick_ms",deadline);
    number(&a[6],L"raw_java_model_count",0);
    text(&a[7],L"dispatch_contract",L"queued_native_command_v1");
    if(mode==20)registration_status=-7;
    owned_exit_registration_status=owned_exit_register();
    owned_exit_registration_reported=owned_exit_registration_witness(argv[1]);
    switch(mode) {
      case 1:++a[0].value.v.i;break;
      case 2:wcscpy(creation,L"1");break;
      case 3:wcscpy(operation,L"../bad");break;
      case 4:instance[0]=L'A';break;
      case 5:wcscpy(deadline,L"10000");break;
      case 6:wcscpy(deadline,L"50001");break;
      case 7:a[6].value.v.i=1;break;
      case 8:nonempty_type=PRO_MDL_2DSECTION;break;
      case 9:fail_type=PRO_MDL_REPORT;break;
      case 10:expire_in_list=1;break;
      case 11:flush_fail=1;break;
      case 12:end_status=-7;break;
      case 13:wcscpy(other,argv[1]);wcscat(other,L"-other");a[4].value.v.w=other;break;
      case 14:wcscpy(a[6].label,L"expected_pid");break;
      case 15:inputs_count=9;number(&a[8],L"unknown",0);break;
      case 16:wcscpy(deadline,L"18446744073709551616");break;
      case 18:expire_in_flush=1;break;
      case 19:end_status=-7;returned_create_fail=1;break;
      case 21:macro_status=-7;break;
      case 22:inline_command=1;break;
      case 29:inputs_count=7;break;
      case 30:a[7].value.v.w=L"inline_legacy";break;
      case 32:end_status=-7;all_after_end_io_fail=1;break;
    }
    first=creo_cli_session_exit(a,&out);free(out);out=NULL;result=first;
    queued_end=end_calls;queued_lists=list_calls;
    if(first==0&&mode!=24) {
        if(mode==25)++owned_exit_pending.pid;
        if(mode==26)++owned_exit_pending.birth;
        if(mode==27)_wputenv_s(L"CREO_CLI_CONFIG_DIR",L"C:\\foreign-runtime");
        if(mode==28)tick+=2000;
        if(mode==31){wcscpy(operation,L"bad-original-pointer");instance[0]=L'X';}
        callback_context=1;
        registered_callback(mode==23?(uiCmdCmdId)0x9999:registered_id,NULL,NULL);
        callback_context=0;
    }
    if(mode==17){result=creo_cli_session_exit(a,&out);free(out);}
    printf("{\"status\":%d,\"first_status\":%d,\"end_calls\":%d,\"list_calls\":%d,\"toolkit_after_end\":%d,\"queue_end_calls\":%d,\"queue_list_calls\":%d,\"macro_calls\":%d,\"wrong_end_context\":%d}\n",result,first,end_calls,list_calls,toolkit_after_end,queued_end,queued_lists,macro_calls,wrong_end_context);
    return 0;
}
"""


@unittest.skipUnless(os.name == "nt", "Windows-only C ownership and witness harness")
class OwnedExitNativeC(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="owned-exit-c-")
        cls.root = Path(cls.temp.name)
        section = (
            SOURCE.read_text(encoding="utf-8")
            .split(
                "/* --------------------------------------------------------- owned empty exit */",
                1,
            )[1]
            .split(
                "/* ----------------------------------------------------------- DLL lifecycle */", 1
            )[0]
        )
        code = cls.root / "harness.c"
        code.write_text(HARNESS.replace("/*REAL_EXIT_SECTION*/", section), encoding="utf-8")
        cls.binary = cls.root / "harness.exe"
        batch = cls.root / "compile.bat"
        batch.write_text(
            f'@echo off\r\ncall "{build_native_sketch.vcvars()}" >nul || exit /b 1\r\n'
            f'cl /nologo /W3 /utf-8 /Fe"{cls.binary}" "{code}" '
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

    def run_case(
        self, mode, *, existing_entered=False, existing_returned=False, unicode_path=False
    ):
        prefix = "原生 witness " if unicode_path else "case-"
        folder = self.root / f"{prefix}{mode}-{self.id().rsplit('.', 1)[-1]}"
        folder.mkdir()
        if existing_entered:
            (folder / "owned-exit-0123456789abcdef0123456789abcdef.entered.json").write_text("old")
        if existing_returned:
            (folder / "owned-exit-0123456789abcdef0123456789abcdef.returned.json").write_text("old")
        result = subprocess.run(
            [str(self.binary), str(folder), str(mode)],
            capture_output=True,
            check=True,
            timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return json.loads(result.stdout), folder

    def test_only_exact_empty_owner_enters_fixed_api(self):
        data, folder = self.run_case(0)
        self.assertEqual(
            data,
            {
                "status": 0,
                "first_status": 0,
                "end_calls": 1,
                "list_calls": 11,
                "toolkit_after_end": 0,
                "queue_end_calls": 0,
                "queue_list_calls": 0,
                "macro_calls": 1,
                "wrong_end_context": 0,
            },
        )
        entered = json.loads(next(folder.glob("*.entered.json")).read_text())
        returned = json.loads(next(folder.glob("*.returned.json")).read_text())
        self.assertEqual(entered["entrypoint"], "ProEngineerEnd")
        self.assertTrue(entered["raw_java_empty_checked"])
        self.assertTrue(entered["native_known_types_empty"])
        self.assertEqual(entered["dispatch_contract"], "queued_native_command_v1")
        self.assertEqual(entered["dispatch_context"], "registered_native_command")
        self.assertEqual(returned["native_return_code"], 0)
        self.assertTrue(returned["api_called"])

    def test_wrong_identity_scope_deadline_or_inputs_never_exit(self):
        for mode in [1, 2, 3, 4, 5, 6, 7, 13, 14, 15, 16, 20, 29, 30]:
            with self.subTest(mode=mode):
                data, folder = self.run_case(mode)
                self.assertNotEqual(data["status"], 0)
                self.assertEqual(data["end_calls"], 0)
                self.assertEqual(data["list_calls"], 0)
                self.assertEqual(list(folder.glob("*.entered.json")), [])

    def test_hidden_section_and_inventory_failure_refuse(self):
        for mode in [8, 9]:
            with self.subTest(mode=mode):
                data, folder = self.run_case(mode)
                self.assertEqual(data["status"], 0)  # Queue acknowledgement is not success.
                self.assertEqual(data["end_calls"], 0)
                self.assertEqual(list(folder.glob("*.entered.json")), [])
                self.assertTrue(list(folder.glob("*.failed.json")))

    def test_expired_getter_stops_before_next_getter_or_exit(self):
        data, _ = self.run_case(10)
        self.assertEqual(data["list_calls"], 1)
        self.assertEqual(data["end_calls"], 0)

    def test_witness_must_flush_and_never_overwrite(self):
        data, _ = self.run_case(11)
        self.assertEqual(data["status"], 0)
        self.assertEqual(data["end_calls"], 0)
        data, folder = self.run_case(0, existing_entered=True)
        self.assertEqual(data["status"], 0)
        self.assertEqual(data["end_calls"], 0)
        self.assertEqual(next(folder.glob("*.entered.json")).read_text(), "old")

    def test_return_failure_is_retained_without_success(self):
        data, folder = self.run_case(12)
        self.assertEqual(data["end_calls"], 1)
        self.assertEqual(data["status"], 0)
        returned = json.loads(next(folder.glob("*.returned.json")).read_text())
        self.assertEqual(returned["native_return_code"], -7)
        self.assertTrue(returned["api_called"])
        failed = json.loads(next(folder.glob("*.failed.json")).read_text())
        self.assertEqual(failed["native_return_code"], -7)
        self.assertTrue(failed["api_called"])
        self.assertTrue(failed["returned_witness_recorded"])

    def test_fixed_exit_is_single_use_for_process(self):
        data, _ = self.run_case(17)
        self.assertEqual(data["first_status"], 0)
        self.assertEqual(data["status"], -39)
        self.assertEqual(data["end_calls"], 1)
        self.assertEqual(data["list_calls"], 11)

    def test_deadline_after_durable_entered_marker_still_prevents_api(self):
        data, folder = self.run_case(18)
        self.assertEqual(data["status"], 0)
        self.assertEqual(data["end_calls"], 0)
        returned = json.loads(next(folder.glob("*.returned.json")).read_text())
        self.assertFalse(returned["api_called"])
        self.assertEqual(returned["native_return_code"], -3)

    def test_returned_witness_failure_cannot_return_success_or_overwrite(self):
        data, folder = self.run_case(0, existing_returned=True)
        self.assertEqual(data["end_calls"], 1)
        self.assertEqual(data["status"], 0)
        self.assertEqual(next(folder.glob("*.returned.json")).read_text(), "old")
        failed = json.loads(next(folder.glob("*.failed.json")).read_text())
        self.assertEqual(failed["native_return_code"], 0)
        self.assertFalse(failed["returned_witness_recorded"])

    def test_native_runtime_path_preserves_unicode_and_spaces(self):
        data, folder = self.run_case(0, unicode_path=True)
        self.assertEqual(data["status"], 0)
        self.assertTrue(next(folder.glob("*.entered.json")).is_file())

    def test_no_toolkit_output_or_getter_after_end_even_on_fail_or_replay(self):
        for mode in (0, 12, 17):
            with self.subTest(mode=mode):
                data, _ = self.run_case(mode)
                self.assertEqual(data["toolkit_after_end"], 0)

    def test_known_native_failure_and_missing_return_witness_are_not_success(self):
        data, folder = self.run_case(19)
        self.assertEqual(data["end_calls"], 1)
        self.assertEqual(data["status"], 0)
        self.assertTrue(next(folder.glob("*.entered.json")).is_file())
        self.assertEqual(list(folder.glob("*.returned.json")), [])
        self.assertEqual(data["toolkit_after_end"], 0)
        failed = json.loads(next(folder.glob("*.failed.json")).read_text())
        self.assertEqual(failed["native_return_code"], -7)
        self.assertTrue(failed["api_called"])
        self.assertFalse(failed["returned_witness_recorded"])

    def test_known_return_failure_vetoes_early_stop_even_without_returned_file(self):
        for mode in (12, 19):
            with self.subTest(mode=mode):
                data, folder = self.run_case(mode)
                self.assertEqual(data["status"], 0)  # Scheduling only.
                self.assertEqual(data["toolkit_after_end"], 0)
                raw = next(folder.glob("*.entered.json")).read_bytes()
                entered = json.loads(raw)
                failed = json.loads(next(folder.glob("*.failed.json")).read_text())
                common = {
                    key: entered[key]
                    for key in (
                        "operation_id",
                        "service_instance_id",
                        "native_pid",
                        "native_creation_filetime",
                    )
                }
                digest = hashlib.sha256(raw).hexdigest()
                # Deliberately synthetic: this does not observe a Native exit.
                observation = {
                    "operation_id": entered["operation_id"],
                    "process": {
                        "signaled": True,
                        "alive": False,
                        "exit_code": 0,
                        "pid": entered["native_pid"],
                        "creation_filetime": entered["native_creation_filetime"],
                        "image": str(self.binary),
                    },
                    "entered": {"data": entered, "file": {"sha256": digest}},
                    "returned": None,
                    "stop": {
                        "data": {
                            **common,
                            "status": "service_stop_after_owned_native_entry",
                            "entered_sha256": digest,
                        }
                    },
                    "failed": {"data": failed},
                }
                expected = {
                    "expected_pid": entered["native_pid"],
                    "expected_creation_filetime": entered["native_creation_filetime"],
                    "expected_native_image": str(self.binary),
                    "service_instance_id": entered["service_instance_id"],
                }
                self.assertFalse(owned_exit.qualified(observation, expected))
                observation["failed"] = None
                self.assertTrue(owned_exit.qualified(observation, expected))

    def test_total_post_end_io_failure_cannot_claim_a_durable_veto(self):
        data, folder = self.run_case(32)
        self.assertEqual(data["end_calls"], 1)
        self.assertEqual(data["toolkit_after_end"], 0)
        self.assertTrue(list(folder.glob("*.entered.json")))
        self.assertEqual(list(folder.glob("*.returned.json")), [])
        self.assertEqual(list(folder.glob("*.failed.json")), [])

    def test_queued_or_foreign_callback_never_executes_inline(self):
        for mode in (22, 23, 24):
            with self.subTest(mode=mode):
                data, folder = self.run_case(mode)
                self.assertEqual(data["queue_end_calls"], 0)
                self.assertEqual(data["queue_list_calls"], 0)
                self.assertEqual(data["end_calls"], 0)
                self.assertEqual(data["wrong_end_context"], 0)
                self.assertEqual(list(folder.glob("*.entered.json")), [])

    def test_native_callback_rechecks_owner_runtime_and_deadline(self):
        for mode in (25, 26, 27, 28):
            with self.subTest(mode=mode):
                data, folder = self.run_case(mode)
                self.assertEqual(data["status"], 0)
                self.assertEqual(data["end_calls"], 0)
                self.assertEqual(data["list_calls"], 0)
                self.assertEqual(list(folder.glob("*.entered.json")), [])
                self.assertTrue(
                    list(folder.glob("*.failed.json")) or list(folder.glob("*.cancelled.json"))
                )

    def test_failed_queue_does_not_enter_or_repeat(self):
        data, folder = self.run_case(21)
        self.assertEqual(data["status"], -7)
        self.assertEqual(data["end_calls"], 0)
        self.assertEqual(data["macro_calls"], 1)
        self.assertTrue(list(folder.glob("*.failed.json")))

    def test_callback_owns_copies_after_export_returns(self):
        data, folder = self.run_case(31)
        self.assertEqual(data["end_calls"], 1)
        self.assertEqual(data["wrong_end_context"], 0)
        entered = json.loads(next(folder.glob("*.entered.json")).read_text())
        self.assertEqual(entered["operation_id"], "0123456789abcdef0123456789abcdef")
        self.assertEqual(entered["service_instance_id"], "01234567-89ab-cdef-0123-456789abcdef")
