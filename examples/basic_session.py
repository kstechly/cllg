from __future__ import annotations

import sys

from cllg import open_log_session


def main() -> int:
    with open_log_session(command="basic-session", argv=sys.argv) as session:
        session.event("message", text="starting example")
        session.write_json_artifact(
            "run_record.json",
            {"example": "basic_session", "stop_reason": "complete"},
        )
        print(session.path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
