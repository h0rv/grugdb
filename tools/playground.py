"""Build the browser's learner files from the same declarations as `poe start`."""

import ast
import json
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
from textwrap import dedent

from tools.course import EXERCISES, exercise_module, exercise_source

RUNTIME_TESTS = ("test_table", "test_query", "test_schema", "test_model_types", "test_exercises")
LESSON_TESTS = {
    1: (
        "test_table",
        (
            "test_insert_get",
            "test_insert_trusts_constructed_row",
            "test_wrong_row_class_is_rejected",
            "test_duplicate_rows_have_distinct_internal_ids",
            "test_update_constructs_replacement_once",
            "test_update_replaces_row",
            "test_invalid_update_preserves_old_row",
            "test_delete",
            "test_missing_ids_raise_key_error",
            "test_update_where_stages_validation",
            "test_delete_where",
            "test_scan_and_len_follow_successful_writes",
            "test_write_during_scan_invalidates_live_iteration",
        ),
    ),
    2: (
        "test_query",
        (
            "test_compare_operators",
            "test_ordering_comparison_with_none_is_false",
            "test_combinators_is_none_and_in",
            "test_where_select",
            "test_select_several_fields_yields_tuples",
            "test_where_select_empty",
            "test_where_preserves_duplicates_and_order",
            "test_queries_are_reusable_and_do_not_mutate_parents",
            "test_queries_read_current_rows_on_each_execution",
            "test_first_count",
            "test_where_and_select_are_lazy",
        ),
    ),
    3: (
        "test_query",
        (
            "test_joins_agree_and_keep_order",
            "test_joins_with_empty_or_unmatched_input",
            "test_duplicate_keys_produce_every_pair",
            "test_nested_join_consumes_right_once_per_execution",
            "test_none_keys_match_by_python_equality",
            "test_join_then_where_then_select",
            "test_self_join_field_is_ambiguous",
        ),
    ),
    4: (
        "test_query",
        (
            "test_limit_is_lazy",
            "test_limit_offset_consumes_only_requested_rows",
            "test_limit_beyond_end",
            "test_order_by_empty",
            "test_order_by_ascending_and_descending",
            "test_order_by_puts_none_last_ascending_and_first_descending",
            "test_order_by_is_stable",
            "test_order_by_several_keys",
            "test_group_by_aggregates",
            "test_group_by_keeps_first_seen_key_order",
            "test_aggregates_skip_none",
            "test_group_by_on_joined_rows",
            "test_group_by_empty",
        ),
    ),
}


EXERCISE_GROUPS = {
    "Table.insert": "TestInsert",
    "Table.get": "TestGet",
    "Table.update": "TestUpdate",
    "Table.delete": "TestDelete",
    "Table.update_where": "TestUpdateWhere",
    "Table.delete_where": "TestDeleteWhere",
    "Table.scan": "TestScan",
    "Table.__len__": "TestLen",
    "Compare.test": "TestCompare",
    "Where.__iter__": "TestWhere",
    "Select.__iter__": "TestSelect",
    "NestedLoopJoin.__iter__": "TestNestedLoopJoin",
    "HashJoin.__iter__": "TestHashJoin",
    "OrderBy.__iter__": "TestOrderBy",
    "GroupBy.__iter__": "TestGroupBy",
    "Limit.__iter__": "TestLimit",
}
EXERCISE_LESSONS = {
    "Table": 1,
    "Compare": 2,
    "Where": 2,
    "Select": 2,
    "NestedLoopJoin": 3,
    "HashJoin": 3,
    "OrderBy": 4,
    "GroupBy": 4,
    "Limit": 4,
}


@dataclass(frozen=True)
class Exercise:
    """An inline editor and its focused checks, with a range in the initial scaffold.

    Lines are one-based and inclusive in Workspace.files[file]. Source removes the
    shared class indentation; re-indent it before replacing that full-file range.
    Checks run against the whole learner workspace and can require earlier methods.
    """

    id: str
    file: str
    class_name: str
    method: str
    lesson: str
    tests: tuple[str, ...]
    start_line: int
    end_line: int
    source: str


@dataclass(frozen=True)
class Lesson:
    slug: str
    title: str
    file: str
    tests: tuple[str, ...]
    local: bool = False


@dataclass(frozen=True)
class Workspace:
    version: int
    revision: str
    files: dict[str, str]
    editable: tuple[str, ...]
    tests: tuple[str, ...]
    lessons: tuple[Lesson, ...]
    exercises: tuple[Exercise, ...]
    test_descriptions: dict[str, str]

    def json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2) + "\n"


def workspace_exercises(files: dict[str, str], lessons: tuple[Lesson, ...]) -> tuple[Exercise, ...]:
    """Locate every canonical assignment in the redacted files, never reference source."""
    lesson_slugs = {int(lesson.slug.partition("-")[0]): lesson.slug for lesson in lessons}
    exercises = []
    for file, targets in EXERCISES.items():
        lines = files[file].splitlines(keepends=True)
        classes = {
            node.name: node
            for node in ast.parse(files[file]).body
            if isinstance(node, ast.ClassDef)
        }
        for class_name, methods in targets.items():
            functions = {
                node.name: node
                for node in classes[class_name].body
                if isinstance(node, ast.FunctionDef)
            }
            number = EXERCISE_LESSONS[class_name]
            for method in methods:
                node = functions[method]
                if node.end_lineno is None:
                    raise ValueError(f"Missing source range for {class_name}.{method}")
                start = min([node.lineno, *(item.lineno for item in node.decorator_list)])
                exercise_id = f"{class_name}.{method}"
                exercises.append(
                    Exercise(
                        id=exercise_id,
                        file=file,
                        class_name=class_name,
                        method=method,
                        lesson=lesson_slugs[number],
                        tests=tuple(
                            f"tests.test_exercises.{EXERCISE_GROUPS[exercise_id]}.{node.name}"
                            for cls in ast.parse(files["tests/test_exercises.py"]).body
                            if isinstance(cls, ast.ClassDef)
                            and cls.name == EXERCISE_GROUPS[exercise_id]
                            for node in cls.body
                            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
                        ),
                        start_line=start,
                        end_line=node.end_lineno,
                        source=dedent("".join(lines[start - 1 : node.end_lineno])),
                    )
                )
    return tuple(exercises)


def learner_source(source: str, class_name: str | None = None, method: str | None = None) -> str:
    """Hide assigned bodies in source previews as well as in the editor."""
    targets = {name: methods for classes in EXERCISES.values() for name, methods in classes.items()}
    if class_name not in targets:
        return source
    if method is None:
        return exercise_source(source, {class_name: targets[class_name]})
    if method not in targets[class_name]:
        return source
    node = ast.parse(source).body[0]
    if not isinstance(node, ast.FunctionDef):
        return source
    node.body = [
        ast.Raise(
            exc=ast.Call(
                func=ast.Name(id="NotImplementedError", ctx=ast.Load()),
                args=[ast.Constant(value=f"Exercise: {class_name}.{method}")],
                keywords=[],
            ),
            cause=None,
        )
    ]
    return ast.unparse(node)


def workspace(root: Path) -> Workspace | None:
    """Include supplied Python and tests, never the reference exercise bodies."""
    if not all((root / path).is_file() for path in EXERCISES):
        return None
    paths = [*sorted((root / "src/grugdb").glob("*.py"))]
    paths.extend(root / f"tests/{name}.py" for name in RUNTIME_TESTS)
    paths.extend([root / "tests/__init__.py", root / "tests/typing/__init__.py"])
    paths.extend(sorted((root / "tests/typing").glob("models.py")))
    files: dict[str, str] = {}
    for path in paths:
        if path.is_file():
            relative = path.relative_to(root).as_posix()
            source = path.read_text(encoding="utf-8")
            files[relative] = (
                exercise_module(source, EXERCISES[relative], relative)
                if relative in EXERCISES
                else source
            )
    lessons = []
    for path in sorted((root / "chapters").glob("*.md")):
        number = int(path.name.partition("-")[0])
        if number == 0:
            continue
        title = next(
            line.removeprefix("# ")
            for line in path.read_text().splitlines()
            if line.startswith("# ")
        )
        file = "src/grugdb/table.py" if number == 1 else "src/grugdb/query.py"
        module, names = LESSON_TESTS.get(number, ("", ()))
        cls = "TestTable" if number == 1 else "TestQuery"
        tests = tuple(f"tests.{module}.{cls}.{name}" for name in names)
        lessons.append(Lesson(path.stem, title, file, tests, number in {5, 10, 11, 12}))
    tests = tuple(
        f"tests.{name}.{cls.name}.{method.name}"
        for name in RUNTIME_TESTS
        if (source := files.get(f"tests/{name}.py")) is not None
        for cls in ast.parse(source).body
        if isinstance(cls, ast.ClassDef)
        for method in cls.body
        if isinstance(method, ast.FunctionDef)
        and method.name.startswith("test_")
        and "second_process" not in method.name
    )
    descriptions = {
        f"tests.{name}.{cls.name}.{method.name}": (
            ast.get_docstring(method) or method.name.removeprefix("test_").replace("_", " ")
        )
        for name in RUNTIME_TESTS
        if (source := files.get(f"tests/{name}.py")) is not None
        for cls in ast.parse(source).body
        if isinstance(cls, ast.ClassDef)
        for method in cls.body
        if isinstance(method, ast.FunctionDef) and method.name.startswith("test_")
    }
    exercises = workspace_exercises(files, tuple(lessons))
    revision = sha256(
        json.dumps(
            {
                "files": files,
                "lessons": [asdict(lesson) for lesson in lessons],
                "exercises": [asdict(exercise) for exercise in exercises],
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    return Workspace(
        1,
        revision,
        files,
        tuple(path for path in files if path.startswith("src/")),
        tests,
        tuple(lessons),
        exercises,
        descriptions,
    )
