from __future__ import annotations

import argparse
import json
import time

from cllg import cllg, make_progress


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Show cllg progress behavior.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--steps", type=_positive_int, default=8)
    parser.add_argument("--delay", type=_non_negative_float, default=0.08)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    with cllg() as log:
        progress = make_progress(session=log, json_mode=args.json)
        with progress.task("demo work", total=args.steps) as task:
            for index in range(args.steps):
                time.sleep(args.delay)
                task.update(text=f"item {index + 1}/{args.steps}")
        payload = {"ok": True, "steps": args.steps}
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(f"processed {args.steps} steps")
    return 0


def _positive_int(raw_value: str) -> int:
    value = int(raw_value)
    if value < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return value


def _non_negative_float(raw_value: str) -> float:
    value = float(raw_value)
    if value < 0:
        raise argparse.ArgumentTypeError("must be non-negative")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
