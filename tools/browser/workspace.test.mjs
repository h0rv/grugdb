import assert from "node:assert/strict";
import {after, before, test} from "node:test";
import {createServer} from "node:http";
import {mkdtemp, readFile, rm} from "node:fs/promises";
import {tmpdir} from "node:os";
import {join} from "node:path";
import {execFileSync} from "node:child_process";
import {fileURLToPath, pathToFileURL} from "node:url";
import {chromium} from "@playwright/test";
import {findMethod} from "./methods.js";
import {readBackup} from "../site/workspace-state.js";

const root = fileURLToPath(new URL("../../", import.meta.url));
let site, previewPath;
let browser, server, origin, manifest;
const failures = [];
before(async () => {
  previewPath = await mkdtemp(join(tmpdir(), "grugdb-workspace-check-"));
  site = pathToFileURL(`${previewPath}/`);
  execFileSync("uv", ["run", "python", "-m", "tools.site", "--output", previewPath], {cwd: root});
  manifest = JSON.parse(await readFile(new URL("workspace.json", site), "utf8"));
  server = createServer(async (request, response) => {
    const path = new URL(request.url, "http://localhost").pathname.slice(1) || "index.html";
    if (path.includes("..")) { response.writeHead(403).end(); return; }
    try {
      const data = await readFile(new URL(path, site));
      response.setHeader("Content-Type", ({js: "text/javascript", mjs: "text/javascript", wasm: "application/wasm", json: "application/json", css: "text/css", html: "text/html"})[path.split(".").at(-1)] ?? "application/octet-stream");
      response.end(data);
    } catch { response.writeHead(404).end(); }
  });
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  origin = `http://127.0.0.1:${server.address().port}`;
  browser = await chromium.launch({channel: process.env.PLAYWRIGHT_CHANNEL || undefined});
});
after(async () => {
  await browser?.close(); await new Promise(resolve => server?.close(resolve));
  if (previewPath) await rm(previewPath, {recursive: true, force: true});
});
const card = (page, id) => page.locator(`[data-exercise="${id}"]`);
async function open(context, chapter = "01-rows-and-tables") {
  const page = await context.newPage();
  page.on("pageerror", error => failures.push(error.message));
  await page.goto(`${origin}/${chapter}.html`);
  await page.locator(".method-editor .cm-content").first().waitFor();
  return page;
}
async function replace(page, id, text) {
  const content = card(page, id).locator(".cm-content");
  await content.click();
  await page.keyboard.press(process.platform === "darwin" ? "Meta+A" : "Control+A");
  await page.keyboard.insertText(text);
  await page.waitForFunction(() => document.querySelector(".save-status").textContent === "Saved");
}
async function reference(id) {
  const item = manifest.exercises.find(item => item.id === id);
  return findMethod(await readFile(new URL(`../../${item.file}`, import.meta.url), "utf8"), item.class_name, item.method).code;
}
async function settled(page) {
  await page.waitForFunction(() => document.querySelectorAll(".exercise-feedback .test-summary").length > 0 && document.querySelector(".chapter-checks [role=status]").dataset.running === "false", null, {timeout: 60000});
}

test("methods appear at the assignment, checks run automatically, and the full workspace starts closed", {timeout: 120000}, async () => {
  const context = await browser.newContext();
  const page = await open(context);
  try {
    assert.equal(Math.round((await page.locator(".shell > aside").boundingBox()).x), 0);
    assert.equal(await page.locator(".exercise .cm-editor").count(), 8);
    assert.equal(await page.locator(".side-status .checks-status, .side-status .save-status").count(), 0);
    assert.equal(await page.locator(".workspace-pane").isVisible(), false);
    await page.screenshot({path: "/tmp/grugdb-lesson-desktop.png"});
    assert.equal(await page.locator('select,input[type="checkbox"]').count(), 0);
    assert.equal(await page.getByRole("button", {name: /^Run .*tests$/}).count(), 0);
    assert.equal(await page.getByRole("tab", {name: "Output", exact: true}).count(), 0);
    await settled(page);
    assert.match(await page.locator(".chapter-checks").textContent(), /0 of 13 chapter tests passing/);
    assert.match(await card(page, "Table.insert").locator(".exercise-status").textContent(), /0\/3 passed/);
    assert.equal(await page.locator(".local-only[open]").count(), 0);
    await page.waitForFunction(() => document.querySelector(".checks-status").textContent === "Checks passing", {timeout: 60000});
    assert.equal(await page.locator(".checks-status").textContent(), "Checks passing");
    await card(page, "Table.insert").scrollIntoViewIfNeeded();
    await page.screenshot({path: "/tmp/grugdb-inline-light.png"});
    await page.getByRole("button", {name: "Switch to dark mode"}).click();
    await card(page, "Table.insert").scrollIntoViewIfNeeded();
    await page.screenshot({path: "/tmp/grugdb-inline-dark.png"});
  } finally { await context.close(); }
});

test("implementing insert alone flips its tests, preserves other snippets, and survives reload", {timeout: 120000}, async () => {
  const context = await browser.newContext();
  const page = await open(context);
  try {
    await replace(page, "Table.insert", await reference("Table.insert"));
    await page.waitForFunction(() => document.querySelector('[data-exercise="Table.insert"] .exercise-status').textContent === "3/3 passed", {timeout: 60000});
    assert.match(await card(page, "Table.get").locator(".cm-content").textContent(), /NotImplementedError/);
    await replace(page, "Table.get", await reference("Table.get"));
    await page.waitForFunction(() => document.querySelector('[data-exercise="Table.get"] .exercise-status').textContent === "2/2 passed", {timeout: 60000});
    await page.reload();
    await page.locator(".method-editor .cm-content").first().waitFor();
    assert.match(await card(page, "Table.insert").locator(".cm-content").textContent(), /row_id/);
    assert.match(await card(page, "Table.get").locator(".cm-content").textContent(), /return/);
    assert.equal(await page.locator('.editor-keys input[value="standard"]').isChecked(), true);
    await page.getByRole("button", {name: "Source files", exact: true}).click();
    const download = page.waitForEvent("download");
    await page.getByRole("button", {name: "Export backup", exact: true}).click();
    const backup = JSON.parse(await readFile(await (await download).path(), "utf8"));
    assert.match(backup.files["src/grugdb/table.py"], /return self\._rows\[row_id\]/);
    assert.match(backup.files["src/grugdb/table.py"], /Exercise: Table.delete/);
    assert.equal(backup.results, undefined);
  } finally { await context.close(); }
});

test("right workspace splits, resizes, expands, has a file tree, and keeps snippets in sync", {timeout: 120000}, async () => {
  const context = await browser.newContext({viewport: {width: 1600, height: 1000}});
  const page = await open(context);
  try {
    await page.getByRole("button", {name: "Source files", exact: true}).click();
    assert.equal(await page.locator(".workspace-pane").isVisible(), true);
    assert.equal(await page.locator(".file-tree details").count(), 0);
    assert.equal(await page.locator(".sidebar-tabs").count(), 0);
    assert.equal(await page.locator(".workspace-header strong").count(), 0);
    assert.equal(await page.locator(".file-tree .tree-actions button").count(), 2);
    assert.match(await page.locator(".tree-file").first().evaluate(node => getComputedStyle(node).fontFamily), /monospace/);
    assert.equal(await page.getByRole("button", {name: "New file", exact: true}).count(), 0);
    assert.equal(await page.locator(".workspace-transfers details").count(), 0);
    assert.equal(await page.getByRole("button", {name: "Reset file", exact: true}).count(), 0);
    const width = await page.locator(".workspace-pane").evaluate(node => node.getBoundingClientRect().width);
    await page.getByRole("separator", {name: "Resize workspace"}).press("ArrowLeft");
    assert.ok(await page.locator(".workspace-pane").evaluate(node => node.getBoundingClientRect().width) > width);
    await page.getByRole("button", {name: "Hide files", exact: true}).click();
    assert.equal(await page.locator(".file-tree").isVisible(), false);
    await page.getByRole("button", {name: "Show files", exact: true}).click();
    assert.equal(await page.locator(".file-tree").isVisible(), true);
    await page.getByRole("button", {name: "Full screen"}).click();
    assert.equal(await page.locator(".shell").isVisible(), false);
    assert.equal(await page.locator(".file-tree").isVisible(), true);
    await page.getByRole("button", {name: "Split view"}).click();
    assert.equal(await page.locator(".shell").isVisible(), true);
    await page.getByRole("button", {name: "Hide sidebar"}).click();
    assert.equal(await page.locator(".shell > aside").isVisible(), false);
    await page.getByRole("button", {name: "Show sidebar"}).click();
    const tree = page.getByRole("navigation", {name: "Project files"});
    await tree.getByRole("button", {name: "test_table.py", exact: true}).click();
    assert.equal(await page.locator(".full-editor .cm-content").getAttribute("contenteditable"), "false");
    await tree.getByRole("button", {name: "table.py", exact: true}).click();
    assert.equal(await page.locator(".full-editor .cm-content").getAttribute("contenteditable"), "true");
    await page.screenshot({path: "/tmp/grugdb-split-workspace.png"});
    await page.getByRole("button", {name: "Close editor"}).click();
    assert.equal(await page.locator(".workspace-pane").isVisible(), false);
  } finally { await context.close(); }
});

test("automatic diagnostics mark the inline method without any Check button", {timeout: 120000}, async () => {
  const context = await browser.newContext();
  const page = await open(context);
  try {
    await replace(page, "Table.get", 'def get(self, row_id: RowId) -> T:\n    return "wrong"');
    await page.waitForFunction(() => document.querySelector('[data-exercise="Table.get"] .cm-lintRange-error'), {timeout: 60000});
    assert.equal(await page.getByRole("button", {name: "Check types + lint"}).count(), 0);
    await page.getByRole("button", {name: "Source files", exact: true}).click();
    await page.getByRole("tab", {name: /^Problems/}).click();
    assert.match(await page.locator("#console-problems").textContent(), /invalid-return-type|invalid-return|assignable/);
  } finally { await context.close(); }
});

test("stopping infinite code keeps the page responsive and storage failures remain visible", {timeout: 120000}, async () => {
  const context = await browser.newContext();
  const page = await open(context);
  try {
    await replace(page, "Table.insert", "def insert(self, row: T) -> RowId:\n    while True:\n        pass");
    await page.waitForFunction(() => document.querySelector('.chapter-checks [role="status"]').dataset.running === "true", {timeout: 60000});
    await page.getByRole("button", {name: "Source files", exact: true}).click();
    await page.getByRole("button", {name: "Stop", exact: true}).click();
    assert.match(await page.locator("#console-tests").textContent(), /Stopped/);
    assert.equal(await page.getByRole("button", {name: "Stop", exact: true}).isVisible(), false);
  } finally { await context.close(); }
  const denied = await browser.newContext();
  await denied.addInitScript(() => Object.defineProperty(window, "indexedDB", {get() { throw new Error("storage denied"); }}));
  const unavailable = await open(denied);
  try { assert.match(await unavailable.locator(".save-warning").textContent(), /Autosave unavailable/); }
  finally { await denied.close(); }
});

test("settings and help live in the sidebar, default keys are standard, and starter checks are clean", {timeout: 120000}, async () => {
  const context = await browser.newContext();
  const page = await open(context);
  try {
    assert.equal(await page.locator("main .local-only").count(), 0);
    assert.equal(await page.locator("main .editor-keys").count(), 0);
    await page.waitForFunction(() => document.querySelector(".checks-status").textContent === "Checks passing", {timeout: 60000});
    await page.getByRole("button", {name: "Editor settings", exact: true}).click();
    assert.equal(await page.getByRole("radio", {name: "Standard", exact: true}).isChecked(), true);
    await page.getByRole("radio", {name: "Vim", exact: true}).check();
    await page.getByRole("button", {name: "Close settings"}).click();
    await page.reload();
    await page.locator(".method-editor .cm-content").first().waitFor();
    assert.equal(await page.locator('.editor-keys input[value="vim"]').isChecked(), true);
    await page.getByRole("button", {name: "Help", exact: true}).click();
    assert.match(await page.locator(".course-help-dialog").textContent(), /Ctrl\/⌘ Enter/);
    assert.ok(await page.locator(".course-help-dialog .local-only").count() > 0);
    await page.getByRole("button", {name: "Close help"}).click();
  } finally { await context.close(); }
});

test("method expand jumps to its full source and static examples expand without changing project files", {timeout: 120000}, async () => {
  const context = await browser.newContext();
  const page = await open(context);
  try {
    await page.getByRole("button", {name: "Open full file for Table.insert", exact: true}).click();
    assert.equal(await page.locator(".workspace-pane").isVisible(), true);
    assert.match(await page.locator(".full-editor .cm-content").textContent(), /def insert/);
    await page.getByRole("button", {name: "Close editor"}).click();
    const expand = page.locator("main .code-block").first();
    await expand.hover();
    await expand.getByRole("button", {name: "Expand code block"}).click();
    assert.equal(await page.locator(".workspace-header code").textContent(), "Example");
    assert.equal(await page.locator(".full-editor .cm-content").getAttribute("contenteditable"), "false");
    const download = page.waitForEvent("download");
    await page.getByRole("button", {name: "Export backup", exact: true}).click();
    const backup = JSON.parse(await readFile(await (await download).path(), "utf8"));
    assert.deepEqual(backup.files, {});
  } finally { await context.close(); }
});

test("all chapter editors render and imported implementations pass the same browser suites", {timeout: 120000}, async () => {
  const context = await browser.newContext();
  const page = await open(context);
  try {
    const files = {};
    for (const path of ["src/grugdb/table.py", "src/grugdb/expr.py", "src/grugdb/query.py"]) files[path] = await readFile(new URL(`../../${path}`, import.meta.url), "utf8");
    await page.getByRole("button", {name: "Source files", exact: true}).click();
    page.once("dialog", dialog => dialog.accept());
    await page.locator('.workspace-pane input[type="file"]').setInputFiles({name: "backup.json", mimeType: "application/json", buffer: Buffer.from(JSON.stringify({version: 1, revision: manifest.revision, files}))});
    await page.waitForFunction(() => document.querySelector(".chapter-checks").textContent.includes("13 of 13"), {timeout: 60000});
    await page.getByRole("button", {name: "Close editor"}).click();
    for (const lesson of manifest.lessons.slice(1, 4)) {
      await page.goto(`${origin}/${lesson.slug}.html`);
      await page.locator(".method-editor .cm-content").first().waitFor();
      assert.equal(await page.locator(".exercise .cm-editor").count(), manifest.exercises.filter(item => item.lesson === lesson.slug).length);
      await page.waitForFunction(count => document.querySelector(".chapter-checks").textContent.includes(`${count} of ${count}`), lesson.tests.length, {timeout: 60000});
    }
    await page.getByRole("button", {name: "Source files", exact: true}).click();

    const outcome = await page.evaluate(({files, tests}) => new Promise((resolve, reject) => {
      const worker = new Worker("python-worker.js", {type: "module"});
      worker.onerror = event => reject(new Error(event.message));
      worker.onmessage = ({data}) => { worker.terminate(); resolve(data); };
      worker.postMessage({id: 1, files, tests, runtimeURL: new URL("vendor/pyodide/pyodide.mjs", location.href).href});
    }), {files: {...manifest.files, ...files}, tests: manifest.tests});
    assert.equal(outcome.kind, "result");
    assert.equal(outcome.tests.length, manifest.tests.length);
    assert.ok(outcome.tests.every(item => item.status === "passed"));
  } finally { await context.close(); }
});

test("concurrent tabs can save results but never overwrite another tab's source edits", {timeout: 120000}, async () => {
  const context = await browser.newContext();
  const first = await open(context);
  const second = await open(context);
  try {
    await settled(first); await settled(second);
    assert.equal(await first.locator(".save-warning").isVisible(), false);
    assert.equal(await second.locator(".save-warning").isVisible(), false);
    await replace(first, "Table.insert", await reference("Table.insert"));
    const content = card(second, "Table.get").locator(".cm-content");
    await content.click();
    await second.keyboard.press(process.platform === "darwin" ? "Meta+A" : "Control+A");
    await second.keyboard.insertText(await reference("Table.get"));
    await second.waitForFunction(() => document.querySelector(".save-warning").textContent.includes("Another tab"));
    assert.match(await content.textContent(), /return/);
    await settled(first);
    await first.reload();
    await first.locator(".method-editor .cm-content").first().waitFor();
    assert.match(await card(first, "Table.insert").locator(".cm-content").textContent(), /row_id/);
    assert.match(await card(first, "Table.get").locator(".cm-content").textContent(), /NotImplementedError/);
  } finally { await context.close(); }
});

test("course update notices clear after automatic rechecking without discarding edits", {timeout: 120000}, async () => {
  const context = await browser.newContext();
  const page = await open(context);
  try {
    await replace(page, "Table.insert", await reference("Table.insert"));
    await settled(page);
    await page.evaluate(() => new Promise((resolve, reject) => {
      const request = indexedDB.open("grugdb-workspace-v1", 1);
      request.onsuccess = () => {
        const db = request.result;
        const tx = db.transaction("workspace", "readwrite");
        const store = tx.objectStore("workspace");
        const read = store.get("work");
        read.onsuccess = () => store.put({...read.result, revision: "older-course", sequence: read.result.sequence + 1}, "work");
        tx.oncomplete = () => { db.close(); resolve(); };
        tx.onerror = () => reject(tx.error);
      };
    }));
    await page.reload();
    await page.locator(".method-editor .cm-content").first().waitFor();
    await page.waitForFunction(() => document.querySelector(".save-warning").hidden, {timeout: 60000});
    assert.match(await card(page, "Table.insert").locator(".cm-content").textContent(), /row_id/);
    assert.doesNotMatch(await page.locator(".side-status").textContent(), /course changed|run the tests again|Rechecking/);
  } finally { await context.close(); }
});

test("legacy import maintenance preserves learner methods and does not create starter warnings", {timeout: 120000}, async () => {
  const context = await browser.newContext();
  const page = await open(context);
  try {
    const original = manifest.files["src/grugdb/table.py"];
    const target = findMethod(original, "Table", "insert");
    const {applyMethodEdit} = await import("./methods.js");
    const implementation = await reference("Table.insert");
    const legacy = applyMethodEdit(original, target, implementation).source
      .replace("from grugdb.query import Query", "from grugdb.query import Query, Scan")
      .replaceAll("from grugdb.", "from .");
    await page.getByRole("button", {name: "Source files", exact: true}).click();
    page.once("dialog", dialog => dialog.accept());
    await page.locator('.workspace-pane input[type="file"]').setInputFiles({name: "legacy.json", mimeType: "application/json", buffer: Buffer.from(JSON.stringify({version: 1, revision: "old-course", files: {"src/grugdb/table.py": legacy}}))});
    await page.waitForFunction(() => document.querySelector(".checks-status").textContent === "Checks passing", {timeout: 60000});
    await page.waitForFunction(() => document.querySelector(".save-warning").hidden, {timeout: 60000});
    const download = page.waitForEvent("download");
    await page.getByRole("button", {name: "Export backup", exact: true}).click();
    const backup = JSON.parse(await readFile(await (await download).path(), "utf8"));
    const source = backup.files["src/grugdb/table.py"];
    assert.doesNotMatch(source, /^from \./m);
    assert.match(source, /from grugdb.query import Query, Scan.*supplied for exercises/);
    assert.equal(findMethod(source, "Table", "insert").code, implementation);
  } finally { await context.close(); }
});

test("focused editor has readable regular-weight tokens and unclipped three-digit line numbers", {timeout: 120000}, async () => {
  const context = await browser.newContext({viewport: {width: 1440, height: 1000}});
  const page = await open(context);
  const rendering = host => {
    const numbers = [...host.querySelectorAll(".cm-lineNumbers .cm-gutterElement")].filter(node => getComputedStyle(node).visibility !== "hidden" && node.getBoundingClientRect().height > 10);
    const clipped = numbers.filter(node => {
      const range = document.createRange(); range.selectNodeContents(node);
      const text = range.getBoundingClientRect(), box = node.getBoundingClientRect();
      return text.left < box.left - 1 || text.right > box.right + 1 || text.top < box.top - 1 || text.bottom > box.bottom + 1;
    }).map(node => {
      const range = document.createRange(); range.selectNodeContents(node);
      return {line: node.textContent, text: range.getBoundingClientRect().toJSON(), box: node.getBoundingClientRect().toJSON()};
    });
    const spans = [...host.querySelectorAll(".cm-line span")];
    return {clipped, colors: new Set(spans.map(node => getComputedStyle(node).color)).size,
      bold: spans.some(node => Number(getComputedStyle(node).fontWeight) > 400),
      font: getComputedStyle(host.querySelector(".cm-content")).fontFamily};
  };
  try {
    await page.getByRole("button", {name: "Source files", exact: true}).click();
    await page.getByRole("button", {name: "Full screen", exact: true}).click();
    for (const theme of ["light", "dark"]) {
      await page.evaluate(theme => { document.documentElement.dataset.theme = theme; }, theme);
      await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
      const rendered = await page.locator(".full-editor").evaluate(rendering);
      await page.screenshot({path: `/tmp/grugdb-editor-rendering-${theme}.png`});
      assert.deepEqual(rendered.clipped, []);
      assert.ok(rendered.colors >= 4, JSON.stringify(rendered));
      assert.equal(rendered.bold, false);
      assert.match(rendered.font, /JetBrains Mono/);
    }
    await page.getByRole("navigation", {name: "Project files"}).getByRole("button", {name: "test_exercises.py", exact: true}).click();
    await page.locator(".full-editor .cm-content").press(process.platform === "darwin" ? "Meta+End" : "Control+End");
    await page.waitForFunction(() => [...document.querySelectorAll(".full-editor .cm-lineNumbers .cm-gutterElement")].some(node => /^\d{3}$/.test(node.textContent) && node.getBoundingClientRect().height > 10));
    await page.waitForFunction(() => new Set([...document.querySelectorAll(".full-editor .cm-line span")].map(node => getComputedStyle(node).color)).size >= 4);
    await page.evaluate(async () => {
      await document.fonts.ready;
      await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    });
    await page.screenshot({path: "/tmp/grugdb-editor-three-digit-gutter.png"});
    assert.deepEqual((await page.locator(".full-editor").evaluate(rendering)).clipped, []);
  } finally { await context.close(); }
});

test("mobile methods fit the viewport and backups round-trip large drafts without allowing supplied test edits", {timeout: 120000}, async () => {
  const context = await browser.newContext({viewport: {width: 390, height: 844}, hasTouch: true, isMobile: true});
  await context.addInitScript(() => localStorage.setItem("grugdb-vim", "true"));
  const page = await open(context);
  try {
    assert.equal(await page.locator(".shell > aside").isVisible(), false);
    await page.screenshot({path: "/tmp/grugdb-mobile-lesson.png"});
    await page.getByRole("button", {name: "Show sidebar", exact: true}).click();
    assert.equal(await page.locator(".shell > aside").isVisible(), true);
    await page.getByRole("button", {name: "Editor settings", exact: true}).click();
    assert.equal(await page.locator('.editor-keys input[value="standard"]').isChecked(), true);
    assert.equal(await page.locator('.editor-keys input[value="vim"]').isDisabled(), true);
    assert.equal(await page.evaluate(() => localStorage.getItem("grugdb-vim")), "true");
    await page.screenshot({path: "/tmp/grugdb-mobile-settings.png"});
    await page.getByRole("button", {name: "Close settings", exact: true}).click();
    await page.getByRole("button", {name: "Close chapters", exact: true}).click();
    assert.equal(await page.locator(".shell > aside").isVisible(), false);
    await card(page, "Table.insert").scrollIntoViewIfNeeded();
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    assert.equal(await card(page, "Table.insert").locator(".cm-content").evaluate(node => getComputedStyle(node).fontSize), "16px");
    await page.screenshot({path: "/tmp/grugdb-inline-mobile.png"});
    await card(page, "Table.insert").getByRole("button", {name: "Open full file"}).click();
    assert.equal(await page.locator(".workspace-pane").isVisible(), true);
    await page.screenshot({path: "/tmp/grugdb-mobile-full-file.png"});
    await page.setViewportSize({width: 390, height: 420});
    await page.waitForFunction(() => document.querySelector(".workspace-pane").getBoundingClientRect().height <= 420);
    await page.getByRole("button", {name: "Close editor", exact: true}).click();
    assert.equal(await page.locator(".workspace-pane").isVisible(), false);
    const value = {version: 1, revision: manifest.revision, files: {"src/grugdb/table.py": "x".repeat(2_000_001)}};
    assert.equal(readBackup(value, manifest)["src/grugdb/table.py"].length, 2_000_001);
    assert.throws(() => readBackup({...value, files: {"tests/test_table.py": "pass"}}, manifest));
    assert.deepEqual(failures, []);
  } finally { await context.close(); }
});
