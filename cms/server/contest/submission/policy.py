# Contest Management System - http://cms-dev.github.io/
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Shared outer participant admission policy for CWS and the native IDE."""
from cms.db import Participation
from cms.server.contest.phase_management import compute_actual_phase


def lock_submission_participation(sql_session, participation):
    """Serialize count/interval checks across all participant ingress paths.

    FOR NO KEY UPDATE also permits ordinary foreign-key KEY SHARE references.
    The caller owns the transaction and must commit/rollback after admission.
    """
    # Materialize a newly-added participation before binding its identifier.
    sql_session.flush()
    return sql_session.query(Participation).filter(
        Participation.id == participation.id).with_for_update(
            key_share=True).one()


def participant_phase(participation, timestamp):
    contest = participation.contest
    return compute_actual_phase(
        timestamp, contest.start, contest.stop,
        contest.analysis_start if contest.analysis_enabled else None,
        contest.analysis_stop if contest.analysis_enabled else None,
        contest.per_user_time, participation.starting_time,
        participation.delay_time, participation.extra_time)[0]


def check_submission_phase(participation, task, timestamp):
    from .workflow import UnacceptableSubmission
    if task.contest_id != participation.contest_id:
        raise UnacceptableSubmission("Task unavailable", "Task is not in this contest.")
    phase = participant_phase(participation, timestamp)
    if phase not in (0, 3) and not participation.unrestricted:
        raise UnacceptableSubmission("Submissions unavailable", "Submissions are not allowed in the current contest phase.")
    return phase


def accept_contest_submission(sql_session, file_cacher, participation, task,
                              timestamp, tornado_files, language_name):
    """Apply the CWS phase and official-bit rules, then its normal workflow.

    timestamp must be the server's request-receipt timestamp, never a browser
    value. Keep the same inclusive deadline/per-user/analysis semantics as CWS.
    """
    from .workflow import accept_submission
    lock_submission_participation(sql_session, participation)
    phase = check_submission_phase(participation, task, timestamp)
    return accept_submission(sql_session, file_cacher, participation, task,
                             timestamp, tornado_files, language_name, phase == 0)
