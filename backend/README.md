# Missus Tom backend

The backend owns filesystem discovery, manifest validation, workstation checks,
project saving, run planning, controlled local execution, cancellation, logs,
and result indexing. Runs use validated project manifests, managed native tools,
and fixed argument arrays; the optional legacy configured human-demo manifest
remains separate from Dashboard synthetic bulk demos. Frontend values are never
interpreted as shell commands.

See the repository root README for setup and development commands.
