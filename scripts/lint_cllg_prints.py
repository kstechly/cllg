from __future__ import annotations

import ast
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    roots = [Path(arg) for arg in (sys.argv[1:] if argv is None else argv)]
    if not roots:
        roots = [Path("examples"), Path("src")]

    violations: list[str] = []
    for path in _python_files(roots):
        if _is_allowed_print_path(path):
            continue
        violations.extend(_print_violations(path))

    if violations:
        sys.stdout.write("\n".join(violations) + "\n")
        return 1
    return 0


def _python_files(roots: list[Path]) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        if root.is_file() and root.suffix == ".py":
            files.append(root)
        elif root.is_dir():
            files.extend(sorted(root.rglob("*.py")))
    return files


def _is_allowed_print_path(path: Path) -> bool:
    parts = path.resolve().parts
    return "tests" in parts or ("src" in parts and "cllg" in parts)


def _print_violations(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _is_print_call(node.func):
            violations.append(f"{path}:{node.lineno}: use cllg.output(...) instead of print(...)")
    return violations


def _is_print_call(func: ast.expr) -> bool:
    return isinstance(func, ast.Name) and func.id == "print"


if __name__ == "__main__":
    raise SystemExit(main())
