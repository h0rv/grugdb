const assetURL = path => {
  const url = new URL(path, import.meta.url);
  url.search = new URL(import.meta.url).search;
  return url;
};
const {openStorage, projectFiles, readBackup, saveEdit, validPath} = await import(assetURL("./workspace-state.js"));

const navToggle = document.querySelector("#nav-toggle");
const navReopen = document.querySelector("#nav-reopen");
let navHidden = matchMedia("(max-width: 899px)").matches;
try {
  const savedNav = localStorage.getItem("grugdb-nav-hidden");
  if (savedNav !== null) navHidden = savedNav === "true";
} catch {}
function setNavHidden(value) {
  document.body.classList.toggle("nav-hidden", value);
  navToggle?.setAttribute("aria-expanded", String(!value));
  navToggle?.setAttribute("aria-label", value ? "Show sidebar" : "Hide sidebar");
}
setNavHidden(navHidden);
for (const toggle of [navToggle, navReopen, document.querySelector("#nav-dismiss")]) toggle?.addEventListener("click", () => {
  navHidden = !document.body.classList.contains("nav-hidden");
  setNavHidden(navHidden);
  try { localStorage.setItem("grugdb-nav-hidden", String(navHidden)); } catch {}
});

const toolbar = document.querySelector("[data-course]");
if (!toolbar) document.querySelector("#open-workspace")?.addEventListener("click", () => { location.href = "index.html#files"; });
if (!toolbar) document.querySelector("#workspace-settings")?.addEventListener("click", () => { location.href = "index.html#settings"; });
if (!toolbar) document.querySelector("#course-help")?.addEventListener("click", () => { location.href = "index.html#help"; });
if (toolbar) start().catch(error => {
  const status = document.querySelector(".side-status");
  if (status) status.textContent = `Editors unavailable. ${error.message}`;
});

async function start() {
  if (location.protocol === "file:") return;
  const response = await fetch(new URL("workspace.json", import.meta.url), {cache: "no-store"});
  if (!response.ok) throw new Error("Could not load the exercise files.");
  const manifest = await response.json();
  const {createEditor, zipFiles, findMethod, applyMethodEdit, normalizeSavedImports} = await import(assetURL("./vendor/editor.js"));
  await document.fonts.load('14px "JetBrains Mono"').catch(() => {});
  const lesson = manifest.lessons.find(item => item.slug === toolbar.dataset.lesson) ?? manifest.lessons[0];
  const exercises = manifest.exercises.filter(item => item.lesson === toolbar.dataset.lesson);
  let edits = {}, results = {}, sourceVersion = 0, storage = null, warning = "";
  let saveQueue = Promise.resolve(), pendingSaves = 0, courseChanged = false;
  let vim = false;
  try { vim = localStorage.getItem("grugdb-vim") === "true"; } catch {}
  try {
    storage = await openStorage();
    if (storage.record) {
      edits = readBackup(storage.record, manifest);
      sourceVersion = Number.isSafeInteger(storage.record.sourceVersion) ? storage.record.sourceVersion : 0;
      if (storage.record.revision === manifest.revision) {
        for (const [id, result] of Object.entries(storage.record.results ?? {})) {
          if (manifest.tests.includes(id) && result?.sourceVersion === sourceVersion &&
              ["passed", "failed", "error", "skipped"].includes(result.status)) results[id] = result;
        }
      } else { courseChanged = true; warning = "Rechecking your saved work after a course update…"; }
    }
  } catch (error) { warning = `Autosave unavailable. ${error.message} Download a backup before leaving.`; }
  function maintainImports() {
    let changed = false;
    for (const [path, source] of Object.entries(edits)) {
      if (!path.startsWith("src/grugdb/")) continue;
      const normalized = normalizeSavedImports(source, manifest.files[path] ?? "");
      if (normalized !== source) { edits[path] = normalized; changed = true; }
    }
    return changed;
  }
  const importsChanged = maintainImports();
  if (importsChanged) { sourceVersion++; results = {}; }
  const files = () => projectFiles(manifest, edits);
  const editable = name => manifest.editable.includes(name) || (validPath(name) && !Object.hasOwn(manifest.files, name));
  const backup = () => ({version: 1, revision: manifest.revision, files: {...edits}});
  const models = [];
  const dark = () => document.documentElement.dataset.theme
    ? document.documentElement.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  let fullEditor = null, currentFile = lesson.file, diagnostics = [], checkWorker = null;
  let checkTimer, checkTimeout, autoRunTimer, pythonWorker = null, runTimeout, activeTestEditor = null;

  const el = (tag, text, parent, className) => {
    const node = document.createElement(tag);
    if (text) node.textContent = text;
    if (className) node.className = className;
    parent?.append(node);
    return node;
  };
  const button = (text, action, parent, label) => {
    const node = el("button", text, parent);
    node.type = "button";
    if (label) { node.setAttribute("aria-label", label); node.title = label; }
    node.addEventListener("click", action);
    return node;
  };
  const sideStatus = document.querySelector(".side-status");
  const settings = el("dialog", "", document.body, "editor-settings-dialog");
  el("h2", "Editor settings", settings);
  button("Close", () => settings.close(), settings, "Close settings");
  const keyControls = el("fieldset", "", settings, "editor-keys");
  const help = el("dialog", "", document.body, "course-help-dialog");
  el("h2", "Help", help);
  button("Close", () => help.close(), help, "Close help");
  el("p", "Edits save in this browser. Types, lint, and tests update after a short pause.", help);
  el("p", "The editor is CodeMirror 6. Ty checks types, and Ruff checks lint. Python runs in your browser with Pyodide.", help);
  el("p", "Ctrl/⌘ Enter reruns the current method's tests. Ctrl/⌘ Space opens completions. Escape, then Tab leaves an editor.", help);
  el("p", "Download a backup to keep a separate copy. Clearing site data removes browser edits.", help);
  for (const local of document.querySelectorAll("main .local-only")) help.append(local);
  document.querySelector("#workspace-settings")?.addEventListener("click", () => settings.showModal());
  document.querySelector("#course-help")?.addEventListener("click", () => help.showModal());
  const sidebar = document.querySelector(".shell > aside");
  const filesButton = document.querySelector("#open-workspace");
  filesButton?.addEventListener("click", () => openWorkspace());
  el("legend", "Keys", keyControls);
  for (const [value, label] of [[false, "Standard"], [true, "Vim"]]) {
    const wrap = el("label", "", keyControls);
    const input = el("input", "", wrap);
    input.type = "radio"; input.name = "editor-keys"; input.value = value ? "vim" : "standard"; input.checked = vim === value;
    el("span", label, wrap);
    input.addEventListener("change", () => {
      vim = value;
      for (const model of models) model.editor?.setVim(vim);
      fullEditor?.setVim(vim);
      try { localStorage.setItem("grugdb-vim", String(vim)); } catch {}
    });
  }
  const saved = el("span", Object.keys(edits).length ? "Saved" : "Autosave on", settings, "save-status");
  saved.hidden = true;
  const checksStatus = el("p", "Starting checks…", null, "checks-status");
  checksStatus.setAttribute("role", "status");
  const warningBox = el("p", warning, sideStatus, "save-warning");
  warningBox.hidden = !warning;
  warningBox.setAttribute("role", "status");

  const pane = el("section", "", document.body, "workspace-pane");
  pane.id = "full-workspace"; pane.hidden = true;
  pane.setAttribute("aria-label", "Full workspace");
  function fitEditorViewport() {
    pane.style.height = `${visualViewport?.height ?? innerHeight}px`;
    pane.style.top = `${visualViewport?.offsetTop ?? 0}px`;
    pane.style.bottom = "auto";
  }
  visualViewport?.addEventListener("resize", fitEditorViewport);
  visualViewport?.addEventListener("scroll", fitEditorViewport);
  window.addEventListener("resize", fitEditorViewport);
  fitEditorViewport();
  const resize = el("div", "", pane, "workspace-resize");
  resize.tabIndex = 0; resize.setAttribute("role", "separator");
  resize.setAttribute("aria-orientation", "vertical"); resize.setAttribute("aria-label", "Resize workspace");
  const paneHeader = el("header", "", pane, "workspace-header");
  const filename = el("code", currentFile, paneHeader);
  const fileState = el("span", "", paneHeader);
  let filesHidden = innerWidth < 900;
  const filesToggle = button("Files", () => setFilesHidden(!filesHidden), paneHeader);
  paneHeader.prepend(filesToggle);
  const maximize = button("Full screen", () => {
    if (innerWidth < 900 && document.body.classList.contains("workspace-full")) closeWorkspace();
    else setFull(!document.body.classList.contains("workspace-full"));
  }, paneHeader, "Full screen");
  button("Close editor", closeWorkspace, paneHeader);
  const workBody = el("div", "", pane, "workspace-body");
  const tree = el("nav", "", workBody, "file-tree");
  tree.setAttribute("aria-label", "Project files");
  const fileArea = el("section", "", workBody, "file-area");
  const fullEditorHost = el("div", "", fileArea, "full-editor");
  const consoleArea = el("section", "", pane, "workspace-console");
  consoleArea.hidden = true;
  const consoleActions = el("div", "", consoleArea, "console-actions");
  const stopButton = button("Stop", () => stopTests("Stopped. These tests did not finish."), consoleActions);
  stopButton.hidden = true;
  const tabs = el("div", "", consoleArea, "console-tabs");
  tabs.setAttribute("role", "tablist");
  const panels = {}, tabButtons = {};
  for (const name of ["tests", "problems"]) {
    const tab = button(name[0].toUpperCase() + name.slice(1), () => selectTab(name), tabs);
    tab.id = `console-tab-${name}`; tab.setAttribute("role", "tab"); tab.setAttribute("aria-controls", `console-${name}`);
    const panel = el("div", "", consoleArea, "console-panel");
    panel.id = `console-${name}`; panel.setAttribute("role", "tabpanel"); panel.setAttribute("aria-labelledby", tab.id);
    panels[name] = panel; tabButtons[name] = tab;
  }
  selectTab("tests");
  el("p", "Tests update automatically when you edit.", panels.tests);
  panels.problems.append(checksStatus);
  button("Download Python files (.zip)", () => download(zipFiles(files()), "grugdb-exercises.zip", "application/zip"), help);
  const treeActions = el("div", "", tree, "tree-actions");
  button("Export backup", () => download(JSON.stringify(backup(), null, 2), "grugdb-workspace.json", "application/json"), treeActions);
  const upload = el("input", "", treeActions); upload.type = "file"; upload.accept = ".json,application/json"; upload.hidden = true;
  button("Import backup", () => upload.click(), treeActions);

  upload.addEventListener("change", async () => {
    try {
      const file = upload.files[0]; if (!file) return;
      if (file.size > 4_000_000 && !confirm("This is a large backup. Continue?")) return;
      const value = JSON.parse(await file.text());
      const imported = readBackup(value, manifest);
      if (!confirm("Replace your browser edits with this backup? Download a backup first to keep both.")) return;
      stopTests(); edits = imported; maintainImports();
      courseChanged = value.revision !== manifest.revision;
      warning = courseChanged ? "Rechecking your imported work…" : "";
      sourceChanged(); for (const path of new Set(models.map(model => model.exercise.file))) syncFile(path);
      if (!Object.hasOwn(files(), currentFile)) currentFile = lesson.file;
      openFile(currentFile); renderTree();
    } catch (error) { alert(error.message); }
    finally { upload.value = ""; }
  });

  for (const exercise of exercises) {
    const card = document.querySelector(`[data-exercise="${CSS.escape(exercise.id)}"]`);
    if (!card) continue;
    card.replaceChildren();
    const header = el("header", "", card, "exercise-header");
    el("code", exercise.id, header);
    button("Open full file", () => {
      openWorkspace(null, exercise.file);
      fullEditor.focus(model.range?.startLine ?? exercise.start_line);
    }, header, `Open full file for ${exercise.id}`);
    const status = el("span", "Not run", header, "exercise-status"); status.setAttribute("role", "status");
    const editorHost = el("div", "", card, "method-editor");
    const hint = el("p", "", card, "exercise-hint"); hint.hidden = true;
    const feedback = el("div", "", card, "exercise-feedback");
    const range = findMethod(files()[exercise.file], exercise.class_name, exercise.method);
    const model = {exercise, card, status, hint, feedback, range, editor: null};
    model.editor = createEditor({parent: editorHost, doc: range?.code ?? exercise.source, vim, dark: dark(), inline: true, readOnly: !range,
      onRun: () => runTests(exercise.tests, exercise.id, model),
      onChange(text) {
        if (!model.range) return;
        const previous = model.range;
        const updated = applyMethodEdit(files()[exercise.file], previous, text);
        saveEdit(edits, manifest, exercise.file, updated.source);
        model.range = updated.range;
        const delta = updated.range.to - previous.to;
        for (const other of models) {
          if (other === model || other.exercise.file !== exercise.file || !other.range) continue;
          if (other.range.from >= previous.to) {
            other.range = {...other.range, from: other.range.from + delta, to: other.range.to + delta};
            other.range.startLine = updated.source.slice(0, other.range.from).split("\n").length;
          }
        }
        if (fullEditor && currentFile === exercise.file) fullEditor.setValue(updated.source);
        sourceChanged();
      },
    });
    models.push(model);
    if (!range) showMissing(model);
  }
  const chapter = el("section", "", null, "chapter-checks");
  if (models.length) models.at(-1).card.closest("ul, ol").after(chapter);
  const chapterStatus = el("p", "Chapter checks are starting…", chapter);
  chapterStatus.setAttribute("role", "status");
  function showMissing(model) {
    model.hint.hidden = false;
    model.hint.replaceChildren();
    el("span", "This method could not be located. Your file is kept. ", model.hint);
    button("Open full file", () => openWorkspace("problems", model.exercise.file), model.hint);
  }
  function syncFile(path) {
    const source = files()[path];
    for (const model of models.filter(item => item.exercise.file === path)) {
      model.range = findMethod(source, model.exercise.class_name, model.exercise.method);
      model.editor.setReadOnly(!model.range);
      model.hint.hidden = Boolean(model.range);
      if (model.range) model.editor.setValue(model.range.code);
      else showMissing(model);
    }
    if (fullEditor && currentFile === path && fullEditor.getValue() !== source) fullEditor.setValue(source);
  }
  function openFile(path, line) {
    if (!Object.hasOwn(files(), path)) return;
    const switched = currentFile !== path;
    currentFile = path; filename.textContent = path; fileState.textContent = editable(path) ? "" : "Read only";
    if (!fullEditor) fullEditor = createEditor({parent: fullEditorHost, doc: files()[path], vim, dark: dark(), readOnly: !editable(path),
      onRun: () => runTests(lesson.tests, lesson.title),
      onChange(text) {
        if (!editable(currentFile)) return;
        saveEdit(edits, manifest, currentFile, text);
        sourceChanged(); syncFile(currentFile);
      },
    });
    else {
      if (switched || fullEditor.getValue() !== files()[path]) fullEditor.setValue(files()[path]);
      fullEditor.setReadOnly(!editable(path));
    }
    fullEditor.setDiagnostics(diagnostics.filter(item => item.path === path));
    if (line) fullEditor.focus(line);
    renderTree();
  }
  function renderTree() {
    tree.querySelector(".tree-root")?.remove();
    const root = el("ul", "", null, "tree-root");
    tree.prepend(root);
    const folders = new Map([["", root]]);
    for (const path of Object.keys(files()).sort()) {
      const parts = path.split("/");
      let prefix = "", parent = root;
      for (const part of parts.slice(0, -1)) {
        prefix += `${part}/`;
        if (!folders.has(prefix)) {
          const folder = el("li", "", parent, "tree-folder");
          el("span", `${part}/`, folder, "tree-folder-label");
          folders.set(prefix, el("ul", "", folder, "tree-children"));
        }
        parent = folders.get(prefix);
      }
      const item = el("li", "", parent);
      const file = button(parts.at(-1), () => openWorkspace(null, path), item);
      file.className = "tree-file"; file.title = path;
      file.setAttribute("aria-current", String(path === currentFile));
    }
  }
  function openWorkspace(tab, path) {
    pane.hidden = false;
    document.body.classList.add("workspace-open");
    if (innerWidth < 900) { setNavHidden(true); setFull(true); }
    openFile(path ?? currentFile);
    if (!checkWorker) scheduleChecks();
    if (tab) { consoleArea.hidden = false; selectTab(tab); }
  }
  function openExample(pre) {
    const code = (pre.querySelector("code") ?? pre).textContent;
    openWorkspace();
    currentFile = null;
    filename.textContent = "Example";
    fileState.textContent = "Read only";
    fullEditor.setValue(code);
    fullEditor.setReadOnly(true);
    fullEditor.focus(1);
    document.querySelector('[aria-label="Close preview"]')?.click();
    renderTree();
  }
  function expandControls(root) {
    for (const pre of root.querySelectorAll("pre.highlight")) {
      const wrap = document.createElement("div");
      wrap.className = "code-block";
      pre.replaceWith(wrap); wrap.append(pre);
      const expand = el("button", "↗", wrap, "code-expand");
      expand.type = "button"; expand.dataset.expandCode = "";
      expand.setAttribute("aria-label", "Expand code block");
    }
  }
  expandControls(document.querySelector("main"));
  expandControls(help);
  for (const template of document.querySelectorAll('template[id^="api-preview-"]')) expandControls(template.content);
  document.addEventListener("click", event => {
    const expand = event.target.closest("[data-expand-code]");
    if (expand) openExample(expand.closest(".code-block").querySelector("pre"));
  });
  function setFilesHidden(hidden) {
    filesHidden = hidden;
    tree.inert = hidden;
    tree.setAttribute("aria-hidden", String(hidden));
    workBody.classList.toggle("files-hidden", hidden);
    filesToggle.setAttribute("aria-label", hidden ? "Show files" : "Hide files");
    filesToggle.title = hidden ? "Show files" : "Hide files";
    filesToggle.setAttribute("aria-expanded", String(!hidden));
  }
  function setFull(full) {
    document.body.classList.toggle("workspace-full", full);
    maximize.textContent = full ? "Split view" : "Full screen";
    maximize.setAttribute("aria-label", maximize.textContent);
    maximize.hidden = innerWidth < 900;
  }
  function closeWorkspace() {
    setFull(false);
    pane.hidden = true; document.body.classList.remove("workspace-open");
    filesButton?.focus();
  }
  function selectTab(name) {
    for (const key of Object.keys(panels)) {
      panels[key].hidden = key !== name;
      tabButtons[key].setAttribute("aria-selected", String(key === name));
    }
  }
  resize.addEventListener("pointerdown", event => {
    resize.setPointerCapture(event.pointerId);
    const move = event => setWidth(innerWidth - event.clientX);
    resize.addEventListener("pointermove", move);
    resize.addEventListener("pointerup", () => resize.removeEventListener("pointermove", move), {once: true});
  });
  resize.addEventListener("keydown", event => {
    if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
    event.preventDefault(); setWidth(pane.getBoundingClientRect().width + (event.key === "ArrowLeft" ? 40 : -40));
  });
  function setWidth(width) {
    const minimumLeft = 320 + (document.body.classList.contains("nav-hidden") ? 0 : sidebar.getBoundingClientRect().width);
    const maximumWidth = Math.max(360, innerWidth - minimumLeft);
    document.documentElement.style.setProperty("--workspace-width", `${Math.max(360, Math.min(maximumWidth, width))}px`);
  }
  document.addEventListener("click", event => {
    const link = event.target.closest("[data-edit-file]");
    if (link) { event.preventDefault(); openWorkspace(null, link.dataset.editFile); }
  });
  window.addEventListener("beforeunload", event => {
    if (pendingSaves || (warning && Object.keys(edits).length)) { event.preventDefault(); event.returnValue = ""; }
  });
  function clearCourseNotice() {
    if (!courseChanged) return;
    courseChanged = false;
    if (warning.startsWith("Rechecking")) {
      warning = ""; warningBox.textContent = ""; warningBox.hidden = true;
      persist();
    }
  }
  function persist() {
    warningBox.textContent = warning; warningBox.hidden = !warning;
    if (!storage || warning.startsWith("Autosave") || warning.startsWith("Another tab")) return;
    const snapshot = structuredClone({...backup(), results, sourceVersion});
    pendingSaves++; saved.textContent = "Saving…";
    saveQueue = saveQueue.then(() => storage.write(snapshot)).then(() => {
      pendingSaves--; saved.textContent = pendingSaves ? "Saving…" : "Saved";
    }).catch(error => {
      pendingSaves--; warning = error.message; saved.textContent = "Not saved";
      warningBox.textContent = warning; warningBox.hidden = false;
    });
  }
  function sourceChanged() {
    stopTests();
    sourceVersion++; results = {}; diagnostics = [];
    for (const model of models) { model.editor?.setDiagnostics([]); model.feedback.replaceChildren(); }
    fullEditor?.setDiagnostics([]);
    updateProgress(); persist(); scheduleChecks(); scheduleTests();
  }
  function updateProgress() {
    for (const model of models) {
      const known = model.exercise.tests.map(id => results[id]).filter(item => item?.sourceVersion === sourceVersion);
      const passed = known.filter(item => item.status === "passed").length;
      model.status.textContent = known.length ? `${passed}/${model.exercise.tests.length} passed` : "Not run";
    }
    const chapterPassed = lesson.tests.filter(id => results[id]?.sourceVersion === sourceVersion && results[id].status === "passed").length;
    if (chapterStatus) chapterStatus.textContent = `${chapterPassed} of ${lesson.tests.length} chapter tests passing.`;
    for (const item of manifest.lessons) {
      const link = document.querySelector(`nav a[href="${CSS.escape(item.slug)}.html"]`);
      link?.querySelector(".test-progress")?.remove();
      if (!item.tests.length || !item.tests.some(id => results[id]?.sourceVersion === sourceVersion)) continue;
      const passed = item.tests.filter(id => results[id]?.sourceVersion === sourceVersion && results[id].status === "passed").length;
      if (link) el("small", `${passed}/${item.tests.length} tests`, link, "test-progress");
    }
  }
  function scheduleTests() {
    clearTimeout(autoRunTimer);
    if (lesson.local || (!models.length && pane.hidden)) return;
    const tests = [...new Set([...lesson.tests, ...exercises.flatMap(item => item.tests)])];
    autoRunTimer = setTimeout(() => runTests(tests, lesson.title), 900);
  }
  function scheduleChecks() {
    clearTimeout(checkTimer); checksStatus.textContent = "Checking…";
    checkTimer = setTimeout(checkCode, 500);
  }
  function checkCode() {
    const version = sourceVersion;
    if (!checkWorker) {
      checkWorker = new Worker(assetURL("vendor/checks-worker.js"), {type: "module"});
      checkWorker.onerror = event => { checksStatus.textContent = "Checks unavailable"; panels.problems.textContent = event.message; };
      checkWorker.onmessage = ({data}) => {
        if (data.id !== sourceVersion) return;
        clearTimeout(checkTimeout);
        diagnostics = data.diagnostics ?? [];
        tabButtons.problems.textContent = diagnostics.length ? `Problems (${diagnostics.length})` : "Problems";
        const types = diagnostics.filter(item => item.source === "ty").length;
        const lint = diagnostics.filter(item => item.source === "ruff").length;
        const unavailable = !data.available?.ty || !data.available?.ruff;
        checksStatus.textContent = unavailable ? "Checks unavailable" : types + lint ? `${types + lint} problems` : "Checks passing";
        checksStatus.title = `Ty: ${types}. Ruff: ${lint}. View problems.`;
        if (!unavailable) clearCourseNotice();
        panels.problems.replaceChildren(checksStatus);
        if (data.error) el("p", data.error, panels.problems);
        if (!diagnostics.length) el("p", "No problems found.", panels.problems);
        for (const item of diagnostics.slice(0, 500)) {
          const row = button(`${item.path}:${item.line} ${item.message}`, () => openFile(item.path, item.line), panels.problems);
          row.className = "problem-row";
        }
        if (diagnostics.length > 500) el("p", `Showing 500 of ${diagnostics.length} problems.`, panels.problems);
        for (const model of models) {
          if (!model.range) continue;
          const endLine = model.range.startLine + model.editor.getValue().split("\n").length - 1;
          const indentation = typeof model.range.indent === "string" ? model.range.indent.length : model.range.indent;
          model.editor.setDiagnostics(diagnostics.filter(item => item.path === model.exercise.file && item.line >= model.range.startLine && item.line <= endLine)
            .map(item => ({...item, line: item.line - model.range.startLine + 1, endLine: item.endLine - model.range.startLine + 1,
              column: Math.max(1, item.column - indentation), endColumn: Math.max(1, item.endColumn - indentation)})));
        }
        fullEditor?.setDiagnostics(diagnostics.filter(item => item.path === currentFile));
      };
    }
    clearTimeout(checkTimeout);
    checkTimeout = setTimeout(() => {
      checkWorker?.terminate(); checkWorker = null; checksStatus.textContent = "Checks timed out";
    }, 30000);
    checkWorker.postMessage({id: version, files: files()});
  }
  function stopTests(message) {
    clearTimeout(runTimeout); pythonWorker?.terminate(); pythonWorker = null;
    stopButton.hidden = true;
    if (chapterStatus) chapterStatus.dataset.running = "false";
    if (message && activeTestEditor) activeTestEditor.status.textContent = message;
    if (message) { panels.tests.replaceChildren(); el("p", message, panels.tests); }
  }
  function runTests(tests, title, model = null) {
    clearTimeout(autoRunTimer);
    stopTests();
    if (!tests.length) { openWorkspace("tests"); panels.tests.textContent = "This chapter has no supplied tests. Continue with the local exercises."; return; }
    const version = sourceVersion;
    activeTestEditor = model;
    consoleArea.hidden = false;
    stopButton.hidden = false;
    if (chapterStatus) chapterStatus.dataset.running = "true";
    if (model) { model.status.textContent = "Running…"; model.feedback.replaceChildren(); button("Stop", () => stopTests("Stopped"), model.feedback); }
    panels.tests.replaceChildren(); el("p", `Running ${title}…`, panels.tests);
    const worker = new Worker(assetURL("python-worker.js"), {type: "module"}); pythonWorker = worker;
    worker.onerror = event => { if (pythonWorker === worker) stopTests(event.message); };
    worker.onmessage = ({data}) => {
      if (pythonWorker !== worker) return;
      if (data.kind === "error") { stopTests(data.message); return; }
      if (data.kind !== "result") return;
      stopTests();
      if (version !== sourceVersion) { if (model) model.status.textContent = "Code changed. Run again."; return; }
      for (const id of tests) {
        if (!manifest.tests.includes(id)) continue;
        const matches = data.tests.filter(item => item.id === id);
        results[id] = matches.length === 1 ? {...matches[0], sourceVersion}
          : {id, status: "error", detail: data.tests.map(item => item.detail).filter(Boolean).join("\n"), sourceVersion};
      }
      clearCourseNotice(); updateProgress(); persist();
      renderTests(data.tests, panels.tests, title);
      if (model) renderTests(data.tests, model.feedback, "");
      else for (const item of models) {
        const focused = data.tests.filter(test => item.exercise.tests.includes(test.id));
        if (focused.length) renderTests(focused, item.feedback, "");
      }
      if (data.output) {
        el("h3", "Output", panels.tests);
        el("pre", data.output, panels.tests, "program-output");
      }
    };
    worker.postMessage({id: version, files: files(), tests, runtimeURL: new URL("vendor/pyodide/pyodide.mjs", import.meta.url).href});
    runTimeout = setTimeout(() => stopTests("Stopped after 60 seconds. Your edits are kept."), 60000);
  }
  function renderTests(tests, container, title) {
    container.replaceChildren();
    const passed = tests.filter(item => item.status === "passed").length;
    el("p", `${title ? `${title}: ` : ""}${passed} of ${tests.length} passed.`, container, "test-summary");
    for (const test of tests) {
      const detail = el("details", "", container, `test-row test-${test.status}`);
      const label = manifest.test_descriptions?.[test.id] ?? test.id.split(".").at(-1).replace(/^test_/, "").replaceAll("_", " ");
      el("summary", `${test.status === "passed" ? "✓" : test.status === "skipped" ? "○" : "×"} ${label}`, detail);
      el("code", test.id, detail);
      if (test.detail) el("pre", test.detail, detail);
    }
  }
  function download(value, filename, type) {
    const url = URL.createObjectURL(new Blob([value], {type}));
    const link = el("a"); link.href = url; link.download = filename; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  const setDark = () => { for (const model of models) model.editor?.setDark(dark()); fullEditor?.setDark(dark()); };
  new MutationObserver(setDark).observe(document.documentElement, {attributes: true, attributeFilter: ["data-theme"]});
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", setDark);
  renderTree(); updateProgress(); setFilesHidden(filesHidden);
  if (importsChanged) persist();
  if (models.length) { scheduleChecks(); scheduleTests(); }
  if (location.hash === "#files") openWorkspace();
  if (location.hash === "#settings") settings.showModal();
  if (location.hash === "#help" || (location.hash && help.contains(document.getElementById(location.hash.slice(1))))) help.showModal();
}
