from __future__ import annotations

import json
import os
import platform
import socket
import subprocess
import sys
from contextlib import AbstractContextManager, contextmanager, nullcontext
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import TracebackType
from typing import Any, Callable, Iterable, Iterator, Protocol, TextIO

Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def open_log_session(
    *,
    command: str,
    argv: list[str] | tuple[str, ...] | None = None,
    log_root: str | Path = "logs",
    cwd: str | Path | None = None,
    clock: Clock = _utc_now,
    env_keys: tuple[str, ...] = (),
) -> LogSession:
    argv_list = list(sys.argv if argv is None else argv)
    cwd_path = (Path.cwd() if cwd is None else Path(cwd)).resolve()
    opened_at = clock()
    path = _unique_run_path(
        Path(log_root) / opened_at.strftime("%Y-%m-%d"),
        f"{opened_at.strftime('%H%M%S')}-{_slug(command)}",
    )
    path.mkdir(parents=True)
    _write_json(
        path / "command.json",
        _command_metadata(
            command=command,
            argv=argv_list,
            cwd=cwd_path,
            opened_at=opened_at,
            env_keys=env_keys,
        ),
    )
    (path / "events.jsonl").touch()
    return LogSession(
        path=path,
        clock=clock,
    )


@dataclass(frozen=True, slots=True)
class LogSession(AbstractContextManager["LogSession"]):
    path: Path
    clock: Clock = _utc_now

    def __enter__(self) -> LogSession:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        if exc_value is not None:
            self.event(
                "exception",
                text=str(exc_value),
                data={"exception_type": exc_type.__name__ if exc_type else None},
            )
        return None

    def event(
        self,
        event_type: str,
        *,
        text: str = "",
        data: dict[str, Any] | None = None,
        **fields: Any,
    ) -> None:
        event = {
            "type": event_type,
            "timestamp": self.clock().isoformat(),
            "text": text,
            "data": data or {},
            **fields,
        }
        with (self.path / "events.jsonl").open("a", encoding="utf-8") as file:
            file.write(json.dumps(event, sort_keys=True) + "\n")

    def write_json_artifact(self, name: str, payload: Any) -> Path:
        path = self._artifact_path(name)
        _write_json(path, payload)
        self.event("artifact", text=name, data={"path": str(path)})
        return path

    @contextmanager
    def capture_stdio(self) -> Iterator[None]:
        stdout_path = self.path / "stdout.txt"
        stderr_path = self.path / "stderr.txt"
        original_stdout = sys.stdout
        original_stderr = sys.stderr
        with stdout_path.open("a", encoding="utf-8") as stdout_file, stderr_path.open(
            "a",
            encoding="utf-8",
        ) as stderr_file:
            sys.stdout = _TeeTextIO(original_stdout, stdout_file)  # type: ignore[assignment]
            sys.stderr = _TeeTextIO(original_stderr, stderr_file)  # type: ignore[assignment]
            try:
                yield
            finally:
                sys.stdout = original_stdout
                sys.stderr = original_stderr

    def _artifact_path(self, name: str) -> Path:
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"artifact name must be relative to the log session: {name!r}")
        path = self.path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        return path


class _TeeTextIO:
    def __init__(self, stream: TextIO, artifact: TextIO) -> None:
        self._stream = stream
        self._artifact = artifact

    @property
    def encoding(self) -> str | None:
        return getattr(self._stream, "encoding", None)

    @property
    def errors(self) -> str | None:
        return getattr(self._stream, "errors", None)

    @property
    def newlines(self) -> Any:
        return getattr(self._stream, "newlines", None)

    @property
    def closed(self) -> bool:
        return self._stream.closed

    def write(self, text: str) -> int:
        written = self._stream.write(text)
        self._artifact.write(text)
        return written

    def writelines(self, lines: Iterable[str]) -> None:
        for line in lines:
            self.write(line)

    def flush(self) -> None:
        self._stream.flush()
        self._artifact.flush()

    def isatty(self) -> bool:
        return self._stream.isatty()

    def fileno(self) -> int:
        return self._stream.fileno()


def make_progress(
    *,
    session: LogSession,
    json_mode: bool,
    stream: TextIO | None = None,
) -> ProgressReporter:
    return ProgressReporter(
        session=session,
        sink=_make_progress_sink(json_mode=json_mode, stream=stream or sys.stderr),
    )


@dataclass(frozen=True, slots=True)
class ProgressReporter:
    session: LogSession
    sink: ProgressSink

    def task(self, title: str, *, total: int | None = None) -> AbstractContextManager[ProgressTask]:
        return _progress_task(
            session=self.session,
            sink=self.sink,
            title=title,
            total=total,
        )


@dataclass(slots=True)
class ProgressTask:
    session: LogSession
    display: ProgressDisplay
    title: str
    total: int | None = None
    _current: int = 0

    @property
    def current(self) -> int:
        return self._current

    def message(self, text: str, *, data: dict[str, Any] | None = None) -> None:
        self.session.event(
            "progress_message",
            text=text,
            data=data,
            current=self._current,
            total=self.total,
        )
        self.display.message(text)

    def update(
        self,
        advance: int = 1,
        *,
        text: str = "",
        data: dict[str, Any] | None = None,
    ) -> None:
        self._current += advance
        self.session.event(
            "progress_advance",
            text=text,
            data=data,
            current=self._current,
            total=self.total,
            advance=advance,
        )
        self.display.update(advance=advance, text=text)


@contextmanager
def _progress_task(
    *,
    session: LogSession,
    sink: ProgressSink,
    title: str,
    total: int | None,
) -> Iterator[ProgressTask]:
    current = 0
    session.event("progress_start", text=title, current=current, total=total)
    with sink.task(title=title, total=total) as display:
        task = ProgressTask(
            session=session,
            display=display,
            title=title,
            total=total,
        )
        try:
            yield task
        finally:
            session.event(
                "progress_finish",
                text=title,
                current=task.current,
                total=total,
            )


class ProgressDisplay(Protocol):
    def update(self, *, advance: int, text: str) -> None:
        ...

    def message(self, text: str) -> None:
        ...


class ProgressSink(Protocol):
    def task(
        self,
        *,
        title: str,
        total: int | None,
    ) -> AbstractContextManager[ProgressDisplay]:
        ...


class NoopProgressSink(ProgressSink):
    def task(
        self,
        *,
        title: str,
        total: int | None,
    ) -> AbstractContextManager[ProgressDisplay]:
        return nullcontext(NoopProgressDisplay())


class NoopProgressDisplay(ProgressDisplay):
    def update(self, *, advance: int, text: str) -> None:
        return None

    def message(self, text: str) -> None:
        return None


class AliveProgressSink(ProgressSink):
    def __init__(self, stream: TextIO) -> None:
        self._stream = stream

    def task(
        self,
        *,
        title: str,
        total: int | None,
    ) -> AbstractContextManager[ProgressDisplay]:
        from alive_progress import alive_bar

        return AliveProgressContext(
            alive_bar(
                total,
                title=title,
                file=self._stream,
                enrich_print=True,
                dual_line=True,
                receipt=True,
            )
        )


class AliveProgressContext(AbstractContextManager[ProgressDisplay]):
    def __init__(self, manager: AbstractContextManager[Any]) -> None:
        self._manager = manager

    def __enter__(self) -> ProgressDisplay:
        return AliveProgressDisplay(self._manager.__enter__())

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        return self._manager.__exit__(exc_type, exc_value, traceback)


@dataclass(frozen=True, slots=True)
class AliveProgressDisplay(ProgressDisplay):
    bar: Any

    def update(self, *, advance: int, text: str) -> None:
        if text:
            self.message(text)
        self.bar(advance)

    def message(self, text: str) -> None:
        if not text:
            return
        text_attr = getattr(self.bar, "text", None)
        if callable(text_attr):
            text_attr(text)


def _make_progress_sink(*, json_mode: bool, stream: TextIO) -> ProgressSink:
    if json_mode or not stream.isatty():
        return NoopProgressSink()
    return AliveProgressSink(stream)


def _command_metadata(
    *,
    command: str,
    argv: list[str],
    cwd: Path,
    opened_at: datetime,
    env_keys: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "command": command,
        "argv": argv,
        "cwd": str(cwd),
        "timestamp": opened_at.isoformat(),
        "python": {
            "version": platform.python_version(),
            "executable": sys.executable,
            "implementation": platform.python_implementation(),
        },
        "platform": platform.platform(),
        "hostname": socket.gethostname(),
        "env": {key: os.environ[key] for key in env_keys if key in os.environ},
        "git": _git_metadata(cwd),
    }


def _git_metadata(cwd: Path) -> dict[str, Any]:
    repo_root = _git(cwd, "rev-parse", "--show-toplevel")
    if repo_root is None:
        return {"present": False}
    commit = _git(cwd, "rev-parse", "HEAD")
    branch = _git_branch(cwd, commit=commit)
    status_short = (_git(cwd, "status", "--short") or "").splitlines()
    head = _git_head(commit=commit, branch=branch)
    return {
        "present": True,
        "repo_root": repo_root,
        "head": head,
        "dirty": bool(status_short),
        "status_short": status_short,
    }


def _git_head(*, commit: str | None, branch: str | None) -> dict[str, Any]:
    if commit is None:
        return {"kind": "unborn", "branch": branch or "HEAD"}
    return {
        "kind": "commit",
        "commit": commit,
        "short_commit": commit[:8],
        "branch": branch or "HEAD",
    }


def _git_branch(cwd: Path, *, commit: str | None) -> str | None:
    if commit is None:
        return _git(cwd, "symbolic-ref", "--short", "HEAD")
    return _git(cwd, "rev-parse", "--abbrev-ref", "HEAD")


def _git(cwd: Path, *args: str) -> str | None:
    completed = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


def _unique_run_path(parent: Path, stem: str) -> Path:
    parent.mkdir(parents=True, exist_ok=True)
    candidate = parent / stem
    if not candidate.exists():
        return candidate
    index = 2
    while True:
        candidate = parent / f"{stem}-{index}"
        if not candidate.exists():
            return candidate
        index += 1


def _slug(raw: str) -> str:
    chars = [char.lower() if char.isalnum() else "-" for char in raw.strip()]
    slug = "-".join(part for part in "".join(chars).split("-") if part)
    return slug or "command"


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
