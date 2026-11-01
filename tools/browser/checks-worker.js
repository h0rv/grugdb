import initTy, { Workspace as TyWorkspace, PositionEncoding as TyEncoding, Severity } from "./.cache/ty.js";
import initRuff, { Workspace as RuffWorkspace, PositionEncoding as RuffEncoding } from "@astral-sh/ruff-wasm-web";
import { fileEntries } from "./files.js";

const tyOptions = {
  environment: {
    "python-version": "3.14",
    "extra-paths": ["/workspace/src", "/workspace"],
  },
  rules: { "unsound-assignment": "error", "unsound-return-statement": "error" },
};
const ruffOptions = {
  "target-version": "py314",
  "line-length": 100,
  lint: { select: ["E", "F", "I", "UP", "B", "SIM", "RUF", "ANN", "C4", "PERF"] },
};

let loading;
function loadCheckers() {
  return loading ??= Promise.allSettled([
    initTy({ module_or_path: new URL("./ty.wasm", import.meta.url) }),
    initRuff({ module_or_path: new URL("./ruff.wasm", import.meta.url) }),
  ]);
}

function checkTy(files) {
  // Ty validates import directories when options are applied, before files exist.
  const workspace = new TyWorkspace("/workspace", TyEncoding.Utf16, {});
  const handles = [];
  try {
    const placeholder = workspace.openFile("/workspace/src/.browser-root.py", "");
    workspace.closeFile(placeholder);
    // Load every supplied module before checking, including provided read-only
    // modules. A fresh workspace also removes files deleted since the last run.
    for (const file of files) {
      handles.push({ ...file, handle: workspace.openFile(`/workspace/${file.relative}`, file.content) });
    }
    workspace.updateOptions(tyOptions);
    const result = [];
    for (const { path, handle } of handles) {
      const diagnostics = workspace.checkFile(handle);
      for (const diagnostic of diagnostics) {
        let range;
        let start;
        let end;
        try {
          range = diagnostic.toRange(workspace);
          start = range?.start;
          end = range?.end;
          const severity = diagnostic.severity();
          result.push({
            path,
            line: start?.line ?? 1,
            column: start?.column ?? 1,
            endLine: end?.line ?? 1,
            endColumn: end?.column ?? 1,
            message: `${diagnostic.message()} [${diagnostic.id()}]`,
            severity: severity === Severity.Warning ? "warning"
              : severity === Severity.Info || severity === Severity.Hint ? "info" : "error",
            source: "ty",
          });
        } finally {
          start?.free(); end?.free(); range?.free(); diagnostic.free();
        }
      }
    }
    return result;
  } finally {
    for (const { handle } of handles) handle.free();
    workspace.free();
  }
}

function checkRuff(files) {
  const result = [];
  for (const { path, relative, content } of files) {
    // Ruff's direct WASM API checks text, not a filesystem. Configure the one
    // course per-file exception explicitly because check() has no path argument.
    const options = relative === "src/grugdb/query.py"
      ? { ...ruffOptions, lint: { ...ruffOptions.lint, ignore: ["ANN401"] } } : ruffOptions;
    const workspace = new RuffWorkspace(options, RuffEncoding.Utf16);
    try {
      for (const diagnostic of workspace.check(content)) {
        result.push({
          path,
          line: diagnostic.start_location.row,
          column: diagnostic.start_location.column,
          endLine: diagnostic.end_location.row,
          endColumn: diagnostic.end_location.column,
          message: `${diagnostic.message}${diagnostic.code ? ` [${diagnostic.code}]` : ""}`,
          severity: diagnostic.code === null ? "error" : "warning",
          source: "ruff",
        });
      }
    } finally { workspace.free(); }
  }
  return result;
}

export async function checkFiles({ id, files }) {
  const loaded = await loadCheckers();
  const available = { ty: loaded[0].status === "fulfilled", ruff: loaded[1].status === "fulfilled" };
  const diagnostics = [];
  const errors = loaded.flatMap((item, index) => item.status === "rejected"
    ? [`${index === 0 ? "ty" : "ruff"}: ${String(item.reason)}`] : []);
  try {
    const sources = fileEntries(files).filter(({ relative }) => /\.(py|pyi)$/.test(relative));
    for (const [name, check] of [["ty", checkTy], ["ruff", checkRuff]]) {
      if (!available[name]) continue;
      try { diagnostics.push(...check(sources)); } catch (error) {
        errors.push(`${name}: ${String(error)}`);
        available[name] = false;
      }
    }
  } catch (error) { errors.push(String(error)); }
  return { id, kind: "result", diagnostics, available, ...(errors.length ? { error: errors.join("\n") } : {}) };
}

// Serialize requests so one check cannot mutate a checker's WASM state during
// another request. The id lets callers discard replies for older edits.
let pending = Promise.resolve();
self.addEventListener("message", ({ data }) => {
  pending = pending.then(() => checkFiles(data)).then(
    (result) => self.postMessage(result),
    (error) => self.postMessage({ id: data?.id, kind: "result", diagnostics: [], available: { ty: false, ruff: false }, error: String(error) }),
  );
});
