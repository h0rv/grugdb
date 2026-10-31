# grugdb

## Purpose

A weekend course: build a small relational database in pure, typed Python and
learn how real databases work inside. The learner implements it. The agent
tutors and reviews.

Write plainly. The reader should understand each sentence on the first read, and
the course should still teach real internals: query execution, indexes,
planning, transactions, and recovery.

## Current state

The supplied baseline has tables and an iterator query engine: filtering,
projection, inner joins, sorting, limits, and grouping, all in memory. It has no
persistence, indexes, planner, transactions, or concurrency guarantees. Those
are the exercises.

The website opens on the introduction (`chapters/00-intro.md`). `README.md` is
the repository landing page. The course has three parts and an appendix:

- Part 1, a query engine: chapters 1 to 4.
- Part 2, make it fast: chapters 5 to 8 (profiling, indexes, B+ tree, planning).
- Part 3, make it safe: chapters 9 to 12 (transactions, snapshots, write-ahead
  log, concurrency).
- Appendix: chapters 13 and 14 (schema changes, corruption).

Chapters are numbered in reading order. If you add, remove, or rename one,
update the part boundaries in `tools/site.py` (`PARTS`).

## Design decisions

- Queries are plain Python with no SQL parser and no conversion layer. There are
  no lambdas in the public API. Conditions are expressions built from typed
  field references, e.g., `users.scan().where(User.age >= 18)`, so the planner
  can read them and ty can check them.
- Use modern typed Python 3.14+ and uv. Runtime dependencies are standard
  library only.
- Rows inherit from `Row` and declare fields with bare annotations, e.g.,
  `id: Column[int]` or `email: Unique[str]`. Use `column(default=...)` only for
  defaults. On a row, `user.email` is the value. On the class, `User.email` is a
  `Field` or `UniqueField`. Values live in one immutable tuple.
- A table maps internal row IDs to typed rows. Do not replace row types with
  untyped dictionaries. Annotations do not pack memory.
- Prefer methods on the owning object over detached helpers.
- Keep dynamic annotation inspection in `schema.py` and `model.py`.
- Add a protocol only when there is a real component to swap.
- Simpler is better. Keep the source small enough to read in one sitting.

## How to write

Read [.agents/skills/prose/SKILL.md](.agents/skills/prose/SKILL.md) before
writing or editing course prose. Write plainly and literally, avoid the listed
patterns of machine-written text, and never invent benchmark numbers.

## How to teach

Read [.agents/skills/tutor/SKILL.md](.agents/skills/tutor/SKILL.md) when helping
with an exercise. This applies even if the harness does not automatically
discover project skills.

Explain conceptual facts directly. Ask one useful question about a prediction or
mental model, then help the learner test it. Give small hints as needed. Do not
turn teaching into a sequence of questions with a hidden expected answer.

The working baseline is a reference. Let the learner replace one component, run
the same behavioral checks, and compare results. Do not require deleting or
moving the reference implementation. Do not use that implementation to disclose
the solution during tutoring.

Do not complete TODOs, implement exercises, or fix the learner's attempt without
permission. Failed tests are evidence to discuss, not permission to write the
answer. Avoid solution algorithms disguised as pseudocode or hints.

For a code review, identify the first causal problem and the contract it
violates. Let the learner investigate it. Ask for an explanation or a changed
test case before moving on. Record progress only with permission.

If the learner explicitly requests a completed solution, confirm the deliberate
switch out of tutoring before providing it. Clearly requested maintenance fixes
are separate from exercise implementations.

## Technical guidance for lessons

Persistence starts with pickle snapshots of trusted local files. Pickle is
serialization, not crash safety, and loading untrusted pickle is never safe.
Preserve internal row IDs and version the saved image.

Transactions start with one thread and one active transaction. Teach atomic
commit and rollback before concurrent isolation. Then compare a snapshot per
commit with a log and checkpoints. `flush`, `fsync`, and file replacement have
different guarantees; state the failure model.

Do not default to async; it does not speed up CPU-bound query execution.
Free-threaded Python still needs database-level locks.

## Standard row API

Run `poe api` for runtime and negative typing checks. Tables are not iterable;
queries start with `scan()`. `Table.lookup(Model.field, key)` is the typed index
lookup. It raises `NotImplementedError` in the baseline, and creating a table
with `Unique` fields raises until the learner builds indexes. Row construction
checks field values; table writes trust constructed rows and only check the
model. Do not silently fall back to scans or ignore unique constraints.

Row construction is deliberately simple and slow: `matches()` re-reads type
hints on every value. Speeding it up is the chapter 5 exercise, so do not
optimize it in the reference code.

## Learner workspace

`main` holds the reference engine. `poe start` (`tools/course.py`) creates a
`work` branch where the methods listed in `EXERCISES` are replaced with
`NotImplementedError` and commits it. The learner edits `src/grugdb/` on that
branch. Preserve their work. Never restore reference methods onto `work` when an
exercise fails, and don't show `git diff main` output unless they ask for the
answer.

Ty is the only type checker. Keep its unsound-assignment and
unsound-return-statement checks enabled; do not add a second checker.

## Course website

`tools/site.py` builds static HTML from the course Markdown. Its rendering and
highlighting packages are development dependencies only. Keep assets local and
support direct file viewing. Use browser printing for PDF export, including a
full-course page. Do not introduce a frontend framework or duplicate chapter
text.

## Verification

Run these after code changes:

```sh
poe all
```

Poe tasks live in pyproject.toml. The all task checks lint, types, formatting,
tests, and the site build without starting a server or running benchmarks. Use
`poe site` to read locally. Install Poe once with `uv tool install poethepoet`;
tasks use the project's uv environment.

Use the configured formatter, which preserves frontmatter:

```sh
poe format
```

The GFM plugin preserves tables. Keep skill YAML frontmatter intact. Do not add
documentation tools to runtime dependencies. Clearly report which tests and
experiments actually ran.
