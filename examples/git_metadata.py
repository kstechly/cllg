from __future__ import annotations

import json

import cllg


def main() -> int:
    with cllg.cllg() as session:
        command = json.loads((session.path / "command.json").read_text(encoding="utf-8"))
        cllg.print(human=json.dumps(command["git"], indent=2, sort_keys=True), agent=command["git"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
