from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _read_events(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _events_of_type(events: list[dict[str, object]], event_type: str) -> list[dict[str, object]]:
    return [event for event in events if event["type"] == event_type]


def _json_stdout(completed: subprocess.CompletedProcess[str]) -> dict[str, object]:
    payload = json.loads(completed.stdout)
    assert isinstance(payload, dict)
    return payload


def _run_example(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "examples" / args[0]), *args[1:]],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )


def _only_log_dir(tmp_path: Path) -> Path:
    log_dirs = sorted(path for path in (tmp_path / "logs").glob("*/*") if path.is_dir())
    assert len(log_dirs) == 1
    return log_dirs[0]


def test_json_mode_example_prints_json_normally_and_logs_stdout(
    tmp_path: Path,
) -> None:
    completed = _run_example(tmp_path, "json_mode.py", "--json")
    payload = _json_stdout(completed)
    log_dir = _only_log_dir(tmp_path)

    assert completed.stderr == ""
    assert payload["ok"] is True
    assert (log_dir / "stdout.txt").read_text(encoding="utf-8") == completed.stdout
    assert (log_dir / "stderr.txt").read_text(encoding="utf-8") == ""
    assert (log_dir / "command.json").is_file()


def test_human_mode_example_keeps_printing_human_output_and_logs_it(
    tmp_path: Path,
) -> None:
    completed = _run_example(tmp_path, "json_mode.py")
    log_dir = _only_log_dir(tmp_path)

    assert completed.stdout == "ok\n"
    assert completed.stderr == ""
    assert (log_dir / "stdout.txt").read_text(encoding="utf-8") == completed.stdout
    assert (log_dir / "stderr.txt").read_text(encoding="utf-8") == ""


def test_progress_demo_json_mode_keeps_stdout_machine_parseable(
    tmp_path: Path,
) -> None:
    completed = _run_example(
        tmp_path,
        "progress_demo.py",
        "--json",
        "--steps",
        "2",
        "--delay",
        "0",
    )
    payload = _json_stdout(completed)
    log_dir = _only_log_dir(tmp_path)
    events = _read_events(log_dir / "events.jsonl")

    assert completed.stderr == ""
    assert payload["ok"] is True
    assert payload["steps"] == 2
    assert (log_dir / "stdout.txt").read_text(encoding="utf-8") == completed.stdout
    assert len(_events_of_type(events, "progress_advance")) == 2
    assert _events_of_type(events, "progress_start")
    assert _events_of_type(events, "progress_finish")


def test_command_vs_events_example_shows_static_metadata_and_timeline(
    tmp_path: Path,
) -> None:
    completed = _run_example(tmp_path, "command_vs_events.py", "--json")
    payload = _json_stdout(completed)
    log_dir = _only_log_dir(tmp_path)
    command_path = log_dir / str(payload["command"]["file"])
    events_path = log_dir / str(payload["events"]["file"])
    events = _read_events(events_path)

    assert completed.stderr == ""
    assert command_path.is_file()
    assert events_path.is_file()
    assert payload["command"]["command"] == "command_vs_events.py"
    assert payload["events"]["count"] == len(payload["events"]["types"])
    assert {"progress_start", "progress_advance", "progress_finish"} <= set(
        payload["events"]["types"]
    )
    assert _events_of_type(events, "output")
