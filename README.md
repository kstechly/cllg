# cllg

Opinionated persistent debug logging and dual-mode output for Python CLI commands.

```python
from cllg import cllg, output

with cllg():
    output(human="processed 3 items", agent={"ok": True, "items": 3})
```

`cllg()` must run inside a git repository. It creates a timestamped run
directory under the repository root's `logs/` directory, writes invocation
metadata, and tees stdout/stderr into log files without changing
what the command prints. Running from a subdirectory still writes to the repo
root, not the process working directory.

## What Gets Logged

- `command.json`: argv, derived command name, cwd, timestamp, Python/platform/host metadata, allowlisted environment metadata, and git state.
- `events.jsonl`: structured debug timeline events.
- `stdout.txt`: stdout bytes emitted inside the context.
- `stderr.txt`: stderr bytes emitted inside the context.

`cllg` captures at the stdout/stderr file-descriptor level. That includes
`print(...)`, `sys.stdout.write(...)`, `sys.stdout.buffer.write(...)`, Python
logging handlers that write to stdout/stderr, and subprocess output inherited on
file descriptors 1 and 2. Handlers or subprocesses pointed at explicit files,
sockets, pipes, or custom streams are outside the capture boundary.

Nested sessions are allowed. The outer session log includes inner session
output, because the outer session represents the whole command run; the inner
session log contains its own slice.

`stdout.txt` and `stderr.txt` preserve output bytes. They are named `.txt`
because normal CLI output is text, but invalid UTF-8 bytes are not rewritten or
dropped.

`command.json` does not dump the full process environment. Its `env` field is
self-describing:

```json
{
  "kind": "allowlist",
  "values": {
    "CUDA_VISIBLE_DEVICES": "0,1",
    "MASTER_ADDR": "127.0.0.1",
    "PATH": "/usr/bin",
    "TORCH_HOME": "/models/torch",
    "WORLD_SIZE": "8"
  }
}
```

The allowlist covers common execution-context variables: `PATH`, `PYTHONPATH`,
virtualenv/conda/uv markers, CUDA/NVIDIA settings, PyTorch cache/debug settings,
NCCL settings, torchrun/distributed rank settings, and common thread-count
settings. Secrets and arbitrary environment variables are intentionally not
logged.

If the current working directory is not inside a git repository, `cllg()` raises
before creating a log directory. That is intentional: logs are repo-local debug
history, and silently writing wherever the shell happens to be is brittle
garbage.

## Output

Use `output(human=..., agent=...)` instead of `print(...)` for command results
that need to be useful to both people and agents.

```python
from cllg import output

output(
    human="epoch 3/10 loss=0.410",
    agent={"event": "epoch", "epoch": 3, "epochs": 10, "loss": 0.410},
)
```

Human mode prints the human string. `--json` mode prints the agent object as
stable JSON. Inside `cllg()`, output calls are also recorded in `events.jsonl`.

`human` must be a string. `agent` must be a JSON-serializable object with string
keys. `cllg` validates before printing, so bad agent payloads fail before
polluting stdout with broken machine output.

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

The important shape is that only the CLI boundary needs `cllg()`. The training
loop can live in normal imported code and still use `progress(...)` directly:

```python
from cllg import cllg, output, progress


def main() -> int:
    with cllg():
        loss = train_model(epochs=10)
        output(
            human=f"training complete loss={loss:.3f}",
            agent={"ok": True, "loss": loss},
        )
    return 0


def train_model(*, epochs: int) -> float:
    loss = 1.0
    with progress("training", total=epochs) as task:
        task.message(
            human="initialized training loop",
            agent={"event": "training_initialized", "epochs": epochs},
        )
        for epoch in range(1, epochs + 1):
            loss = train_epoch(epoch, loss)
            task.update(
                human=f"epoch {epoch}/{epochs} loss={loss:.3f}",
                agent={"event": "epoch", "epoch": epoch, "loss": loss},
            )
    return loss
```

See `examples/training_loop.py` for a runnable version.

In `--json` mode progress is logged but not painted to the terminal. In human
TTY mode it uses `alive-progress`. When `progress(...)` runs inside `cllg()`,
TTY detection uses the original stderr state from before fd-level capture, so
progress bars still paint on a real terminal.

`progress(...)` also works outside `cllg()`. In that case it can still paint
human progress when stderr is a TTY, but it has no active session, so it does
not append progress events to `events.jsonl`.

### Progress API

`progress(title, total=None, stream=None)` returns a context manager. `title`
names the progress task. `total` is the expected number of updates, or `None`
for open-ended work. `stream` defaults to `sys.stderr`.

Inside the context, `task.message(...)` records or displays a status message
without advancing the counter:

```python
task.message(
    human="loaded dataset",
    agent={"event": "dataset_loaded", "rows": 1200},
)
```

`task.update(...)` advances the counter. `advance` defaults to `1`.

```python
task.update(
    human="epoch 3/10 loss=0.410",
    agent={"event": "epoch", "epoch": 3, "epochs": 10, "loss": 0.410},
)
```

Both methods validate `agent` as a JSON-serializable object with string keys.
Use `message(...)` for a checkpoint that does not represent completed work; use
`update(...)` when the task made measurable progress.

### Progress Events

When a progress task runs inside `cllg()`, `events.jsonl` receives these event
types:

- `progress_start`: emitted when the progress context opens.
- `progress_message`: emitted by `task.message(...)`.
- `progress_advance`: emitted by `task.update(...)`.
- `progress_finish`: emitted when the progress context exits.

All progress events include:

- `type`: one of the event types above.
- `timestamp`: ISO-8601 UTC timestamp.
- `text`: the human text for the event.
- `data`: the agent payload, or `{}`.

Progress events also include task counters:

- `current`: current completed count.
- `total`: configured total, or `null`.
- `advance`: only on `progress_advance`, the amount added by that update.

Example `progress_advance` line:

```json
{"advance": 1, "current": 3, "data": {"epoch": 3, "event": "epoch", "loss": 0.41}, "text": "epoch 3/10 loss=0.410", "timestamp": "2026-05-05T14:12:33+00:00", "total": 10, "type": "progress_advance"}
```

## Migrating From Print

For a CLI command, start by wrapping the command body:

```python
from cllg import cllg


def main() -> int:
    with cllg():
        run_command()
    return 0
```

That immediately tees normal CLI output into `stdout.txt` and `stderr.txt` while
preserving normal terminal output. This includes Python text writes, Python
buffer writes, stdout/stderr logging handlers, and subprocess output inherited
on standard file descriptors.

Then replace result-producing prints with `output(...)`:

```python
# Before
print(f"processed {count} items")

# After
output(
    human=f"processed {count} items",
    agent={"ok": True, "items": count},
)
```

Use `progress(...)` for loops and long-running work, including code below the
CLI boundary. Do not pass a `log` object through the call stack just to report
progress.

Raw prints are still captured inside `cllg()`, so migration can be incremental.
The point of `output(...)` is not logging; it is keeping human output and
machine-readable `--json` output under one validated API.

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
uv run python examples/training_loop.py --json | uv run python -m json.tool
uv run python examples/command_vs_events.py
uv run python examples/json_mode.py --json | uv run python -m json.tool
uv run python examples/git_metadata.py
```
