"""Exercise durable boundaries in fresh, SDK-free JVMs, including a real unreturned call."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JDK = Path(os.environ["JAVA_HOME"]) / "bin" if os.environ.get("JAVA_HOME") else None
JAVAC = str(JDK / "javac.exe") if JDK and (JDK / "javac.exe").is_file() else shutil.which("javac")
JAVA = str(JDK / "java.exe") if JDK and (JDK / "java.exe").is_file() else shutil.which("java")
FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)


@unittest.skipUnless(JAVAC and JAVA, "SDK-free durable diagnostics require an available JDK")
class NativeReadTraceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scratch = tempfile.TemporaryDirectory(prefix="creo-native-trace-controls-")
        cls.classes = Path(cls.scratch.name) / "classes"
        source = ROOT / "service/src/com/fateforge/creocli/service"
        result = subprocess.run(
            [
                JAVAC,
                "--release",
                "17",
                "-encoding",
                "UTF-8",
                "-d",
                str(cls.classes),
                str(source / "Json.java"),
                str(source / "NativeReadTrace.java"),
                str(ROOT / "tests/java/NativeReadTraceHarness.java"),
                str(ROOT / "tests/java/NativeReadTraceOwnedChannelHarness.java"),
            ],
            capture_output=True,
            timeout=30,
            creationflags=FLAGS,
        )
        if result.returncode:
            cls.scratch.cleanup()
            raise AssertionError(result.stderr.decode("utf-8", "replace"))

    @classmethod
    def tearDownClass(cls):
        cls.scratch.cleanup()

    def command(self, mode, directory):
        return [
            JAVA,
            "-cp",
            str(self.classes),
            "com.fateforge.creocli.service.NativeReadTraceHarness",
            mode,
            str(directory),
        ]

    def run_case(self, mode):
        directory = Path(self.scratch.name) / mode
        result = subprocess.run(
            self.command(mode, directory), capture_output=True, timeout=15, creationflags=FLAGS
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        return json.loads(result.stdout), directory

    def inspect(self, directory):
        result = subprocess.run(
            self.command("inspect", directory), capture_output=True, timeout=15, creationflags=FLAGS
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        return json.loads(result.stdout)

    def owned_command(self, mode, directory):
        command = self.command(mode, directory)
        command[3] = "com.fateforge.creocli.service.NativeReadTraceOwnedChannelHarness"
        return command

    def run_owned_case(self, mode):
        directory = Path(self.scratch.name) / ("owned-" + mode)
        result = subprocess.run(
            self.owned_command(mode, directory),
            capture_output=True,
            timeout=30,
            creationflags=FLAGS,
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        value = json.loads(result.stdout)
        self.assertFalse(value["injected_Sink"])
        self.assertEqual(value["actual_CAD_calls"], 0)
        return value, directory

    @unittest.skipUnless(os.name == "nt", "actual Windows default-writer sharing contract")
    def test_default_owned_writer_reuses_channel_and_forces_each_record_with_history(self):
        for mode, calls in (("normal", 4), ("history", 60)):
            with self.subTest(mode=mode):
                result, directory = self.run_owned_case(mode)
                self.assertEqual(result["calls"], calls)
                self.assertTrue(result["channel"]["open_before_JVM_exit"])
                self.assertEqual(result["channel"]["close_calls"], 0)
                rows = self.inspect(directory)["complete_records"]
                self.assertEqual(
                    len(rows) - result["channel"]["records_before_spy"],
                    result["channel"]["force_true_calls"],
                )
                self.assertGreater(
                    result["channel"]["write_calls"], result["channel"]["force_true_calls"]
                )
                if mode == "history":
                    self.assertGreater(result["history_bytes"], 20_000_000)
                    self.assertEqual(len([row for row in rows if "synthetic_history" in row]), 80)
                    self.assertEqual(len([row for row in rows if "trace_schema" in row]), 125)
                # The child JVM has exited; its sole lifetime-owned handle is released.
                before = (directory / "native-read-trace.ndjson").read_bytes()
                with (directory / "native-read-trace.ndjson").open("ab"):
                    pass
                self.assertEqual((directory / "native-read-trace.ndjson").read_bytes(), before)

    @unittest.skipUnless(os.name == "nt", "actual Windows default-writer sharing contract")
    def test_default_owned_writer_serializes_concurrent_records_and_retains_late_expiry_end(self):
        for mode, calls in (("concurrent", 24), ("expiry", 1)):
            with self.subTest(mode=mode):
                result, directory = self.run_owned_case(mode)
                self.assertEqual(result["calls"], calls)
                self.assertEqual(result["channel"]["close_calls"], 0)
                rows = self.inspect(directory)["complete_records"]
                begins = {row["sequence"] for row in rows if row["event"] == "begin"}
                ends = {row["sequence"] for row in rows if row["event"] == "end"}
                self.assertEqual(begins, ends)
                self.assertEqual(len(ends), calls)
                if mode == "expiry":
                    expiry = next(
                        i
                        for i, row in enumerate(rows)
                        if row["event"] == "request_wait_expired_while_started"
                    )
                    self.assertTrue(
                        any(i > expiry and row["event"] == "end" for i, row in enumerate(rows))
                    )
                    self.assertTrue(
                        any(
                            i > expiry and row.get("effect") == "owned_returned_effect"
                            for i, row in enumerate(rows)
                        )
                    )
                    self.assertEqual(
                        result["native_diagnostic"]["reason"],
                        "native_request_unreturned_at_wait_expiry",
                    )

    @unittest.skipUnless(os.name == "nt", "actual Windows default-writer sharing contract")
    def test_default_owned_writer_failure_poison_keeps_begin_zero_end_one_and_partial_tail(self):
        for mode in (
            "write-begin",
            "partial-begin",
            "force-begin",
            "write-end",
            "partial-end",
            "force-end",
        ):
            with self.subTest(mode=mode):
                result, directory = self.run_owned_case(mode)
                self.assertEqual(result["calls"], 1 if mode.endswith("-end") else 0)
                self.assertEqual(
                    result["native_diagnostic"]["reason"], "diagnostic_persistence_failed"
                )
                self.assertEqual(
                    result["native_diagnostic"]["last"]["status"], "diagnostic_persistence_failed"
                )
                self.assertFalse(result["channel"]["open_before_JVM_exit"])
                self.assertEqual(result["channel"]["close_calls"], 1)
                if mode.startswith("partial-"):
                    read = self.inspect(directory)
                    self.assertFalse(read["complete"])
                    self.assertGreater(read["incomplete_tail_bytes"], 0)

    @unittest.skipUnless(os.name == "nt", "actual Windows default-writer sharing contract")
    def test_default_owned_writer_non_io_failures_keep_original_class_and_poison(self):
        for prefix, expected_class in (
            ("unchecked", "java.lang.UnsupportedOperationException"),
            ("security", "java.lang.SecurityException"),
            (
                "error",
                "com.fateforge.creocli.service.NativeReadTraceOwnedChannelHarness$ControlledStorageError",
            ),
        ):
            for boundary, expected_calls in (("begin", 0), ("end", 1)):
                with self.subTest(prefix=prefix, boundary=boundary):
                    result, _ = self.run_owned_case(prefix + "-" + boundary)
                    self.assertEqual(result["calls"], expected_calls)
                    self.assertGreater(result["no_reopen_checks_passed"], 0)
                    self.assertGreater(result["next_action_block_checks_passed"], 0)
                    self.assertEqual(result["channel"]["close_calls"], 1)
                    diagnostic = result["native_diagnostic"]
                    self.assertEqual(diagnostic["reason"], "diagnostic_persistence_failed")
                    self.assertEqual(
                        (diagnostic["last"]["failure_class"], diagnostic["cause_class"]),
                        (expected_class, expected_class),
                    )

    @unittest.skipUnless(os.name == "nt", "actual Windows default-writer sharing contract")
    def test_default_owned_writer_closed_interrupted_wrong_path_and_length_drift_never_reopen(self):
        for mode in (
            "owner-finish",
            "closed-channel",
            "interrupted-channel",
            "wrong-path",
            "extra-append",
            "truncate",
        ):
            with self.subTest(mode=mode):
                result, _ = self.run_owned_case(mode)
                self.assertEqual(result["calls"], 1 if mode == "owner-finish" else 0)
                self.assertTrue(result["native_diagnostic"]["stopped"])
                self.assertEqual(
                    result["native_diagnostic"]["reason"], "diagnostic_persistence_failed"
                )
                self.assertFalse(result["channel"]["open_before_JVM_exit"])

    @unittest.skipUnless(os.name == "nt", "actual Windows default-writer sharing contract")
    def test_default_owned_writer_initialization_failures_close_and_poison(self):
        for mode in ("init-mkdir-failure", "init-open-failure", "init-log-failure"):
            with self.subTest(mode=mode):
                result, _ = self.run_owned_case(mode)
                self.assertEqual(result["calls"], 0)
                self.assertTrue(result["native_diagnostic"]["stopped"])

    def test_default_owned_writer_unsupported_provider_has_no_unprotected_fallback(self):
        result, _ = self.run_owned_case("provider-refusal")
        self.assertEqual(result["calls"], 0)
        self.assertTrue(result["native_diagnostic"]["stopped"])
        self.assertEqual(result["native_diagnostic"]["reason"], "diagnostic_persistence_failed")

    @unittest.skipUnless(os.name == "nt", "actual Windows default-writer sharing contract")
    def test_default_owned_writer_denies_other_write_delete_and_parent_path_drift(self):
        result, _ = self.run_owned_case("external-access")
        self.assertTrue(result["external_mutation_blocked"])
        self.assertEqual(result["calls"], 1)
        self.assertFalse(result["native_diagnostic"]["stopped"])
        renamed, _ = self.run_owned_case("parent-rename")
        self.assertEqual(renamed["calls"], 1 if renamed["parent_rename_blocked"] else 0)

    @unittest.skipUnless(os.name == "nt", "actual Windows parent reparse provenance contract")
    def test_default_owned_writer_refuses_parent_junction_before_any_action(self):
        target = Path(self.scratch.name) / "junction-target"
        link = Path(self.scratch.name) / "junction-state"
        target.mkdir()
        result = subprocess.run(
            ["cmd.exe", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            timeout=10,
            creationflags=FLAGS,
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        child = subprocess.run(
            self.owned_command("reparse-parent", link),
            capture_output=True,
            timeout=15,
            creationflags=FLAGS,
        )
        self.assertEqual(child.returncode, 0, child.stderr.decode("utf-8", "replace"))
        answer = json.loads(child.stdout)
        self.assertEqual(answer["calls"], 0)
        self.assertTrue(answer["native_diagnostic"]["stopped"])
        self.assertFalse((target / "native-read-trace.ndjson").exists())

    @unittest.skipUnless(os.name == "nt", "actual Windows read-sharing and durable default BEGIN")
    def test_default_owned_writer_python_read_copy2_and_independent_reader_while_getter_blocked(
        self,
    ):
        directory = Path(self.scratch.name) / "owned-hang"
        child = subprocess.Popen(
            self.owned_command("hang", directory),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=FLAGS,
        )
        try:
            journal = directory / "native-read-trace.ndjson"
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if journal.exists() and b"OwnedGetterThatDoesNotReturn" in journal.read_bytes():
                    break
                self.assertIsNone(child.poll())
                time.sleep(0.05)
            else:
                self.fail("default writer did not force its blocked getter BEGIN")
            actual = journal.read_bytes()
            copy = directory / "actual-python-copy2.ndjson"
            shutil.copy2(journal, copy)
            self.assertEqual(copy.read_bytes(), actual)
            independent = self.inspect(directory)
            self.assertTrue(independent["complete"])
            self.assertEqual(
                independent["complete_records"][-1]["getter"], "OwnedGetterThatDoesNotReturn"
            )
            with self.assertRaises(subprocess.TimeoutExpired):
                child.communicate(timeout=0.3)
            self.assertIsNone(child.poll())
        finally:
            # Only the SDK-free child created immediately above; no CAD process.
            child.terminate()
            child.communicate(timeout=10)

    @unittest.skipUnless(
        os.name == "nt", "actual Windows durable default BEGIN after abnormal JVM exit"
    )
    def test_default_owned_writer_abnormal_exit_preserves_forced_begin(self):
        directory = Path(self.scratch.name) / "owned-halt"
        child = subprocess.run(
            self.owned_command("halt", directory),
            capture_output=True,
            timeout=15,
            creationflags=FLAGS,
        )
        self.assertEqual(child.returncode, 73)
        read = self.inspect(directory)
        self.assertTrue(read["complete"])
        self.assertEqual(read["complete_records"][-1]["event"], "begin")
        self.assertEqual(read["complete_records"][-1]["getter"], "OwnedGetterThatDoesNotReturn")

    def test_persistence_boundaries_keep_zero_or_one_call_and_cross_request_stop(self):
        for mode, expected in (
            ("persist-begin-failed", 0),
            ("persist-begin-partial", 0),
            ("persist-end-failed", 1),
            ("persist-end-partial", 1),
            ("observer-persist-failure", 0),
        ):
            with self.subTest(mode=mode):
                result, directory = self.run_case(mode)
                self.assertEqual(result["calls"], expected)
                stopped = result["native_diagnostic"]
                self.assertTrue(stopped["stopped"])
                self.assertEqual(stopped["reason"], "diagnostic_persistence_failed")
                if mode.endswith("partial"):
                    read = self.inspect(directory)
                    self.assertFalse(read["complete"])
                    self.assertGreater(read["incomplete_tail_bytes"], 0)
                    self.assertTrue(read["complete_records"])

    def test_normal_null_proxy_exception_and_effect_are_plain_and_not_pending(self):
        result, directory = self.run_case("normal")
        self.assertEqual(result["calls"], 4)
        self.assertFalse(result["native_diagnostic"]["stopped"])
        rows = self.inspect(directory)["complete_records"]
        ends = [row for row in rows if row["event"] == "end"]
        self.assertEqual(
            [row["result"] for row in ends],
            ["returned_object", "returned_null", "threw", "returned_scalar"],
        )
        self.assertEqual(
            ends[2]["exception_class"], "com.fateforge.creocli.service.NativeReadTraceHarness$2"
        )
        self.assertTrue(all(row["cli_invocation_id"] is None for row in ends))
        self.assertEqual(result["native_diagnostic"]["effects"][0]["facts"]["id"], "7")

    def test_visible_serious_split_marker_and_delayed_flush_have_accurate_return_facts(self):
        for mode, expected in (
            ("serious-returned", 1),
            ("serious-split", 1),
            ("delayed-serious", 2),
        ):
            with self.subTest(mode=mode):
                result, directory = self.run_case(mode)
                self.assertEqual(result["calls"], expected)
                self.assertEqual(
                    result["native_diagnostic"]["reason"], "native_serious_message_observed"
                )
                self.assertEqual(
                    result["native_diagnostic"]["last_call"]["result"], "returned_scalar"
                )
                records = self.inspect(directory)["complete_records"]
                matches = [
                    row
                    for row in records
                    if row["event"] == "native_log_window" and row["window"]["serious_detected"]
                ]
                self.assertEqual(len(matches), 1)
                self.assertFalse(matches[0]["window"]["native_event_time_known"])
                self.assertEqual(matches[0]["window"]["candidate_call_sequence_through"], expected)

    def test_log_identity_truncation_overwrite_deletion_and_bounded_coverage_stop_before_next_call(
        self,
    ):
        for mode in ("truncate", "replace", "rewrite", "disappear", "oversized", "partial-line"):
            with self.subTest(mode=mode):
                result, _ = self.run_case(mode)
                self.assertEqual(result["calls"], 1)
                self.assertEqual(
                    result["native_diagnostic"]["reason"], "native_log_observation_unreliable"
                )

    def test_safe_appends_are_observed_once_and_do_not_stop(self):
        result, directory = self.run_case("safe-increment")
        self.assertEqual(result["calls"], 3)
        rows = self.inspect(directory)["complete_records"]
        windows = [row["window"] for row in rows if row["event"] == "native_log_window"]
        nonempty = [row for row in windows if row["offset_end"] > row["offset_start"]]
        self.assertEqual(len(nonempty), 3)
        self.assertEqual([row["offset_start"] for row in nonempty], [0, 14, 28])

    def test_two_native_log_channels_remain_separate_without_claiming_two_events(self):
        result, directory = self.run_case("channels")
        self.assertEqual(result["calls"], 1)
        rows = self.inspect(directory)["complete_records"]
        windows = [
            row["window"]
            for row in rows
            if row["event"] == "native_log_window" and row["window"]["serious_detected"]
        ]
        self.assertEqual(len(windows), 2)
        self.assertEqual({Path(row["path"]).name for row in windows}, {"std.out", "trail.txt.1"})
        self.assertTrue(all(row["channels_are_not_additive_event_counts"] for row in windows))
        self.assertEqual({row["candidate_call_sequence_through"] for row in windows}, {1})

    def test_only_initial_absence_is_legal_and_a_non_file_is_not_absence(self):
        result, directory = self.run_case("absent")
        self.assertEqual(result["calls"], 2)
        self.assertFalse(result["native_diagnostic"]["stopped"])
        windows = [
            row["window"]
            for row in self.inspect(directory)["complete_records"]
            if row["event"] == "native_log_window"
        ]
        self.assertEqual(windows[0]["status"], "absent_at_initial_observation")
        self.assertEqual(windows[1]["offset_start"], 0)
        failed, _ = self.run_case("not-regular")
        self.assertEqual(failed["calls"], 0)
        self.assertEqual(failed["native_diagnostic"]["reason"], "native_log_observation_unreliable")

    def test_real_unreturned_jvm_getter_keeps_forced_begin_after_parent_timeout(self):
        directory = Path(self.scratch.name) / "hang"
        child = subprocess.Popen(
            self.command("hang", directory),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=FLAGS,
        )
        try:
            journal = directory / "native-read-trace.ndjson"
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if journal.exists() and b"GetterThatDoesNotReturn" in journal.read_bytes():
                    break
                self.assertIsNone(child.poll())
                time.sleep(0.05)
            else:
                self.fail("unreturned getter did not leave a durable begin")
            with self.assertRaises(subprocess.TimeoutExpired):
                child.communicate(timeout=0.3)
            self.assertIsNone(
                child.poll(), "client wait expiry must not stand in for native cancellation"
            )
            # A genuinely new reader process sees disk bytes while the original JVM waits.
            reader = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "import json,pathlib,sys;"
                    "rows=pathlib.Path(sys.argv[1]).read_text().splitlines();"
                    "print(json.dumps([json.loads(x) for x in rows]))",
                    str(journal),
                ],
                capture_output=True,
                timeout=10,
                creationflags=FLAGS,
            )
            self.assertEqual(reader.returncode, 0, reader.stderr.decode())
            last = json.loads(reader.stdout)[-1]
            self.assertEqual(last["event"], "begin")
            self.assertEqual(last["getter"], "GetterThatDoesNotReturn")
            self.assertEqual(last["drawing_observed"], "owned-test.drw")
            self.assertEqual(last["note_id"], "12")
            self.assertEqual(last["line_index"], "0")
            self.assertEqual(last["diagnostic_request_id"], "unreturned-request")
        finally:
            # This is solely the SDK-free child created by this test, never a CAD process.
            child.terminate()
            child.communicate(timeout=10)

    def test_abnormal_process_exit_leaves_complete_begin_for_new_reader(self):
        directory = Path(self.scratch.name) / "halt"
        result = subprocess.run(
            self.command("halt", directory), capture_output=True, timeout=15, creationflags=FLAGS
        )
        self.assertEqual(result.returncode, 73)
        read = self.inspect(directory)
        self.assertTrue(read["complete"])
        self.assertEqual(read["complete_records"][-1]["event"], "begin")
        self.assertEqual(read["complete_records"][-1]["getter"], "GetterThatDoesNotReturn")

    def test_wait_expiry_stops_new_requests_but_preserves_later_actual_getter_end(self):
        result, directory = self.run_case("wait-expiry-completion")
        self.assertEqual(result["calls"], 1)
        diagnostic = result["native_diagnostic"]
        self.assertEqual(diagnostic["reason"], "native_request_unreturned_at_wait_expiry")
        self.assertEqual(diagnostic["unreturned_request"]["original_error"]["code"], "E_BUSY")
        self.assertTrue(diagnostic["unreturned_request"]["original_error"]["started"])
        self.assertFalse(diagnostic["unreturned_request"]["native_cancelled"])
        rows = self.inspect(directory)["complete_records"]
        expires = [
            index
            for index, row in enumerate(rows)
            if row["event"] == "request_wait_expired_while_started"
        ]
        ends = [(index, row) for index, row in enumerate(rows) if row["event"] == "end"]
        self.assertEqual(len(expires), 1)
        self.assertEqual(len(ends), 1)
        self.assertGreater(ends[0][0], expires[0])
        self.assertEqual(ends[0][1]["getter"], "ReturnsAfterHttpWaitExpired")
        self.assertEqual(ends[0][1]["result"], "returned_scalar")
        self.assertEqual(ends[0][1]["scalar_value"], 9)
        self.assertEqual(diagnostic["effects"][0]["facts"]["id"], "19")


if __name__ == "__main__":
    unittest.main()
