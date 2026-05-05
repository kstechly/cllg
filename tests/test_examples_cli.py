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


def _json_stdout(completed: subprocess.CompletedProcess[str]) -> dict[str, object]:
    payload = json.loads(completed.stdout)
    assert isinstance(payload, dict)
    return payload


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

    payload = _json_stdout(completed)
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

    payload = _json_stdout(completed)

    assert completed.stderr == ""
    assert payload["ok"] is True
    log_dir = Path(payload["log_dir"])
    assert log_dir.is_dir()
    assert (log_dir / "result.json").is_file()


def test_capture_stdio_example_captures_chatter_and_keeps_json_clean(
    tmp_path: Path,
) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "examples/capture_stdio.py",
            "--json",
            "--log-root",
            str(tmp_path / "logs"),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = _json_stdout(completed)
    log_dir = Path(payload["log_dir"])
    captured_stdout = (log_dir / "stdout.txt").read_text(encoding="utf-8")
    captured_stderr = (log_dir / "stderr.txt").read_text(encoding="utf-8")

    assert payload["ok"] is True
    assert log_dir.is_dir()
    assert captured_stdout
    assert captured_stderr
    assert captured_stdout not in completed.stdout
    assert completed.stderr == captured_stdout + captured_stderr
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

    payload = _json_stdout(completed)
    log_dir = Path(payload["log_dir"])
    command_path = log_dir / str(payload["command"]["file"])
    events_path = log_dir / str(payload["events"]["file"])
    events = _read_events(events_path)

    assert completed.stderr == ""
    assert log_dir.is_dir()
    assert command_path.is_file()
    assert events_path.is_file()
    assert payload["command"]["command"] == "command-vs-events"
    assert payload["events"]["count"] == len(events)
    assert {"progress_start", "progress_advance", "progress_finish", "artifact"} <= set(
        payload["events"]["types"]
    )
