import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from agents.actor import subgoals


class StepMarkerTests(unittest.TestCase):
    def test_has_step_marker_detects_all_markers(self):
        self.assertTrue(subgoals.has_step_marker("STEP_DONE: opened page"))
        self.assertTrue(subgoals.has_step_marker("step_failed: blocked"))
        self.assertTrue(subgoals.has_step_marker("TASK_COMPLETE: here is the answer"))
        self.assertTrue(subgoals.has_step_marker("Step Done: opened page"))
        self.assertTrue(subgoals.has_step_marker("task-complete: answer"))
        self.assertFalse(subgoals.has_step_marker("just some text"))

    def test_has_step_marker_rejects_plain_marker_like_sentences(self):
        self.assertFalse(
            subgoals.has_step_marker(
                "The current step done status is only a note, not a control marker."
            )
        )
        self.assertFalse(
            subgoals.has_step_marker(
                "The task complete phrase appears in ordinary prose."
            )
        )
        self.assertFalse(
            subgoals.has_step_marker(
                "Do not write TASK_COMPLETE unless you are actually finished."
            )
        )

    def test_classify_step_done(self):
        result, reason, final = subgoals.classify_step_final_text(
            step_id=1, final_text="STEP_DONE: opened the page", steps=2
        )
        self.assertEqual(result, "done")
        self.assertIsNone(final)

    def test_classify_step_failed(self):
        result, reason, final = subgoals.classify_step_final_text(
            step_id=1, final_text="STEP_FAILED: element missing", steps=2
        )
        self.assertEqual(result, "failed")
        self.assertIsNone(final)

    def test_classify_task_complete_returns_final_answer(self):
        result, reason, final = subgoals.classify_step_final_text(
            step_id=3, final_text="Task Complete: The price is $12.", steps=1
        )
        self.assertEqual(result, "done")
        self.assertIsNotNone(final)
        self.assertIn("price is $12", final)
        self.assertNotIn("Task Complete", final)

    def test_clean_task_complete_only_removes_control_prefix(self):
        final = subgoals.clean_step_reason_for_answer(
            "TASK_COMPLETE: Explain the marker.\n"
            "TASK_COMPLETE: is only a literal token in this sentence."
        )
        self.assertIn("Explain the marker.", final)
        self.assertIn("TASK_COMPLETE: is only a literal token", final)

    def test_classify_marker_like_plain_text_as_missing_status(self):
        result, reason, final = subgoals.classify_step_final_text(
            step_id=3,
            final_text="I checked the page, and the task complete phrase is visible.",
            steps=1,
        )
        self.assertEqual(result, "failed")
        self.assertIn("ended without declaring a status", reason)
        self.assertIsNone(final)

    def test_classify_empty_is_failed(self):
        result, reason, final = subgoals.classify_step_final_text(
            step_id=2, final_text="   ", steps=4
        )
        self.assertEqual(result, "failed")
        self.assertIsNone(final)


if __name__ == "__main__":
    unittest.main()
