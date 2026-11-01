"""The website ships learner scaffolding and measures only the selected exercise."""

import ast
import json
import unittest
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from textwrap import indent
from unittest.mock import patch

from grugdb import Table
from grugdb.expr import Compare
from grugdb.query import GroupBy, HashJoin, Limit, NestedLoopJoin, OrderBy, Select, Where
from tools.course import EXERCISES
from tools.playground import EXERCISE_GROUPS, LESSON_TESTS, learner_source, workspace
from tools.site import Site

ROOT = Path(__file__).resolve().parents[1]


class TestPlayground(unittest.TestCase):
    def test_workspace_uses_canonical_stubs_not_reference_bodies(self) -> None:
        manifest = workspace(ROOT)
        self.assertIsNotNone(manifest)
        assert manifest is not None
        for path, targets in EXERCISES.items():
            classes = {
                node.name: node
                for node in ast.parse(manifest.files[path]).body
                if isinstance(node, ast.ClassDef)
            }
            for name, methods in targets.items():
                functions = {
                    node.name: node
                    for node in classes[name].body
                    if isinstance(node, ast.FunctionDef)
                }
                for method in methods:
                    body = functions[method].body
                    if ast.get_docstring(functions[method]) is not None:
                        body = body[1:]
                    self.assertEqual(len(body), 1, (path, name, method))
                    self.assertIsInstance(body[0], ast.Raise)
                    self.assertIn(f"Exercise: {name}.{method}", ast.unparse(body[0]))
        self.assertIn("tests/test_table.py", manifest.files)
        self.assertIn("tests/typing/models.py", manifest.files)
        self.assertNotIn("tools/site.py", manifest.files)
        self.assertNotIn("tests/test_playground.py", manifest.files)
        self.assertEqual(json.loads(manifest.json())["version"], 1)

    def test_lesson_checks_exist_and_exclude_unrelated_supplied_behavior(self) -> None:
        manifest = workspace(ROOT)
        assert manifest is not None
        self.assertEqual([len(lesson.tests) for lesson in manifest.lessons[:4]], [13, 11, 7, 13])
        for lesson in manifest.lessons:
            for test in lesson.tests:
                self.assertIn(test, manifest.tests)
        for lesson in manifest.lessons[4:]:
            self.assertEqual(lesson.tests, ())
        self.assertFalse(any("second_process" in test for test in manifest.tests))
        self.assertFalse(any("same_class_same_table" in test for test in manifest.lessons[0].tests))
        self.assertTrue(manifest.lessons[9].local)
        self.assertTrue(manifest.lessons[10].local)
        self.assertTrue(manifest.lessons[11].local)

    def test_changing_lesson_selectors_invalidates_persisted_test_results(self) -> None:
        original = workspace(ROOT)
        assert original is not None
        module, tests = LESSON_TESTS[1]
        with patch.dict(LESSON_TESTS, {1: (module, tests[:-1])}):
            changed = workspace(ROOT)
        assert changed is not None
        self.assertNotEqual(changed.revision, original.revision)

    def test_every_canonical_method_has_serializable_inline_metadata(self) -> None:
        manifest = workspace(ROOT)
        assert manifest is not None
        expected = [
            (f"{class_name}.{method}", file, class_name, method)
            for file, classes in EXERCISES.items()
            for class_name, methods in classes.items()
            for method in methods
        ]
        self.assertEqual(
            [(item.id, item.file, item.class_name, item.method) for item in manifest.exercises],
            expected,
        )
        payload = json.loads(manifest.json())
        self.assertEqual(len(payload["exercises"]), len(expected))
        for exercise, serialized in zip(manifest.exercises, payload["exercises"], strict=True):
            self.assertEqual(serialized["id"], exercise.id)
            self.assertEqual(serialized["source"], exercise.source)
            self.assertEqual(serialized["tests"], list(exercise.tests))
            lesson = next(item for item in manifest.lessons if item.slug == exercise.lesson)
            self.assertTrue(exercise.tests, exercise.id)
            self.assertEqual(len(exercise.tests), len(set(exercise.tests)))
            for test in exercise.tests:
                self.assertIn(test, manifest.tests)
                self.assertNotIn(test, lesson.tests)
        for lesson in manifest.lessons[:4]:
            focused = {
                test
                for exercise in manifest.exercises
                if exercise.lesson == lesson.slug
                for test in exercise.tests
            }
            self.assertTrue(focused)
            self.assertTrue(focused.isdisjoint(lesson.tests))

    def test_inline_ranges_cover_only_the_scaffold_method_and_preserve_docstrings(self) -> None:
        manifest = workspace(ROOT)
        assert manifest is not None
        for exercise in manifest.exercises:
            with self.subTest(exercise=exercise.id):
                lines = manifest.files[exercise.file].splitlines(keepends=True)
                self.assertGreaterEqual(exercise.start_line, 1)
                self.assertLessEqual(exercise.end_line, len(lines))
                self.assertGreaterEqual(exercise.end_line, exercise.start_line)
                full_source = "".join(lines[exercise.start_line - 1 : exercise.end_line])
                self.assertEqual(indent(exercise.source, "    "), full_source)
                nodes = ast.parse(exercise.source).body
                self.assertEqual(len(nodes), 1)
                method = nodes[0]
                assert isinstance(method, ast.FunctionDef)
                self.assertEqual(method.name, exercise.method)
                original_class = next(
                    node
                    for node in ast.parse((ROOT / exercise.file).read_text()).body
                    if isinstance(node, ast.ClassDef) and node.name == exercise.class_name
                )
                original = next(
                    node
                    for node in original_class.body
                    if isinstance(node, ast.FunctionDef) and node.name == exercise.method
                )
                self.assertEqual(ast.dump(method.args), ast.dump(original.args))
                self.assertTrue(ast.get_docstring(method), exercise.id)
                self.assertEqual(ast.get_docstring(method), ast.get_docstring(original))
                body = method.body[1:] if ast.get_docstring(method) is not None else method.body
                self.assertEqual(len(body), 1)
                self.assertIsInstance(body[0], ast.Raise)
                self.assertIn(f"Exercise: {exercise.id}", ast.unparse(body[0]))
                self.assertEqual(method.end_lineno, len(exercise.source.splitlines()))

    def test_method_checks_are_isolated_from_chapter_integration_checks(self) -> None:
        manifest = workspace(ROOT)
        assert manifest is not None
        for exercise in manifest.exercises:
            group = EXERCISE_GROUPS[exercise.id]
            self.assertTrue(exercise.tests)
            self.assertTrue(
                all(test.startswith(f"tests.test_exercises.{group}.") for test in exercise.tests)
            )
            lesson = next(item for item in manifest.lessons if item.slug == exercise.lesson)
            self.assertTrue(set(exercise.tests).isdisjoint(lesson.tests))

    def test_changing_focused_checks_invalidates_persisted_results(self) -> None:
        original = workspace(ROOT)
        assert original is not None
        with patch.dict(EXERCISE_GROUPS, {"Table.insert": "TestGet"}):
            changed = workspace(ROOT)
        assert changed is not None
        self.assertEqual(changed.files, original.files)
        self.assertEqual(changed.lessons, original.lessons)
        self.assertNotEqual(changed.revision, original.revision)
        self.assertNotEqual(changed.exercises, original.exercises)

    def test_each_focused_group_passes_with_every_other_method_stubbed(self) -> None:
        owners = {
            "Table": Table,
            "Compare": Compare,
            "Where": Where,
            "Select": Select,
            "NestedLoopJoin": NestedLoopJoin,
            "HashJoin": HashJoin,
            "OrderBy": OrderBy,
            "GroupBy": GroupBy,
            "Limit": Limit,
        }
        for exercise, group in EXERCISE_GROUPS.items():
            with self.subTest(exercise=exercise), ExitStack() as stack:
                for classes in EXERCISES.values():
                    for name, methods in classes.items():
                        for method in methods:
                            if f"{name}.{method}" != exercise:
                                stack.enter_context(
                                    patch.object(
                                        owners[name],
                                        method,
                                        side_effect=NotImplementedError("Other exercise"),
                                    )
                                )
                suite = unittest.defaultTestLoader.loadTestsFromName(
                    f"tests.test_exercises.{group}"
                )
                result = unittest.TestResult()
                suite.run(result)
                self.assertGreater(result.testsRun, 0)
                self.assertTrue(
                    result.wasSuccessful(), f"{exercise}: {result.errors} {result.failures}"
                )

    def test_missing_course_sources_do_not_create_an_empty_playground(self) -> None:
        with TemporaryDirectory() as directory:
            self.assertIsNone(workspace(Path(directory)))

    def test_source_previews_redact_assigned_class_and_method_bodies(self) -> None:
        source = (ROOT / "src/grugdb/table.py").read_text()
        cls = next(node for node in ast.parse(source).body if isinstance(node, ast.ClassDef))
        preview = learner_source(ast.unparse(cls), "Table")
        self.assertIn("Exercise: Table.insert", preview)
        self.assertNotIn("self._rows[row_id] = row", preview)
        standalone = learner_source(
            "def scan(self):\n    return SECRET_SOLUTION\n", "Table", "scan"
        )
        self.assertIn("Exercise: Table.scan", standalone)
        self.assertNotIn("SECRET_SOLUTION", standalone)
        supplied = "def lookup(self):\n    raise NotImplementedError\n"
        self.assertEqual(learner_source(supplied, "Table", "lookup"), supplied)

    def test_built_site_contains_editor_files_and_no_table_solution_in_previews(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory)
            Site(ROOT, output).build()
            page = (output / "01-rows-and-tables.html").read_text()
            self.assertIn('data-course data-lesson="01-rows-and-tables"', page)
            self.assertIn('type="module" src="workspace.js?v=', page)
            self.assertNotIn('type="checkbox"', page)
            self.assertNotIn("self._rows[row_id] = row", page)
            self.assertTrue((output / "workspace.json").is_file())
            self.assertTrue((output / "python-worker.js").is_file())
            self.assertFalse((output / "test-playground.html").exists())


if __name__ == "__main__":
    unittest.main()
