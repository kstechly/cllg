from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _read_events(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_progress_demo_json_mode_keeps_stdout_machine_parseable(
    tmp_path: Path,
) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "examples/progress_demo.py",
            "--json",
            "--log-root",
            str(tmp_path / "logs"),
            "--steps",
            "2",
            "--delay",
            "0",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(completed.stdout)
    log_dir = Path(payload["log_dir"])

    assert completed.stderr == ""
    assert payload["ok"] is True
    assert payload["steps"] == 2
    assert log_dir.is_dir()
    assert [event["type"] for event in _read_events(log_dir / "events.jsonl")] == [
        "progress_start",
        "progress_advance",
        "progress_advance",
        "progress_finish",
        "artifact",
    ]


def test_progress_demo_human_mode_prints_log_path(
    tmp_path: Path,
) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "examples/progress_demo.py",
            "--log-root",
            str(tmp_path / "logs"),
            "--steps",
            "1",
            "--delay",
            "0",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    log_dir = Path(completed.stdout.strip())

    assert log_dir.is_dir()
    assert (log_dir / "command.json").is_file()


def test_json_mode_example_json_flag_controls_machine_output(
    tmp_path: Path,
) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "examples/json_mode.py",
            "--json",
            "--log-root",
            str(tmp_path / "logs"),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(completed.stdout)

    assert completed.stderr == ""
    assert payload["ok"] is True
    assert Path(payload["log_dir"]).is_dir()


def test_json_mode_example_defaults_to_human_output(
    tmp_path: Path,
) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "examples/json_mode.py",
            "--log-root",
            str(tmp_path / "logs"),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    log_dir = Path(completed.stdout.strip())

    assert log_dir.is_dir()
    assert (log_dir / "result.json").is_file()
