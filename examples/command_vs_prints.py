from __future__ import annotations

import argparse
import json
from pathlib import Path

import cllg


COMMAND_PURPOSE = "one invocation metadata snapshot"
PRINTS_PURPOSE = "append-only structured cllg.print records"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Show command.json vs prints.jsonl.")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    with cllg.cllg() as log:
        with cllg.progress("write timeline", total=1) as task:
            task.update(
                human="progress marker recorded",
                agent={"event": "progress_marker_recorded"},
            )
        payload = _payload(log.path)
        cllg.print(human=_human_payload(payload), agent=payload)
    return 0


def _payload(log_dir: Path) -> dict[str, object]:
    command = json.loads((log_dir / "command.json").read_text(encoding="utf-8"))
    prints = [
        json.loads(line)
        for line in (log_dir / "prints.jsonl").read_text(encoding="utf-8").splitlines()
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
        "prints": {
            "file": "prints.jsonl",
            "purpose": PRINTS_PURPOSE,
            "count": len(prints),
            "kinds": [record["kind"] for record in prints],
        },
    }


def _human_payload(payload: dict[str, object]) -> str:
    prints = payload["prints"]
    assert isinstance(prints, dict)
    return "\n".join(
        [
            f"command.json: {COMMAND_PURPOSE}",
            f"prints.jsonl: {PRINTS_PURPOSE}",
            f"prints: {prints['count']}",
        ]
    )


if __name__ == "__main__":
    raise SystemExit(main())
