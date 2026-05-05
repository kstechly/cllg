# cllg Development Notes

This project is intentionally opinionated. `cllg` is not a general logging
framework and should not accumulate knobs for every edge case.

## Product Contract

`cllg()` means: open a command run, create repo-local persistent debug logs, tee
Python stdout/stderr, record command metadata, and make human/agent output
boring to consume.

Defaults should be correct by construction:

- Logs are repo-local. Running outside a git repository is an error.
- stdout/stderr teeing is on when `cllg()` is active.
- Python logging that writes to stdout/stderr should be captured by default.
- `output(human=..., agent=...)` is the command-result API.
- `progress(...)` is context-local and usable from deep code without passing a
  log object.
- `--json` affects rendering, not whether logging exists.

Avoid optional escape hatches unless there is a real user problem already seen
in this codebase. `capture_logging=True`, `capture_stdio=True`, and similar
flags are usually design backsliding.

## Capture Semantics

Capture should be fd-level, broad for normal CLI code, and honest about
boundaries. Use Wurlitzer for the fd/pipe/thread machinery instead of
hand-rolling it.

Expected to capture:

- `print(...)` inside `cllg()`.
- `sys.stdout.write(...)` and `sys.stderr.write(...)` inside `cllg()`.
- `sys.stdout.buffer.write(...)` and `sys.stderr.buffer.write(...)` inside
  `cllg()`.
- Python logging handlers that write to stdout/stderr while `cllg()` is active.
- subprocess output inherited on file descriptors 1 and 2.

Not in scope:

- logging handlers pointed at files, sockets, custom streams, or other explicit
  destinations.
- subprocesses explicitly redirected away from inherited stdout/stderr.

Do not replace `sys.stdout` or `sys.stderr` with duck-typed shims. They should
remain normal text streams while `cllg()` is active.

Nested sessions should preserve the command-run mental model: outer logs include
inner output, and inner logs contain the inner slice.

Progress TTY detection must use the original stderr state from before fd-level
capture. Checking `sys.stderr.isatty()` after Wurlitzer has redirected fd 2 sees
the capture pipe and silently kills terminal progress.

## Environment Metadata

`command.json["env"]` is allowlisted metadata, not a full environment dump.
Never dump arbitrary `os.environ`; that leaks secrets and turns logs into a
security footgun.

The env shape should stay self-describing:

```json
{
  "kind": "allowlist",
  "values": {}
}
```

Adding more env vars is fine when they are execution-context variables, such as
CUDA, PyTorch, torchrun/distributed, venv/uv, or thread-count settings. Do not
add token, credential, key, secret, password, or auth variables.

## Tests

Test behavior and stable contracts. Do not test garbage.

Good tests:

- Run an example CLI and parse its stdout as JSON.
- Assert stdout/stderr files contain the user-visible output.
- Assert `events.jsonl` contains the expected event types and payloads.
- Assert command metadata captures the repo root, dirty state, and allowlisted
  env values.
- Assert resource cleanup after exceptions.

Bad tests:

- Exact implementation call sequences unless the budget itself is the contract.
- Tests that assert a known hole exists instead of fixing or documenting it.
- Exact prose/docs assertions.
- Brittle string snapshots when the behavior is structured data.

Performance-sensitive tests should assert a budget or observable product
constraint, not a specific private implementation sequence.

## Documentation

Docs should explain how a CLI script changes when adopting `cllg`:

- Wrap the CLI boundary with `with cllg():`.
- Leave ordinary deep code mostly ordinary.
- Use `output(...)` for command results.
- Use `progress(...)` for loops and long-running work.
- Rely on capture for incidental stdout/stderr during migration.

Do not describe unrelated Python patterns as if they are `cllg` features.
