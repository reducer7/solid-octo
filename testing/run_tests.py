from __future__ import annotations

import json
import tempfile
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Keep direct script execution working without requiring manual PYTHONPATH setup.
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.common.config_loader import load_engine_config
from backend.database.redis_store import InMemoryStore
from backend.pipeline import PipelineError, process_submission


class PipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = load_engine_config(PROJECT_ROOT)
        self.config["root"]["fuzz"]["enabled"] = False
        self.store = InMemoryStore()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.log_path = Path(self.temp_dir.name) / "submission_log.jsonl"
        self.config["report"]["submission_logging_enabled"] = True
        self.config["report"]["submission_log_path"] = str(self.log_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_novel_submission_runs_pass2(self) -> None:
        response = process_submission(
            raw_request={
                "text": "This is a normal sentence for analysis.",
                "captcha_token": "ok",
                "datetimeUTC": "2026-05-19T10:00:00Z",
                "simhash": None,
            },
            store=self.store,
            config=self.config,
            project_root=PROJECT_ROOT,
        )
        self.assertTrue(response["novel_text"])
        self.assertFalse(response["reused_result"])

        lines = self.log_path.read_text(encoding="utf-8").strip().splitlines()
        entry = json.loads(lines[-1])
        self.assertEqual(entry["triggered_tests"], ["similarity", "garbage"])
        self.assertTrue(any(item["score"] == "human" for item in entry["score_contributions"]))
        self.assertTrue(any(item["score"] == "ai" for item in entry["score_contributions"]))

    def test_similarity_reuse_skips_pass2(self) -> None:
        payload = {
            "text": "Reuse this same sentence for similarity.",
            "captcha_token": "ok",
            "datetimeUTC": "2026-05-19T10:00:00Z",
            "simhash": None,
        }
        first = process_submission(payload, self.store, self.config, PROJECT_ROOT)
        second = process_submission(payload, self.store, self.config, PROJECT_ROOT)

        self.assertTrue(first["novel_text"])
        self.assertFalse(first["reused_result"])
        self.assertFalse(second["novel_text"])
        self.assertTrue(second["reused_result"])
        self.assertEqual(second.get("skip_reason"), "pass1_similarity_reuse")

    def test_terminal_garbage_short_circuit(self) -> None:
        payload = {
            "text": "@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@",
            "captcha_token": "ok",
            "datetimeUTC": "2026-05-19T10:00:00Z",
            "simhash": None,
        }
        result = process_submission(payload, self.store, self.config, PROJECT_ROOT)
        self.assertEqual(result["garbage_score"], 999)
        self.assertIn("skip_reason", result)

    def test_require_captcha_toggle_enforced(self) -> None:
        self.config["root"]["app"]["require_captcha"] = True
        payload = {
            "text": "Captcha should be required in this test.",
            "datetimeUTC": "2026-05-19T10:00:00Z",
            "simhash": None,
        }
        with self.assertRaises(PipelineError):
            process_submission(payload, self.store, self.config, PROJECT_ROOT)

    def test_construction_pass_runs_for_novel_text(self) -> None:
        # Text covers all 30 reference bigrams so bigram KL stays below the terminal threshold.
        text = (
            "The children ran happily through the green fields, and they enjoyed the warm sunlight. "
            "It was an especially pleasant afternoon, with birds singing in the old trees nearby. "
            "Everyone gathered around the table, sharing stories and laughter with great enthusiasm. "
            "The end of the long day brought rest, comfort, and a sense of peaceful satisfaction."
        )
        process_submission(
            raw_request={
                "text": text,
                "captcha_token": "ok",
                "datetimeUTC": "2026-05-19T10:00:00Z",
                "simhash": None,
            },
            store=self.store,
            config=self.config,
            project_root=PROJECT_ROOT,
        )
        lines = self.log_path.read_text(encoding="utf-8").strip().splitlines()
        entry = json.loads(lines[-1])
        self.assertIn("construction", entry["triggered_tests"])
        self.assertTrue(
            any(item["source"].startswith("pass3_") for item in entry["score_contributions"]),
            "Expected at least one pass3_ score contribution",
        )

    def test_terminal_garbage_skips_construction(self) -> None:
        # A terminal garbage result (repeated chars) must not reach the construction pass.
        payload = {
            "text": "@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@",
            "captcha_token": "ok",
            "datetimeUTC": "2026-05-19T10:00:00Z",
            "simhash": None,
        }
        process_submission(payload, self.store, self.config, PROJECT_ROOT)
        lines = self.log_path.read_text(encoding="utf-8").strip().splitlines()
        entry = json.loads(lines[-1])
        self.assertNotIn("construction", entry["triggered_tests"])

    def test_honeypot_field_rejected(self) -> None:
        payload = {
            "text": "This should trigger bot trap.",
            "datetimeUTC": "2026-05-19T10:00:00Z",
            "simhash": None,
            "hp_website": "https://spam.example",
        }
        with self.assertRaises(PipelineError):
            process_submission(payload, self.store, self.config, PROJECT_ROOT)

    def test_submission_logging_writes_input_and_triggered_tests(self) -> None:
        payload = {
            "text": "This sample should be logged with its triggered tests.",
            "captcha_token": "ok",
            "datetimeUTC": "2026-05-19T10:00:00Z",
            "simhash": None,
        }

        process_submission(payload, self.store, self.config, PROJECT_ROOT)
        process_submission(payload, self.store, self.config, PROJECT_ROOT)

        lines = self.log_path.read_text(encoding="utf-8").strip().splitlines()
        self.assertGreaterEqual(len(lines), 2)
        first_entry = json.loads(lines[-2])
        second_entry = json.loads(lines[-1])
        self.assertEqual(first_entry["input_text"], payload["text"])
        self.assertEqual(first_entry["triggered_tests"], ["similarity", "garbage"])
        self.assertFalse(first_entry["is_duplicate"])
        self.assertEqual(second_entry["input_text"], payload["text"])
        self.assertTrue(second_entry["is_duplicate"])
        self.assertEqual(second_entry["duplicate_of"]["simhash"], first_entry["simhash"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
