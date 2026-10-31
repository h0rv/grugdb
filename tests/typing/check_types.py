"""Check that deliberately invalid public API uses remain type errors."""

import re
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory


def main() -> None:
    directory = Path(__file__).resolve().parent
    root = directory.parents[1]
    source = (directory / "negative.py.txt").read_text(encoding="utf-8")
    expected = {
        number for number, line in enumerate(source.splitlines(), start=1) if "# error" in line
    }
    with TemporaryDirectory(prefix="grugdb-typing-") as temporary:
        path = Path(temporary) / "negative.py"
        path.write_text(source, encoding="utf-8")
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "ty",
                "check",
                "--extra-search-path",
                str(root),
                "--output-format",
                "concise",
                str(path),
            ],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
    found = {
        int(match[1])
        for match in re.finditer(r"^.*:(\d+):\d+: error\[", result.stdout, re.MULTILINE)
    }
    if result.returncode != 1 or found != expected:
        print(result.stdout, end="")
        print(result.stderr, end="", file=sys.stderr)
        raise SystemExit(f"Expected errors on lines {sorted(expected)}, found {sorted(found)}")
    print(f"PASS: all {len(expected)} invalid usage cases rejected")


if __name__ == "__main__":
    main()
