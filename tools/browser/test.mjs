import assert from "node:assert/strict";
import { after, before, test } from "node:test";
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { chromium } from "@playwright/test";
import { strFromU8, unzipSync } from "fflate";
import { fileEntries } from "./files.js";

let server;
let browser;
let origin;
const vendor = new URL("../site/vendor/", import.meta.url);
before(async () => {
  server = createServer(async (request, response) => {
    if (request.url === "/") {
      response.setHeader("Content-Type", "text/html");
      response.end(`<!doctype html><style>
        :root { --paper: #fbf1c7; --ink: #654735; --surface: #f4e8be; --accent: #6c782e; --muted: #928374; --line: color-mix(in srgb, var(--ink) 20%, var(--paper)); }
        :root[data-theme="dark"] { --paper: #282828; --ink: #d4be98; --surface: #32302f; --accent: #a9b665; }
      </style><button id="before">Before editor</button><div id="editor"></div><button id="after">After editor</button>`);
      return;
    }
    const name = new URL(request.url, "http://localhost").pathname.slice(1);
    if (name.includes("..")) { response.writeHead(403).end(); return; }
    try {
      const bytes = await readFile(new URL(name, vendor));
      response.setHeader("Content-Type", name.endsWith(".wasm") ? "application/wasm" : name.endsWith(".js") || name.endsWith(".mjs") ? "text/javascript" : "application/octet-stream");
      response.end(bytes);
    } catch { response.writeHead(404).end(); }
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  origin = `http://127.0.0.1:${server.address().port}`;
  browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || undefined });
});
after(async () => {
  await browser?.close();
  await new Promise((resolve) => server?.close(resolve));
});

async function editorPage() {
  const page = await browser.newPage();
  await page.goto(origin);
  await page.evaluate(async () => {
    const { createEditor } = await import("/editor.js");
    window.changes = [];
    window.runs = 0;
    window.editor = createEditor({
      parent: document.querySelector("#editor"), doc: "start",
      onChange: (value) => window.changes.push(value), onRun: () => window.runs++,
    });
    editor.focus();
  });
  return page;
}

async function checker(page, files, id = 1) {
  return page.evaluate(({ files, id }) => new Promise((resolve, reject) => {
    window.checkWorker ??= new Worker("/checks-worker.js", { type: "module" });
    const worker = window.checkWorker;
    const timeout = setTimeout(() => reject(new Error("Checker timeout")), 30000);
    worker.addEventListener("message", function receive(event) {
      if (event.data.id !== id) return;
      clearTimeout(timeout);
      worker.removeEventListener("message", receive);
      resolve(event.data);
    });
    worker.postMessage({ id, files });
  }), { files, id });
}

test("editor edits, silent replacement, indent, escape, run, Vim, themes and diagnostics", async () => {
  const page = await editorPage();
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  try {
    await page.evaluate(() => { editor.setValue(""); editor.setValue(""); });
    assert.deepEqual(await page.evaluate(() => changes), []);
    await page.keyboard.type("x = 1");
    assert.equal(await page.evaluate(() => editor.getValue()), "x = 1");
    assert.equal(await page.evaluate(() => changes.at(-1)), "x = 1");
    await page.keyboard.press("Control+Enter");
    assert.equal(await page.evaluate(() => runs), 1);
    await page.keyboard.press("Home");
    await page.keyboard.press("Tab");
    assert.equal(await page.evaluate(() => editor.getValue()), "    x = 1");
    await page.keyboard.press("Escape");
    await page.keyboard.press("Tab");
    assert.equal(await page.evaluate(() => document.activeElement.id), "after");
    await page.evaluate(() => {
      editor.setValue("value = 2\n");
      editor.setVim(true);
      editor.focus();
    });
    await page.keyboard.press("Escape");
    await page.keyboard.press("g");
    await page.keyboard.press("g");
    await page.keyboard.press("d");
    await page.keyboard.press("d");
    assert.equal(await page.evaluate(() => editor.getValue()), "");
    await page.keyboard.press("i");
    await page.keyboard.type("vim_text");
    await page.keyboard.press("Escape");
    assert.equal(await page.evaluate(() => editor.getValue()), "vim_text");
    await page.keyboard.press("Meta+Enter");
    assert.equal(await page.evaluate(() => runs), 2);
    await page.keyboard.press("Escape");
    await page.keyboard.press("Tab");
    assert.equal(await page.evaluate(() => document.activeElement.id), "after");
    await page.evaluate(() => {
      editor.setVim(false);
      editor.setDark(true);
      document.documentElement.dataset.theme = "dark";
      editor.setDiagnostics([{ line: 1, column: 1, endLine: 1, endColumn: 4, message: "Test diagnostic", source: "ty", severity: "error" }]);
    });
    assert.equal(await page.locator(".cm-editor").evaluate((el) => getComputedStyle(el).backgroundColor), "rgb(40, 40, 40)");
    assert.equal(await page.locator(".cm-lintRange-error").count(), 1);
    await page.evaluate(() => { editor.setDark(false); document.documentElement.dataset.theme = "light"; });
    assert.equal(await page.locator(".cm-editor").evaluate((el) => getComputedStyle(el).backgroundColor), "rgb(251, 241, 199)");
    assert.equal(await page.locator(".cm-editor").evaluate((el) => getComputedStyle(el).color), "rgb(101, 71, 53)");
    await page.evaluate(() => document.documentElement.style.setProperty("--paper", "rgb(240, 230, 200)"));
    assert.equal(await page.locator(".cm-editor").evaluate((el) => getComputedStyle(el).backgroundColor), "rgb(240, 230, 200)");
    await page.evaluate(() => editor.destroy());
    assert.equal(await page.locator(".cm-editor").count(), 0);
    assert.deepEqual(errors, []);
  } finally { await page.close(); }
});

for (const vim of [false, true]) {
  test(`file replacement isolates undo and redo, including identical text (Vim ${vim})`, async () => {
    const page = await editorPage();
    const undo = async () => page.keyboard.press(vim ? "u" : process.platform === "darwin" ? "Meta+z" : "Control+z");
    const redo = async () => page.keyboard.press(vim ? "Control+r" : process.platform === "darwin" ? "Meta+Shift+z" : "Control+Shift+z");
    const type = async (text) => {
      if (vim) await page.keyboard.press("i");
      await page.keyboard.type(text);
      if (vim) await page.keyboard.press("Escape");
    };
    try {
      await page.evaluate((vim) => { editor.setVim(vim); editor.setValue("file_a\n"); editor.focus(1); }, vim);
      await type("old_");
      assert.equal(await page.evaluate(() => editor.getValue()), "old_file_a\n");
      const count = await page.evaluate(() => changes.length);
      await page.evaluate(() => editor.setValue("file_b\n"));
      assert.equal(await page.evaluate(() => changes.length), count);
      await undo();
      await redo();
      assert.equal(await page.evaluate(() => editor.getValue()), "file_b\n");
      assert.equal(await page.evaluate(() => changes.length), count);
      await page.evaluate(() => editor.focus(1));
      await type("new_");
      assert.equal(await page.evaluate(() => editor.getValue()), "new_file_b\n");
      await undo();
      assert.equal(await page.evaluate(() => editor.getValue()), "file_b\n");
      await redo();
      assert.equal(await page.evaluate(() => editor.getValue()), "new_file_b\n");
      const beforeSwitch = await page.evaluate(() => changes.length);
      await page.evaluate(() => editor.setValue(editor.getValue()));
      await undo();
      await redo();
      assert.equal(await page.evaluate(() => editor.getValue()), "new_file_b\n");
      assert.equal(await page.evaluate(() => changes.length), beforeSwitch);
    } finally { await page.close(); }
  });
}

test("a single Escape then Tab exits Vim insert/normal modes and plain editing", async () => {
  const page = await editorPage();
  try {
    for (const mode of ["plain", "normal", "insert"]) {
      for (const backwards of [false, true]) {
        await page.evaluate((mode) => {
          editor.setVim(mode !== "plain"); editor.setValue("text\n"); editor.focus();
        }, mode);
        if (mode === "insert") {
          await page.keyboard.press("i");
          await page.keyboard.press("Tab");
          assert.equal(await page.evaluate(() => editor.getValue()), "    text\n");
        }
        const text = await page.evaluate(() => editor.getValue());
        await page.keyboard.press("Escape");
        await page.keyboard.press(backwards ? "Shift+Tab" : "Tab");
        assert.equal(await page.evaluate(() => document.activeElement.id), backwards ? "before" : "after", mode);
        assert.equal(await page.evaluate(() => editor.getValue()), text);
      }
    }
  } finally { await page.close(); }
});

test("standard search works with Vim slash search and line navigation scrolls", async () => {
  const page = await editorPage();
  try {
    await page.evaluate(() => {
      editor.setVim(true);
      editor.setValue("first\nneedle\nlast\n");
      editor.focus(1);
    });
    await page.keyboard.press("Control+f");
    assert.equal(await page.locator(".cm-search").count(), 1);
    await page.locator('.cm-search input[name="search"]').pressSequentially("needle");
    await page.keyboard.press("Enter");
    assert.equal(await page.locator(".cm-searchMatch-selected").count(), 1);
    await page.keyboard.press("Escape");
    await page.evaluate(() => editor.focus(1));
    await page.keyboard.press("/");
    assert.equal(await page.locator(".cm-vim-panel input").count(), 1);
    await page.locator(".cm-vim-panel input").pressSequentially("last");
    await page.keyboard.press("Enter");
    await page.keyboard.press("i");
    await page.keyboard.type("found_");
    await page.keyboard.press("Escape");
    assert.equal(await page.evaluate(() => editor.getValue()), "first\nneedle\nfound_last\n");
    await page.evaluate(() => {
      editor.setVim(false);
      editor.setValue(Array.from({ length: 100 }, (_, i) => `line_${i + 1}`).join("\n"));
      document.querySelector(".cm-editor").style.height = "150px";
      editor.revealLine(70);
    });
    await page.waitForFunction(() => document.querySelector(".cm-scroller").scrollTop > 0);
    await page.keyboard.type("jump_");
    assert.equal(await page.evaluate(() => editor.getValue().split("\n")[69]), "jump_line_70");
    await page.evaluate(() => editor.focus(2));
    await page.keyboard.type("focus_");
    assert.equal(await page.evaluate(() => editor.getValue().split("\n")[1]), "focus_line_2");
  } finally { await page.close(); }
});

test("source ZIP round-trips UTF-8 and rejects unsafe paths", async () => {
  const page = await editorPage();
  try {
    const bytes = await page.evaluate(async () => {
      const { zipFiles } = await import("/editor.js");
      return Array.from(zipFiles({ "src/example.py": "text = 'café'\n" }));
    });
    const files = unzipSync(new Uint8Array(bytes));
    assert.deepEqual(Object.keys(files), ["src/example.py"]);
    assert.equal(strFromU8(files["src/example.py"]), "text = 'café'\n");
    assert.throws(() => fileEntries({ "../outside.py": "" }), /Invalid/);
    assert.throws(() => fileEntries([{ path: "a.py", content: "" }, { path: "/workspace/a.py", content: "" }]), /duplicate/);
  } finally { await page.close(); }
});

test("Ty resolves multiple project files and enables both unsound rules; Ruff lints", async () => {
  const page = await browser.newPage();
  await page.goto(origin);
  try {
    const files = {
      "src/pkg/__init__.py": "",
      "helper.py": "def known() -> int:\n    return 1\n",
      "src/pkg/values.py": 'from typing import Any\n\ndef get_value() -> Any:\n    return "text"\n',
      "main.py": "from pkg.values import get_value\nfrom helper import known\n\nvalue: int = get_value()\nother: int = known()\n\ndef read() -> int:\n    return get_value()\n",
      "lint.py": "import os\n",
    };
    const result = await checker(page, files);
    assert.deepEqual(result.available, { ty: true, ruff: true }, result.error);
    assert.equal(result.kind, "result");
    assert.equal(result.id, 1);
    assert.equal(result.error, undefined);
    const typed = result.diagnostics.filter((item) => item.source === "ty");
    assert.ok(typed.some((item) => item.message.includes("unsound-assignment") && item.path === "main.py"), JSON.stringify(typed));
    assert.ok(typed.some((item) => item.message.includes("unsound-return-statement") && item.path === "main.py"), JSON.stringify(typed));
    assert.ok(!typed.some((item) => item.message.includes("unresolved-import")), JSON.stringify(typed));
    assert.ok(result.diagnostics.some((item) => item.source === "ruff" && item.message.includes("F401") && item.path === "lint.py"));
    for (const item of result.diagnostics) {
      assert.ok(item.line >= 1 && item.column >= 1 && item.endLine >= item.line);
    }
    const clean = await checker(page, [{ path: "main.py", content: 'from string.templatelib import Template\n\nvalue: Template = t"text"\n' }], 2);
    assert.deepEqual(clean.available, { ty: true, ruff: true }, clean.error);
    assert.deepEqual(clean.diagnostics.filter((item) => item.source === "ty"), []);
    const removed = await checker(page, { "main.py": "from pkg.values import get_value\n" }, 3);
    assert.ok(removed.diagnostics.some((item) => item.source === "ty" && item.message.includes("unresolved-import")));
  } finally { await page.close(); }
});

test("Ruff still runs if Ty cannot load, and invalid paths return an error", async () => {
  const page = await browser.newPage();
  await page.route("**/ty.wasm", (route) => route.abort());
  await page.goto(origin);
  try {
    const result = await checker(page, { "lint.py": "import os\n" });
    assert.deepEqual(result.available, { ty: false, ruff: true });
    assert.match(result.error, /ty:/);
    assert.ok(result.diagnostics.some((item) => item.source === "ruff" && item.message.includes("F401")));
    const invalid = await checker(page, { "../outside.py": "" }, 2);
    assert.match(invalid.error, /Invalid/);
    assert.deepEqual(invalid.diagnostics, []);
  } finally { await page.close(); }
});

test("local Pyodide runs Python 3.14", async () => {
  const page = await browser.newPage();
  await page.goto(origin);
  try {
    const version = await page.evaluate(async () => {
      const { loadPyodide } = await import("/pyodide/pyodide.mjs");
      const runtime = await loadPyodide({ indexURL: new URL("/pyodide/", location.href).href });
      return runtime.runPython("import sys\nstr(sys.version_info[:2])");
    });
    assert.equal(version, "(3, 14)");
  } finally { await page.close(); }
});
