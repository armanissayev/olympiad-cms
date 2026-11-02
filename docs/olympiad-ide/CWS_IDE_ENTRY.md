# Contest-page IDE entry

The authenticated ContestWebServer overview now places a prominent Olympiad IDE box before General information. Its large “Open Olympiad IDE” link uses the same origin at `/ide/`, so public and tunnel access both retain the normal CMS login.

The entry is present only when the optional integration is enabled and CWS serves one explicit matching contest. Feature-disabled CWS, signed-out login and multi-contest views retain their usual flow. Native authentication/phase/task checks still apply after following the link.

The box has a labeled semantic section, keyboard focus indication and scoped responsive layout for narrow viewports. Only the enabled overview gets the mobile layout adjustment; other CMS pages are unchanged.

Actual WSGI/PostgreSQL test command:

```sh
CMS_CONFIG=/private/tmp/cms-regression.conf PYTHONPATH=/Users/isaevarman/Developer/cms /private/tmp/cms-integration-venv/bin/python -m pytest cmstestsuite/unit_tests/server/contest/overview_ide_test.py -q --tb=short -p no:cacheprovider
```

Observed: **4 passed**, 29 existing upstream deprecation warnings in0.97s. The test database is the task-owned `cmsregressionfortesting` on local PostgreSQL14 port55459. These are actual template/handler renderings for enabled, disabled, signed-out and multi-contest conditions. Deployed desktop/mobile visual verification belongs to the combined release acceptance.
