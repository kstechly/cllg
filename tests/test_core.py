from __future__ import annotations

import io
import json
import logging
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

import cllg as cllg_module
from cllg import cllg, progress


class FakeTty(io.StringIO):
    def isatty(self) -> bool:
        return True


def _read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_prints(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _log_dirs(repo: Path) -> list[Path]:
    return sorted(path for path in (repo / "logs").glob("*/*") if path.is_dir())


def _only_log_dir(repo: Path) -> Path:
    log_dirs = _log_dirs(repo)
    assert len(log_dirs) == 1
    return log_dirs[0]


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

    with pytest.raises(RuntimeError, match="git repository"):
        cllg(json=False)

    assert not (tmp_path / "logs").exists()


def test_cllg_creates_run_directory_and_command_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _init_and_enter_git_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "argv", ["/usr/local/bin/smoke", "fixed", "--json"])
    monkeypatch.setattr("cllg.core._utc_now", _fixed_clock)

    with cllg(json=False):
        pass

    log_dir = _only_log_dir(repo)
    command = _read_json(log_dir / "command.json")

    assert log_dir.parent == repo / "logs" / "2026-05-05"
    assert log_dir.name.startswith("141233-smoke")
    assert command["argv"] == ["/usr/local/bin/smoke", "fixed", "--json"]
    assert "command" not in command
    assert command["cwd"] == str(repo)
    assert command["git"]["present"] is True
    assert (log_dir / "prints.jsonl").is_file()
    assert not (log_dir / "events.jsonl").exists()
    assert (log_dir / "stdout.out").is_file()
    assert (log_dir / "stderr.err").is_file()


def test_cllg_print_replaces_print_and_records_prints_jsonl(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    repo = _init_and_enter_git_repo(tmp_path, monkeypatch)

    with cllg(json=False):
        cllg_module.print(human="processed 3 items", agent={"ok": True, "items": 3})

    assert capfd.readouterr().out == "processed 3 items\n"
    records = _read_prints(_only_log_dir(repo) / "prints.jsonl")
    assert records == [
        {
            "agent": {"items": 3, "ok": True},
            "human": "processed 3 items",
            "kind": "print",
            "timestamp": records[0]["timestamp"],
        }
    ]


def test_cllg_print_json_mode_emits_jsonl_for_multiple_prints(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    repo = _init_and_enter_git_repo(tmp_path, monkeypatch)

    with cllg(json=True):
        cllg_module.print(human="one", agent={"event": "one"})
        cllg_module.print(human="two", agent={"event": "two"})

    assert [json.loads(line) for line in capfd.readouterr().out.splitlines()] == [
        {"event": "one"},
        {"event": "two"},
    ]
    assert [record["agent"] for record in _read_prints(_only_log_dir(repo) / "prints.jsonl")] == [
        {"event": "one"},
        {"event": "two"},
    ]


def test_cllg_print_deep_code_uses_active_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def deep_print() -> None:
        cllg_module.print(human="deep", agent={"scope": "deep"})

    repo = _init_and_enter_git_repo(tmp_path, monkeypatch)

    with cllg(json=False):
        deep_print()

    records = _read_prints(_only_log_dir(repo) / "prints.jsonl")
    assert [record["agent"] for record in records] == [{"scope": "deep"}]


def test_cllg_creates_distinct_run_directories_with_same_timestamp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _init_and_enter_git_repo(tmp_path, monkeypatch)
    monkeypatch.setattr("cllg.core._utc_now", _fixed_clock)

    with cllg(json=False):
        pass
    with cllg(json=False):
        pass

    first, second = _log_dirs(repo)
    assert first != second
    assert first.parent == second.parent
    assert first.name.startswith("141233-")
    assert second.name.startswith("141233-")


def test_cllg_writes_logs_at_git_root_when_invoked_from_subdirectory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    nested = repo / "src" / "tool"
    nested.mkdir(parents=True)
    _init_git_repo(repo)
    monkeypatch.chdir(nested)
    monkeypatch.setattr("cllg.core._utc_now", _fixed_clock)

    with cllg(json=False):
        pass

    log_dir = _only_log_dir(repo)
    command = _read_json(log_dir / "command.json")

    assert log_dir.parent == repo / "logs" / "2026-05-05"
    assert command["cwd"] == str(nested)
    assert command["git"]["repo_root"] == str(repo)


def test_cllg_records_only_allowlisted_environment_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _init_and_enter_git_repo(tmp_path, monkeypatch)
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "0,1")
    monkeypatch.setenv("TORCH_HOME", "/models/torch")
    monkeypatch.setenv("MASTER_ADDR", "127.0.0.1")
    monkeypatch.setenv("WORLD_SIZE", "8")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "do-not-log")

    with cllg(json=False):
        pass

    env = _read_json(_only_log_dir(repo) / "command.json")["env"]
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

    with cllg(json=False):
        pass

    command = _read_json(_only_log_dir(repo) / "command.json")
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

    with cllg(json=False):
        pass

    git = _read_json(_only_log_dir(repo) / "command.json")["git"]

    assert git["present"] is True
    assert git["head"] == {"kind": "unborn", "branch": "main"}
    assert git["dirty"] is True
    assert any("untracked.txt" in entry for entry in git["status_short"])


def test_nested_print_records_go_to_the_active_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _init_and_enter_git_repo(tmp_path, monkeypatch)

    with cllg(json=False):
        with cllg(json=False):
            cllg_module.print(human="inner", agent={"scope": "inner"})
        cllg_module.print(human="outer", agent={"scope": "outer"})

    log_records = [_read_prints(log_dir / "prints.jsonl") for log_dir in _log_dirs(repo)]

    agent_records = [[record["agent"] for record in records] for records in log_records]
    assert sorted(agent_records, key=repr) == [
        [{"scope": "inner"}],
        [{"scope": "outer"}],
    ]


def test_print_validates_human_and_agent_shape_before_printing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    repo = _init_and_enter_git_repo(tmp_path, monkeypatch)

    with cllg(json=False):
        with pytest.raises(TypeError, match="human"):
            cllg_module.print(human=object(), agent={"ok": True})  # type: ignore[arg-type]
        with pytest.raises(TypeError, match="agent"):
            cllg_module.print(human="bad", agent=["not", "object"])  # type: ignore[arg-type]
        with pytest.raises(TypeError, match="string keys"):
            cllg_module.print(human="bad", agent={1: "bad"})  # type: ignore[dict-item]

    assert capfd.readouterr().out == ""


def test_print_requires_active_cllg_context() -> None:
    with pytest.raises(RuntimeError, match="active cllg session"):
        cllg_module.print(human="outside", agent={"ok": True})


def test_progress_requires_active_cllg_context() -> None:
    with pytest.raises(RuntimeError, match="active cllg session"):
        with progress("outside", total=1):
            pass


def test_cllg_forwards_stdout_and_stderr(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    repo = _init_and_enter_git_repo(tmp_path, monkeypatch)

    with cllg(json=False):
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
    repo = _init_and_enter_git_repo(tmp_path, monkeypatch)
    original_stdout = sys.stdout
    original_stderr = sys.stderr

    with pytest.raises(RuntimeError, match="boom"):
        with cllg(json=False):
            print("captured before exception")
            raise RuntimeError("boom")

    assert sys.stdout is original_stdout
    assert sys.stderr is original_stderr
    print("outside capture")

    assert capfd.readouterr().out == "captured before exception\noutside capture\n"
    command = _read_json(_only_log_dir(repo) / "command.json")
    assert command["exception"] == {"type": "RuntimeError", "message": "boom"}
    assert command["ended_at"] is not None


def test_clean_exit_does_not_write_lifecycle_prints(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _init_and_enter_git_repo(tmp_path, monkeypatch)

    with cllg(json=False):
        pass

    log_dir = _only_log_dir(repo)
    assert _read_prints(log_dir / "prints.jsonl") == []
    assert not (log_dir / "events.jsonl").exists()


def test_command_json_records_started_and_ended_timestamps(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _init_and_enter_git_repo(tmp_path, monkeypatch)

    with cllg(json=False):
        log_dir = _only_log_dir(repo)
        mid_run = _read_json(log_dir / "command.json")
        assert mid_run["ended_at"] is None
        assert datetime.fromisoformat(mid_run["started_at"]).tzinfo is not None

    final = _read_json(log_dir / "command.json")
    started = datetime.fromisoformat(final["started_at"])
    ended = datetime.fromisoformat(final["ended_at"])
    assert started == datetime.fromisoformat(mid_run["started_at"])
    assert ended >= started
    assert final["exception"] is None


def test_cllg_captures_logging_handlers_bound_inside_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    repo = _init_and_enter_git_repo(tmp_path, monkeypatch)
    logger = logging.getLogger("cllg.tests.capture")
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.INFO)

    with cllg(json=False):
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


def test_progress_writes_records_for_start_message_and_each_update(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream = FakeTty()
    repo = _init_and_enter_git_repo(tmp_path, monkeypatch)
    with cllg(json=True):
        with progress("smoke fixed limerick", total=2, stream=stream) as task:
            task.message(human="loaded", agent={"event": "loaded"})
            task.update(human="replication 1", agent={"replication": 1})
            task.update(human="replication 2", agent={"replication": 2})

    assert stream.getvalue() == ""
    records = _read_prints(_only_log_dir(repo) / "prints.jsonl")
    assert [record["kind"] for record in records] == [
        "progress_start",
        "progress_message",
        "progress_advance",
        "progress_advance",
    ]

    start = records[0]
    assert start["human"] == "smoke fixed limerick"
    assert start["agent"] == {}
    assert start["title"] == "smoke fixed limerick"
    assert start["total"] == 2

    message = records[1]
    assert message["human"] == "loaded"
    assert message["agent"] == {"event": "loaded"}
    assert message["current"] == 0
    assert message["total"] == 2

    first_advance = records[2]
    assert first_advance["human"] == "replication 1"
    assert first_advance["agent"] == {"replication": 1}
    assert first_advance["current"] == 1
    assert first_advance["total"] == 2
    assert first_advance["advance"] == 1

    second_advance = records[3]
    assert second_advance["agent"] == {"replication": 2}
    assert second_advance["current"] == 2


def test_non_tty_progress_records_start_and_advance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream = io.StringIO()
    repo = _init_and_enter_git_repo(tmp_path, monkeypatch)
    with cllg(json=False):
        with progress("batch", total=1, stream=stream) as task:
            task.update(human="done", agent={"done": True})

    assert stream.getvalue() == ""
    records = _read_prints(_only_log_dir(repo) / "prints.jsonl")
    assert [record["kind"] for record in records] == [
        "progress_start",
        "progress_advance",
    ]
    assert records[1]["agent"] == {"done": True}
    assert records[1]["current"] == 1
