from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version as _pkg_version

from cllg.core import cllg, print, progress

try:
    __version__ = _pkg_version("cllg")
except PackageNotFoundError:
    __version__ = "0.0.0+unknown"

__all__ = [
    "__version__",
    "cllg",
    "print",
    "progress",
]
