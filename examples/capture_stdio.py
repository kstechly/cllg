from __future__ import annotations

import argparse
import json
import sys
from contextlib import nullcontext, redirect_stdout

from cllg import open_log_session


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Show explicit stdout/stderr capture.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--log-root", default="logs")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    with open_log_session(
        command="capture-stdio",
        argv=sys.argv if argv is None else ["capture_stdio.py", *argv],
        log_root=args.log_root,
    ) as session:
        noisy_stdout = redirect_stdout(sys.stderr) if args.json else nullcontext()
        with noisy_stdout, session.capture_stdio():
            print("human/progress chatter")
            print("warnings", file=sys.stderr)

        payload = {"ok": True, "log_dir": str(session.path)}
        session.write_json_artifact("result.json", payload)
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(session.path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
