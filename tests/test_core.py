from __future__ import annotations

import io
import json
import logging
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from cllg import cllg, current_session, output, progress


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


def _events_of_type(events: list[dict[str, object]], event_type: str) -> list[dict[str, object]]:
    return [event for event in events if event["type"] == event_type]


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


def _init_and_enter_git_repo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)
    monkeypatch.chdir(repo)
    return repo


def _fixed_clock() -> datetime:
    return datetime(2026, 5, 5, 14, 12, 33, tzinfo=timezone.utc)


def test_cllg_fails_early_outside_git_repo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["smoke"])

    with pytest.raises(RuntimeError, match="git repository"):
        cllg()

    assert not (tmp_path / "logs").exists()


def test_cllg_creates_run_directory_and_command_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _init_and_enter_git_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "argv", ["/usr/local/bin/smoke", "fixed", "--json"])
    monkeypatch.setattr("cllg.core._utc_now", _fixed_clock)

    with cllg() as session:
        assert session.path.is_dir()
        assert session.path.parent == repo / "logs" / "2026-05-05"
        assert session.path.name.startswith("141233-smoke")

    command = _read_json(session.path / "command.json")

    assert command["command"] == "smoke"
    assert command["argv"] == ["/usr/local/bin/smoke", "fixed", "--json"]
    assert command["cwd"] == str(repo)
    assert command["git"]["present"] is True
    assert (session.path / "events.jsonl").is_file()
    assert (session.path / "stdout.txt").is_file()
    assert (session.path / "stderr.txt").is_file()


def test_cllg_writes_logs_at_git_root_when_invoked_from_subdirectory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    nested = repo / "src" / "tool"
    nested.mkdir(parents=True)
    _init_git_repo(repo)
    monkeypatch.chdir(nested)
    monkeypatch.setattr(sys, "argv", ["nested-command"])
    monkeypatch.setattr("cllg.core._utc_now", _fixed_clock)

    with cllg() as session:
        pass

    command = _read_json(session.path / "command.json")

    assert session.path.parent == repo / "logs" / "2026-05-05"
    assert command["cwd"] == str(nested)
    assert command["git"]["repo_root"] == str(repo)


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


def test_cllg_collects_git_metadata_with_one_root_lookup_and_one_status_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)
    monkeypatch.chdir(repo)
    monkeypatch.setattr(sys, "argv", ["game"])

    calls: list[tuple[str, ...]] = []
    real_run = subprocess.run

    def spy_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        command = args[0]
        if isinstance(command, list) and command and command[0] == "git":
            calls.append(tuple(str(part) for part in command[1:]))
        return real_run(*args, **kwargs)

    monkeypatch.setattr("cllg.core.subprocess.run", spy_run)

    with cllg():
        pass

    assert calls == [
        ("rev-parse", "--show-toplevel"),
        ("status", "--porcelain=v2", "--branch"),
    ]


def test_cllg_logs_events(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _init_and_enter_git_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "argv", ["smoke"])

    with cllg() as session:
        session.event("message", text="starting", data={"replication": 0})

    events = _read_events(session.path / "events.jsonl")
    messages = _events_of_type(events, "message")
    assert len(messages) == 1
    assert messages[0]["text"] == "starting"
    assert messages[0]["data"] == {"replication": 0}


def test_current_session_is_context_local_and_restored_for_nested_sessions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _init_and_enter_git_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "argv", ["outer"])

    assert current_session() is None
    with cllg() as outer:
        assert current_session() is outer
        with cllg() as inner:
            assert current_session() is inner
        assert current_session() is outer

    assert current_session() is None


def test_output_prints_human_text_and_records_event_inside_cllg(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forwarded_stdout = io.StringIO()
    _init_and_enter_git_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "argv", ["command"])
    monkeypatch.setattr(sys, "stdout", forwarded_stdout)

    with cllg() as session:
        output(human="processed 3 items", agent={"ok": True, "items": 3})

    assert forwarded_stdout.getvalue() == "processed 3 items\n"
    assert (session.path / "stdout.txt").read_text(encoding="utf-8") == (
        "processed 3 items\n"
    )
    events = _read_events(session.path / "events.jsonl")
    outputs = _events_of_type(events, "output")
    assert len(outputs) == 1
    assert outputs[0]["text"] == "processed 3 items"
    assert outputs[0]["data"] == {"ok": True, "items": 3}


def test_output_prints_agent_json_in_json_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forwarded_stdout = io.StringIO()
    _init_and_enter_git_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "argv", ["command", "--json"])
    monkeypatch.setattr(sys, "stdout", forwarded_stdout)

    with cllg() as session:
        output(human="processed 3 items", agent={"items": 3, "ok": True})

    assert json.loads(forwarded_stdout.getvalue()) == {"items": 3, "ok": True}
    assert (session.path / "stdout.txt").read_text(encoding="utf-8") == (
        forwarded_stdout.getvalue()
    )


def test_output_validates_human_and_agent_before_printing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forwarded_stdout = io.StringIO()
    _init_and_enter_git_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "argv", ["command"])
    monkeypatch.setattr(sys, "stdout", forwarded_stdout)

    with cllg():
        with pytest.raises(TypeError, match="human"):
            output(human=object(), agent={"ok": True})  # type: ignore[arg-type]
        with pytest.raises(TypeError, match="agent"):
            output(human="bad", agent=["not", "object"])  # type: ignore[arg-type]
        with pytest.raises(TypeError, match="string keys"):
            output(human="bad", agent={1: "bad"})  # type: ignore[dict-item]
        with pytest.raises(TypeError, match="JSON-serializable"):
            output(human="bad", agent={"bad": object()})

    assert forwarded_stdout.getvalue() == ""


def test_output_works_without_active_cllg_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forwarded_stdout = io.StringIO()
    monkeypatch.setattr(sys, "argv", ["command"])
    monkeypatch.setattr(sys, "stdout", forwarded_stdout)

    output(human="outside", agent={"ok": True})

    assert forwarded_stdout.getvalue() == "outside\n"


def test_cllg_automatically_captures_stdout_and_stderr_while_forwarding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forwarded_stdout = io.StringIO()
    forwarded_stderr = io.StringIO()
    _init_and_enter_git_repo(tmp_path, monkeypatch)
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
    _init_and_enter_git_repo(tmp_path, monkeypatch)
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
    exceptions = _events_of_type(events, "exception")
    assert len(exceptions) == 1
    assert exceptions[0]["data"] == {"exception_type": "RuntimeError"}


def test_cllg_captures_logging_handlers_bound_inside_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forwarded_stderr = io.StringIO()
    _init_and_enter_git_repo(tmp_path, monkeypatch)
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
    _init_and_enter_git_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "argv", ["smoke", "--json"])
    with cllg() as session:
        with progress("smoke fixed limerick", total=2, stream=stream) as task:
            task.message(human="loaded", agent={"event": "loaded"})
            task.update(human="replication 1", agent={"replication": 1})
            task.update(human="replication 2", agent={"replication": 2})

    assert stream.getvalue() == ""
    events = _read_events(session.path / "events.jsonl")
    starts = _events_of_type(events, "progress_start")
    advances = _events_of_type(events, "progress_advance")
    finishes = _events_of_type(events, "progress_finish")

    assert len(starts) == 1
    assert len(advances) == 2
    assert len(finishes) == 1
    assert starts[0]["total"] == 2
    assert finishes[0]["current"] == 2
    assert {"replication": 1} in [advance["data"] for advance in advances]


def test_non_tty_progress_falls_back_to_logged_events_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream = io.StringIO()
    _init_and_enter_git_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "argv", ["batch"])
    with cllg() as session:
        with progress("batch", total=1, stream=stream) as task:
            task.update(human="done", agent={"done": True})

    assert stream.getvalue() == ""
    events = _read_events(session.path / "events.jsonl")
    assert {event["type"] for event in events} == {
        "progress_start",
        "progress_advance",
        "progress_finish",
    }
