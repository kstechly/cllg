from __future__ import annotations

import json
import platform
import socket
import subprocess
import sys
from contextlib import AbstractContextManager, contextmanager, nullcontext
from contextvars import ContextVar, Token
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import TracebackType
from typing import Any, Callable, Iterable, Iterator, Protocol, TextIO

Clock = Callable[[], datetime]
_CURRENT_SESSION: ContextVar[LogSession | None] = ContextVar(
    "cllg_current_session",
    default=None,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def cllg() -> LogSession:
    argv = list(sys.argv)
    command = _command_from_argv(argv)
    cwd = Path.cwd().resolve()
    opened_at = _utc_now()
    path = _unique_run_path(
        Path("logs").resolve() / opened_at.strftime("%Y-%m-%d"),
        f"{opened_at.strftime('%H%M%S')}-{_slug(command)}",
    )
    path.mkdir(parents=True)
    _write_json(
        path / "command.json",
        _command_metadata(
            command=command,
            argv=argv,
            cwd=cwd,
            opened_at=opened_at,
        ),
    )
    (path / "events.jsonl").touch()
    (path / "stdout.txt").touch()
    (path / "stderr.txt").touch()
    return LogSession(
        path=path,
    )


@dataclass(slots=True)
class LogSession(AbstractContextManager["LogSession"]):
    path: Path
    clock: Clock = _utc_now
    _original_stdout: TextIO | None = None
    _original_stderr: TextIO | None = None
    _stdout_file: TextIO | None = None
    _stderr_file: TextIO | None = None
    _context_token: Token[LogSession | None] | None = None

    def __enter__(self) -> LogSession:
        self._context_token = _CURRENT_SESSION.set(self)
        self._original_stdout = sys.stdout
        self._original_stderr = sys.stderr
        self._stdout_file = (self.path / "stdout.txt").open("a", encoding="utf-8")
        self._stderr_file = (self.path / "stderr.txt").open("a", encoding="utf-8")
        sys.stdout = _TeeTextIO(self._original_stdout, self._stdout_file)  # type: ignore[assignment]
        sys.stderr = _TeeTextIO(self._original_stderr, self._stderr_file)  # type: ignore[assignment]
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        try:
            if exc_value is not None:
                self.event(
                    "exception",
                    text=str(exc_value),
                    data={"exception_type": exc_type.__name__ if exc_type else None},
                )
        finally:
            self._restore_stdio()
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

    def _restore_stdio(self) -> None:
        if self._original_stdout is not None:
            sys.stdout = self._original_stdout
        if self._original_stderr is not None:
            sys.stderr = self._original_stderr
        if self._stdout_file is not None:
            self._stdout_file.close()
        if self._stderr_file is not None:
            self._stderr_file.close()
        if self._context_token is not None:
            _CURRENT_SESSION.reset(self._context_token)
            self._context_token = None


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


def current_session() -> LogSession | None:
    return _CURRENT_SESSION.get()


def output(*, human: str, agent: dict[str, Any]) -> None:
    _validate_output_payload(human=human, agent=agent)
    text = _agent_text(agent) if _json_mode() else human
    print(text)
    session = current_session()
    if session is not None:
        session.event("output", text=human, data=agent)


def progress(
    title: str,
    *,
    total: int | None = None,
    stream: TextIO | None = None,
) -> AbstractContextManager[ProgressTask]:
    session = current_session()
    sink = _make_progress_sink(json_mode=_json_mode(), stream=stream or sys.stderr)
    return _progress_task(session=session, sink=sink, title=title, total=total)


@dataclass(slots=True)
class ProgressTask:
    session: LogSession | None
    display: ProgressDisplay
    title: str
    total: int | None = None
    _current: int = 0

    @property
    def current(self) -> int:
        return self._current

    def message(
        self,
        *,
        human: str = "",
        agent: dict[str, Any] | None = None,
    ) -> None:
        agent_payload = _validate_agent_payload(agent or {})
        if self.session is not None:
            self.session.event(
                "progress_message",
                text=human,
                data=agent_payload,
                current=self._current,
                total=self.total,
            )
        self.display.message(human)

    def update(
        self,
        advance: int = 1,
        *,
        human: str = "",
        agent: dict[str, Any] | None = None,
    ) -> None:
        agent_payload = _validate_agent_payload(agent or {})
        self._current += advance
        if self.session is not None:
            self.session.event(
                "progress_advance",
                text=human,
                data=agent_payload,
                current=self._current,
                total=self.total,
                advance=advance,
            )
        self.display.update(advance=advance, text=human)


@contextmanager
def _progress_task(
    *,
    session: LogSession | None,
    sink: ProgressSink,
    title: str,
    total: int | None,
) -> Iterator[ProgressTask]:
    current = 0
    if session is not None:
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
            if session is not None:
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
        "env": {},
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


def _json_mode() -> bool:
    return "--json" in sys.argv


def _validate_output_payload(*, human: str, agent: dict[str, Any]) -> None:
    if not isinstance(human, str):
        raise TypeError("human output must be a string")
    _validate_agent_payload(agent)


def _validate_agent_payload(agent: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(agent, dict):
        raise TypeError("agent output must be a JSON object")
    _validate_string_keys(agent)
    try:
        json.dumps(agent, sort_keys=True)
    except TypeError as exc:
        raise TypeError("agent output must be JSON-serializable") from exc
    return agent


def _validate_string_keys(value: Any) -> None:
    if isinstance(value, dict):
        for key, nested_value in value.items():
            if not isinstance(key, str):
                raise TypeError("agent output must use string keys")
            _validate_string_keys(nested_value)
    elif isinstance(value, list):
        for item in value:
            _validate_string_keys(item)


def _agent_text(agent: dict[str, Any]) -> str:
    return json.dumps(agent, sort_keys=True)


def _command_from_argv(argv: list[str]) -> str:
    if not argv:
        return "command"
    return Path(argv[0]).name or "command"


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
