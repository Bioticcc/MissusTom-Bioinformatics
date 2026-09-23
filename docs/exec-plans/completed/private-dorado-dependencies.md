# Private Dorado dependencies

User requests installer-managed pipeline software only, without falling back to
external/system pipeline libraries. OS utilities, Docker daemon/GPU drivers, and
explicit biological input/reference paths remain separate prerequisites.

Root: archive library repair and private library provisioning. Inventory agent:
read-only upstream archive metadata. Runtime agent: private executable/library
resolution and isolation regression tests. Preserve all current source changes.

Acceptance: known upstream external library links become private links to bundled
or downloaded compatible libraries; unknown escape links remain rejected. Missing
private software reports missing even when system equivalents exist. Extraction
tests, runtime isolation checks, and full app checks pass; clearly distinguish
source verification from large real installation/operator scientific acceptance.

## Delivered and verified

The reviewed upstream archive has eight cuDNN `/etc/alternatives` aliases plus all
eight regular versioned `9.8.0` libraries. Only these exact reviewed aliases are
localized to bundled relative targets. Missing bundled targets and unknown
external links remain errors; no host library target is read/copied. On-disk
private libraries are installed by extracting the downloaded distribution.

Managed tool detection rejects system fallback and escaping executable links.
Candidate checks use the same isolated environment as runtime. Inherited Java,
R/Python/Conda, and loader configuration is removed; private library paths are
supplied. Docker remains an explicit system-daemon prerequisite. Package
isolation is not an OS/filesystem sandbox.

Validation: 152 backend tests, frontend lint/tests/typecheck/build, and ten ONT
tests passed via `scripts/check.sh`. Real retained archive metadata validation
repaired all eight host links with no unsafe links remaining. This check did not
extract/execute Dorado or change the user's failed environment. Archive fixture
tests cover all eight aliases, missing private targets, and unknown external
links; runtime fixtures cover isolation and the retained Docker prerequisite.

Restart the backend before retrying the app's installation button. Full retry
installation and scientific operator acceptance were not performed in this task.
