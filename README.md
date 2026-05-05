# cllg

Opinionated persistent debug logging and dual-mode output for Python CLI commands.

```python
from cllg import cllg, output

with cllg():
    output(human="processed 3 items", agent={"ok": True, "items": 3})
```

`cllg()` must run inside a git repository. It creates a timestamped run
directory under the repository root's `logs/` directory, writes invocation
metadata, and tees Python-level stdout/stderr into log files without changing
what the command prints. Running from a subdirectory still writes to the repo
root, not the process working directory.

## What Gets Logged

- `command.json`: argv, derived command name, cwd, timestamp, Python/platform/host metadata, and git state.
- `events.jsonl`: structured debug timeline events.
- `stdout.txt`: Python-level stdout emitted inside the context.
- `stderr.txt`: Python-level stderr emitted inside the context.

`cllg` captures Python `sys.stdout` and `sys.stderr`. Subprocess output inherited
directly from file descriptors 1 and 2 is out of scope.

If the current working directory is not inside a git repository, `cllg()` raises
before creating a log directory. That is intentional: logs are repo-local debug
history, and silently writing wherever the shell happens to be is brittle
garbage.

## Output

Use `output(human=..., agent=...)` instead of `print(...)`.

```python
from cllg import output

output(
    human="epoch 3/10 loss=0.410",
    agent={"event": "epoch", "epoch": 3, "epochs": 10, "loss": 0.410},
)
```

Human mode prints the human string. `--json` mode prints the agent object as
stable JSON. Inside `cllg()`, output calls are also recorded in `events.jsonl`.

## Progress

`progress(...)` uses the active `cllg()` session, so deep code does not need a
`log` parameter.

```python
from cllg import progress

with progress("training", total=epochs) as task:
    for epoch in range(epochs):
        loss = train_epoch(epoch)
        task.update(
            human=f"epoch {epoch + 1}/{epochs} loss={loss:.3f}",
            agent={"epoch": epoch + 1, "epochs": epochs, "loss": loss},
        )
```

In `--json` mode progress is logged but not painted to the terminal. In human
TTY mode it uses `alive-progress`.

## Consumer Linting

Consumer projects can use Ruff's `T201` rule to keep raw `print(...)` out of
their app code:

```toml
[tool.ruff.lint]
extend-select = ["T201"]

[tool.ruff.lint.per-file-ignores]
"tests/**/*.py" = ["T201"]
```

Then run:

```bash
uv run ruff check .
```

`cllg` itself intentionally contains print calls in its internals and tests;
the Ruff rule belongs in consumer repositories.

## Examples

```bash
uv run python examples/basic_session.py
uv run python examples/progress_demo.py
uv run python examples/command_vs_events.py
uv run python examples/json_mode.py --json | uv run python -m json.tool
uv run python examples/git_metadata.py
```
