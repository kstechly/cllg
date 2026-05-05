from __future__ import annotations

import io
import json
import logging
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from cllg import cllg, make_progress


class FakeTty(io.StringIO):
    def isatty(self) -> bool:
        return True


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


def _fixed_clock() -> datetime:
    return datetime(2026, 5, 5, 14, 12, 33, tzinfo=timezone.utc)


def test_cllg_creates_run_directory_and_command_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["/usr/local/bin/smoke", "fixed", "--json"])
    monkeypatch.setattr("cllg.core._utc_now", _fixed_clock)

    with cllg() as session:
        assert session.path.is_dir()
        assert session.path.parent == tmp_path / "logs" / "2026-05-05"
        assert session.path.name.startswith("141233-smoke")

    command = _read_json(session.path / "command.json")

    assert command["command"] == "smoke"
    assert command["argv"] == ["/usr/local/bin/smoke", "fixed", "--json"]
    assert command["cwd"] == str(tmp_path)
    assert command["git"] == {"present": False}
    assert (session.path / "events.jsonl").is_file()
    assert (session.path / "stdout.txt").is_file()
    assert (session.path / "stderr.txt").is_file()


def test_cllg_records_git_commit_and_dirty_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)
    (repo / "tracked.txt").write_text("dirty\n", encoding="utf-8")
    monkeypatch.chdir(repo)
    monkeypatch.setattr(sys, "argv", ["game"])

    with cllg() as session:
        pass

    command = _read_json(session.path / "command.json")
    git = command["git"]

    assert git["present"] is True
    assert git["head"]["kind"] == "commit"
    assert isinstance(git["head"]["commit"], str)
    assert len(git["head"]["commit"]) == 40
    assert git["head"]["short_commit"] == git["head"]["commit"][:8]
    assert isinstance(git["head"]["branch"], str)
    assert git["head"]["branch"]
    assert git["dirty"] is True
    assert any("tracked.txt" in entry for entry in git["status_short"])


def test_cllg_records_unborn_git_repo_without_fake_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    (repo / "untracked.txt").write_text("dirty\n", encoding="utf-8")
    monkeypatch.chdir(repo)
    monkeypatch.setattr(sys, "argv", ["game"])

    with cllg() as session:
        pass

    git = _read_json(session.path / "command.json")["git"]

    assert git["present"] is True
    assert git["head"] == {"kind": "unborn", "branch": "main"}
    assert git["dirty"] is True
    assert any("untracked.txt" in entry for entry in git["status_short"])


def test_cllg_logs_events(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["smoke"])

    with cllg() as session:
        session.event("message", text="starting", data={"replication": 0})

    events = _read_events(session.path / "events.jsonl")
    assert events[0]["type"] == "message"
    assert events[0]["text"] == "starting"
    assert events[0]["data"] == {"replication": 0}


def test_cllg_automatically_captures_stdout_and_stderr_while_forwarding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forwarded_stdout = io.StringIO()
    forwarded_stderr = io.StringIO()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["capture"])
    monkeypatch.setattr(sys, "stdout", forwarded_stdout)
    monkeypatch.setattr(sys, "stderr", forwarded_stderr)

    with cllg() as session:
        print("stdout print")
        sys.stdout.write("stdout write\n")
        print("stderr print", file=sys.stderr)
        sys.stderr.write("stderr write\n")

    expected_stdout = "stdout print\nstdout write\n"
    expected_stderr = "stderr print\nstderr write\n"
    assert forwarded_stdout.getvalue() == expected_stdout
    assert forwarded_stderr.getvalue() == expected_stderr
    assert (session.path / "stdout.txt").read_text(encoding="utf-8") == expected_stdout
    assert (session.path / "stderr.txt").read_text(encoding="utf-8") == expected_stderr


def test_cllg_restores_streams_after_exception(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forwarded_stdout = io.StringIO()
    forwarded_stderr = io.StringIO()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["capture"])
    monkeypatch.setattr(sys, "stdout", forwarded_stdout)
    monkeypatch.setattr(sys, "stderr", forwarded_stderr)

    with pytest.raises(RuntimeError, match="boom"):
        with cllg() as session:
            print("captured before exception")
            raise RuntimeError("boom")

    assert sys.stdout is forwarded_stdout
    assert sys.stderr is forwarded_stderr
    print("outside capture")

    assert forwarded_stdout.getvalue() == "captured before exception\noutside capture\n"
    assert (
        session.path / "stdout.txt"
    ).read_text(encoding="utf-8") == "captured before exception\n"
    assert (session.path / "stderr.txt").read_text(encoding="utf-8") == ""
    events = _read_events(session.path / "events.jsonl")
    assert events[-1]["type"] == "exception"
    assert events[-1]["data"] == {"exception_type": "RuntimeError"}


def test_cllg_captures_logging_handlers_bound_inside_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forwarded_stderr = io.StringIO()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["capture"])
    monkeypatch.setattr(sys, "stderr", forwarded_stderr)
    logger = logging.getLogger("cllg.tests.capture")
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.INFO)

    with cllg() as session:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s:%(message)s"))
        logger.addHandler(handler)
        try:
            logger.info("captured log")
        finally:
            logger.removeHandler(handler)
            handler.close()

    expected = "INFO:captured log\n"
    assert forwarded_stderr.getvalue() == expected
    assert (session.path / "stderr.txt").read_text(encoding="utf-8") == expected


def test_progress_events_are_logged_without_terminal_output_in_json_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream = FakeTty()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["smoke"])
    with cllg() as session:
        progress = make_progress(session=session, json_mode=True, stream=stream)
        with progress.task("smoke fixed limerick", total=2) as task:
            task.message("loaded")
            task.update(text="replication 1")
            task.update(text="replication 2")

    assert stream.getvalue() == ""
    events = _read_events(session.path / "events.jsonl")
    advances = [event for event in events if event["type"] == "progress_advance"]

    assert events[0]["type"] == "progress_start"
    assert events[-1]["type"] == "progress_finish"
    assert len(advances) == 2
    assert events[0]["total"] == 2
    assert events[-1]["current"] == 2


def test_non_tty_progress_falls_back_to_logged_events_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream = io.StringIO()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["batch"])
    with cllg() as session:
        progress = make_progress(session=session, json_mode=False, stream=stream)
        with progress.task("batch", total=1) as task:
            task.update(text="done")

    assert stream.getvalue() == ""
    events = _read_events(session.path / "events.jsonl")
    assert {event["type"] for event in events} == {
        "progress_start",
        "progress_advance",
        "progress_finish",
    }
