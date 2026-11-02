# SPDX-License-Identifier: AGPL-3.0-or-later
"""Independent PostgreSQL admission client used only by concurrency tests."""
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from cms import config
from cms.db import Session, Participation, Task
from cms.db.filecacher import FileCacher
from cms.server.contest.submission import UnacceptableSubmission
from cms.server.contest.submission.policy import accept_contest_submission
from cms.server.olympiadide.admission import prepare_intent, admit_intent


def main():
    request = json.loads(Path(sys.argv[1]).read_text())
    config.submit_local_copy = False
    config.secret_key = "12" * 16
    session = Session()
    try:
        participation = session.query(Participation).get(request["participationId"])
        task = session.query(Task).get(request["taskId"])
        prepared = prepare_intent(request["body"])
        cacher = FileCacher(path=request["storage"])
        Path(request["ready"]).touch()
        deadline = time.monotonic() + 10
        while not Path(request["start"]).exists():
            if time.monotonic() >= deadline:
                raise RuntimeError("Concurrent test did not release start barrier")
            time.sleep(0.01)
        timestamp = datetime.fromisoformat(request["timestamp"])
        try:
            if request["cws"]:
                submission = accept_contest_submission(session, cacher, participation, task,
                    timestamp, prepared[1], request["body"]["language"])
                session.flush()
                value = [submission.id, True]
            else:
                receipt, created = admit_intent(session, cacher, request["installation"],
                    participation, task, timestamp, prepared)
                value = [receipt.submission_id, created]
            session.commit()
        except UnacceptableSubmission:
            session.rollback()
            value = None
        print(json.dumps(value))
    finally:
        session.close()


if __name__ == "__main__":
    main()
