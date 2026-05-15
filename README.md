# cllg

Opinionated persistent debug logging and structured print replacement for
Python CLI commands to force my LLMs to have logs (thus killing `tail -n 1` issues) and to enforce providing both human friendly from machine readable output at every print and progress bar.

Basically just an opinionated wrapper!

```python
import cllg

with cllg.cllg(json=False):
    cllg.print(human="processed 3 items", agent={"ok": True, "items": 3})
```

`cllg(json=...)` must run inside a git repository. It creates a timestamped run
directory under the repository root's `logs/` directory, writes invocation
metadata, and tees stdout/stderr into log files without changing what the
command prints. Running from a subdirectory still writes to the repo root, not
the process working directory.

Applications own CLI parsing. `cllg` records `sys.argv` as provenance, but it
never reads argv to decide behavior. Pass your parsed JSON-mode flag explicitly
as `cllg.cllg(json=args.json)`.

## What Gets Logged

- `command.json`: argv, cwd, `started_at`, `ended_at`
  (null until the session closes cleanly), exception metadata, Python/platform/
  host metadata, allowlisted environment metadata, and git state.
- `prints.jsonl`: structured records for `cllg.print(...)` calls and for every
  `progress(...)` lifecycle event — `progress_start`, `progress_message`, and
  `progress_advance`.
- `stdout.out`: stdout bytes emitted inside the context.
- `stderr.err`: stderr bytes emitted inside the context.

`cllg` captures at the stdout/stderr file-descriptor level. That includes
`print(...)`, `sys.stdout.write(...)`, `sys.stdout.buffer.write(...)`, Python
logging handlers that write to stdout/stderr, and subprocess output inherited on
file descriptors 1 and 2. Handlers or subprocesses pointed at explicit files,
sockets, pipes, or custom streams are outside the capture boundary.

Nested sessions are allowed. But why are you using them... The outer session log includes inner session
output, because the outer session represents the whole command run; the inner
session log contains its own slice.

`stdout.out` and `stderr.err` preserve output bytes. Invalid UTF-8 bytes are not
rewritten or dropped.

## Structured Print

Use `cllg.print(human=..., agent=...)` where you would otherwise use
`print(...)` for command narration or results that should be useful to both
people and agents.

```python
cllg.print(
    human="epoch 3/10 loss=0.410",
    agent={"event": "epoch", "epoch": 3, "epochs": 10, "loss": 0.410},
)
```

Human mode prints the human string. When the active session was opened with
`json=True`, `cllg.print(...)` prints the agent object as one stable JSON line.
Multiple `cllg.print(...)` calls in JSON mode produce JSONL on stdout.

Inside `cllg(json=...)`, every `cllg.print(...)` call is also appended to
`prints.jsonl` with `kind`, `timestamp`, `human`, and `agent` fields. Deep code
can call `cllg.print(...)` directly; it finds the active session from context,
so you do not need to thread a logger through the call stack.
Calling `cllg.print(...)` without an active session is an error.

`human` must be a string. `agent` must be a JSON-serializable object with string
keys. `cllg` validates before printing, so bad agent payloads fail before
polluting stdout with broken machine output.

## Progress

`progress(...)` uses the active `cllg(json=...)` session, so deep code does not
need a `log` parameter.
Calling `progress(...)` without an active session is an error.

```python
import cllg

with cllg.progress("training", total=epochs) as task:
    for epoch in range(epochs):
        loss = train_epoch(epoch)
        task.update(
            human=f"epoch {epoch + 1}/{epochs} loss={loss:.3f}",
            agent={"epoch": epoch + 1, "epochs": epochs, "loss": loss},
        )
```

In human TTY mode, progress uses `alive-progress`. Progress is always logged to
`prints.jsonl`, regardless of JSON mode: opening a progress context appends
a `kind: "progress_start"` record with `title` and `total`, then each
`task.message(...)` and `task.update(...)` appends a `kind: "progress_message"`
or `kind: "progress_advance"` record carrying the user's `agent` payload plus
`current` / `total` counters (and `advance` on advances). In JSON mode,
progress does not stream to stdout — agents tail `prints.jsonl` for updates.

## Migrating From Print

For a CLI command, start by wrapping the command body:

```python
import cllg


def main() -> int:
    args = parse_args()
    with cllg.cllg(json=args.json):
        run_command()
    return 0
```

That immediately tees normal CLI output into `stdout.out` and `stderr.err` while
preserving normal terminal output. This includes Python text writes, Python
buffer writes, stdout/stderr logging handlers, and subprocess output inherited
on standard file descriptors.

Then replace important prints with `cllg.print(...)`:

```python
# Before
print(f"processed {count} items")

# After
cllg.print(
    human=f"processed {count} items",
    agent={"ok": True, "items": count},
)
```

Raw prints are still captured inside `cllg(json=...)`, so migration can be incremental.
The point of `cllg.print(...)` is keeping human output and machine-readable
JSON output under one validated API.

## Consumer Linting

Consumer projects can use Ruff's `T201` rule to keep raw `print(...)` out of
their app code:

```toml
[tool.ruff.lint]
extend-select = ["T201"]
```

Then run:

```bash
uv run ruff check .
```

`cllg` itself intentionally contains print calls in its internals and tests; the
Ruff rule belongs in consumer repositories.

## Examples

```bash
uv run python examples/basic_session.py
uv run python examples/progress_demo.py
uv run python examples/training_loop.py --json
uv run python examples/command_vs_prints.py
uv run python examples/json_mode.py --json
uv run python examples/git_metadata.py
```
