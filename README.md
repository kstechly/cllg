# cllg

A simple package for building LLM-friendly, debuggable CLI commands.

Features:
  - Per-command run record.
  - Timestamped local run directory under logs/.
  - Captured stdout/stderr.
  - Command/config/env/host metadata.
  - Intermediates/artifacts.
  - --json stdout remains machine-readable.
  - All non-JSON stdout has progress/verbose UX.
