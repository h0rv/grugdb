import { build } from "esbuild";
import { createHash } from "node:crypto";
import { copyFile, mkdir, readFile, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const here = fileURLToPath(new URL(".", import.meta.url));
const vendor = new URL("../site/vendor/", import.meta.url);
const cache = new URL(".cache/", import.meta.url);
await Promise.all([mkdir(vendor, { recursive: true }), mkdir(cache, { recursive: true })]);

// Ty has no npm WASM release. These are the official playground's immutable,
// content-named assets. Verify the complete downloads before extracting only
// the standalone wasm-bindgen glue; no React or Monaco is shipped.
async function pinnedAsset(name, url, sha256) {
  const path = new URL(name, cache);
  let bytes;
  try { bytes = await readFile(path); } catch (error) {
    if (error.code !== "ENOENT") throw error;
    const response = await fetch(url);
    if (!response.ok) throw new Error(`${url}: HTTP ${response.status}`);
    bytes = Buffer.from(await response.arrayBuffer());
  }
  if (createHash("sha256").update(bytes).digest("hex") !== sha256) {
    throw new Error(`Integrity check failed for ${name}`);
  }
  await writeFile(path, bytes);
  return bytes;
}

const [playground, tyWasm] = await Promise.all([
  pinnedAsset("ty-playground.js", "https://play.ty.dev/assets/index-DKRGxPWq.js", "65fbae3aace3282ef07bc49ad48d3cb0f535f94c654d2bf2a4a717459c5c179b"),
  pinnedAsset("ty.wasm", "https://play.ty.dev/assets/ty_wasm_bg-BRDyL9SY.wasm", "9349851cf46dc2bb7e1e55f1a922851d9b21a6d94eca86f0b1a4ba5c2d8fdfdc"),
]);
const source = playground.toString("utf8");
const start = source.indexOf(",F7=class e{", source.indexOf("var V6e=t({CodeAction:"));
const end = source.indexOf("var O8e=", start);
if (start < 0 || end < start) throw new Error("The pinned Ty glue boundaries were not found.");
const glue = `var ${source.slice(start + 1, end)}\nexport { D8e as default, E8e as initSync, i9 as Workspace, q6e as PositionEncoding, Y6e as Severity, Q6e as version };\n`;
await Promise.all([
  writeFile(new URL("ty.js", cache), glue),
  writeFile(new URL("ty.wasm", vendor), tyWasm),
  copyFile(new URL("node_modules/@astral-sh/ruff-wasm-web/ruff_wasm_bg.wasm", import.meta.url), new URL("ruff.wasm", vendor)),
]);
await build({
  absWorkingDir: here,
  entryPoints: ["editor.js", "checks-worker.js"],
  outdir: fileURLToPath(vendor),
  bundle: true,
  format: "esm",
  target: "es2022",
  minify: true,
  legalComments: "eof",
});

const pyodide = new URL("pyodide/", vendor);
await mkdir(pyodide, { recursive: true });
await Promise.all([
  "pyodide.js", "pyodide.mjs", "pyodide.asm.mjs", "pyodide.asm.wasm",
  "python_stdlib.zip", "pyodide-lock.json",
].map((name) => copyFile(new URL(`node_modules/pyodide/${name}`, import.meta.url), new URL(name, pyodide))));
await copyFile(
  new URL("node_modules/@fontsource/jetbrains-mono/files/jetbrains-mono-latin-400-normal.woff2", import.meta.url),
  new URL("jetbrains-mono.woff2", vendor),
);
const licenses = new URL("licenses/", vendor);
await mkdir(licenses, { recursive: true });
const packages = [
  "@fontsource/jetbrains-mono", "@astral-sh/ruff-wasm-web", "@codemirror/autocomplete", "@codemirror/commands",
  "@codemirror/lang-python", "@codemirror/language", "@codemirror/lint", "@codemirror/search",
  "@codemirror/state", "@codemirror/view", "@lezer/common",
  "@lezer/highlight", "@lezer/lr", "@lezer/python", "@marijn/find-cluster-break",
  "@replit/codemirror-vim", "@replit/codemirror-vim-core", "crelt", "fflate", "style-mod", "w3c-keyname",
];
await Promise.all(packages.map((name) => copyFile(
  new URL(`node_modules/${name}/LICENSE`, import.meta.url),
  new URL(`${name.replaceAll("/", "-")}.txt`, licenses),
)));
await writeFile(new URL("pyodide.txt", licenses), await pinnedAsset(
  "pyodide-LICENSE", "https://raw.githubusercontent.com/pyodide/pyodide/314.0.7/LICENSE",
  "1f256ecad192880510e84ad60474eab7589218784b9a50bc7ceee34c2b91f1d5",
));
await writeFile(new URL("ty.txt", licenses), await pinnedAsset(
  "ty-LICENSE", "https://raw.githubusercontent.com/astral-sh/ty/main/LICENSE",
  "860e3d7a86b84e6a7012c7a635fc64df475cebc6cce34dfeb73a5982ec58176c",
));
console.log("Built editor.js and checks-worker.js, Ty/Ruff WASM, and Pyodide 314.0.7 in tools/site/vendor/.");
