from __future__ import annotations

import io
import json
import logging
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from cllg import cllg, output, progress
from cllg.core import _unique_run_path


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


def _git_output(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


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
    assert (session.path / "stdout.out").is_file()
    assert (session.path / "stderr.err").is_file()


def test_unique_run_path_adds_entropy_before_directory_exists(
    tmp_path: Path,
) -> None:
    parent = tmp_path / "logs"

    first = _unique_run_path(parent, "141233-smoke")
    second = _unique_run_path(parent, "141233-smoke")

    assert first != second
    assert first.is_dir()
    assert second.is_dir()
    assert first.name.startswith("141233-smoke")
    assert second.name.startswith("141233-smoke")


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


def test_cllg_records_only_allowlisted_environment_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _init_and_enter_git_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "argv", ["env-check"])
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "0,1")
    monkeypatch.setenv("TORCH_HOME", "/models/torch")
    monkeypatch.setenv("MASTER_ADDR", "127.0.0.1")
    monkeypatch.setenv("WORLD_SIZE", "8")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "do-not-log")

    with cllg() as session:
        pass

    env = _read_json(session.path / "command.json")["env"]
    required_values = {
        "CUDA_VISIBLE_DEVICES": "0,1",
        "MASTER_ADDR": "127.0.0.1",
        "PATH": "/usr/bin",
        "TORCH_HOME": "/models/torch",
        "WORLD_SIZE": "8",
    }

    assert env["kind"] == "allowlist"
    assert required_values.items() <= env["values"].items()
    assert "AWS_SECRET_ACCESS_KEY" not in env["values"]


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
    assert git["head"] == {
        "kind": "commit",
        "commit": _git_output(repo, "rev-parse", "HEAD"),
        "short_commit": _git_output(repo, "rev-parse", "--short=8", "HEAD"),
        "branch": "main",
    }
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


def test_cllg_records_complete_git_metadata_with_small_git_call_budget(
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

    with cllg() as session:
        pass

    git = _read_json(session.path / "command.json")["git"]
    assert git["present"] is True
    assert git["repo_root"] == str(repo)
    assert git["head"]["kind"] == "commit"
    assert git["dirty"] is False
    assert len(calls) <= 2


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


def test_nested_output_events_go_to_the_active_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _init_and_enter_git_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "argv", ["outer"])

    with cllg() as outer:
        with cllg() as inner:
            output(human="inner", agent={"scope": "inner"})
        output(human="outer", agent={"scope": "outer"})

    outer_outputs = _events_of_type(_read_events(outer.path / "events.jsonl"), "output")
    inner_outputs = _events_of_type(_read_events(inner.path / "events.jsonl"), "output")

    assert [event["data"] for event in outer_outputs] == [{"scope": "outer"}]
    assert [event["data"] for event in inner_outputs] == [{"scope": "inner"}]


def test_output_prints_human_text_and_records_event_inside_cllg(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    _init_and_enter_git_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "argv", ["command"])

    with cllg() as session:
        output(human="processed 3 items", agent={"ok": True, "items": 3})

    captured = capfd.readouterr()
    assert captured.out == "processed 3 items\n"
    events = _read_events(session.path / "events.jsonl")
    outputs = _events_of_type(events, "output")
    assert len(outputs) == 1
    assert outputs[0]["text"] == "processed 3 items"
    assert outputs[0]["data"] == {"ok": True, "items": 3}


def test_output_prints_agent_json_in_json_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    _init_and_enter_git_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "argv", ["command", "--json"])

    with cllg() as session:
        output(human="processed 3 items", agent={"items": 3, "ok": True})

    captured = capfd.readouterr()
    assert json.loads(captured.out) == {"items": 3, "ok": True}


def test_output_validates_human_and_agent_shape_before_printing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    _init_and_enter_git_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "argv", ["command"])

    with cllg():
        with pytest.raises(TypeError, match="human"):
            output(human=object(), agent={"ok": True})  # type: ignore[arg-type]
        with pytest.raises(TypeError, match="agent"):
            output(human="bad", agent=["not", "object"])  # type: ignore[arg-type]
        with pytest.raises(TypeError, match="string keys"):
            output(human="bad", agent={1: "bad"})  # type: ignore[dict-item]

    assert capfd.readouterr().out == ""


def test_output_human_mode_does_not_pre_check_agent_value_serializability(
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(sys, "argv", ["command"])

    output(human="hello", agent={"unserializable": object()})

    assert capfd.readouterr().out == "hello\n"


def test_output_works_without_active_cllg_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forwarded_stdout = io.StringIO()
    monkeypatch.setattr(sys, "argv", ["command"])
    monkeypatch.setattr(sys, "stdout", forwarded_stdout)

    output(human="outside", agent={"ok": True})

    assert forwarded_stdout.getvalue() == "outside\n"


def test_cllg_forwards_stdout_and_stderr(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    _init_and_enter_git_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "argv", ["capture"])

    with cllg():
        print("stdout print")
        sys.stdout.write("stdout write\n")
        print("stderr print", file=sys.stderr)
        sys.stderr.write("stderr write\n")

    expected_stdout = "stdout print\nstdout write\n"
    expected_stderr = "stderr print\nstderr write\n"
    captured = capfd.readouterr()
    assert captured.out == expected_stdout
    assert captured.err == expected_stderr


def test_cllg_restores_streams_after_exception(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    _init_and_enter_git_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "argv", ["capture"])
    original_stdout = sys.stdout
    original_stderr = sys.stderr

    with pytest.raises(RuntimeError, match="boom"):
        with cllg() as session:
            print("captured before exception")
            raise RuntimeError("boom")

    assert sys.stdout is original_stdout
    assert sys.stderr is original_stderr
    print("outside capture")

    assert capfd.readouterr().out == "captured before exception\noutside capture\n"
    events = _read_events(session.path / "events.jsonl")
    session_ends = _events_of_type(events, "session_end")
    assert len(session_ends) == 1
    assert session_ends[0]["text"] == "boom"
    assert session_ends[0]["data"] == {"exception_type": "RuntimeError"}


def test_cllg_emits_session_end_on_clean_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _init_and_enter_git_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "argv", ["smoke"])

    with cllg() as session:
        pass

    events = _read_events(session.path / "events.jsonl")
    session_ends = _events_of_type(events, "session_end")
    assert len(session_ends) == 1
    assert session_ends[0]["text"] == ""
    assert session_ends[0]["data"] == {}


def test_cllg_captures_logging_handlers_bound_inside_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    _init_and_enter_git_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "argv", ["capture"])
    logger = logging.getLogger("cllg.tests.capture")
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.INFO)

    with cllg():
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s:%(message)s"))
        logger.addHandler(handler)
        try:
            logger.info("captured log")
        finally:
            logger.removeHandler(handler)
            handler.close()

    expected = "INFO:captured log\n"
    assert capfd.readouterr().err == expected


def test_cllg_keeps_stdout_as_real_text_stream(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _init_and_enter_git_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "argv", ["capture"])

    with cllg():
        assert isinstance(sys.stdout, io.TextIOBase)


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
        "session_end",
    }
