# SPDX-License-Identifier: AGPL-3.0-or-later

"""Participant-visible contest bootstrap; no judge assets or secrets."""
from urllib.parse import quote

from cms import config
from cms.grading.languagemanager import LANGUAGES
from cms.grading.tasktypes import get_task_type
from .base import IDEAPIHandler


def timestamp(value):
    return value.isoformat() + "Z" if value is not None else None


def cws_path(*parts):
    base = config.olympiad_ide_cws_base_path.rstrip("/")
    return base + "/" + "/".join(quote(str(part), safe="") for part in parts)


class ContextHandler(IDEAPIHandler):
    requires_principal = False

    def get(self):
        from .admission import task_capability
        participation = self.current_user
        tasks = []
        visible = self.r_params["actual_phase"] in (0, 3) or participation.unrestricted
        if visible:
            available = {language.name: language for language in LANGUAGES}
            for task in self.contest.tasks:
                supported, reason = task_capability(task)
                dataset = task.active_dataset
                commands = get_task_type(dataset.task_type, dataset.task_type_parameters).get_compilation_commands(task.submission_format) if supported else {}
                languages = [{"id": name, "name": name, "extension": available[name].source_extension,
                              "extensions": available[name].source_extensions}
                             for name in self.contest.languages if name in available and name in (commands or {})]
                parameters = dataset.task_type_parameters if dataset else None
                custom_supported = bool(supported and parameters and parameters[1] == ["", ""])
                tasks.append({
                    "id": task.id, "name": task.name, "title": task.title,
                    "languages": languages, "submissionFormat": list(task.submission_format),
                    "supported": supported, "reason": reason,
                    "customRunSupported": custom_supported,
                    "customRunReason": None if custom_supported else "Use the normal CMS workflow for this task's I/O or grader mode.",
                    "statementUrl": cws_path("tasks", task.name, "description"),
                    "submissionsUrl": cws_path("tasks", task.name, "submissions"),
                    "statements": [{"language": language, "url": cws_path("tasks", task.name, "statements", language)} for language in sorted(task.statements)],
                    "attachments": [{"name": name, "url": cws_path("tasks", task.name, "attachments", name)} for name in sorted(task.attachments)],
                })
        csrf = self.xsrf_token
        self.write_json({
            "schemaVersion": 1, "identity": self.ide_identity,
            "user": {"username": participation.user.username, "firstName": participation.user.first_name, "lastName": participation.user.last_name},
            "contest": {"id": self.contest.id, "name": self.contest.name, "description": self.contest.description},
            "executionProfileMap": {profile: {
                "cmsLanguage": language, "enabled": language in self.contest.languages,
                "versionVerification": "unverified",
                "reason": "Official language is not enabled in this contest." if language not in self.contest.languages else "CMS toolchain versions must be verified on the judging hosts; custom-run versions are independent.",
            } for profile, language in (("cpp17", "C++17 / g++"), ("cpp20", "C++20 / g++"),
                                        ("python3", "Python 3 / CPython"), ("java17", "Java / JDK"))},
            "actualPhase": self.r_params["actual_phase"], "serverTime": timestamp(self.timestamp),
            "phaseEnd": timestamp(self.r_params["current_phase_end"]), "tasks": tasks,
            "csrfToken": csrf.decode("ascii") if isinstance(csrf, bytes) else csrf,
            "links": {"login": cws_path(), "logout": cws_path("logout"), "fallback": cws_path(),
                      "announcements": cws_path("communication"), "clarifications": cws_path("communication")},
        })
