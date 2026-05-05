from __future__ import annotations

import json

from cllg import cllg, output


def main() -> int:
    with cllg() as session:
        command = json.loads((session.path / "command.json").read_text(encoding="utf-8"))
        output(human=json.dumps(command["git"], indent=2, sort_keys=True), agent=command["git"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
