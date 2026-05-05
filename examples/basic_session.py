from __future__ import annotations

import cllg


def main() -> int:
    with cllg.cllg():
        cllg.print(human="starting example", agent={"event": "starting"})
        cllg.print(human="complete", agent={"event": "complete", "ok": True})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
