# Source, wheel and clean installation verification

Recorded 2 November 2026 on macOS arm64/Python3.12.6/Node24.19.0. The source repository is complete; there are no runtime imports/symlinks pointing to the original IDE. All124 original source hashes and sizes were independently rechecked unchanged. Original-source paths appear only in provenance/historical documentation.

The opt-in frontend build uses the committed lockfile and stages13 public assets with SHA256 in a generated manifest. Ordinary CMS installation does not invoke Node. The upstream global build ignore is explicitly overridden for the frontend build-plugin source/tests; generated build output, dependencies, keys and environment state remain ignored. MANIFEST.in includes frontend source/lock/build plugins, supported Node marker, browser verifier, private backend/worker sources, load guide, deployment templates and the asset manifest needed to rebuild an extracted sdist.

## Executed build/install checks

```
# From the CMS checkout, with Node24 on PATH and a prior successful npm ci
python3 tools/build_olympiad_ide.py --skip-install
/private/tmp/cms-integration-venv/bin/python -m pip wheel --no-deps --no-build-isolation --wheel-dir /private/tmp/cms-native-release .
/opt/homebrew/bin/python3.12 -m venv /private/tmp/cms-native-clean-venv
/private/tmp/cms-native-clean-venv/bin/python -m pip install --no-input -r /Users/isaevarman/Developer/cms/requirements-olympiad-ide.lock
/private/tmp/cms-native-clean-venv/bin/python -m pip install --no-deps /private/tmp/cms-native-release/cms-1.5.1-py3-none-any.whl
/private/tmp/cms-native-clean-venv/bin/python -m pip check
```

Clean dependency and wheel installation passed. Both original CMS/runtime environments also pass pip check. Launcher --help passed outside the checkout with no source PYTHONPATH, importing the installed native service. Explicit-contest launch validation rejects missing -c and ALL with exit1; missing contest no longer invokes interactive selection. CMS's shared parser retains its generic option help, while the native description and actual validation state the narrower contract.

The actual database-fault smoke used clean installed launcher/service code and assets with PYTHONPATH unset, two native shards, real CWS/TLS and independent fresh runtime/database fixtures. See DATABASE_FAULTS.md. The final launcher-only missing-contest change was then rebuilt/reinstalled and separately checked; it does not change the explicit-contest fault-test path.

A Python ZIP inspection compares every installed public asset byte hash with the build manifest, compares native server/gateway/receipt/updater source bytes, verifies both installed launchers, and rejects dependency directories, environment files, private-key files and compiled Python caches. Source archive inspection additionally verifies every SOURCE_IMPORT target and required new build/test/deployment source, no dependency/state/secret entries, and the rebuild manifest. Final hashes and inspection results are saved in /private/tmp/cms-native-release/SHA256SUMS and package-check.json; these are generated artifacts, not committed credentials.

The CMS wheel installs the native CMS components/assets. Separate runtime/worker/frontend sources are distributed in the repository and source archive for their own environment/install workflow; a CMS worker does not acquire FastAPI/Node dependencies. Production Linux/systemd/nginx installation, helper/toolchain privileges and actual judging remain separate release gates.

Final inspection passed:13 exact public asset hashes,124/124 imported source targets and15 additional required source paths; no forbidden entries or symlinks. Wheel scripts normalize their shebang as required by the Python wheel format; their remaining source matches exactly. Final wheel SHA256: 43564de3883c52842f1700fa162a6be02f9414edeaf293d038b9c796f2a813ba (2,628,732 bytes). The final source archive includes this evidence note; its SHA256 is recorded alongside the generated artifacts, avoiding a self-referential archive hash.
