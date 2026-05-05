# cllg

A simple package for building LLM-friendly, debuggable CLI commands.

Features:
  - Per-command run record.
  - Timestamped local run directory under `logs/`.
  - Command/config/env/host metadata, including git hash and dirty state.
  - Intermediates/artifacts.
  - Explicit Python-level stdout/stderr capture to `stdout.txt` and `stderr.txt`.
  - `--json` stdout remains machine-readable.
  - Non-JSON TTY runs get `alive-progress` terminal progress.

## Usage

```python
import sys

from cllg import make_progress, open_log_session

with open_log_session(command="smoke", argv=sys.argv) as session:
    progress = make_progress(session=session, json_mode=args.json)

    with progress.task("smoke fixed limerick", total=args.replication_count) as task:
        task.update(text="replication complete")

    session.write_json_artifact("run_record.json", payload)
```

For noisy Python output, keep capture explicit:

```python
import json
import sys
from contextlib import nullcontext, redirect_stdout

noisy_stdout = redirect_stdout(sys.stderr) if args.json else nullcontext()
with noisy_stdout, session.capture_stdio():
    print("human/progress chatter")
    print("warnings", file=sys.stderr)

print(json.dumps(payload, sort_keys=True))
```

This captures Python-level writes to `sys.stdout` and `sys.stderr`. Subprocess
output inherited directly from file descriptors 1 and 2 is out of scope; capture
that explicitly and write artifacts/events when you need it.

## Examples

```bash
uv run python examples/basic_session.py
uv run python examples/progress_demo.py
uv run python examples/command_vs_events.py
uv run python examples/json_mode.py --json | uv run python -m json.tool
uv run python examples/capture_stdio.py --json | uv run python -m json.tool
uv run python examples/git_metadata.py
```
