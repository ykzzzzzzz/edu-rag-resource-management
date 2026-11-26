"""spike_llm.py 的单元测试。只使用标准库，不发起任何网络请求。

运行：
  E:\\scf-env\\venv\\Scripts\\python.exe -m unittest discover -s D:\\codex\\scf\\scripts\\tests -v
"""
from __future__ import annotations

import contextlib
import http.server
import io
import json
import shutil
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))

import spike_llm as sl  # noqa: E402

VALID = {1, 2, 3}


def _j(**kw) -> str:
    return json.dumps(kw, ensure_ascii=False)


class ValidateOutputTests(unittest.TestCase):
    def test_valid_answer_passes(self):
        raw = _j(status="answered", answer="隔离性指互不干扰[1]。", citation_numbers=[1])
        r = sl.validate_model_output(raw, VALID)
        self.assertTrue(r["structure_ok"])
        self.assertEqual(r["validation_errors"], [])
        self.assertEqual(r["answer_citation_numbers"], [1])

    def test_valid_refusal_passes(self):
        raw = _j(status="insufficient_evidence", answer="资料中没有相关依据。", citation_numbers=[])
        r = sl.validate_model_output(raw, VALID)
        self.assertTrue(r["structure_ok"])

    def test_non_json_fails(self):
        r = sl.validate_model_output("这是普通文字，不是 JSON", VALID)
        self.assertFalse(r["structure_ok"])
        self.assertIn("json_invalid", r["validation_errors"])

    def test_json_array_not_object_fails(self):
        r = sl.validate_model_output("[1, 2]", VALID)
        self.assertIn("not_object", r["validation_errors"])

    def test_empty_output_fails(self):
        for raw in ("", "   ", None):
            r = sl.validate_model_output(raw, VALID)
            self.assertFalse(r["structure_ok"])
            self.assertIn("empty_output", r["validation_errors"])

    def test_missing_field_fails(self):
        raw = _j(status="answered", answer="x[1]")
        r = sl.validate_model_output(raw, VALID)
        self.assertFalse(r["structure_ok"])
        self.assertTrue(any(e.startswith("missing_fields:") and "citation_numbers" in e
                            for e in r["validation_errors"]))

    def test_bad_status_fails(self):
        raw = _j(status="maybe", answer="x[1]", citation_numbers=[1])
        r = sl.validate_model_output(raw, VALID)
        self.assertIn("status_invalid", r["validation_errors"])

    def test_answer_wrong_type_fails(self):
        raw = _j(status="answered", answer=["x"], citation_numbers=[1])
        r = sl.validate_model_output(raw, VALID)
        self.assertIn("answer_type", r["validation_errors"])

    def test_empty_answer_fails(self):
        raw = _j(status="answered", answer="  ", citation_numbers=[1])
        r = sl.validate_model_output(raw, VALID)
        self.assertIn("answer_empty", r["validation_errors"])

    def test_citation_out_of_range_fails(self):
        raw = _j(status="answered", answer="x[5]", citation_numbers=[5])
        r = sl.validate_model_output(raw, VALID)
        self.assertFalse(r["structure_ok"])
        self.assertIn("citation_out_of_range", r["validation_errors"])

    def test_citation_out_of_range_only_in_answer_fails(self):
        raw = _j(status="answered", answer="x[7]", citation_numbers=[1])
        r = sl.validate_model_output(raw, VALID)
        self.assertIn("citation_out_of_range", r["validation_errors"])
        self.assertIn("citation_mismatch", r["validation_errors"])

    def test_answer_numbers_disagree_with_array_fails(self):
        raw = _j(status="answered", answer="x[1]", citation_numbers=[1, 2])
        r = sl.validate_model_output(raw, VALID)
        self.assertIn("citation_mismatch", r["validation_errors"])

    def test_array_has_number_answer_lacks_fails(self):
        raw = _j(status="answered", answer="x。", citation_numbers=[2])
        r = sl.validate_model_output(raw, VALID)
        self.assertIn("citation_mismatch", r["validation_errors"])

    def test_answered_without_citation_fails(self):
        raw = _j(status="answered", answer="隔离性指互不干扰。", citation_numbers=[])
        r = sl.validate_model_output(raw, VALID)
        self.assertFalse(r["structure_ok"])
        self.assertIn("answered_without_citation", r["validation_errors"])

    def test_insufficient_with_citation_fails(self):
        raw = _j(status="insufficient_evidence", answer="没有依据[1]", citation_numbers=[1])
        r = sl.validate_model_output(raw, VALID)
        self.assertIn("insufficient_with_citation", r["validation_errors"])

    def test_citation_element_type_fails(self):
        raw = _j(status="answered", answer="x[1]", citation_numbers=["1"])
        r = sl.validate_model_output(raw, VALID)
        self.assertIn("citation_type", r["validation_errors"])

    def test_bool_is_not_a_citation_number(self):
        raw = _j(status="answered", answer="x", citation_numbers=[True])
        r = sl.validate_model_output(raw, VALID)
        self.assertIn("citation_type", r["validation_errors"])

    def test_citation_field_not_list_fails(self):
        raw = _j(status="answered", answer="x[1]", citation_numbers=1)
        r = sl.validate_model_output(raw, VALID)
        self.assertIn("citation_type", r["validation_errors"])


class AutoDecisionTests(unittest.TestCase):
    def test_answerable_answered(self):
        self.assertEqual(sl.auto_decision(True, "answered", True), "answered")

    def test_answerable_refused_is_false_refusal(self):
        self.assertEqual(sl.auto_decision(True, "insufficient_evidence", True), "false_refusal")

    def test_unanswerable_refusal_is_correct(self):
        self.assertEqual(sl.auto_decision(False, "insufficient_evidence", True), "correct_refusal")

    def test_unanswerable_answered_is_wrong(self):
        self.assertEqual(sl.auto_decision(False, "answered", True), "wrongly_answered")

    def test_invalid_structure_is_not_judged(self):
        self.assertEqual(sl.auto_decision(False, "insufficient_evidence", False), "invalid")
        self.assertEqual(sl.auto_decision(True, None, False), "invalid")


class GoldOverlapTests(unittest.TestCase):
    def test_overlap_hit(self):
        self.assertEqual(sl.gold_overlap([1, 2], [2]), ([2], True))

    def test_overlap_miss(self):
        self.assertEqual(sl.gold_overlap([3], [2]), ([], False))

    def test_no_gold_returns_empty(self):
        self.assertEqual(sl.gold_overlap([], []), ([], None))

    def test_non_list_returns_none(self):
        self.assertEqual(sl.gold_overlap(None, [1]), (None, None))


class RequestBodyTests(unittest.TestCase):
    def test_bailian_disables_thinking_via_enable_thinking(self):
        body = sl.build_request_body("bailian", "m", [], 0.1)
        self.assertIs(body["enable_thinking"], False)
        self.assertNotIn("thinking", body)
        self.assertEqual(body["response_format"], {"type": "json_object"})
        self.assertEqual(body["max_tokens"], 512)
        self.assertIs(body["stream"], False)

    def test_deepseek_disables_thinking_via_thinking_field(self):
        body = sl.build_request_body("deepseek", "m", [], 0.1)
        self.assertEqual(body["thinking"], {"type": "disabled"})
        self.assertNotIn("enable_thinking", body)

    def test_prompt_contains_json_and_sample(self):
        q = {"question": "问", "chunks": [{"n": 1, "source": "s", "locator": "p1", "text": "t"}]}
        msgs = sl.build_messages(q)
        user = msgs[1]["content"]
        self.assertIn("JSON", user)
        self.assertIn("citation_numbers", user)
        self.assertIn("[1]", user)
        self.assertIn("忽略", msgs[0]["content"])

    def test_prompt_versions_differ_and_default_is_v1(self):
        q = {"question": "问", "chunks": [{"n": 1, "source": "s", "locator": "p1", "text": "t"}]}
        v1 = sl.build_messages(q)[0]["content"]
        v1_explicit = sl.build_messages(q, "spike-v1")[0]["content"]
        v2 = sl.build_messages(q, "spike-v2")[0]["content"]
        self.assertEqual(v1, v1_explicit)
        self.assertNotEqual(v1, v2)
        self.assertIn("直接", v2)
        self.assertIn("忽略", v2)

    def test_v2_prompt_does_not_leak_question_content(self):
        text = sl.PROMPT_VERSIONS["spike-v2"]
        with open(sl.DEFAULT_QUESTIONS, encoding="utf-8") as f:
            for line in f:
                for word in ("DHCP", "补交", "补考", "迟交", "报名费"):
                    self.assertNotIn(word, text)

    def test_unknown_prompt_version_rejected_by_cli(self):
        with self.assertRaises(SystemExit):
            with contextlib.redirect_stderr(io.StringIO()):
                sl.main(["--mock", "--prompt-version", "spike-v9"])

    def test_interval_validation(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(sl.main(["--mock", "--interval", "-1"]), 2)
            self.assertEqual(sl.main(["--mock", "--interval", "61"]), 2)

    def test_default_interval_is_zero_for_mock_and_positive_for_live(self):
        self.assertGreater(sl.DEFAULT_INTERVAL_SECONDS, 1.0)

class ConfigTests(unittest.TestCase):
    def test_missing_env_raises_clear_error(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(sl.ConfigError) as ctx:
                sl.load_live_config()
            self.assertIn("LLM_BASE_URL", str(ctx.exception))
            self.assertIn("LLM_API_KEY", str(ctx.exception))

    def test_non_http_base_rejected(self):
        env = {"LLM_BASE_URL": "ftp://x", "LLM_API_KEY": "k", "LLM_MODEL": "m"}
        with mock.patch.dict("os.environ", env, clear=True):
            with self.assertRaises(sl.ConfigError):
                sl.load_live_config()

    def test_missing_config_exits_nonzero_without_network(self):
        with mock.patch.dict("os.environ", {}, clear=True), \
                mock.patch.object(sl.urllib.request, "urlopen") as up:
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                code = sl.main(["--questions", str(sl.DEFAULT_QUESTIONS),
                                "--out", str(Path(tempfile.gettempdir()) / "spike_test_unused.jsonl"),
                                "--limit", "1"])
            self.assertEqual(code, 2)
            self.assertIn("缺少环境变量", err.getvalue())
            up.assert_not_called()


class ErrorMappingTests(unittest.TestCase):
    def _http(self, code):
        err = urllib.error.HTTPError("http://x", code, "msg", {}, io.BytesIO(b""))
        self.addCleanup(err.close)
        return err

    def test_status_codes(self):
        cases = {401: "auth_failed", 402: "insufficient_balance", 429: "rate_limited",
                 400: "upstream_client_error", 500: "service_unavailable", 503: "service_unavailable"}
        for code, cat in cases.items():
            with self.subTest(code=code):
                self.assertEqual(sl.classify_error(self._http(code)), (cat, code))

    def test_timeout_variants(self):
        self.assertEqual(sl.classify_error(TimeoutError()), ("timeout", None))
        self.assertEqual(sl.classify_error(urllib.error.URLError(TimeoutError())), ("timeout", None))

    def test_network_error(self):
        self.assertEqual(sl.classify_error(urllib.error.URLError("refused"))[0], "network_error")

    def test_app_status_mapping(self):
        self.assertEqual(sl.APP_STATUS_BY_ERROR["timeout"], 504)
        self.assertEqual(sl.APP_STATUS_BY_ERROR["upstream_bad_response"], 502)
        self.assertEqual(sl.APP_STATUS_BY_ERROR["auth_failed"], 503)


class MockFlowTests(unittest.TestCase):
    def _run_mock(self, extra=None):
        tmp = Path(tempfile.mkdtemp(prefix="spike_mock_"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        out = tmp / "mock.jsonl"
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = sl.main(["--mock", "--out", str(out)] + (extra or []))
        records = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
        summary = json.loads((tmp / "mock_summary.json").read_text(encoding="utf-8"))
        csv_text = (tmp / "mock_manual_scoring.csv").read_text(encoding="utf-8-sig")
        return code, records, summary, csv_text

    def test_mock_runs_20_questions_without_network(self):
        with mock.patch.object(sl.urllib.request, "urlopen", side_effect=AssertionError("不应联网")):
            code, records, summary, _ = self._run_mock()
        self.assertEqual(code, 0)
        self.assertEqual(len(records), 20)
        self.assertEqual(summary["totals"], {"questions": 20, "answerable": 15, "unanswerable": 5})
        self.assertIn("待人工评分", summary["screening_reference_lines"]["answerable_correct"]["verdict"])
        self.assertIn("人工", summary["manual_review_note"])

    def test_mock_bad_outputs_are_flagged(self):
        _, records, summary, _ = self._run_mock()
        by_id = {r["id"]: r for r in records}
        self.assertFalse(by_id["NET-003"]["structure_ok"])
        self.assertIn("json_invalid", by_id["NET-003"]["validation_errors"])
        self.assertIn("citation_out_of_range", by_id["DB-005"]["validation_errors"])
        self.assertIn("citation_mismatch", by_id["NET-005"]["validation_errors"])
        self.assertIn("answer_empty", by_id["PY-004"]["validation_errors"])
        self.assertEqual(summary["structure"]["pass"], 16)

    def test_mock_correct_refusals_counted(self):
        _, records, summary, _ = self._run_mock()
        unans = [r for r in records if not r["answerable"]]
        self.assertEqual(sum(r["auto_decision"] == "correct_refusal" for r in unans), 4)
        self.assertEqual(summary["unanswerable_auto"]["wrongly_answered_auto"], 1)

    def test_mock_csv_template_has_blank_score_columns(self):
        _, records, _, csv_text = self._run_mock()
        lines = csv_text.strip().splitlines()
        self.assertEqual(lines[0].lstrip("\ufeff").split(","), ["题号", "模型回答", "gold_answer", "答对?", "引用能支撑?"])
        self.assertEqual(len(lines), 21)

    def test_limit_option(self):
        _, records, _, _ = self._run_mock(["--limit", "3"])
        self.assertEqual(len(records), 3)


class LoaderTests(unittest.TestCase):
    def test_bad_jsonl_line_reports_line_number(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "q.jsonl"
            p.write_text('{"id": "A"}\nnot json\n', encoding="utf-8")
            with self.assertRaises(ValueError) as ctx:
                sl.load_questions(p)
            self.assertIn("第 1 行", str(ctx.exception))

    def test_shipped_question_set_is_well_formed(self):
        items = sl.load_questions(sl.DEFAULT_QUESTIONS)
        self.assertEqual(len(items), 20)
        self.assertEqual(sum(1 for i in items if i["answerable"]), 15)
        self.assertEqual(sum(1 for i in items if not i["answerable"]), 5)
        for i in items:
            self.assertGreaterEqual(len(i["chunks"]), 3)
            self.assertLessEqual(len(i["chunks"]), 5)
            self.assertEqual([c["n"] for c in i["chunks"]], list(range(1, len(i["chunks"]) + 1)))
            if i["answerable"]:
                self.assertTrue(i["gold_chunk_numbers"], i["id"])
                self.assertTrue(i["gold_answer"], i["id"])
            else:
                self.assertEqual(i["gold_chunk_numbers"], [], i["id"])
                self.assertEqual(i["gold_answer"], "", i["id"])


class EnvFileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="spike_envtest_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _write(self, text: str) -> Path:
        p = self.tmp / "test.env"
        p.write_text(text, encoding="utf-8")
        return p

    def test_parses_four_keys_with_quotes_and_comments(self):
        p = self._write(
            "# 注释行\n"
            "\n"
            "LLM_BASE_URL = 'https://example.invalid/v1'  \n"
            'LLM_API_KEY="sk-fake-quoted"\n'
            "LLM_MODEL=qwen-fake\n"
            "LLM_PROVIDER=deepseek\n"
        )
        values = sl.parse_env_file(p)
        self.assertEqual(values, {
            "LLM_BASE_URL": "https://example.invalid/v1",
            "LLM_API_KEY": "sk-fake-quoted",
            "LLM_MODEL": "qwen-fake",
            "LLM_PROVIDER": "deepseek",
        })

    def test_ignores_other_keys(self):
        p = self._write("OTHER_SECRET=sk-fake-other\nLLM_MODEL=m1\n")
        self.assertEqual(sl.parse_env_file(p), {"LLM_MODEL": "m1"})

    def test_value_may_contain_equals_sign(self):
        p = self._write("LLM_API_KEY=sk-fake=abc\n")
        self.assertEqual(sl.parse_env_file(p)["LLM_API_KEY"], "sk-fake=abc")

    def test_malformed_line_error_hides_content(self):
        p = self._write("LLM_API_KEY sk-fake-leaked-line\n")
        with self.assertRaises(sl.ConfigError) as ctx:
            sl.parse_env_file(p)
        self.assertIn("第 1 行", str(ctx.exception))
        self.assertNotIn("sk-fake-leaked-line", str(ctx.exception))

    def test_missing_file_error_names_only_file(self):
        with self.assertRaises(sl.ConfigError) as ctx:
            sl.parse_env_file(self.tmp / "nope.env")
        self.assertIn("nope.env", str(ctx.exception))

    def test_existing_environment_variable_is_not_overwritten(self):
        p = self._write("LLM_API_KEY=sk-fake-from-file\nLLM_MODEL=model-from-file\n")
        with mock.patch.dict("os.environ", {"LLM_API_KEY": "sk-fake-from-env"}, clear=True):
            applied = sl.load_env_file(p)
            self.assertEqual(sl.os.environ["LLM_API_KEY"], "sk-fake-from-env")
            self.assertEqual(sl.os.environ["LLM_MODEL"], "model-from-file")
            self.assertEqual(applied, ["LLM_MODEL"])

    def test_resolve_provider_priority(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(sl.resolve_provider(None), "bailian")
        with mock.patch.dict("os.environ", {"LLM_PROVIDER": "deepseek"}, clear=True):
            self.assertEqual(sl.resolve_provider(None), "deepseek")
            self.assertEqual(sl.resolve_provider("bailian"), "bailian")
        with mock.patch.dict("os.environ", {"LLM_PROVIDER": "openai"}, clear=True):
            with self.assertRaises(sl.ConfigError):
                sl.resolve_provider(None)


class _FakeServerHandler(http.server.BaseHTTPRequestHandler):
    """本地假服务器。mode="drip" 每隔一小段时间吐一个字节；mode="fixed" 返回固定的 HTTP 错误。"""

    def log_message(self, *args):  # 保持测试输出干净
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length:
            self.rfile.read(length)
        srv = self.server
        if srv.mode == "fixed":
            body = srv.fixed_body
            self.send_response(srv.fixed_status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        for _ in range(srv.drip_count):
            if srv.stop_event.is_set():
                return
            try:
                self.wfile.write(b" ")
                self.wfile.flush()
            except OSError:
                return
            time.sleep(srv.drip_interval)


class FakeServerTests(unittest.TestCase):
    def _start(self, **attrs):
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _FakeServerHandler)
        srv.stop_event = threading.Event()
        srv.mode = "drip"
        srv.drip_count = 200
        srv.drip_interval = 0.1
        srv.fixed_status = 400
        srv.fixed_body = b"{}"
        for k, v in attrs.items():
            setattr(srv, k, v)
        threading.Thread(target=srv.serve_forever, daemon=True).start()

        def _stop():
            srv.stop_event.set()
            srv.shutdown()
            srv.server_close()

        self.addCleanup(_stop)
        return f"http://127.0.0.1:{srv.server_address[1]}/v1"

    def test_slow_drip_hits_total_deadline(self):
        base = self._start()
        cfg = {"base_url": base, "api_key": "sk-fake-drip", "model": "m"}
        messages = [{"role": "user", "content": "hi"}]
        t0 = time.monotonic()
        with self.assertRaises(TimeoutError):
            sl.request_chat(cfg, "bailian", messages, 0.1, timeout=1)
        elapsed = time.monotonic() - t0
        # 每 0.1 秒吐一个字节，套接字超时不会触发；只能靠总时限中断
        self.assertGreaterEqual(elapsed, 0.9)
        self.assertLess(elapsed, 2.5)

    def test_run_question_classifies_drip_as_timeout_504(self):
        base = self._start()
        cfg = {"base_url": base, "api_key": "sk-fake-drip", "model": "m"}
        q = sl.load_questions(sl.DEFAULT_QUESTIONS)[0]
        rec = sl.run_question(q, "bailian", 0.1, "live", cfg, timeout=1)
        self.assertEqual(rec["http_error_category"], "timeout")
        self.assertEqual(rec["app_http_status"], 504)
        self.assertFalse(rec["structure_ok"])

    def test_http_error_message_is_redacted_truncated_and_has_no_auth(self):
        key = "sk-fake-redact-me"
        long_msg = "参数错误 enable_thinking " + "x" * 600
        body = json.dumps({"error": {"message": f"echo Bearer {key} {long_msg}", "code": "InvalidParameter"}},
                          ensure_ascii=False).encode("utf-8")
        base = self._start(mode="fixed", fixed_status=400, fixed_body=body)
        cfg = {"base_url": base, "api_key": key, "model": "m"}
        q = sl.load_questions(sl.DEFAULT_QUESTIONS)[0]
        rec = sl.run_question(q, "bailian", 0.1, "live", cfg, timeout=5)
        self.assertEqual(rec["http_error_category"], "upstream_client_error")
        self.assertEqual(rec["upstream_http_status"], 400)
        msg = rec["upstream_error_message"]
        self.assertIsNotNone(msg)
        self.assertIn("enable_thinking", msg)
        self.assertLessEqual(len(msg), sl.UPSTREAM_MSG_MAX)
        self.assertNotIn(key, msg)
        dumped = json.dumps(rec, ensure_ascii=False)
        self.assertNotIn(key, dumped)
        self.assertNotIn("Authorization", dumped)
        self.assertNotIn("Bearer " + key, dumped)

    def test_bad_timeout_argument_rejected(self):
        with mock.patch.object(sl.urllib.request, "urlopen", side_effect=AssertionError("不应联网")):
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                code = sl.main(["--mock", "--timeout", "0", "--limit", "1"])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
