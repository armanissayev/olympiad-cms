# Public HTTPS Admin access for the authorized staging instance

The viewer was updated on 5 November 2026 to select actual submitted files and grouped editing periods. Use [FILE_HISTORY_ACCEPTANCE](FILE_HISTORY_ACCEPTANCE.md) for the current browser command/evidence; the earlier recording-selector browser command below is historical. HTTPS routing/authentication remain in effect.

Deployed and verified **4 November 2026** on the explicitly authorized disposable instance `i-0ade1f8ddf0b0dad8`. Open **https://54.206.171.67/admin/**, or code history directly at **https://54.206.171.67/admin/contest/1/ide-history**. No SSH tunnel is needed. Sign in with an enabled CMS administrator account; code history requires full CMS Admin permissions. Choose a participant and problem, Load recordings, then choose a recording. Participant credentials and participant cookies do not authorize the panel or history API.

Public browser acceptance passed using normal trusted TLS, the existing disposable Admin/participant fixture, and the previously uploaded real source. The actual source SHA-256 matched `704fa61aae911881a42e2ffb330f44a6e388efb52ed2ba42c07df1f538c8faf5`. Guest and participant denial, native logout and browser-back denial, XSRF rejection, cookie flags, prefixed navigation/static/history requests and timeline controls all passed. There were zero page/server errors and zero history mutations. [Browser results](evidence/public-admin-https/browser-results.json), [screenshot](evidence/public-admin-https/public-admin-code-history.png).

Only the HTTPS ingress was reloaded. All nine service main PIDs and start times stayed unchanged; all remain active and enabled, and `cms-staging-ops` still has three tmux windows. Native Admin remains `127.0.0.1:18889` and private TLS 28444 remains loopback. Public listeners are still only SSH 22 and HTTP/HTTPS 80/443. CMS GET and native IDE readiness return 200; HTTP `/admin/` redirects 308 to HTTPS. The existing trusted certificate covers the public IP, currently expires 9 November 2026 11:57:40 UTC, and the existing renewal timer is active. [Host checks](evidence/public-admin-https/host-final.json).

Initial management access failed twice on TCP22 while public CMS returned 200 and `/admin/login` returned 404. The operator restored SSH access, after which deployment and verification succeeded. The [initial pre-deployment state](evidence/public-admin-https/pre-deployment.json) is retained separately; it is superseded by the successful results, not erased. No account/password, database, DNS, security-group rule or sandbox configuration was changed by the agent.

## Reviewed change

[install_public_admin.py](../../olympiad_ide/tools/linux_staging/install_public_admin.py) adds `/admin/` to the existing trusted public-IP HTTPS server, stripping that prefix before forwarding to the existing loopback Admin listener `127.0.0.1:18889`. It adds a canonical `/admin` redirect, a per-IP login request limit of 10/minute with burst 10, explicit Secure/HttpOnly/SameSite=Strict protection for `awslogin`, no-store response headers and frame denial. Existing trusted forwarding headers and Authorization stripping are inherited unchanged. Native Admin relative URLs preserve the prefix.

The existing root `_xsrf` cookie stays shared with CWS on the same origin. Rewriting every cookie path would introduce duplicate `_xsrf` values; stock nginx cannot selectively scope only `awslogin` by cookie name. The Admin session remains HttpOnly and separately signed from participant authentication. Existing native XSRF checks apply to Admin POSTs.

No new listener, security-group rule, database change or CMS restart is needed. Private Admin port 28444, native/RPC/database listeners, existing CMS process ownership, separate Python environments and sandbox configuration remain unchanged. Only the ingress unit is reloaded. The installer validates the exact known staging layout, owner/mode, private Admin binding and proxy count; makes a root-only backup; validates the candidate as the ingress UID with its existing capabilities; atomically activates; retries trusted-TLS login readiness after asynchronous reload; and restores/reloads the previous configuration on failure. Identical repeat runs validate/reload without overwriting the backup. Different pre-existing Admin locations are refused.

## Reproduce deployment

For future operator access, verify in EC2 Sydney that the security group attached to `i-0ade1f8ddf0b0dad8` permits TCP 22 from the operator computer's current public IP. Use the console's **My IP** option and keep SSH restricted to that address. The previously identified staging security group was `sg-02b8de8487449d935`; verify its current attachment before changing it. Public TCP 80/443 already work and need no change. No production group, DNS or networking change is authorized by this procedure.

From the integration checkout, after reviewing the script:

```sh
ssh -i /Users/isaevarman/Developer/olympiad-ide/olympiad-worker-key.pem \
  -o BatchMode=yes -o ConnectTimeout=15 -o StrictHostKeyChecking=yes \
  -o UserKnownHostsFile=/private/tmp/cms-linux-staging-known-hosts \
  ubuntu@ec2-54-206-171-67.ap-southeast-2.compute.amazonaws.com \
  'sudo systemctl is-active cms-ide-stage-ingress; sudo ss -lntp'

scp -i /Users/isaevarman/Developer/olympiad-ide/olympiad-worker-key.pem \
  -o StrictHostKeyChecking=yes \
  -o UserKnownHostsFile=/private/tmp/cms-linux-staging-known-hosts \
  olympiad_ide/tools/linux_staging/install_public_admin.py \
  ubuntu@ec2-54-206-171-67.ap-southeast-2.compute.amazonaws.com:/opt/cms-ide-stage/incoming/install_public_admin.py

ssh -i /Users/isaevarman/Developer/olympiad-ide/olympiad-worker-key.pem \
  -o BatchMode=yes -o ConnectTimeout=15 -o StrictHostKeyChecking=yes \
  -o UserKnownHostsFile=/private/tmp/cms-linux-staging-known-hosts \
  ubuntu@ec2-54-206-171-67.ap-southeast-2.compute.amazonaws.com \
  'sudo /opt/cms-ide-stage/cms-venv/bin/python /opt/cms-ide-stage/incoming/install_public_admin.py'
```

The installer prints its backup path and status without keys, passwords or cookies. Retain that output as deployment evidence. Verify native listeners remain loopback and all existing staging units remain healthy. Native services remain supervised independently of SSH and tmux.

## Real public-browser acceptance

[verify-public-admin.cjs](../../olympiad_ide/frontend/tools/verify-public-admin.cjs) uses the existing protected disposable fixture and previous successful participant source. It uses normal public TLS verification, with no localhost tunnel, SPKI exception or trust-store change. It performs only native login/logout and read-only history review. Run after successful deployment:

```sh
PLAYWRIGHT_CHROMIUM_PATH=/Users/isaevarman/Library/Caches/ms-playwright/chromium-1155/chrome-mac/Chromium.app/Contents/MacOS/Chromium \
  /Users/isaevarman/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node \
  olympiad_ide/frontend/tools/verify-public-admin.cjs \
  /private/tmp/cms-linux-staging/ui-acceptance.json \
  /private/tmp/cms-linux-staging/public-admin-final \
  /private/tmp/cms-linux-staging/participant-ui-final/results.json
```

Required checks: guest page/API denial; actual participant cookie and credentials denied; full Admin login; Secure/HttpOnly/Strict Admin cookie; missing-XSRF POST denied; prefixed static assets/navigation/forms/history APIs; separate-browser actual participant source/hash replay and timeline; concurrent participant/Admin sessions; native logout and browser-back denial; no history mutations or page/server errors. Inspect/sanitize outputs before retaining evidence. Do not copy the protected credential fixture or cookies into Git.

## Actual commands and outcomes

The exact transfer/activation/browser commands above ran successfully. Host nginx is 1.28.3; the existing CMS Python environment is 3.12.16 and unchanged. Local Node is 24.22.1 and Playwright Chromium is the existing build 1155. Python compilation, JavaScript syntax and independent configuration-render review passed. Render checks include idempotence, unchanged private listeners/debug routes and refusal of unexpected configuration.

First activation validated nginx syntax and created `/etc/cms-ide-stage/before-public-admin-20261104T103513.485084Z/nginx.conf` as the protected rollback copy. [Deployment output](evidence/public-admin-https/deployment.log). An actual second installer run passed nginx validation, reported `changed:false` and created no new backup. Fourteen anonymous loopback-only login requests produced ten 200 and four 429 responses, proving the rate limiter without consuming the operator's public-IP bucket. [Repeat/rate evidence](evidence/public-admin-https/repeat-and-rate.log).

The real browser printed `PUBLIC_ADMIN_HTTPS_PASSED` and passed all ten grouped checks described above. [Browser output](evidence/public-admin-https/browser.log). These tests read a retained uploaded fixture through the new route; they do not rerun judging or change application code. Existing wider load, dependency, backup and production release gates remain in IMPLEMENTATION_STATE.md. No broad suite or load test was needed for this ingress-only change.

To roll back, review the protected backup above, restore it to `/etc/cms-ide-stage/nginx.conf` with owner `cmsingressstage` and mode0600, run nginx validation under the same ingress user/capabilities as the installer, and reload only `cms-ide-stage-ingress`. Do not restore another old staging configuration or restart ResourceService merely to remove this route.
