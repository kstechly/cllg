from __future__ import annotations

import argparse

import cllg


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Show cllg JSON and human output modes.")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    with cllg.cllg():
        with cllg.progress("json safe work", total=1) as task:
            task.update(human="done", agent={"done": True})
        payload = {"ok": True}
        cllg.print(human="ok", agent=payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
