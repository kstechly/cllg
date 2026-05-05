from __future__ import annotations

import argparse
import json
import sys

from cllg import make_progress, open_log_session


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Show cllg JSON and human output modes.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--log-root", default="logs")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    with open_log_session(
        command="json-mode",
        argv=sys.argv if argv is None else ["json_mode.py", *argv],
        log_root=args.log_root,
    ) as session:
        progress = make_progress(session=session, json_mode=args.json)
        with progress.task("json safe work", total=1) as task:
            task.update(text="done")
        payload = {"ok": True, "log_dir": str(session.path)}
        session.write_json_artifact("result.json", payload)
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(session.path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
