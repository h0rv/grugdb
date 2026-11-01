import ast
import shutil
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tools.course import BRANCH, EXERCISES, exercise_module, exercise_source, git, start


class TestCourse(unittest.TestCase):
    def test_scaffold_keeps_signature_fields_and_docstring(self) -> None:
        """Scaffolding removes exercise bodies without changing their declarations."""
        source = '''class Example[T]:
    value: T

    def read(self, /, *, count: int = 1) -> T:
        """Read a value."""
        # Reference implementation, never shown in a starter.
        return self.value

    def supplied(self) -> int: return 7
'''
        starter = exercise_source(source, {"Example": ("read",)})
        self.assertIn("def read(self, /, *, count: int=1) -> T:", starter)
        self.assertIn("Read a value.", starter)
        self.assertIn("value: T", starter)
        self.assertIn("NotImplementedError", starter)
        self.assertNotIn("return self.value", starter)
        self.assertNotIn("Reference implementation", starter)
        self.assertIn("def supplied(self) -> int: return 7", starter)
        ast.parse(starter)

    def test_one_line_exercise_is_supported(self) -> None:
        starter = exercise_source(
            "class Example:\n    def read(self): return 7\n", {"Example": ("read",)}
        )
        self.assertIn("NotImplementedError", starter)
        self.assertNotIn("return 7", starter)
        ast.parse(starter)

    def test_module_removes_only_unused_imports(self) -> None:
        source = '''from collections import deque
from itertools import islice


class Example:
    def read(self, /, *, count: int = 1) -> deque[int]:
        """Read some values."""
        return deque(islice(range(10), count))

    def supplied(self) -> int: return 7
'''
        targets = {"Example": ("read",)}
        scaffold = exercise_source(source, targets)
        starter = exercise_module(source, targets, "example.py")
        self.assertIn("from itertools import islice", scaffold)
        self.assertNotIn("from itertools import islice", starter)
        self.assertIn("from collections import deque", starter)
        self.assertIn("def supplied(self) -> int: return 7", starter)
        self.assertEqual(
            ast.dump(ast.parse(starter).body[-1]),
            ast.dump(ast.parse(scaffold).body[-1]),
        )
        self.assertEqual(exercise_module(starter, targets, "example.py"), starter)

    def test_exercise_modules_have_clean_imports_and_stable_stubs(self) -> None:
        project = Path(__file__).resolve().parents[1]
        for relative, targets in EXERCISES.items():
            with self.subTest(module=relative):
                path = project / relative
                source = path.read_text(encoding="utf-8")
                scaffold = exercise_source(source, targets)
                starter = exercise_module(source, targets, str(path))
                imported = {
                    alias.name
                    for node in ast.walk(ast.parse(starter))
                    if isinstance(node, ast.ImportFrom)
                    for alias in node.names
                }
                self.assertFalse(imported & {"islice", "Desc", "Scan"})
                self.assertEqual(
                    [
                        ast.dump(node)
                        for node in ast.parse(starter).body
                        if not isinstance(node, (ast.Import, ast.ImportFrom))
                    ],
                    [
                        ast.dump(node)
                        for node in ast.parse(scaffold).body
                        if not isinstance(node, (ast.Import, ast.ImportFrom))
                    ],
                )
                self.assertEqual(exercise_module(starter, targets, str(path)), starter)
                self.assertEqual(path.read_text(encoding="utf-8"), source)

    @unittest.skipUnless(shutil.which("git"), "Git is required")
    def test_start_stubs_exercises_on_a_branch_and_keeps_work(self) -> None:
        """Starting creates a stubbed branch once, then only switches back to it."""
        project = Path(__file__).resolve().parents[1]
        with TemporaryDirectory() as directory:
            root = Path(directory) / "course with spaces"
            for relative in [*EXERCISES, "pyproject.toml"]:
                (root / relative).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(project / relative, root / relative)
            git(root, "init", "--quiet", "--initial-branch", "main")
            git(root, "config", "user.name", "Test")
            git(root, "config", "user.email", "test@example.invalid")
            git(root, "config", "commit.gpgsign", "false")
            git(root, "add", ".")
            git(root, "commit", "--quiet", "-m", "Course fixture")
            reference = (root / "src/grugdb/table.py").read_text(encoding="utf-8")

            (root / "notes.txt").write_text("dirty", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Commit or stash"):
                start(root)
            (root / "notes.txt").unlink()

            self.assertTrue(start(root))
            self.assertEqual(git(root, "branch", "--show-current"), BRANCH)
            self.assertEqual(git(root, "status", "--porcelain"), "")
            path = root / "src/grugdb/table.py"
            starter = path.read_text(encoding="utf-8")
            self.assertIn("Exercise: Table.insert", starter)
            self.assertIn("from grugdb.query import Query", starter)
            self.assertNotIn("Scan", starter)
            self.assertNotIn(
                "from itertools import islice",
                (root / "src/grugdb/query.py").read_text(encoding="utf-8"),
            )
            self.assertEqual(git(root, "show", "main:src/grugdb/table.py") + "\n", reference)

            edited = starter.replace(
                'raise NotImplementedError("Exercise: Table.get")', 'raise RuntimeError("mine")'
            )
            path.write_text(edited, encoding="utf-8")
            git(root, "commit", "--quiet", "-am", "Learner work")
            git(root, "switch", "--quiet", "main")
            self.assertFalse(start(root))
            self.assertEqual(path.read_text(encoding="utf-8"), edited)


if __name__ == "__main__":
    unittest.main()
