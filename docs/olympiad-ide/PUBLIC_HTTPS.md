# Public HTTPS staging setup — 3 November 2026

**Public HTTPS is verified and available without SSH:**

- ContestWebServer: [https://54.206.171.67/](https://54.206.171.67/)
- IDE: [https://54.206.171.67/ide/](https://54.206.171.67/ide/)

The same staging credentials apply. The public certificate is trusted by normal curl, Node and Chromium validation. No certificate bypass or OS trust modification was used. All 14 real-worker browser checks passed over this public origin, including actual C++/Python judging, Run/Stop, lost-response receipt reconciliation and offline/logout recovery. See [browser results](evidence/public-https/browser-results.json) and [stdout](evidence/public-https/browser-passed.log).

The sections below retain the initial blocked checkpoint and its resolution. Public access was completed after the user saved the requested AWS TCP80/443 ingress rules; external ACME validation then succeeded.

## Diagnosis and completed work

All existing CMS/systemd services were active when inspected. The local SSH control socket/tunnel was gone, so localhost failed even though AWS CMS remained healthy. Restoring the task-owned SSH tunnel returned native readiness200. No CMS process was duplicated under a second launcher.

Created persistent tmux session `cms-staging-ops`, with an operations shell and `cms-logs` window following journal output. Attach through SSH with `tmux attach -t cms-staging-ops`. Existing ResourceService ownership remains intact; all eight task-owned application/database units are now active and enabled at boot. Isolate and the quota mount are enabled too. No reboot test was performed.

Backed up ingress config/runtime env and ingress unit under `/etc/cms-ide-stage/before-public-https`, protected mode0700/0600. Added an HTTP80 listener serving only the public ACME challenge directory and redirecting other requests to HTTPS. Nginx runs as cmsingressstage with only CAP_NET_BIND_SERVICE in its capability bound/ambient set; existing NoNewPrivileges remains. Admin, ranking, CMS RPC, native/CWS backend and DB listeners remain private.

Local ACME connectivity probe returns its expected staging marker. External HTTP80 probes time out even after confirming nginx is listening on0.0.0.0:80; public443 is not yet active. The instance metadata reports no IAM role. No AWS security-group, network ACL or DNS change has been made by this session.

Ubuntu apt advertises Certbot4.0, which predates IP support. The install attempt also encountered an existing apt lock; it was not killed or bypassed. Installed Certbot/acme5.9.0 from PyPI in a dedicated `/opt/cms-ide-stage/acme-venv`, separate from both CMS and IDE environments. This version supports `--ip-address` and short-lived profiles. No certificate issuance request was attempted while external validation remained blocked.

## Required AWS step

In Sydney/ap-southeast-2, allow inbound TCP80 and443 from0.0.0.0/0 for instance `i-0ade1f8ddf0b0dad8`, public IP54.206.171.67. Current security group: `sg-02b8de8487449d935`. If shared with unrelated instances, use a dedicated staging group instead. Keep SSH rules unchanged and do not expose Admin/DB/RPC/private worker ports. The user was asked to save these rules because SSH access alone provides no AWS control-plane permission. If these rules already exist, inspect the staging subnet/network ACL path rather than broadening unrelated resources.

## Prepared activation

Source scripts are `olympiad_ide/tools/linux_staging/{public-prepare.py,public-activate.sh,persist-services.py}`. Preparation is one-shot; do not rerun it over the existing backup. Configuration tests now run through a transient systemd unit using the ingress UID, NoNewPrivileges and only CAP_NET_BIND_SERVICE. The initial root configuration test created a root-owned proxy temporary directory; this interrupted large asset delivery on the first public browser attempt. Corrected ownership and service-account validation fixed the actual error. The initial failed output is retained in evidence/public-https/browser-initial-failure.log.

Once an external client can retrieve `http://54.206.171.67/.well-known/acme-challenge/staging-connectivity`, start in the existing tmux operations shell:

```sh
sudo bash /opt/cms-ide-stage/incoming/public-activate.sh > /tmp/cms-public-activate.log 2>&1
```

This obtains a publicly trusted Let's Encrypt short-lived IP certificate, verifies its IP SAN/remaining validity, copies the certificate/key with restricted ownership, adds public443 proxy routes for CWS/IDE only, adds the public origin to runtime allowlist, and reloads ingress. It prepares a certificate deploy hook and six-hour systemd renewal timer; these are not installed/enabled until successful issuance/activation. Certificate private keys and ACME account state remain outside Git. HTTP80 must remain reachable for HTTP-01 renewal.

Then verify public TLS from outside AWS without insecure flags, CWS login, IDE/Monaco loading and authenticated runtime operations. Verify private Admin/RPC/DB ports stay private and inspect the renewal timer. Reboot and public-origin browser acceptance remain unverified at this checkpoint. Do not announce the public URL as ready until those external checks succeed.

Let's Encrypt documents IP certificates, Certbot5.4+ webroot support, six-day validity and deploy-hook renewal requirements at [its official guide](https://letsencrypt.org/2026/03/11/shorter-certs-certbot/). AWS explains security-group/ACL HTTP/HTTPS reachability at [its connection guide](https://repost.aws/knowledge-center/connect-http-https-ec2).

## Final verified state

External HTTP challenge probe returned the expected fixture marker; HTTP root returned308 to HTTPS. Public HTTPS readiness returned200. Anonymous native context returned401. Private Admin28444, direct CWS18888 and PostgreSQL15432 were unreachable from the external test client. The inspector asserts host public listeners are exactly22/80/443; Admin/ranking/RPC/backend/DB stay private. See [environment](evidence/public-https/environment.json).

Let's Encrypt issuer YE1 issued an IP SAN54.206.171.67 certificate valid until9November2026 11:57:40UTC. The dedicated Certbot5.9 environment is separate from both application interpreters. Certificate/key copies use0644/0600 ownership for cmsingressstage. The six-hour renewal timer is enabled/active. Actual ACME `renew --dry-run` succeeded, and the corrected deploy hook was tested with the active production certificate; an immediate normal renewal service invocation also completed. See [renewal](evidence/public-https/renewal-dry-run.log) and [persistence/certificate](evidence/public-https/persistence-and-certificate.log). HTTP80 is retained for future HTTP-01 validation.

All eight application/database units are active and enabled, with CMS children still owned only by their existing ResourceService supervisors. The persistent tmux operations and cms-logs windows are available. SSH disconnection does not terminate those services; no reboot was performed. No unrelated production resource or DNS was changed. Public IP stability, the two-day fixture contest expiry and the previously documented production release gates remain relevant; a stop/start that changes the instance IP requires updating this endpoint and certificate.
