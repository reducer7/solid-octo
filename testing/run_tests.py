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
        self.config["root"]["app"]["check_similarity"] = True
        self.store = InMemoryStore()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.log_path = Path(self.temp_dir.name) / "submission_log.jsonl"
        self.config["report"]["submission_logging_enabled"] = True
        self.config["report"]["submission_log_path"] = str(self.log_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_novel_submission_runs_pass2(self) -> None:
        # Text covers all 30 reference bigrams so it is non-terminal in garbage.
        text = (
            "The children ran happily through the green fields, and they enjoyed the warm sunlight. "
            "It was an especially pleasant afternoon, with birds singing in the old trees nearby. "
            "Everyone gathered around the table, sharing stories and laughter with great enthusiasm. "
            "The end of the long day brought rest, comfort, and a sense of peaceful satisfaction."
        )
        response = process_submission(
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
        self.assertTrue(response["novel_text"])
        self.assertFalse(response["reused_result"])

        lines = self.log_path.read_text(encoding="utf-8").strip().splitlines()
        entry = json.loads(lines[-1])
        self.assertEqual(entry["triggered_tests"], ["similarity", "garbage", "construction", "ai", "human"])
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
        self.assertIn("similarity", first_entry["triggered_tests"])
        self.assertIn("garbage", first_entry["triggered_tests"])
        self.assertFalse(first_entry["is_duplicate"])
        self.assertEqual(second_entry["input_text"], payload["text"])
        self.assertTrue(second_entry["is_duplicate"])
        self.assertEqual(second_entry["duplicate_of"]["simhash"], first_entry["simhash"])

    def test_spelling_debug_included_when_highlight_enabled(self) -> None:
        self.config["root"]["app"]["check_similarity"] = False
        self.config["root"]["app"]["highlight_spelling"] = True
        payload = {
            "text": "I keep re-signing that albumn line from the otherway verse.",
            "captcha_token": "ok",
            "datetimeUTC": "2026-05-19T10:00:00Z",
            "simhash": None,
        }

        response = process_submission(payload, self.store, self.config, PROJECT_ROOT)
        self.assertIn("spelling_debug", response)
        self.assertTrue(response["spelling_debug"], "Expected highlighted spelling ranges")
        self.assertTrue(
            any(item.get("token", "").lower() == "albumn" for item in response["spelling_debug"]),
            "Expected misspelled token to appear in spelling_debug",
        )
        for item in response["spelling_debug"]:
            self.assertIsInstance(item.get("start"), int)
            self.assertIsInstance(item.get("end"), int)
            self.assertGreater(item["end"], item["start"])

    def test_spelling_debug_omitted_when_highlight_disabled(self) -> None:
        self.config["root"]["app"]["check_similarity"] = False
        self.config["root"]["app"]["highlight_spelling"] = False
        payload = {
            "text": "I keep re-signing that albumn line from the otherway verse.",
            "captcha_token": "ok",
            "datetimeUTC": "2026-05-19T10:00:00Z",
            "simhash": None,
        }

        response = process_submission(payload, self.store, self.config, PROJECT_ROOT)
        self.assertNotIn("spelling_debug", response)

    # ------------------------------------------------------------------
    # Pass 4: AI detector tests
    # ------------------------------------------------------------------

    def test_ai_pass_runs_for_novel_non_terminal_text(self) -> None:
        # Base text covers all 30 reference bigrams (same guarantee as the
        # construction test).  Em dashes and a typographer double-quote pair
        # are added as AI markers without removing any letters.
        text = (
            "The children ran happily through the green fields\u2014"
            "and they enjoyed the warm sunlight. "
            "It was an especially pleasant afternoon\u2014"
            "with birds singing in the old trees nearby. "
            "\u201cEveryone gathered around the table, sharing stories "
            "and laughter with great enthusiasm.\u201d "
            "The end of the long day brought rest, comfort, and a sense "
            "of peaceful satisfaction."
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
        self.assertIn("ai", entry["triggered_tests"])
        self.assertTrue(
            any(item["source"].startswith("pass4_") for item in entry["score_contributions"]),
            "Expected at least one pass4_ score contribution",
        )

    def test_ai_key_markers_em_dash_scored(self) -> None:
        # Base text covers all 30 reference bigrams.  Exactly two em dashes are
        # added, so pass4_em_dash must contribute amount=2.
        text = (
            "The children ran happily through the green fields\u2014"
            "and they enjoyed the warm sunlight. "
            "It was an especially pleasant afternoon\u2014"
            "with birds singing in the old trees nearby. "
            "Everyone gathered around the table, sharing stories and laughter "
            "with great enthusiasm. "
            "The end of the long day brought rest, comfort, and a sense "
            "of peaceful satisfaction."
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
        em_dash_contributions = [
            item for item in entry["score_contributions"] if item["source"] == "pass4_em_dash"
        ]
        self.assertTrue(em_dash_contributions, "Expected a pass4_em_dash contribution")
        self.assertEqual(em_dash_contributions[0]["amount"], 2)

    def test_ai_grammar_nested_quotes_scored(self) -> None:
        # Base text covers all 30 reference bigrams.  One sentence is modified
        # to include a correctly nested quote; the regex should detect it.
        text = (
            "The children ran happily through the green fields, and they "
            "enjoyed the warm sunlight. "
            "It was an especially pleasant afternoon, with birds singing in "
            "the old trees nearby. "
            "Everyone gathered around the table and said "
            "\"this is a 'great' afternoon for stories\" "
            "and laughter with great enthusiasm. "
            "The end of the long day brought rest, comfort, and a sense "
            "of peaceful satisfaction."
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
        nested_contributions = [
            item for item in entry["score_contributions"] if item["source"] == "pass4_nested_quotes"
        ]
        self.assertTrue(nested_contributions, "Expected a pass4_nested_quotes contribution")
        self.assertEqual(nested_contributions[0]["amount"], 2)

    def test_ai_key_markers_colon_scored(self) -> None:
        # Base text with exactly 2 colons; pass4_colon must contribute amount=2.
        text = (
            "The children ran happily through the green fields: they enjoyed the warm sunlight. "
            "It was an especially pleasant afternoon: birds singing in the old trees nearby. "
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
        colon_contributions = [
            item for item in entry["score_contributions"] if item["source"] == "pass4_colon"
        ]
        self.assertTrue(colon_contributions, "Expected a pass4_colon contribution")
        self.assertEqual(colon_contributions[0]["amount"], 2)

    def test_ai_key_markers_aside_scored(self) -> None:
        # Base text with exactly 2 parenthetical asides; pass4_aside must contribute amount=2.
        text = (
            "The children ran happily through the green fields (especially in summer), "
            "and they enjoyed the warm sunlight. "
            "It was an especially pleasant afternoon (with birds singing) in the old trees nearby. "
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
        aside_contributions = [
            item for item in entry["score_contributions"] if item["source"] == "pass4_aside"
        ]
        self.assertTrue(aside_contributions, "Expected a pass4_aside contribution")
        self.assertEqual(aside_contributions[0]["amount"], 2)

    def test_ai_key_markers_en_dash_scored(self) -> None:
        # Base text with exactly 2 en dashes (U+2013); pass4_en_dash must contribute amount=2.
        text = (
            "The children ran happily through the green fields\u2013"
            "and they enjoyed the warm sunlight. "
            "It was an especially pleasant afternoon\u2013"
            "with birds singing in the old trees nearby. "
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
        en_dash_contributions = [
            item for item in entry["score_contributions"] if item["source"] == "pass4_en_dash"
        ]
        self.assertTrue(en_dash_contributions, "Expected a pass4_en_dash contribution")
        self.assertEqual(en_dash_contributions[0]["amount"], 2)

    def test_ai_key_markers_typo_double_quote_scored(self) -> None:
        # Base text with one typographer double-quote pair; pass4_typo_double_quote
        # must contribute amount=1.
        text = (
            "The children ran happily through the green fields, and they enjoyed the warm sunlight. "
            "It was an especially pleasant afternoon, with birds singing in the old trees nearby. "
            "\u201cEveryone gathered around the table, sharing stories and laughter "
            "with great enthusiasm.\u201d "
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
        typo_contributions = [
            item for item in entry["score_contributions"] if item["source"] == "pass4_typo_double_quote"
        ]
        self.assertTrue(typo_contributions, "Expected a pass4_typo_double_quote contribution")
        self.assertEqual(typo_contributions[0]["amount"], 1)

    def test_ai_key_markers_single_curly_quote_scored(self) -> None:
        # Base text with exactly 2 single curly apostrophes (U+2019) outside any
        # typographer double-quote pair; pass4_single_curly_quote must contribute amount=2.
        text = (
            "The children\u2019s laughter filled the green fields, "
            "and they\u2019re enjoying the warm sunlight. "
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
        curly_contributions = [
            item for item in entry["score_contributions"] if item["source"] == "pass4_single_curly_quote"
        ]
        self.assertTrue(curly_contributions, "Expected a pass4_single_curly_quote contribution")
        self.assertEqual(curly_contributions[0]["amount"], 2)

    def test_ai_grammar_plural_possessive_scored(self) -> None:
        # Base text with one plural possessive ("teachers'"); pass4_plural_possessive
        # must contribute amount=1.
        text = (
            "The teachers' enthusiasm grew through the green fields, "
            "and they enjoyed the warm sunlight. "
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
        plural_contributions = [
            item for item in entry["score_contributions"] if item["source"] == "pass4_plural_possessive"
        ]
        self.assertTrue(plural_contributions, "Expected a pass4_plural_possessive contribution")
        self.assertEqual(plural_contributions[0]["amount"], 1)

    def test_ai_constructed_sentences_scored(self) -> None:
        text = (
            "The children ran happily through the green fields, and they enjoyed the warm sunlight. "
            "In summary, the weather stayed mild and everyone remained comfortable all day. "
            "Overall, the group agreed the afternoon was pleasant and calm. "
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
        self.assertTrue(
            any(item["source"] == "pass4_constructed_sentences" for item in entry["score_contributions"]),
            "Expected a pass4_constructed_sentences contribution",
        )

    def test_ai_perfect_parallelism_scored(self) -> None:
        text = (
            "The children ran happily through the green fields, and they enjoyed the warm sunlight. "
            "To plan, to build, to deliver became the team's steady routine throughout the month. "
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
        self.assertTrue(
            any(item["source"] == "pass4_perfect_parallelism" for item in entry["score_contributions"]),
            "Expected a pass4_perfect_parallelism contribution",
        )

    def test_ai_balance_hedge_scored(self) -> None:
        text = (
            "The children ran happily through the green fields, and they enjoyed the warm sunlight. "
            "On the other hand, a smaller team can move quickly and still maintain quality. "
            "It is worth noting that larger teams can improve review coverage in complex projects. "
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
        self.assertTrue(
            any(item["source"] == "pass4_balance_hedge" for item in entry["score_contributions"]),
            "Expected a pass4_balance_hedge contribution",
        )

    def test_ai_over_explanation_scored(self) -> None:
        text = (
            "The children ran happily through the green fields, and they enjoyed the warm sunlight. "
            "A browser means the app you use to open websites and move between pages on the internet. "
            "In other words, a password means a secret word that lets a user sign in to an account. "
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
        self.assertTrue(
            any(item["source"] == "pass4_over_explanation" for item in entry["score_contributions"]),
            "Expected a pass4_over_explanation contribution",
        )

    def test_ai_over_explanation_not_scored_for_domain_specific_definition(self) -> None:
        text = (
            "The children ran happily through the green fields, and they enjoyed the warm sunlight. "
            "In this paper, covariance is defined as the expected product of centered random variables. "
            "The theorem means a compact statement that follows from prior lemmas and assumptions. "
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
        self.assertFalse(
            any(item["source"] == "pass4_over_explanation" for item in entry["score_contributions"]),
            "pass4_over_explanation should not trigger for guarded domain-specific definitions",
        )

    def test_ai_no_personal_experience_scored(self) -> None:
        text = (
            "In general, people evaluate options by comparing cost, reliability, and expected outcomes over time. "
            "Users often prefer clear steps because ambiguity can increase error rates and reduce confidence in decisions. "
            "It is important to review trade-offs before choosing a process, especially when requirements are likely to change. "
            "Individuals tend to adopt methods that are easy to repeat, easy to explain, and easy to verify under pressure. "
            "In many ways, this style emphasizes consistency, predictability, and broad applicability across situations."
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
        self.assertTrue(
            any(item["source"] == "pass4_no_personal_experience" for item in entry["score_contributions"]),
            "Expected a pass4_no_personal_experience contribution",
        )

    def test_ai_no_personal_experience_not_scored_for_personal_anecdote(self) -> None:
        text = (
            "Last year I visited a crowded market near the station on a rainy evening with my brother. "
            "I smelled fried onions and heard a street drummer while we waited for hot tea by a noisy stall. "
            "When I was choosing fruit, the vendor laughed and gave me an extra orange for free. "
            "I still remember the bright lights, the wet pavement, and the sound of trains passing nearby."
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
        self.assertFalse(
            any(item["source"] == "pass4_no_personal_experience" for item in entry["score_contributions"]),
            "pass4_no_personal_experience should not trigger for personal anecdotal text",
        )

    def test_ai_connector_scored(self) -> None:
        text = (
            "The children ran happily through the green fields, and they enjoyed the warm sunlight. "
            "Notably, the group completed the work early and shared results with the wider team. "
            "In essence, the process reduced delays without increasing risk in any substantial way. "
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
        self.assertTrue(
            any(item["source"] == "pass4_ai_connector" for item in entry["score_contributions"]),
            "Expected a pass4_ai_connector contribution",
        )

    def test_ai_overused_intensifier_scored(self) -> None:
        text = (
            "The children ran happily through the green fields, and they enjoyed the warm sunlight. "
            "The team was highly focused, deeply prepared, and remarkably calm during the release. "
            "They strongly preferred a staged rollout because it felt incredibly reliable in practice. "
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
        self.assertTrue(
            any(item["source"] == "pass4_overused_intensifier" for item in entry["score_contributions"]),
            "Expected a pass4_overused_intensifier contribution",
        )

    def test_ai_list_introduction_scored(self) -> None:
        text = (
            "The children ran happily through the green fields, and they enjoyed the warm sunlight. "
            "Here are some key points: keep messages short, check assumptions, and verify outcomes carefully. "
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
        self.assertTrue(
            any(item["source"] == "pass4_list_introduction" for item in entry["score_contributions"]),
            "Expected a pass4_list_introduction contribution",
        )

    def test_ai_terminal_garbage_skips_ai_pass(self) -> None:
        # Terminal garbage input must not reach pass 4.
        payload = {
            "text": "@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@",
            "captcha_token": "ok",
            "datetimeUTC": "2026-05-19T10:00:00Z",
            "simhash": None,
        }
        process_submission(payload, self.store, self.config, PROJECT_ROOT)
        lines = self.log_path.read_text(encoding="utf-8").strip().splitlines()
        entry = json.loads(lines[-1])
        self.assertNotIn("ai", entry["triggered_tests"])
        self.assertFalse(
            any(item["source"].startswith("pass4_") for item in entry["score_contributions"]),
            "pass4 contributions should be absent for terminal garbage",
        )


    # ------------------------------------------------------------------ Pass 3

    def test_pass3_semantic_coherence_scored(self) -> None:
        # Five sentences on completely different topics; every adjacent pair
        # should have cosine_sim < 0.2, giving low_pair_ratio ≥ 0.5.
        text = (
            "Freshly baked sourdough bread requires a long fermentation period and precise temperature control. "
            "The telescope gathered detailed data from distant galaxies far beyond our own solar neighbourhood. "
            "During the penalty shootout the goalkeeper dove to his left and blocked the decisive last shot. "
            "Investors grew anxious as the central bank announced an unexpected sharp rise in interest rates. "
            "The surgeon carefully closed the incision using a fine absorbable suture and sterile technique."
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
        contributions = [
            item for item in entry["score_contributions"]
            if item["source"] == "pass3_semantic_coherence"
        ]
        self.assertTrue(contributions, "Expected a pass3_semantic_coherence contribution")

    def test_pass3_topic_persistence_high_scored(self) -> None:
        # Five sentences on entirely different topics → each gets its own
        # embedding cluster → cluster_ratio = 1.0 > 0.75.
        text = (
            "Freshly baked sourdough bread requires a long fermentation period and precise temperature control. "
            "The telescope gathered detailed data from distant galaxies far beyond our own solar neighbourhood. "
            "During the penalty shootout the goalkeeper dove to his left and blocked the decisive last shot. "
            "Investors grew anxious as the central bank announced an unexpected sharp rise in interest rates. "
            "The surgeon carefully closed the incision using a fine absorbable suture and sterile technique."
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
        contributions = [
            item for item in entry["score_contributions"]
            if item["source"] == "pass3_topic_persistence_high"
        ]
        self.assertTrue(contributions, "Expected a pass3_topic_persistence_high contribution")

    def test_pass3_embedding_variance_mod_high_scored(self) -> None:
        # Coherent four-sentence paragraph covering a pleasant afternoon; measured
        # embedding variance ≈ 0.31, which lands in the mod_high band (0.25–0.35).
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
        contributions = [
            item for item in entry["score_contributions"]
            if item["source"] == "pass3_embedding_variance_mod_high"
        ]
        self.assertTrue(contributions, "Expected a pass3_embedding_variance_mod_high contribution")

    def test_pass3_marker_clause_misuse_scored(self) -> None:
        # First sentence starts with "Because"; no main clause precedes the
        # marker, so pass3_marker_clause_misuse must fire.
        text = (
            "Because the weather was extremely cold and windy, everyone decided to stay indoors. "
            "The children played board games by the fireplace and drank hot chocolate all evening. "
            "They laughed and told stories until it was very late and time for bed. "
            "The next morning the sun came out and the temperature slowly began to rise."
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
        contributions = [
            item for item in entry["score_contributions"]
            if item["source"] == "pass3_marker_clause_misuse"
        ]
        self.assertTrue(contributions, "Expected a pass3_marker_clause_misuse contribution")

    def test_pass3_semantic_because_low_scored(self) -> None:
        # "because" joins two completely unrelated clauses (groceries / nuclear
        # fusion) → cosine_sim < 0.2 → pass3_semantic_because_low.
        text = (
            "The children ran happily through the green fields, and they enjoyed the warm sunlight. "
            "It was an especially pleasant afternoon, with birds singing in the old trees nearby. "
            "She bought fresh vegetables at the market because nuclear fusion releases enormous amounts of energy. "
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
        contributions = [
            item for item in entry["score_contributions"]
            if item["source"] == "pass3_semantic_because_low"
        ]
        self.assertTrue(contributions, "Expected a pass3_semantic_because_low contribution")

    def test_pass3_semantic_however_very_low_scored(self) -> None:
        # "However" opens sentence 3; the fallback clause_a is the preceding
        # sentence (dogs / loyalty) and clause_b is about bridge engineering –
        # completely unrelated → sim < 0.1 → pass3_semantic_however_very_low.
        text = (
            "The children ran happily through the green fields, and they enjoyed the warm sunlight. "
            "Dogs make wonderful loyal companions and they are known for their affectionate behaviour. "
            "However, the construction of suspension bridges requires careful engineering and precise calculation. "
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
        contributions = [
            item for item in entry["score_contributions"]
            if item["source"] == "pass3_semantic_however_very_low"
        ]
        self.assertTrue(contributions, "Expected a pass3_semantic_however_very_low contribution")

    def test_pass3_semantic_therefore_low_scored(self) -> None:
        # "therefore" joins unrelated clauses (Arctic birds / bakery) → sim ≤ 0.4
        # → pass3_semantic_therefore_low.
        text = (
            "The children ran happily through the green fields, and they enjoyed the warm sunlight. "
            "It was an especially pleasant afternoon, with birds singing in the old trees nearby. "
            "Scientists studied the migration of Arctic birds therefore the bakery sold fresh bread daily. "
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
        contributions = [
            item for item in entry["score_contributions"]
            if item["source"] == "pass3_semantic_therefore_low"
        ]
        self.assertTrue(contributions, "Expected a pass3_semantic_therefore_low contribution")

    def test_pass3_semantic_although_low_scored(self) -> None:
        # "although" mid-sentence joins a technology clause to a food clause
        # → sim < 0.2 → pass3_semantic_although_low.
        text = (
            "The children ran happily through the green fields, and they enjoyed the warm sunlight. "
            "It was an especially pleasant afternoon, with birds singing in the old trees nearby. "
            "The microchip contained billions of transistors although the local bakery made excellent fresh pastries. "
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
        contributions = [
            item for item in entry["score_contributions"]
            if item["source"] == "pass3_semantic_although_low"
        ]
        self.assertTrue(contributions, "Expected a pass3_semantic_although_low contribution")

    def test_pass3_marker_spiral_multi_sentence_scored(self) -> None:
        # Sentence 3 contains both "although" and "because" → two markers in
        # one sentence → pass3_marker_spiral_multi_sentence must fire.
        text = (
            "The children ran happily through the green fields, and they enjoyed the warm sunlight. "
            "It was an especially pleasant afternoon, with birds singing in the old trees nearby. "
            "She stayed although it was very late because she still had important work to finish. "
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
        contributions = [
            item for item in entry["score_contributions"]
            if item["source"] == "pass3_marker_spiral_multi_sentence"
        ]
        self.assertTrue(contributions, "Expected a pass3_marker_spiral_multi_sentence contribution")

    def test_pass3_marker_spiral_multi_type_scored(self) -> None:
        # Text uses three distinct marker types (because, however, therefore)
        # → unique_markers ≥ 3 → pass3_marker_spiral_multi_type must fire.
        text = (
            "She stayed inside because the cold weather made going outside very unpleasant for everyone. "
            "However, the temperature began to rise steadily by the middle of the afternoon. "
            "She felt much warmer therefore she decided to take a short walk around the garden. "
            "Everyone agreed it had been a genuinely pleasant day despite the difficult start that morning."
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
        contributions = [
            item for item in entry["score_contributions"]
            if item["source"] == "pass3_marker_spiral_multi_type"
        ]
        self.assertTrue(contributions, "Expected a pass3_marker_spiral_multi_type contribution")

    # ------------------------------------------------------------------ Pass 5

    _BASE = (
        "The children ran happily through the green fields, and they enjoyed the warm sunlight. "
        "It was an especially pleasant afternoon, with birds singing in the old trees nearby. "
    )

    def _run(self, text: str) -> dict:
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
        return json.loads(lines[-1])

    def _assert_source(self, entry: dict, source: str) -> None:
        self.assertTrue(
            any(item["source"] == source for item in entry["score_contributions"]),
            f"Expected a {source} contribution",
        )

    def test_pass5_single_hyphen_scored(self) -> None:
        entry = self._run(
            self._BASE
            + "She stayed - for reasons unclear - until the very end of the long meeting."
        )
        self._assert_source(entry, "pass5_single_hyphen")

    def test_pass5_double_hyphen_scored(self) -> None:
        entry = self._run(
            self._BASE
            + "She was -- or rather had been -- quite talented at solving difficult problems."
        )
        self._assert_source(entry, "pass5_double_hyphen")

    def test_pass5_straight_quote_scored(self) -> None:
        entry = self._run(
            self._BASE
            + 'She told him "I will be there" and walked quickly away from the crowded room.'
        )
        self._assert_source(entry, "pass5_straight_quote")

    def test_pass5_triple_dot_scored(self) -> None:
        entry = self._run(
            self._BASE
            + "She hesitated... then slowly... finally walked through the big door into the room."
        )
        self._assert_source(entry, "pass5_triple_dot")

    def test_pass5_double_dot_scored(self) -> None:
        entry = self._run(
            self._BASE
            + "Well.. that was something.. I never expected it to turn out quite like that at all."
        )
        self._assert_source(entry, "pass5_double_dot")

    def test_pass5_semicolon_scored(self) -> None:
        entry = self._run(
            self._BASE
            + "She liked reading; he preferred writing; they both enjoyed quiet afternoons at home."
        )
        self._assert_source(entry, "pass5_semicolon")

    def test_pass5_unclosed_bracket_scored(self) -> None:
        entry = self._run(
            self._BASE
            + "She went to the market (to buy vegetables and came back with bread and milk instead."
        )
        self._assert_source(entry, "pass5_unclosed_bracket")

    def test_pass5_possessive_error_scored(self) -> None:
        entry = self._run(
            self._BASE
            + "That book is your's to keep and this one is their's to borrow as long as they need."
        )
        self._assert_source(entry, "pass5_possessive_error")

    def test_pass5_homophone_error_scored(self) -> None:
        entry = self._run(
            self._BASE
            + "Your going to love the new arrangement and your not going to believe how well it works."
        )
        self._assert_source(entry, "pass5_homophone_error")

    def test_pass5_capitalization_scored(self) -> None:
        entry = self._run(
            self._BASE
            + "she arrived late. he left early. they never saw each other again on that particular day."
        )
        self._assert_source(entry, "pass5_capitalization")

    def test_pass5_spacing_scored(self) -> None:
        entry = self._run(
            self._BASE
            + "She bought bread , milk , and eggs at the local market on a cold and rainy afternoon."
        )
        self._assert_source(entry, "pass5_spacing")

    def test_pass5_repeated_word_scored(self) -> None:
        entry = self._run(
            self._BASE
            + "She went to the the store and came back home with fresh bread and warm hot chocolate."
        )
        self._assert_source(entry, "pass5_repeated_word")

    def test_pass5_a_an_error_scored(self) -> None:
        entry = self._run(
            self._BASE
            + "It was a easy task to complete and he needed an book from the large library downtown."
        )
        self._assert_source(entry, "pass5_a_an_error")

    def test_pass5_micro_hesitation_scored(self) -> None:
        entry = self._run(
            self._BASE
            + "She went, I mean she drove, to the market. Or rather, she walked all the way there."
        )
        self._assert_source(entry, "pass5_micro_hesitation")

    def test_pass5_uneven_rhythm_scored(self) -> None:
        # Two very short sentences mixed with one very long sentence.
        entry = self._run(
            "Good. OK. "
            "The children ran very happily through the wide green fields and they all thoroughly "
            "enjoyed the especially warm and golden sunlight on that particularly pleasant afternoon."
        )
        self._assert_source(entry, "pass5_uneven_rhythm")

    def test_pass5_spelling_mistake_scored(self) -> None:
        entry = self._run(
            self._BASE
            + "In the song Evil bt Interpol, I keep re-signing that line and the otherway phrasing from the albumn notes."
        )
        self._assert_source(entry, "pass5_spelling_mistake")

    def test_pass5_spelling_ignores_capitalized_names(self) -> None:
        entry = self._run(
            self._BASE
            + "Batman and Interpol and Monique met at Gotham while discussing albums and lyrics."
        )
        self.assertFalse(
            any(item["source"] == "pass5_spelling_mistake" for item in entry["score_contributions"]),
            "Capitalized name-heavy text should not trigger pass5_spelling_mistake by itself",
        )

    def test_pass5_spelling_counts_elongated_slang(self) -> None:
        entry = self._run(
            self._BASE
            + "That was reeeally goooood and sooo weird but kinda hilarious in the end."
        )
        self._assert_source(entry, "pass5_spelling_mistake")


if __name__ == "__main__":
    unittest.main(verbosity=2)
