import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import test from "node:test";
import { normalizeSavedImports } from "./imports.js";

const supplied = "  # noqa: F401  # supplied for exercises";

test("normalizes only actual single-dot imports and preserves other bytes", () => {
  const source = '"""from .query import Query, Scan\nfrom . import Fake"""\r\n'
    + '# from .query import Scan\r\n'
    + 'text = "from .expr import Desc"\r\n'
    + 'formatted = f"from .query import Scan {1}"\r\n'
    + 'from .query import Query\r\n'
    + 'from . import table as tables\r\n'
    + 'from ..query import Query\r\n'
    + 'from grugdb.model import Row\r\n'
    + '\r\nclass Table:\r\n\tdef scan(self, count=7):\r\n\t\treturn ["🦕", count * 3]  # learner\r\n';
  const expected = source.replace('from .query import Query\r\n', 'from grugdb.query import Query\r\n')
    .replace('from . import table as tables\r\n', 'from grugdb import table as tables\r\n');
  assert.equal(normalizeSavedImports(source), expected);
});

test("marks only the known imported helper names, including aliases", () => {
  const source = 'from itertools import islice as take\n'
    + 'from .expr import Desc as Descending\n'
    + 'from .query import Scan as Source\n'
    + 'from grugdb.query import Something as Scan\n'
    + 'from itertools import chain as islice\n'
    + 'from learner import Desc\n'
    + 'import itertools\n';
  const expected = 'from itertools import islice as take' + supplied + '\n'
    + 'from grugdb.expr import Desc as Descending' + supplied + '\n'
    + 'from grugdb.query import Scan as Source' + supplied + '\n'
    + 'from grugdb.query import Something as Scan\n'
    + 'from itertools import chain as islice\n'
    + 'from learner import Desc\n'
    + 'import itertools\n';
  assert.equal(normalizeSavedImports(source), expected);
  assert.equal(normalizeSavedImports(expected), expected);
});

test("legacy mixed imports use original starter provenance", () => {
  const starter = 'from grugdb.query import Query, Scan\n'
    + 'from grugdb.expr import Aggregate, Desc, Expr, Field, JoinOn, SortKey\n';
  const source = starter.replaceAll('from grugdb.', 'from .')
    + '\nclass Table:\n    def scan(self):\n        return [42]\n';
  const expected = starter.split('\n').filter(Boolean).map((line) => line + supplied + '\n').join('')
    + '\nclass Table:\n    def scan(self):\n        return [42]\n';
  assert.equal(normalizeSavedImports(source, starter), expected);
  assert.equal(normalizeSavedImports(source), source.replaceAll('from .', 'from grugdb.'));
});

test("does not suppress learner additions to supplied import statements", () => {
  const starter = 'from grugdb.query import Query, Scan\n';
  const source = 'from .query import Query, Scan, LearnerHelper\n';
  assert.equal(normalizeSavedImports(source, starter), 'from grugdb.query import Query, Scan, LearnerHelper\n');
  assert.equal(normalizeSavedImports('from itertools import islice, chain\n'), 'from itertools import islice, chain\n');
});

test("parenthesized imports retain layout, commas, aliases and comments", () => {
  const source = 'from .query import (\r\n'
    + '    Query,  # keep this\r\n'
    + '    Scan as Walker,  # saved note\r\n'
    + ')\r\n';
  const expected = 'from grugdb.query import (\r\n'
    + '    Query,  # keep this\r\n'
    + '    Scan as Walker,  # saved note' + supplied + '\r\n'
    + ')\r\n';
  assert.equal(normalizeSavedImports(source), expected);
  assert.equal(normalizeSavedImports(expected), expected);
});

test("noqa on the first line must not hide learner imports on later lines", () => {
  const source = 'from .query import (Scan,\n    LearnerHelper,\n)\n';
  assert.equal(normalizeSavedImports(source), source.replace('from .', 'from grugdb.'));
});

test("preserves existing comments and extends a specific existing noqa", () => {
  const source = 'from itertools import islice # noqa: E501  # keep\n';
  const expected = 'from itertools import islice # noqa: E501, F401  # keep  # supplied for exercises\n';
  assert.equal(normalizeSavedImports(source), expected);
  assert.equal(normalizeSavedImports(expected), expected);
  for (const comment of ['# noqa', '# noqa: F401', '# noqa: E501, F401']) {
    const already = `from itertools import islice ${comment}\n`;
    assert.equal(normalizeSavedImports(already), already);
  }
});

test("incomplete Python and imports remain untouched", () => {
  for (const source of [
    'from .query import (Scan,\n',
    'from .query import Scan as',
    'from .query import Scan,',
    'from .query import Scan garbage\n',
    'from .query import Scan\nclass Table:\n    def scan(',
    '"""from .query import Scan\n',
  ]) assert.equal(normalizeSavedImports(source), source);
});

test("wildcards normalize without adding suppression", () => {
  assert.equal(normalizeSavedImports('from .query import *\n'), 'from grugdb.query import *\n');
});

test("semicolon groups and backslash continuations do not gain broad ignores", () => {
  const source = 'from .query import Scan; import os\n'
    + 'from itertools import \\\n    islice\n';
  assert.equal(normalizeSavedImports(source), source.replace('from .query', 'from grugdb.query'));
});

test("a multiline alias is preserved without an ineffective noqa", () => {
  const source = 'from .query import (\n    Scan as\n    Walker,\n)\n';
  assert.equal(normalizeSavedImports(source), source.replace('from .query', 'from grugdb.query'));
});

const ruff = spawnSync('ruff', ['--version'], { encoding: 'utf8' });
test("Ruff ignores supplied helpers but still reports arbitrary learner imports", { skip: Boolean(ruff.error) }, () => {
  const starter = 'from grugdb.query import Query, Scan\n';
  const source = 'from .query import Query, Scan\n'
    + 'from .expr import (\n    Desc as D,\n    LearnerExpr,\n)\n'
    + 'from itertools import islice as take # original note\n'
    + 'from itertools import chain\n'
    + 'from grugdb.query import Something as Scan\n';
  const normalized = normalizeSavedImports(source, starter);
  const result = spawnSync('ruff', [
    'check', '--isolated', '--select', 'F401', '--output-format', 'json',
    '--stdin-filename', 'src/grugdb/saved.py', '-',
  ], { input: normalized, encoding: 'utf8' });
  assert.equal(result.status, 1, result.stderr);
  const diagnostics = JSON.parse(result.stdout);
  assert.deepEqual(diagnostics.map((diagnostic) => diagnostic.message), [
    '`grugdb.expr.LearnerExpr` imported but unused',
    '`itertools.chain` imported but unused',
    '`grugdb.query.Something` imported but unused',
  ]);
});
