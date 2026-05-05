from __future__ import annotations

import argparse
import json
from pathlib import Path

from cllg import cllg, output, progress


COMMAND_PURPOSE = "one invocation metadata snapshot"
EVENTS_PURPOSE = "append-only timeline of what happened"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Show command.json vs events.jsonl.")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    with cllg() as log:
        log.event("message", text="command.json already exists")
        with progress("write timeline", total=1) as task:
            task.update(
                human="events.jsonl is growing",
                agent={"event": "events_jsonl_growing"},
            )
        payload = _payload(log.path)
        output(human=_human_payload(payload), agent=payload)
    return 0


def _payload(log_dir: Path) -> dict[str, object]:
    command = json.loads((log_dir / "command.json").read_text(encoding="utf-8"))
    events = [
        json.loads(line)
        for line in (log_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return {
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


def _human_payload(payload: dict[str, object]) -> str:
    events = payload["events"]
    assert isinstance(events, dict)
    return "\n".join(
        [
            f"command.json: {COMMAND_PURPOSE}",
            f"events.jsonl: {EVENTS_PURPOSE}",
            f"events: {events['count']}",
        ]
    )


if __name__ == "__main__":
    raise SystemExit(main())
