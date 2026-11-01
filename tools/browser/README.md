# Browser workspace

Learners edit assigned methods in the lesson. Edits autosave immediately. After
a pause, lint, type checks, and relevant tests run automatically, along with the
chapter tests. The chapter test summary appears immediately after the assigned
editors. Open full file shows an optional right-side editor. The Files button
toggles its file tree without moving. Full screen hides the lesson. Close editor
returns to the lesson. Import backup and Export backup sit below the file tree.
Both views edit the same files.

CodeMirror editors use standard keys by default. Learners can change the key
bindings in Settings in the sidebar. Help contains shortcuts and local commands.
Lesson blocks marked `local-only` appear in Help rather than in the lesson.

The website runs learner Python with Pyodide in a fresh Web Worker for each test
run. Ty and Ruff check edits automatically in a separate worker. All runtime
assets are served from the course site. There is no execution server, account
service, or browser shell. The commands below run locally.

## Build and test

<!-- local-only:start -->

Install Node 24 or newer alongside the existing Python development tools.

```sh
poe browser         # build the browser assets and open the course
poe browser-test    # check the editor, WASM tools, and complete workspace
```

Browser tests build in temporary directories, not the served site. For visual
review, use `uv run python -m tools.site --output /tmp/grugdb-preview --serve`.
Check desktop and phone-sized screenshots before replacing the served build.

The browser tests use Playwright Chromium. Install it once if needed:

```sh
cd tools/browser
npx playwright install chromium
```

To use an installed Chrome instead, set `PLAYWRIGHT_CHANNEL=chrome` when running
the browser tests.

`poe build` still builds the readable course without Node. Build the browser
assets first to include the editor and runtimes. The Pages workflow does both.
The generated `tools/site/vendor/` directory is ignored by Git.

<!-- local-only:end -->

## Files and progress

`tools/playground.py` uses `tools/course.py` to remove the assigned bodies. It
packages the supplied Python and tests into `workspace.json`. The editor and
local exercises therefore start with the same stubs. API source previews also
hide assigned bodies.

The browser autosaves source edits in IndexedDB. Supplied tests remain
read-only. Clearing site data removes the saved edits, and edits do not sync
between devices. Download a backup before leaving if autosave fails. A JSON
backup contains the edits, not a complete project, and can be imported in
another browser. A ZIP contains the complete Python project files, including the
supplied tests. The ZIP can be extracted over a local `work` branch. Keep any
existing local edits before replacing files.

Lesson progress records exact test outcomes for the current source version.
Changing any source file invalidates the old results. Supplied tests cover the
first four exercises. Later lessons do not receive a completion score from
unrelated tests. The browser editor uses the supplied files. Learners create new
modules and tests locally for later chapters. These results are learning
feedback, not tamper-proof grades.

Performance measurements and exercises about disk durability, subprocess
crashes, and threads still require local CPython.

## Pinned tools

Dependencies and Pyodide 314.0.7 are pinned in `package-lock.json`. Pyodide runs
CPython 3.14.2, including `annotationlib`.

Ty does not publish its browser WASM package on npm. For this spike, `build.mjs`
downloads hash-pinned assets from the official Ty playground and extracts its
standalone WASM bindings. This depends on those exact playground assets staying
available. A maintained distribution or a build from pinned source would be
preferable before relying on it long term. A failed integrity check stops the
build rather than substituting another checker.

Ruff uses the official `@astral-sh/ruff-wasm-web` package. Both tools use the
course's rules. Ty keeps `unsound-assignment` and `unsound-return-statement`
enabled. Tool failures are shown separately from clean checks.

Upstream license files are copied alongside the generated browser assets.
