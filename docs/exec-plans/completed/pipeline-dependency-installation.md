# Pipeline dependency installation

Add extensible per-pipeline dependency catalogs, readiness checks, and explicit
asynchronous installation from the app. Managed environments are isolated in
the application's state directory; system installations remain usable.

Owners: backend service/API and tests; reusable desktop dependency card; root
runtime resolution, security review, documentation, and final verification.

Scope: automated Linux x86_64 package environments and bulk workflow images;
Docker daemon/driver installation and reference data remain operator-managed.
Package downloads need consent, fixed trusted sources and fixed argv. Analysis
keeps its local-only execution boundary and original scientific gates.

Acceptance: cards available before project setup and later; package/job errors
visible; native runs find managed tools/R; bulk runs find managed Java/Nextflow;
mocked installer/API tests and full application checks pass. No restricted data
or large real installation is needed for routine verification.

## Delivered

Catalog-driven package/tool requirements, readiness probes, explicit-consent API,
persisted background jobs/private streamed logs, shared analysis/install admission
lock, and isolated runtime resolution are implemented. Desktop dependency cards
are available on the dashboard, selected pipeline wizard, and run plan. Install
success refreshes run availability; pipeline changes/unmounts discard stale UI
requests. Startup commands and app source prerequisites are unchanged.

Conda prefixes retain their permanent generation paths. Candidate environments
are checked before an atomic active-pointer switch; failed candidates do not
replace the working environment. Full Dorado distributions and contained library
links are retained. Bootstrap archive and executable hashes are independently
verified against the pinned official release. State writes reject symlink targets
and use private file permissions. Docker Engine and reference inputs are manual.

## Verification and remaining release work

`scripts/check.sh` passed: 146 backend tests, frontend lint/tests/typecheck/build,
and ten ONT workflow tests. Installer/API fixtures cover consent, unavailable
dependencies, restart recovery, admission contention, private logs, unsafe paths,
library preservation, failed-prefix activation, bootstrap integrity, and silent
command timeout cleanup. A real temporary Micromamba bootstrap downloaded,
verified, and ran version 2.3.2. Official Dorado endpoint availability was checked
without downloading its multi-gigabyte archive.

No full pipeline dependency installation or biological analysis was run. Linux
x86_64 automated installation is the initial scope; full platform environment
locks, offline/prebundled distributions, installer cancellation/uninstall/old
generation cleanup, and scientific operator acceptance remain separate work.
