# Administrator-only code history

The private CMS Admin contest sidebar now has **Code history**. On the authorized staging installation this is `https://localhost:28444/contest/1/ide-history`, through the existing private Admin SSH tunnel. Public participant CMS/IDE access does not expose Admin. Log in with an enabled full-permission CMS administrator account, choose a participant and problem, then Load recordings and choose a recording.

The viewer reads uploaded server recordings, so the administrator does not need the participant's browser profile. It provides a timeline, previous/next event, Play/Pause,0.5/1/2/4/8× speed, source-file selection and read-only source. Empty lists mean no retained uploaded recording exists for that identity/problem. Browser-only or expired recordings cannot be recovered here. The existing retention maintenance remains responsible for deleting expired storage; review filters expired records without deleting them.

## Authorization boundary

The page and every data request use the real CMS Admin cookie and `permission_all`, check the current contest's Participation and Task, and only then sign the private request. The runtime uses a separate `olympiad-ide-admin-history` audience, `admin-history` scope and30-second one-use assertion with administrator ID, exact target installation/participant/contest/task, method/path/query/body hashes and nonce. Forged browser role headers and ordinary participant assertions never authorize this namespace. No administrator role is accepted from client payloads or promoted into participant identity mappings.

The read-only runtime namespace exposes only list and replay GETs. Native transport accepts only the configured loopback HTTP runtime, disables environment proxies and redirects, uses four independent slots, existing request/response bounds and a non-symlink private signing key. No browser receives the assertion/key or direct database access. Admin sessions are not created as development/participant owners. Existing principals/workspace bindings are checked, not adopted by username.

CMS participant GETs for telemetry event/checkpoint history return403; writer POSTs and minimal status/acknowledgement/retry endpoints remain available. Standalone development own-history behavior is retained. Participant History/recording diagnostic UI is separately removed by the participant interface update. The browser profile owner still controls their own source/buffers; UI removal does not make client-side recording buffers cryptographically inaccessible to that owner.

## Reconstruction and integrity

Each seek starts at a retained checkpoint whose tree, content and hash agree. Sequence-count checks detect missing stored events without loading dense cursor/key streams. At most5000source/navigation events are loaded per reconstruction segment; excess work returns an explicit notice and the verified checkpoint, rather than inventing a target state. Corrupt checkpoints/events and known missing prefixes are disclosed. A later independent verified checkpoint can show that checkpoint's recorded state while the gap remains disclosed. Gaps clear inferred active-file identity until new recorded navigation. A corrupt later event cannot cause partial nodes to be mislabeled as an earlier checkpoint.

Historical source is assigned through textarea.value/textContent, never injected as HTML or executed. Recording data is not edited by review. Hashes check consistency, not authorship or resistance to a malicious database administrator/browser.

## Verification

Eight focused real-PostgreSQL runtime tests cover administrator versus participant/development authorization, signed target separation, request binding/replay/expiry, CMS participant history denial, server-only cross-browser reconstruction, nearest checkpoints, gaps/corruption, active-file uncertainty and expired-read exclusion without deletion. Five native CMS WSGI/PostgreSQL tests cover actual admin cookies, enabled/full permission, selectors/read-only rendering, contest membership, separate signing audience and private bounded transport. These are included in full-suite totals and do not by themselves prove the deployed browser UI.

Commands (from their indicated source roots):

```sh
# olympiad_ide/backend; isolated schemas in the task-owned local PostgreSQL database
TEST_DATABASE_URL=postgresql+psycopg://isaevarman@127.0.0.1:55459/ideruntime /private/tmp/olympiad-runtime-venv/bin/python -m pytest tests/test_admin_history.py -vv -p no:cacheprovider
# CMS checkout; separate CMS test database
CMS_CONFIG=/private/tmp/cms-regression.conf /private/tmp/cms-integration-venv/bin/python -m pytest cmstestsuite/unit_tests/server/olympiadide/admin_history_test.py -vv -p no:cacheprovider
# Run only after a separate authorized participant acceptance has uploaded its fixture source.
node olympiad_ide/frontend/tools/verify-admin-history.cjs /private/tmp/cms-linux-staging/ui-acceptance.json /private/tmp/cms-linux-staging/admin-history-final /private/tmp/cms-linux-staging/participant-ui-final/results.json
```

The browser tool is limited to the exact authorized fixture and private localhost ports. It pins only the existing localhost certificate public key for private Admin/CWS; it does not disable public TLS validation. It verifies guest and real participant-cookie denial, an actual admin reading the fresh participant's uploaded source/hash in a separate browser, timeline/Play/Pause, read-only source and no history mutation requests. Deployed results are recorded separately by the owning staging acceptance report; an unexecuted script is not claimed as a pass.
