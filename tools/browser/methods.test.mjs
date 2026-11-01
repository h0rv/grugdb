import assert from "node:assert/strict";
import { after, before, describe, test } from "node:test";
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { chromium } from "@playwright/test";
import { findMethod, applyMethodEdit, replaceMethod } from "./methods.js";

const fixture = `# café 🦊
class Box[T]:
    """A container."""

    @decorate(
        "value",
    )
    async def selected(
        self,
        value: T,
    ) -> T:
        """Keep a multiline docstring.

        It includes def fake(self): and class Pretend.
        """
        return value


    # This belongs to the next method.
    @other
    def next(self):
        pass

outside = 3
`;

function assertOutsideUnchanged(source, range, result) {
  assert.equal(result.source.slice(0, result.range.from), source.slice(0, range.from));
  assert.equal(result.source.slice(result.range.to), source.slice(range.to));
  assert.equal(result.range.length, result.range.to - result.range.from);
}

test("generic class, async method, decorators, multiline signature/docstring and source coordinates", () => {
  const range = findMethod(fixture, "Box", "selected");
  assert.ok(range);
  assert.equal(range.startLine, 5);
  assert.equal(range.indent, "    ");
  assert.ok(range.code.startsWith('@decorate(\n    "value",\n)\nasync def selected('));
  assert.ok(range.code.endsWith("    return value"));
  assert.equal(fixture.slice(range.to), "\n\n\n    # This belongs to the next method.\n    @other\n    def next(self):\n        pass\n\noutside = 3\n");
  assert.equal(findMethod(fixture, "Box", "fake"), null);
  assert.equal(findMethod(fixture, "Pretend", "fake"), null);
  assert.equal(applyMethodEdit(fixture, range, range.code).source, fixture);
});

test("replacement changes only the method, preserving separators and the next decorator", () => {
  const range = findMethod(fixture, "Box", "selected");
  const snippet = "def selected(self):\n    # An editable draft.\n    pass\n\n    # More draft text.\n";
  const result = replaceMethod(fixture, "Box", "selected", snippet);
  assertOutsideUnchanged(fixture, range, result);
  assert.equal(result.range.code, snippet);
  assert.equal(result.range.startLine, range.startLine);
  assert.equal(findMethod(result.source, "Box", "next").code, findMethod(fixture, "Box", "next").code);
});

test("known ranges survive arbitrary incomplete edits, renames, deletion and recovery", () => {
  let source = fixture, range = findMethod(source, "Box", "selected");
  for (const snippet of ["d", "def renamed(", "def renamed(self):\n    value = (", 'def renamed(self):\n    """unfinished', "", "\n", "def selected(self):\n    pass"]) {
    const result = applyMethodEdit(source, range, snippet);
    assertOutsideUnchanged(source, range, result);
    assert.equal(result.range.code, snippet);
    source = result.source;
    range = result.range;
  }
  assert.equal(findMethod(source, "Box", "selected").code, range.code);
});

for (const draft of ["def renamed(self):\n    pass", "", 'def selected(self):\n    """unfinished']) {
  test(`one-shot target loss keeps the complete draft: ${JSON.stringify(draft)}`, () => {
    let error;
    try { replaceMethod(fixture, "Box", "selected", draft); } catch (caught) { error = caught; }
    assert.equal(error?.code, "METHOD_TARGET_LOST");
    assert.equal(error.range.code, draft);
    assertOutsideUnchanged(fixture, findMethod(fixture, "Box", "selected"), { source: error.source, range: error.range });
    const recovered = applyMethodEdit(error.source, error.range, "def selected(self):\n    pass");
    assert.ok(findMethod(recovered.source, "Box", "selected"));
  });
}

for (const body of ["return", "return bad +", "value = (", "return (", "if:", "value =", "def nested(:\n            pass"]) {
  test(`body recovery does not consume the next method or its decorator: ${JSON.stringify(body)}`, () => {
    const source = `class Box:\n    def selected(self):\n        ${body}\n\n    @other\n    def next(self):\n        pass\n`;
    const range = findMethod(source, "Box", "selected");
    assert.ok(range);
    assert.equal(range.code, `def selected(self):\n    ${body.replaceAll("\n    ", "\n")}`);
    const next = findMethod(source, "Box", "next");
    assert.ok(next);
    assert.equal(next.code, "@other\ndef next(self):\n    pass");
    const result = replaceMethod(source, "Box", "selected", "def selected(self):\n    pass");
    assertOutsideUnchanged(source, range, result);
  });
}

test("closed strings, f-strings and comments cannot produce fake methods or boundaries", () => {
  const source = `class Box:
    text = """
    def fake(self):
        pass
    """
    def selected(self):
        text = f"""
    @fake
    def fake(self):
        {3}
    """
        # def fake(self):
        pass

    def next(self):
        pass
`;
  assert.equal(findMethod(source, "Box", "fake"), null);
  const range = findMethod(source, "Box", "selected");
  assert.ok(range.code.includes("def fake(self):"));
  assert.ok(range.code.endsWith("    pass"));
  assert.equal(applyMethodEdit(source, range, range.code).source, source);
  const changed = applyMethodEdit(source, range, range.code + "\n    # note");
  assert.ok(changed.source.includes('\n    @fake\n    def fake(self):\n        {3}\n    """'));
});

test("valid continuations may be aligned with the method or the left margin", () => {
  const source = `class Box:
    def selected(
self,
    ):
        values = [
1,
    2,
]
        return (
    values
        )

    def next(self):
        pass
`;
  assert.equal(findMethod(source, "Box", "selected").code, source.slice(source.indexOf("    def"), source.indexOf("\n\n    def next")).split("\n").map((line) => line.startsWith("    ") ? line.slice(4) : line).join("\n"));
});

test("incomplete signatures and body-less methods remain bounded by the next definition", () => {
  for (const header of ["def selected(", "def selected(self)", "async def selected(self):"]) {
    const source = `class Box:\n    ${header}\n\n    @other\n    def next(self):\n        pass\n`;
    const range = findMethod(source, "Box", "selected");
    assert.ok(range);
    assert.equal(range.code, header);
    assert.equal(findMethod(source, "Box", "next").code, "@other\ndef next(self):\n    pass");
  }
});

test("nested functions/classes are not mistaken for direct methods", () => {
  const source = `class Box:
    class Inner:
        def selected(self):
            pass
    def outer(self):
        def selected():
            pass
`;
  assert.equal(findMethod(source, "Box", "selected"), null);
  assert.equal(findMethod(source, "Inner", "selected").code, "def selected(self):\n    pass");
});

test("ambiguous class/method names, missing targets, and swallowed unterminated strings fail safely", () => {
  for (const source of ["", "class Box:\n    pass\n", "class Box:\n    def selected(self): pass\n    def selected(self): pass\n", "class Box:\n    def selected(self): pass\nclass Box:\n    pass\n", 'class Box:\n    def selected(self):\n        """unfinished\n\n    def next(self):\n        pass\n']) {
    assert.equal(findMethod(source, "Box", "selected"), null);
    assert.throws(() => replaceMethod(source, "Box", "selected", "draft"), /Cannot locate/);
  }
});

test("tabs, Unicode identifiers, CRLF, mixed line endings, blank lines, and EOF preserve bytes", () => {
  for (const source of [
    "class Box:\n\tdef selected(self):\n\t\tpass",
    "class Box:\r\n    def selected(self):\r\n        # café 🦊\r\n    \r\n        pass\r\n\r\n    def next(self): pass\r\n",
    "class Box:\r\n    def selected(self):\n        pass\r\n        # note\n",
    "class Box:\n    def selected(self): pass\n",
  ]) {
    const range = findMethod(source, "Box", "selected");
    assert.ok(range);
    assert.equal(applyMethodEdit(source, range, range.code).source, source);
    assertOutsideUnchanged(source, range, applyMethodEdit(source, range, range.code + "\n    # note"));
  }
  const unicode = "class 箱:\n    def 選択(self):\n        pass\n";
  assert.ok(findMethod(unicode, "箱", "選択"));
});

test("independent active ranges can shift by the replacement length", () => {
  const first = findMethod(fixture, "Box", "selected");
  const next = findMethod(fixture, "Box", "next");
  const updated = applyMethodEdit(fixture, first, "def selected(self):\n    pass");
  const delta = updated.range.length - first.length;
  const shifted = { ...next, from: next.from + delta, to: next.to + delta };
  const result = applyMethodEdit(updated.source, shifted, "def next(self):\n    # draft\n    pass");
  assert.equal(result.range.startLine, findMethod(result.source, "Box", "next").startLine);
  assert.equal(result.range.code, findMethod(result.source, "Box", "next").code);
  assert.throws(() => applyMethodEdit(updated.source, next, "draft"), /stale/);
});

describe("bundled method and editor APIs", () => {
  let server, browser, origin;
  before(async () => {
    server = createServer(async (request, response) => {
      if (request.url === "/") {
        response.setHeader("Content-Type", "text/html");
        response.end('<!doctype html><button id="before">Before</button><div id="editor"></div><button id="after">After</button>');
      } else if (request.url === "/editor.js") {
        response.setHeader("Content-Type", "text/javascript");
        response.end(await readFile(new URL("../site/vendor/editor.js", import.meta.url)));
      } else response.writeHead(404).end();
    });
    await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
    origin = `http://127.0.0.1:${server.address().port}`;
    browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || undefined });
  });
  after(async () => {
    await browser?.close();
    if (server) await new Promise((resolve) => server.close(resolve));
  });

  test("exports source-range helpers from the browser bundle", async () => {
    const page = await browser.newPage();
    try {
      await page.goto(origin);
      const result = await page.evaluate(async (source) => {
        const { findMethod, applyMethodEdit, replaceMethod } = await import("/editor.js");
        const range = findMethod(source, "Box", "selected");
        return { range, updated: applyMethodEdit(source, range, "def renamed("), replace: typeof replaceMethod };
      }, fixture);
      assert.equal(result.range.code, findMethod(fixture, "Box", "selected").code);
      assert.equal(result.updated.range.code, "def renamed(");
      assert.equal(result.replace, "function");
    } finally { await page.close(); }
  });

  test("inline auto-height, focus callback, diagnostics, and read-only reconfiguration", async () => {
    const page = await browser.newPage();
    try {
      await page.goto(origin);
      await page.evaluate(async () => {
        const { createEditor } = await import("/editor.js");
        window.changes = []; window.focuses = 0;
        window.editor = createEditor({ parent: document.querySelector("#editor"), doc: "def selected(self):\n    pass", inline: true, readOnly: true,
          onChange: (value) => changes.push(value), onFocus: () => focuses++ });
        editor.focus();
      });
      await page.waitForFunction(() => focuses === 1);
      await page.keyboard.type("not editable");
      assert.equal(await page.evaluate(() => editor.getValue()), "def selected(self):\n    pass");
      assert.deepEqual(await page.evaluate(() => changes), []);
      await page.evaluate(() => { editor.setReadOnly(false); editor.focus(); });
      await page.keyboard.type("draft_");
      assert.equal(await page.evaluate(() => editor.getValue()), "draft_def selected(self):\n    pass");
      await page.evaluate(() => {
        editor.setValue(Array.from({ length: 40 }, (_, i) => `line_${i}`).join("\n"));
        editor.setDiagnostics([{ line: 2, column: 1, endColumn: 4, message: "Draft", severity: "error" }]);
      });
      assert.equal(await page.locator(".cm-lintRange-error").count(), 1);
      assert.ok(await page.locator(".cm-editor").evaluate((el) => el.clientHeight > 500));
      assert.equal(await page.locator(".cm-editor").evaluate((el) => el.style.height), "");
      await page.evaluate(() => { editor.setReadOnly(true); editor.setValue("safe\n"); editor.setVim(true); editor.focus(); });
      await page.keyboard.press("d"); await page.keyboard.press("d");
      assert.equal(await page.evaluate(() => editor.getValue()), "safe\n");
      await page.keyboard.press("Escape"); await page.keyboard.press("Tab");
      assert.equal(await page.evaluate(() => document.activeElement.id), "after");
      await page.evaluate(() => { editor.setReadOnly(false); editor.setValue("editable\n"); editor.focus(); });
      await page.keyboard.press("d"); await page.keyboard.press("d");
      assert.equal(await page.evaluate(() => editor.getValue()), "");
    } finally { await page.close(); }
  });

  for (const vim of [false, true]) {
    test(`Python and local-word completions preserve search/run shortcuts (Vim ${vim})`, async () => {
      const page = await browser.newPage();
      try {
        await page.goto(origin);
        await page.evaluate(async (vim) => {
          const { createEditor } = await import("/editor.js");
          window.runs = 0;
          window.editor = createEditor({ parent: document.querySelector("#editor"), doc: "distinct_local_name = 1\n", vim, onRun: () => runs++ });
          editor.focus(2);
        }, vim);
        if (vim) await page.keyboard.press("i");
        await page.keyboard.type("distinct_");
        await page.keyboard.press("Control+Space");
        await page.getByRole("option", { name: "distinct_local_name", exact: true }).waitFor();
        await page.keyboard.press("Escape");
        await page.evaluate(() => { editor.setValue("pri"); editor.focus(); });
        if (vim) await page.keyboard.press("i");
        await page.keyboard.press("End");
        await page.keyboard.press("Control+Space");
        await page.getByRole("option", { name: "print", exact: true }).click();
        assert.equal(await page.evaluate(() => editor.getValue()), "print");
        await page.keyboard.press("Control+Enter");
        assert.equal(await page.evaluate(() => runs), 1);
        await page.keyboard.press("Escape");
        await page.keyboard.press("Control+f");
        assert.equal(await page.locator(".cm-search").count(), 1);
      } finally { await page.close(); }
    });
  }
});
