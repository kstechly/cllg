from __future__ import annotations

import json
import os
import platform
import socket
import subprocess
import sys
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import TracebackType
from typing import Any, Callable, TextIO

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
    session = LogSession(
        command=command,
        argv=list(sys.argv if argv is None else argv),
        log_root=Path(log_root),
        cwd=(Path.cwd() if cwd is None else Path(cwd)).resolve(),
        clock=clock,
        env_keys=env_keys,
    )
    session.open()
    return session


@dataclass(slots=True)
class LogSession(AbstractContextManager["LogSession"]):
    command: str
    argv: list[str]
    log_root: Path
    cwd: Path
    clock: Clock = _utc_now
    env_keys: tuple[str, ...] = ()
    path: Path | None = None

    def open(self) -> None:
        opened_at = self.clock()
        self.path = _unique_run_path(
            self.log_root / opened_at.strftime("%Y-%m-%d"),
            f"{opened_at.strftime('%H%M%S')}-{_slug(self.command)}",
        )
        self.path.mkdir(parents=True)
        self._write_json(
            self.path / "command.json",
            _command_metadata(
                command=self.command,
                argv=self.argv,
                cwd=self.cwd,
                clock=self.clock,
                env_keys=self.env_keys,
            ),
        )
        (self.path / "events.jsonl").touch()

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
        with (self._require_path() / "events.jsonl").open("a", encoding="utf-8") as file:
            file.write(json.dumps(event, sort_keys=True) + "\n")

    def write_json_artifact(self, name: str, payload: Any) -> Path:
        path = self._artifact_path(name)
        self._write_json(path, payload)
        self.event("artifact", text=name, data={"path": str(path)})
        return path

    def _artifact_path(self, name: str) -> Path:
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"artifact name must be relative to the log session: {name!r}")
        path = self._require_path() / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def _require_path(self) -> Path:
        if self.path is None:
            raise RuntimeError("log session is not open")
        return self.path

    @staticmethod
    def _write_json(path: Path, payload: Any) -> None:
        path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


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


@dataclass(slots=True)
class ProgressReporter:
    session: LogSession
    sink: ProgressSink

    def task(self, title: str, *, total: int | None = None) -> ProgressTask:
        return ProgressTask(
            session=self.session,
            sink=self.sink,
            title=title,
            total=total,
        )


@dataclass(slots=True)
class ProgressTask(AbstractContextManager["ProgressTask"]):
    session: LogSession
    sink: ProgressSink
    title: str
    total: int | None = None
    current: int = 0

    def __enter__(self) -> ProgressTask:
        self.session.event(
            "progress_start",
            text=self.title,
            current=self.current,
            total=self.total,
        )
        self.sink.start(title=self.title, total=self.total)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        self.session.event(
            "progress_finish",
            text=self.title,
            current=self.current,
            total=self.total,
        )
        self.sink.finish()
        return None

    def message(self, text: str, *, data: dict[str, Any] | None = None) -> None:
        self.session.event(
            "progress_message",
            text=text,
            data=data,
            current=self.current,
            total=self.total,
        )
        self.sink.message(text)

    def update(
        self,
        advance: int = 1,
        *,
        text: str = "",
        data: dict[str, Any] | None = None,
    ) -> None:
        self.current += advance
        self.session.event(
            "progress_advance",
            text=text,
            data=data,
            current=self.current,
            total=self.total,
            advance=advance,
        )
        self.sink.update(advance=advance, text=text)


class ProgressSink:
    def start(self, *, title: str, total: int | None) -> None:
        raise NotImplementedError

    def update(self, *, advance: int, text: str) -> None:
        raise NotImplementedError

    def message(self, text: str) -> None:
        raise NotImplementedError

    def finish(self) -> None:
        raise NotImplementedError


class NoopProgressSink(ProgressSink):
    def start(self, *, title: str, total: int | None) -> None:
        return None

    def update(self, *, advance: int, text: str) -> None:
        return None

    def message(self, text: str) -> None:
        return None

    def finish(self) -> None:
        return None


class AliveProgressSink(ProgressSink):
    def __init__(self, stream: TextIO) -> None:
        self._stream = stream
        self._manager: Any = None
        self._bar: Any = None

    def start(self, *, title: str, total: int | None) -> None:
        from alive_progress import alive_bar

        self._manager = alive_bar(
            total,
            title=title,
            file=self._stream,
            enrich_print=True,
            dual_line=True,
            receipt=True,
        )
        self._bar = self._manager.__enter__()

    def update(self, *, advance: int, text: str) -> None:
        if self._bar is None:
            return
        if text:
            self._set_text(text)
        self._bar(advance)

    def message(self, text: str) -> None:
        if self._bar is not None and text:
            self._set_text(text)

    def finish(self) -> None:
        if self._manager is not None:
            self._manager.__exit__(None, None, None)
        self._manager = None
        self._bar = None

    def _set_text(self, text: str) -> None:
        text_attr = getattr(self._bar, "text", None)
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
    clock: Clock,
    env_keys: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "command": command,
        "argv": argv,
        "cwd": str(cwd),
        "timestamp": clock().isoformat(),
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
        return {
            "repo_root": None,
            "commit": None,
            "short_commit": None,
            "branch": None,
            "dirty": False,
            "status_short": [],
        }
    commit = _git(cwd, "rev-parse", "HEAD")
    branch = _git(cwd, "rev-parse", "--abbrev-ref", "HEAD")
    status_short = (_git(cwd, "status", "--short") or "").splitlines()
    return {
        "repo_root": repo_root,
        "commit": commit,
        "short_commit": commit[:8] if commit is not None else None,
        "branch": branch,
        "dirty": bool(status_short),
        "status_short": status_short,
    }


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
