# cllg Development Notes

`cllg` is intentionally opinionated. It is a tiny CLI logging/output contract,
not a general logging framework, and it should not collect knobs for imagined
edge cases.

## Product Contract

`cllg()` opens one command run. While active it:

- creates repo-local persistent debug logs;
- tees stdout/stderr without stopping normal printing;
- records command metadata and structured timeline events;
- makes human/agent command output boring to consume.

Correct defaults are the product. Running outside a git repository is an error.
stdout/stderr capture is on when `cllg()` is active. `--json` changes rendering,
not whether logging exists. `progress(...)` and `output(...)` find the active
session from context, so deep code does not need a `log` parameter.

Avoid flags like `capture_stdio=True`, `capture_logging=True`, or
`use_context_progress=True`. Those are usually design backsliding unless a real
user problem in this codebase proves otherwise.

## Capture

Capture is fd-level and should cover normal CLI behavior:

- `print(...)`, `sys.stdout.write(...)`, and `sys.stderr.write(...)`;
- `sys.stdout.buffer.write(...)` and `sys.stderr.buffer.write(...)`;
- Python logging handlers that write to stdout/stderr;
- subprocess output inherited on file descriptors 1 and 2.

Use Wurlitzer for the fd/pipe/thread machinery. Do not replace `sys.stdout` or
`sys.stderr` with duck-typed shims; that slop breaks code that expects real text
streams.

Out of scope: logging handlers pointed at files, sockets, custom streams, or
other explicit destinations; subprocesses explicitly redirected away from
inherited stdout/stderr.

Nested sessions preserve the command-run model: the outer log includes inner
output, and the inner log contains only its own slice.

Progress TTY detection must use stderr's state from before fd-level capture.
Checking `sys.stderr.isatty()` after Wurlitzer redirects fd 2 sees the capture
pipe and silently kills terminal progress.

## Environment Metadata

`command.json["env"]` is allowlisted metadata, not a full environment dump.
Never dump arbitrary `os.environ`; that leaks secrets and turns logs into a
security footgun.

The env shape is self-describing:

```json
{
  "kind": "allowlist",
  "values": {}
}
```

Allowed env vars should describe execution context: venv/uv, CUDA/NVIDIA,
PyTorch, torchrun/distributed, NCCL, and thread-count settings. Do not add
token, credential, key, secret, password, or auth variables.

## Tests

Test behavior and stable contracts. Delete brittle garbage.

Good tests run example CLIs, parse JSON stdout, assert `stdout.out` and
`stderr.err` match user-visible output, inspect structured events, and verify
command metadata such as repo root, dirty state, and allowlisted env values.

Bad tests assert private class names, exact prose/docs snapshots, fake known
holes, or implementation call sequences unless the budget itself is the public
contract.

## Documentation

Docs should explain the CLI migration:

- wrap the CLI boundary with `with cllg():`;
- leave ordinary deep code mostly ordinary;
- use `output(...)` for command results;
- use `progress(...)` for loops and long-running work;
- rely on capture for incidental stdout/stderr during migration.

Do not describe unrelated Python patterns as if they are `cllg` features.
