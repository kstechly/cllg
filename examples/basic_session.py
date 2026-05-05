from __future__ import annotations

from cllg import cllg


def main() -> int:
    with cllg() as log:
        print("starting example")
        print("complete")
        log.event("message", text="starting example")
        log.event("message", text="completed example")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
