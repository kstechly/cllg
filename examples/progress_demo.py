from __future__ import annotations

import argparse
import time

import cllg


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Show cllg progress behavior.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--steps", type=_positive_int, default=8)
    parser.add_argument("--delay", type=_non_negative_float, default=0.08)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    with cllg.cllg():
        with cllg.progress("demo work", total=args.steps) as task:
            for index in range(args.steps):
                time.sleep(args.delay)
                task.update(
                    human=f"item {index + 1}/{args.steps}",
                    agent={"item": index + 1, "items": args.steps},
                )
        payload = {"ok": True, "steps": args.steps}
        cllg.print(human=f"processed {args.steps} steps", agent=payload)
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
