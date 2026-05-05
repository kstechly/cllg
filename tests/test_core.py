from __future__ import annotations

import io
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from cllg import make_progress, open_log_session


class FakeTty(io.StringIO):
    def isatty(self) -> bool:
        return True


def _fixed_clock() -> datetime:
    return datetime(2026, 5, 5, 14, 12, 33, tzinfo=timezone.utc)


def _read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_events(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def _init_git_repo(repo: Path) -> None:
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "cllg@example.invalid")
    _git(repo, "config", "user.name", "cllg tests")
    (repo / "tracked.txt").write_text("clean\n", encoding="utf-8")
    _git(repo, "add", "tracked.txt")
    _git(repo, "commit", "-m", "initial")


def test_session_creates_dated_run_directory_and_command_metadata(tmp_path: Path) -> None:
    with open_log_session(
        command="smoke",
        argv=["smoke", "fixed"],
        log_root=tmp_path / "logs",
        cwd=tmp_path,
        clock=_fixed_clock,
    ) as session:
        assert session.path == tmp_path / "logs" / "2026-05-05" / "141233-smoke"

    command = _read_json(session.path / "command.json")

    assert command["command"] == "smoke"
    assert command["argv"] == ["smoke", "fixed"]
    assert command["cwd"] == str(tmp_path)
    assert command["git"]["commit"] is None
    assert command["git"]["dirty"] is False


def test_session_records_git_commit_and_dirty_state(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)
    (repo / "tracked.txt").write_text("dirty\n", encoding="utf-8")

    with open_log_session(
        command="game",
        argv=["game"],
        log_root=tmp_path / "logs",
        cwd=repo,
        clock=_fixed_clock,
    ) as session:
        pass

    command = _read_json(session.path / "command.json")
    git = command["git"]

    assert isinstance(git["commit"], str)
    assert len(git["commit"]) == 40
    assert git["short_commit"] == git["commit"][:8]
    assert git["branch"] == "main"
    assert git["dirty"] is True
    assert git["status_short"]


def test_session_writes_json_artifacts_and_jsonl_events(tmp_path: Path) -> None:
    with open_log_session(
        command="smoke",
        argv=["smoke"],
        log_root=tmp_path / "logs",
        cwd=tmp_path,
        clock=_fixed_clock,
    ) as session:
        session.event("message", text="starting", data={"replication": 0})
        session.write_json_artifact("run_record.json", {"stop_reason": "step_limit"})

    assert _read_json(session.path / "run_record.json") == {"stop_reason": "step_limit"}
    events = _read_events(session.path / "events.jsonl")
    assert events[0]["type"] == "message"
    assert events[0]["text"] == "starting"
    assert events[0]["data"] == {"replication": 0}


def test_progress_events_are_logged_without_terminal_output_in_json_mode(
    tmp_path: Path,
) -> None:
    stream = FakeTty()
    with open_log_session(
        command="smoke",
        argv=["smoke"],
        log_root=tmp_path / "logs",
        cwd=tmp_path,
        clock=_fixed_clock,
    ) as session:
        progress = make_progress(session=session, json_mode=True, stream=stream)
        with progress.task("smoke fixed limerick", total=2) as task:
            task.message("loaded")
            task.update(text="replication 1")
            task.update(text="replication 2")

    assert stream.getvalue() == ""
    events = _read_events(session.path / "events.jsonl")
    assert [event["type"] for event in events] == [
        "progress_start",
        "progress_message",
        "progress_advance",
        "progress_advance",
        "progress_finish",
    ]
    assert events[0]["total"] == 2
    assert events[-1]["current"] == 2


def test_non_tty_progress_falls_back_to_logged_events_only(tmp_path: Path) -> None:
    stream = io.StringIO()
    with open_log_session(
        command="batch",
        argv=["batch"],
        log_root=tmp_path / "logs",
        cwd=tmp_path,
        clock=_fixed_clock,
    ) as session:
        progress = make_progress(session=session, json_mode=False, stream=stream)
        with progress.task("batch", total=1) as task:
            task.update(text="done")

    assert stream.getvalue() == ""
    events = _read_events(session.path / "events.jsonl")
    assert [event["type"] for event in events] == [
        "progress_start",
        "progress_advance",
        "progress_finish",
    ]
