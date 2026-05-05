# cllg

A simple package for building LLM-friendly, debuggable CLI commands.

Features:
  - Per-command run record.
  - Timestamped local run directory under `logs/`.
  - Command/config/env/host metadata, including git hash and dirty state.
  - Intermediates/artifacts.
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

## Examples

```bash
uv run python examples/basic_session.py
uv run python examples/progress_demo.py
uv run python examples/command_vs_events.py
uv run python examples/json_mode.py --json | uv run python -m json.tool
uv run python examples/git_metadata.py
```
