"""Start the grugdb exercises on a git branch."""

import ast
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from textwrap import indent

EXERCISES = {
    "src/grugdb/table.py": {
        "Table": (
            "insert",
            "get",
            "update",
            "delete",
            "update_where",
            "delete_where",
            "scan",
            "__len__",
        ),
    },
    "src/grugdb/expr.py": {"Compare": ("test",)},
    "src/grugdb/query.py": dict.fromkeys(
        ("Where", "Select", "NestedLoopJoin", "HashJoin", "OrderBy", "GroupBy", "Limit"),
        ("__iter__",),
    ),
}
BRANCH = "work"


def git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()


def exercise_source(source: str, targets: Mapping[str, tuple[str, ...]]) -> str:
    """Keep signatures and docstrings, replacing only the assigned method bodies."""
    classes = {node.name: node for node in ast.parse(source).body if isinstance(node, ast.ClassDef)}
    changes: list[tuple[int, int, str]] = []
    for name, methods in targets.items():
        functions = {
            node.name: node for node in classes[name].body if isinstance(node, ast.FunctionDef)
        }
        for method in methods:
            node = functions[method]
            if node.end_lineno is None:
                raise ValueError(f"Missing source range for {name}.{method}")
            docstring = node.body[:1] if ast.get_docstring(node) is not None else []
            node.body = [
                *docstring,
                ast.Raise(
                    exc=ast.Call(
                        func=ast.Name(id="NotImplementedError", ctx=ast.Load()),
                        args=[ast.Constant(value=f"Exercise: {name}.{method}")],
                        keywords=[],
                    ),
                    cause=None,
                ),
            ]
            start = min([node.lineno, *(decorator.lineno for decorator in node.decorator_list)]) - 1
            changes.append(
                (start, node.end_lineno, indent(ast.unparse(node), " " * node.col_offset) + "\n")
            )
    lines = source.splitlines(keepends=True)
    for start, end, replacement in sorted(changes, reverse=True):
        lines[start:end] = [replacement]
    return "".join(lines)


def start(root: Path) -> bool:
    """Switch to the exercise branch, creating it with stubbed methods the first time.

    Returns True if the branch was created.
    """
    branches = git(root, "branch", "--list", BRANCH)
    if branches:
        git(root, "switch", BRANCH)
        return False
    if git(root, "status", "--porcelain"):
        raise ValueError("Commit or stash your changes first")
    git(root, "switch", "-c", BRANCH)
    for relative, targets in EXERCISES.items():
        path = root / relative
        path.write_text(exercise_source(path.read_text(encoding="utf-8"), targets), "utf-8")
    subprocess.run(
        [sys.executable, "-m", "ruff", "format", *(str(root / path) for path in EXERCISES)],
        check=True,
        capture_output=True,
        text=True,
    )
    git(root, "add", "--", *EXERCISES)
    git(
        root,
        "-c",
        "user.name=grugdb",
        "-c",
        "user.email=course@example.invalid",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "--quiet",
        "-m",
        "Start exercises",
    )
    return True


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    try:
        created = start(root)
    except (ValueError, subprocess.CalledProcessError) as error:
        detail = error.stderr if isinstance(error, subprocess.CalledProcessError) else str(error)
        sys.exit(f"{detail}".strip())
    print(f"{'Created' if created else 'Switched to'} branch '{BRANCH}'.")
    print("Edit src/grugdb/ and run `poe test`. Peek at the reference with")
    print("`git diff main -- src/grugdb/query.py`, and get course updates with `git merge main`.")


if __name__ == "__main__":
    main()
