from __future__ import annotations

import argparse
import json

from cllg import cllg, make_progress


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Show cllg JSON and human output modes.")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    with cllg() as log:
        progress = make_progress(session=log, json_mode=args.json)
        with progress.task("json safe work", total=1) as task:
            task.update(text="done")
        payload = {"ok": True}
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
