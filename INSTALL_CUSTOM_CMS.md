# Install this custom CMS + Olympiad IDE

This repository contains the complete custom CMS source, Monaco IDE, isolated Run/debug workers, official CMS submission integration and Admin submitted-file history. It preserves upstream CMS v1.5.1 history and its AGPL licence. Current verification is in [VERIFICATION](docs/olympiad-ide/VERIFICATION.md).

## Get the code and make a deployment bundle

Install Git, Python 3.12 and Node 22 or 24 on your build computer. Clone this repository, check out its installation revision, then run:

```sh
git clone https://github.com/armanissayev/olympiad-cms.git
cd olympiad-cms
python3.12 tools/export_custom_cms.py /absolute/path/to/new/cms-bundle
```

The exporter requires a clean checkout, runs locked `npm ci` and a fresh production IDE build, validates generated asset hashes, and exports only committed source plus generated public assets. The bundle contains `cms-source.tar`, `ide-assets.tar`, `source-commit.txt` and `SHA256SUMS`. Keep the exact commit and checksums with each deployment. Generated dependencies, local databases, credentials and private keys do not belong in Git or the bundle. This is source distribution, not a copy of the current contest database.

On the target Linux host, verify and extract both archives into a new checkout directory:

```sh
sha256sum -c SHA256SUMS
mkdir cms
 tar -xf cms-source.tar -C cms
 tar -xf ide-assets.tar -C cms
```

Then follow the [deployment guide](docs/olympiad-ide/DEPLOYMENT.md) for OS dependencies, separate Python environments, database setup, native CMS services, sandbox workers and HTTPS. The tested baseline is Ubuntu 26.04 x86_64; another distribution requires dependency and kernel/sandbox validation. A source archive alone does not install services.

## Installation requirements

- Keep CMS and IDE Python environments separate. Use `requirements-olympiad-ide.lock` for CMS integration additions and `olympiad_ide/backend/requirements.lock` for the IDE runtime. CMS also needs its native `requirements.txt`.
- Build and **install the native CMS wheel** into its CMS environment. Merely updating the checkout will leave installed Admin routes/templates unchanged. Verify installed module paths outside the checkout.
- Configure a new installation identity, fresh signing keys, database credentials and Admin account on each independent installation. Keep secrets outside the repository. Use [DATA_MIGRATION](docs/olympiad-ide/DATA_MIGRATION.md) only when intentionally moving an existing installation and preserving its identity.
- Let CMS ResourceService own its native children. Keep official judging separate from IDE execution workers. Keep native RPC, database and private runtime ports private behind your HTTPS proxy.
- Run every mandatory real Linux isolate/security prerequisite before reviewing and enabling worker approval. Never replace isolate with unrestricted subprocess execution or copy an approval flag from the old server.
- Enable Admin history only with native CMS Admin authentication/full permissions. Configure your own HTTPS host/certificate; do not reuse this staging IP, certificate or credentials.

The [Linux staging guide](olympiad_ide/tools/linux_staging/README.md) records the tested provisioning commands. Its scripts deliberately target the original disposable instance, accounts, database names and paths; **do not run them blindly on another server**. Review/adapt those values and the deployment configuration for the new host. The integration is verified on staging; universal unattended provisioning and production capacity certification are not claimed.

## Updates and recovery

Record the installed Git revision, build a new bundle, back up both databases and protected configuration, install the matching native wheel and runtime code, then restart affected services through their existing supervisors. Verify login, real sandbox execution, official judging and Admin history on the new server. Source rollback must include the matching installed native package; database migrations require their own reviewed recovery procedure.
