from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from cllg import make_progress, open_log_session


COMMAND_PURPOSE = "one invocation metadata snapshot"
EVENTS_PURPOSE = "append-only timeline of what happened"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Show command.json vs events.jsonl.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--log-root", default="logs")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    with open_log_session(
        command="command-vs-events",
        argv=sys.argv if argv is None else ["command_vs_events.py", *argv],
        log_root=args.log_root,
    ) as session:
        session.event("message", text="command.json already exists")
        progress = make_progress(session=session, json_mode=args.json)
        with progress.task("write timeline", total=1) as task:
            task.update(text="events.jsonl is growing")
        session.write_json_artifact("result.json", {"ok": True})
        payload = _payload(session.path)

    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(f"log_dir: {payload['log_dir']}")
        print(f"command.json: {COMMAND_PURPOSE}")
        print(f"events.jsonl: {EVENTS_PURPOSE}")
        print(f"events: {payload['events']['count']}")
    return 0


def _payload(log_dir: Path) -> dict[str, object]:
    command = json.loads((log_dir / "command.json").read_text(encoding="utf-8"))
    events = [
        json.loads(line)
        for line in (log_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return {
        "log_dir": str(log_dir),
        "command": {
            "file": "command.json",
            "purpose": COMMAND_PURPOSE,
            "command": command["command"],
            "argv": command["argv"],
            "git_present": command["git"]["present"],
        },
        "events": {
            "file": "events.jsonl",
            "purpose": EVENTS_PURPOSE,
            "count": len(events),
            "types": [event["type"] for event in events],
        },
    }


if __name__ == "__main__":
    raise SystemExit(main())
