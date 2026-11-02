# Contest Management System - http://cms-dev.github.io/
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Safe native presentation of exactly the shared CWS-visible feedback."""
from html.parser import HTMLParser
from cms.grading import format_status_text
from cms.server.contest.submission.feedback import submission_details, submission_status


class _TextOnly(HTMLParser):
    """Render a CMS score plugin's already-filtered details as inert text."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.suppressed = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.suppressed += 1
        elif tag in ("p", "br", "div", "tr", "li", "h1", "h2", "h3", "h4"):
            self.parts.append("\n")
        elif tag in ("td", "th"):
            self.parts.append("\t")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.suppressed:
            self.suppressed -= 1

    def handle_data(self, value):
        if not self.suppressed:
            self.parts.append(value)


def participant_feedback(sql_session, submission, actual_phase, translation):
    data = submission_status(sql_session, submission, actual_phase, translation)
    sr, details = submission_details(submission, actual_phase, translation)
    if details is not None:
        parser = _TextOnly()
        parser.feed(str(details))
        parser.close()
        text = "".join(parser.parts).strip()
        data["detailsText"] = text[:262144]
        data["detailsTruncated"] = len(text) > 262144
    if sr is not None and sr.compiled():
        data["compilation"] = {
            "text": format_status_text(sr.compilation_text, translation=translation),
            "stdout": sr.compilation_stdout[:262144] if sr.compilation_stdout is not None else None,
            "stderr": sr.compilation_stderr[:262144] if sr.compilation_stderr is not None else None,
            "stdoutTruncated": len(sr.compilation_stdout or "") > 262144,
            "stderrTruncated": len(sr.compilation_stderr or "") > 262144,
            "time": sr.compilation_time, "memory": sr.compilation_memory,
        }
    return data
