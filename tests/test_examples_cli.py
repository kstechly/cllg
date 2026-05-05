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
    events = _read_events(log_dir / "events.jsonl")
    event_types = [event["type"] for event in events]

    assert event_types.count("progress_advance") == 2
    assert "progress_start" in event_types
    assert "progress_finish" in event_types
    assert "artifact" in event_types


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


def test_command_vs_events_example_shows_static_metadata_and_timeline(
    tmp_path: Path,
) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "examples/command_vs_events.py",
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
    assert payload["command"]["file"] == "command.json"
    assert payload["command"]["purpose"] == "one invocation metadata snapshot"
    assert payload["events"]["file"] == "events.jsonl"
    assert payload["events"]["purpose"] == "append-only timeline of what happened"
    assert payload["events"]["count"] >= 3
    assert Path(payload["log_dir"]).is_dir()


def test_command_vs_events_example_human_output_names_both_files(
    tmp_path: Path,
) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "examples/command_vs_events.py",
            "--log-root",
            str(tmp_path / "logs"),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "command.json: one invocation metadata snapshot" in completed.stdout
    assert "events.jsonl: append-only timeline of what happened" in completed.stdout
