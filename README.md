# cllg

Opinionated persistent debug logging for Python CLI commands.

`cllg` is meant to wrap otherwise normal CLI code:

```python
from cllg import cllg

with cllg() as log:
    print("normal human output")
    log.event("loaded")
```

That creates a timestamped run directory under `logs/`, writes invocation
metadata, and tees Python-level stdout/stderr into log files without changing
what the command prints.

## What gets logged

- `command.json`: argv, derived command name, cwd, timestamp, Python/platform/host metadata, and git state.
- `events.jsonl`: structured debug timeline events.
- `stdout.txt`: Python-level stdout emitted inside the context.
- `stderr.txt`: Python-level stderr emitted inside the context.

`cllg` captures Python `sys.stdout` and `sys.stderr`. Subprocess output inherited
directly from file descriptors 1 and 2 is out of scope.

## Progress

```python
from cllg import cllg, make_progress

with cllg() as log:
    progress = make_progress(session=log, json_mode=args.json)
    with progress.task("work", total=items) as task:
        for item in work:
            process(item)
            task.update()
```

In JSON mode progress is logged but not painted to the terminal. In non-JSON TTY
mode it uses `alive-progress`.

## Examples

```bash
uv run python examples/basic_session.py
uv run python examples/progress_demo.py
uv run python examples/command_vs_events.py
uv run python examples/json_mode.py --json | uv run python -m json.tool
uv run python examples/git_metadata.py
```
