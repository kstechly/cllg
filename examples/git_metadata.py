from __future__ import annotations

import json
import sys

from cllg import open_log_session


def main() -> int:
    with open_log_session(command="git-metadata", argv=sys.argv) as session:
        command = json.loads((session.path / "command.json").read_text(encoding="utf-8"))
        print(json.dumps(command["git"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
