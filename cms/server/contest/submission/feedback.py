# Contest Management System - http://cms-dev.github.io/
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Participant feedback policy shared by ordinary CWS and native IDE.

These functions receive an already-authorized, owned Submission. They select
only its active dataset and apply the same token/analysis/precision rules.
"""
from sqlalchemy.orm import joinedload
from cms import FEEDBACK_LEVEL_FULL
from cms.db import Submission, SubmissionResult
from cms.grading.scoring import task_score

def N_(message):
    return message


STATUS_TEXT = {
    SubmissionResult.COMPILING: N_("Compiling..."),
    SubmissionResult.COMPILATION_FAILED: N_("Compilation failed"),
    SubmissionResult.EVALUATING: N_("Evaluating..."),
    SubmissionResult.SCORING: N_("Scoring..."),
    SubmissionResult.SCORED: N_("Evaluated"),
}


def add_task_scores(sql_session, participation, task, data, translation):
    sql_session.query(Submission).filter(
        Submission.participation == participation, Submission.task == task).options(
            joinedload(Submission.token), joinedload(Submission.results)).all()
    data["task_public_score"], public_partial = task_score(
        participation, task, public=True, rounded=True)
    data["task_tokened_score"], tokened_partial = task_score(
        participation, task, only_tokened=True, rounded=True)
    data["task_score_is_partial"] = public_partial or tokened_partial
    score_type = task.active_dataset.score_type_object
    data["task_public_score_message"] = score_type.format_score(
        data["task_public_score"], score_type.max_public_score, None,
        task.score_precision, translation=translation)
    data["task_tokened_score_message"] = score_type.format_score(
        data["task_tokened_score"], score_type.max_score, None,
        task.score_precision, translation=translation)


def submission_status(sql_session, submission, actual_phase, translation):
    task = submission.task
    sr = submission.get_result(task.active_dataset)
    data = {"status": SubmissionResult.COMPILING if sr is None else sr.get_status()}
    data["status_text"] = translation.gettext(STATUS_TEXT[data["status"]])
    if data["status"] in (SubmissionResult.COMPILATION_FAILED, SubmissionResult.SCORED):
        add_task_scores(sql_session, submission.participation, task, data, translation)
        score_type = task.active_dataset.score_type_object
        if score_type.max_public_score > 0:
            data["max_public_score"] = round(score_type.max_public_score, task.score_precision)
            if data["status"] == SubmissionResult.SCORED:
                data["public_score"] = round(sr.public_score, task.score_precision)
                data["public_score_message"] = score_type.format_score(
                    sr.public_score, score_type.max_public_score,
                    sr.public_score_details, task.score_precision, translation=translation)
        if score_type.max_public_score < score_type.max_score:
            data["max_score"] = round(score_type.max_score, task.score_precision)
            if data["status"] == SubmissionResult.SCORED and (submission.token is not None or actual_phase == 3):
                data["score"] = round(sr.score, task.score_precision)
                data["score_message"] = score_type.format_score(
                    sr.score, score_type.max_score, sr.score_details,
                    task.score_precision, translation=translation)
    return data


def submission_details(submission, actual_phase, translation):
    task = submission.task
    sr = submission.get_result(task.active_dataset)
    details = None
    if sr is not None and sr.scored():
        analysis = actual_phase == 3
        raw_details = sr.score_details if submission.tokened() or analysis else sr.public_score_details
        feedback_level = FEEDBACK_LEVEL_FULL if analysis else task.feedback_level
        details = task.active_dataset.score_type_object.get_html_details(
            raw_details, feedback_level, translation=translation)
    return sr, details
