import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { createServer } from "node:net";
import { after, before, test } from "node:test";
import { chromium } from "@playwright/test";
import {mkdtemp, rm} from "node:fs/promises";
import {tmpdir} from "node:os";
import {join} from "node:path";

const root = new URL("../../", import.meta.url);
let serverProcess;
let browser;
let origin;
let previewPath;

before(async () => {
  const probe = createServer();
  await new Promise((resolve) => probe.listen(0, "127.0.0.1", resolve));
  const { port } = probe.address();
  await new Promise((resolve) => probe.close(resolve));
  previewPath = await mkdtemp(join(tmpdir(), "grugdb-layout-check-"));
  serverProcess = spawn("uv", ["run", "python", "-m", "tools.site", "--output", previewPath, "--serve", "--port", String(port)], {
    cwd: root,
    stdio: "ignore",
  });
  origin = `http://127.0.0.1:${port}`;
  for (let attempt = 0; attempt < 100; attempt++) {
    try {
      if ((await fetch(`${origin}/index.html`)).ok) break;
    } catch {}
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  assert.equal((await fetch(`${origin}/index.html`)).ok, true, "site server did not start");
  browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || undefined });
});

after(async () => {
  await browser?.close();
  serverProcess?.kill("SIGTERM");
  if (previewPath) await rm(previewPath, {recursive: true, force: true});
});

test("Introduction prose and code stay bounded at desktop and mobile widths", async () => {
  for (const width of [1730, 1440, 1068, 390]) {
    for (const theme of ["light", "dark"]) {
      const page = await browser.newPage({ viewport: { width, height: 1000 } });
      try {
        await page.goto(`${origin}/index.html`);
        await page.waitForSelector(".code-block .code-expand");
        await page.evaluate((theme) => { document.documentElement.dataset.theme = theme; }, theme);
        const layout = await page.evaluate(() => {
          const prose = document.querySelector(".prose");
          const wrapper = prose.querySelector(".code-block");
          const pre = wrapper.querySelector("pre");
          const code = pre.querySelector("code");
          const rect = (element) => {
            const { left, right, width } = element.getBoundingClientRect();
            return { left, right, width };
          };
          const highlightSpans = pre.querySelectorAll("span").length;
          const originalHtml = code.innerHTML;
          code.append(document.createTextNode(`\n#${"x".repeat(2000)}`));
          const longLineFits = pre.scrollWidth <= pre.clientWidth;
          code.innerHTML = originalHtml;
          return {
            viewport: innerWidth,
            document: document.documentElement.scrollWidth,
            prose: rect(prose),
            wrapper: rect(wrapper),
            pre: rect(pre),
            preClientWidth: pre.clientWidth,
            preScrollWidth: pre.scrollWidth,
            radius: getComputedStyle(pre).borderTopLeftRadius,
            highlightSpans,
            linkedTerms: prose.querySelectorAll("a.api-term").length,
            expandButton: Boolean(wrapper.querySelector(".code-expand")),
            longLineFits,
          };
        });
        assert.equal(layout.viewport, width);
        assert.ok(layout.document <= width, `document overflowed at ${width}px: ${JSON.stringify(layout)}`);
        assert.ok(layout.prose.left >= 0 && layout.prose.right <= width, `prose clipped at ${width}px`);
        assert.ok(layout.wrapper.left >= layout.prose.left && layout.wrapper.right <= layout.prose.right, `code wrapper escaped prose at ${width}px`);
        assert.ok(layout.pre.left >= layout.wrapper.left && layout.pre.right <= layout.wrapper.right, `pre escaped code wrapper at ${width}px`);
        assert.ok(layout.preScrollWidth <= layout.preClientWidth, `code overflowed its block at ${width}px`);
        assert.ok(layout.longLineFits, `long code comment overflowed at ${width}px`);
        assert.notEqual(layout.radius, "0px");
        assert.ok(layout.highlightSpans > 0, "syntax highlighting spans were lost");
        assert.ok(layout.linkedTerms > 0, "API term anchors were lost");
        assert.ok(layout.expandButton, "code expand control was lost");
        await page.screenshot({ path: `/tmp/grugdb-layout-${width}-${theme}.png`, fullPage: true });
      } finally {
        await page.close();
      }
    }
  }
});

test("API tooltip source keeps its intentional unwrapped, horizontally scrollable pre", async () => {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  try {
    await page.goto(`${origin}/index.html`);
    await page.locator(".api-term").first().hover();
    const sourceTab = page.locator('.api-tooltip [role="tab"][data-view="source"]');
    await sourceTab.waitFor({ state: "visible" });
    await sourceTab.click();
    const source = page.locator('.api-tooltip [role="tabpanel"][data-view="source"] pre');
    await source.waitFor();
    assert.equal(await source.evaluate((pre) => getComputedStyle(pre).whiteSpace), "pre");
    assert.equal(await source.evaluate((pre) => getComputedStyle(pre).overflow), "visible");
    assert.ok(await page.locator('.api-tooltip [role="tabpanel"][data-view="source"]').evaluate((panel) => {
      panel.querySelector("code").append(document.createTextNode("\\n" + "x".repeat(2000)));
      return panel.scrollWidth > panel.clientWidth;
    }));
  } finally {
    await page.close();
  }
});
