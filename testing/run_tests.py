from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Keep direct script execution working without requiring manual PYTHONPATH setup.
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.common.config_loader import load_engine_config
from backend.database.redis_store import InMemoryStore
from backend.pipeline import process_submission


class PipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = load_engine_config(PROJECT_ROOT)
        self.config["root"]["fuzz"]["enabled"] = False
        self.store = InMemoryStore()

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
