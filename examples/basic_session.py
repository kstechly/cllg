from __future__ import annotations

from cllg import cllg, output


def main() -> int:
    with cllg() as log:
        output(human="starting example", agent={"event": "starting"})
        output(human="complete", agent={"event": "complete", "ok": True})
        log.event("message", text="starting example")
        log.event("message", text="completed example")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
