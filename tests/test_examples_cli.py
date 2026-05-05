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
    _init_git_repo(tmp_path)
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "examples" / args[0]), *args[1:]],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )


def _run_script(tmp_path: Path, source: str) -> subprocess.CompletedProcess[str]:
    # Wurlitzer captures process fds; pytest's own fd capture is a bad harness
    # for asserting log files. Run fd-capture cases in a child process instead.
    _init_git_repo(tmp_path)
    script = tmp_path / "script.py"
    script.write_text(source, encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(script)],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )


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


def test_training_loop_example_logs_deep_progress_without_polluting_json_stdout(
    tmp_path: Path,
) -> None:
    completed = _run_example(
        tmp_path,
        "training_loop.py",
        "--json",
        "--epochs",
        "2",
        "--delay",
        "0",
    )
    payload = _json_stdout(completed)
    log_dir = _only_log_dir(tmp_path)
    events = _read_events(log_dir / "events.jsonl")

    assert completed.stderr == ""
    assert payload["ok"] is True
    assert payload["epochs"] == 2
    assert (log_dir / "stdout.txt").read_text(encoding="utf-8") == completed.stdout
    assert _events_of_type(events, "progress_message")
    assert len(_events_of_type(events, "progress_advance")) == 2


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


def test_fd_capture_logs_buffer_logging_and_subprocess_output(
    tmp_path: Path,
) -> None:
    completed = _run_script(
        tmp_path,
        """
from __future__ import annotations

import logging
import subprocess
import sys

from cllg import cllg

logger = logging.getLogger("example.preexisting")
logger.handlers.clear()
logger.propagate = False
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter("PRE:%(message)s"))
logger.addHandler(handler)

with cllg():
    print("print stdout")
    sys.stdout.flush()
    sys.stdout.buffer.write(b"buffer stdout\\n")
    sys.stdout.flush()
    print("print stderr", file=sys.stderr)
    logger.info("preexisting logging")
    subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; print('child stdout'); print('child stderr', file=sys.stderr)",
        ],
        check=True,
    )
""",
    )
    log_dir = _only_log_dir(tmp_path)

    assert completed.stdout == b"print stdout\nbuffer stdout\nchild stdout\n"
    assert completed.stderr == b"print stderr\nPRE:preexisting logging\nchild stderr\n"
    assert (log_dir / "stdout.txt").read_bytes() == completed.stdout
    assert (log_dir / "stderr.txt").read_bytes() == completed.stderr


def test_fd_capture_preserves_invalid_stdout_bytes(
    tmp_path: Path,
) -> None:
    completed = _run_script(
        tmp_path,
        """
from __future__ import annotations

import sys

from cllg import cllg

with cllg():
    sys.stdout.buffer.write(b"bad:\\xff\\n")
    sys.stdout.flush()
""",
    )
    log_dir = _only_log_dir(tmp_path)

    assert completed.stdout == b"bad:\xff\n"
    assert (log_dir / "stdout.txt").read_bytes() == b"bad:\xff\n"


def test_nested_cllg_logs_inner_output_to_inner_and_outer_sessions(
    tmp_path: Path,
) -> None:
    completed = _run_script(
        tmp_path,
        """
from __future__ import annotations

from cllg import cllg

with cllg():
    print("outer before")
    with cllg():
        print("inner")
    print("outer after")
""",
    )
    log_dirs = sorted(path for path in (tmp_path / "logs").glob("*/*") if path.is_dir())
    outer = next(
        path
        for path in log_dirs
        if (path / "stdout.txt").read_bytes() == completed.stdout
    )
    inner = next(path for path in log_dirs if path != outer)

    assert completed.stdout == b"outer before\ninner\nouter after\n"
    assert (outer / "stdout.txt").read_bytes() == completed.stdout
    assert (inner / "stdout.txt").read_bytes() == b"inner\n"
