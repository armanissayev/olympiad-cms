# SPDX-License-Identifier: AGPL-3.0-or-later
"""Visibility regression tests for the shared CWS/native feedback policy."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from cms import FEEDBACK_LEVEL_FULL
from cms.db import SubmissionResult
from cms.server.contest.submission.feedback import submission_status, submission_details
from cms.server.olympiadide.feedback import participant_feedback


class TestParticipantFeedback(unittest.TestCase):
    def setUp(self):
        self.translation = Mock(); self.translation.gettext.side_effect = lambda value: value
        self.score_type = Mock(max_public_score=20.0, max_score=100.0)
        self.score_type.format_score.side_effect = lambda score, maximum, details, precision, **kw: str(round(score, precision))
        self.score_type.get_html_details.side_effect = lambda details, level, **kw: "<p>" + details + "</p>"
        self.dataset = SimpleNamespace(score_type_object=self.score_type)
        self.task = SimpleNamespace(active_dataset=self.dataset, score_precision=2, feedback_level="test-level")
        self.result = Mock(score=87.1234, public_score=12.3456, score_details="PRIVATE-DETAILS",
                           public_score_details="PUBLIC-DETAILS", compilation_text=["Compiled"],
                           compilation_stdout="<script>compiler text</script>", compilation_stderr="warning",
                           compilation_time=0.3, compilation_memory=4096)
        self.result.get_status.return_value = SubmissionResult.SCORED
        self.result.scored.return_value = True; self.result.compiled.return_value = True
        self.submission = Mock(task=self.task, participation=Mock(), token=None)
        self.submission.get_result.return_value = self.result
        self.submission.tokened.side_effect = lambda: self.submission.token is not None
        self.session = Mock()
        patcher = patch("cms.server.contest.submission.feedback.add_task_scores")
        self.add_tasks = patcher.start(); self.addCleanup(patcher.stop)
        self.add_tasks.side_effect = lambda _db, _owner, _task, data, _translation: data.update(
            task_public_score=12.35, task_tokened_score=0.0, task_score_is_partial=False)

    def test_public_only_does_not_disclose_private_score_or_details(self):
        data = participant_feedback(self.session, self.submission, 0, self.translation)
        self.assertNotIn("score", data)
        self.assertEqual(data["public_score"], 12.35)
        self.assertNotIn("PRIVATE-DETAILS", json.dumps(data))
        self.assertEqual(data["detailsText"], "PUBLIC-DETAILS")
        self.score_type.get_html_details.assert_called_with("PUBLIC-DETAILS", "test-level", translation=self.translation)

    def test_token_unlocks_score_without_overriding_feedback_level(self):
        self.submission.token = object()
        data = participant_feedback(self.session, self.submission, 0, self.translation)
        self.assertEqual(data["score"], 87.12)
        self.assertEqual(data["detailsText"], "PRIVATE-DETAILS")
        self.score_type.get_html_details.assert_called_with("PRIVATE-DETAILS", "test-level", translation=self.translation)

    def test_analysis_unlocks_full_details_and_precision(self):
        data = participant_feedback(self.session, self.submission, 3, self.translation)
        self.assertEqual(data["score"], 87.12)
        self.score_type.get_html_details.assert_called_with("PRIVATE-DETAILS", FEEDBACK_LEVEL_FULL, translation=self.translation)

    def test_current_dataset_and_rejudging_are_read_fresh(self):
        first = submission_status(self.session, self.submission, 0, self.translation)
        self.assertEqual(first["status"], SubmissionResult.SCORED)
        other = SimpleNamespace(score_type_object=self.score_type)
        self.task.active_dataset = other
        self.result.get_status.return_value = SubmissionResult.EVALUATING
        self.result.scored.return_value = False
        second = participant_feedback(self.session, self.submission, 0, self.translation)
        self.submission.get_result.assert_called_with(other)
        self.assertEqual(second["status"], SubmissionResult.EVALUATING)
        self.assertNotIn("public_score", second)
        self.assertNotIn("detailsText", second)

    def test_missing_result_is_compiling_without_fabricated_verdict(self):
        self.submission.get_result.return_value = None
        data = participant_feedback(self.session, self.submission, 0, self.translation)
        self.assertEqual(data, {"status": SubmissionResult.COMPILING, "status_text": "Compiling..."})

    def test_html_is_inert_text_and_compilation_output_is_not_html(self):
        self.result.public_score_details = '<b>Visible</b><script>SECRET-SCRIPT</script><style>SECRET-STYLE</style>&lt;tag&gt;'
        data = participant_feedback(self.session, self.submission, 0, self.translation)
        self.assertIn("Visible", data["detailsText"])
        self.assertIn("<tag>", data["detailsText"])
        self.assertNotIn("SECRET", data["detailsText"])
        self.assertEqual(data["compilation"]["stdout"], "<script>compiler text</script>")
        self.assertNotIn("html", data)

    def test_native_compiler_output_is_bounded_with_disclosure(self):
        self.result.compilation_stdout = "x" * 300000
        data = participant_feedback(self.session, self.submission, 0, self.translation)
        self.assertEqual(len(data["compilation"]["stdout"]), 262144)
        self.assertTrue(data["compilation"]["stdoutTruncated"])
