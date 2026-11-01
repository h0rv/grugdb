import { Compartment, EditorState, Prec } from "@codemirror/state";
import { EditorView, drawSelection, highlightActiveLine, keymap, lineNumbers } from "@codemirror/view";
import { defaultKeymap, history, historyKeymap, indentWithTab } from "@codemirror/commands";
import { HighlightStyle, LanguageSupport, indentOnInput, indentUnit, syntaxHighlighting } from "@codemirror/language";
import { openSearchPanel, search, searchKeymap } from "@codemirror/search";
import { styleTags, tags } from "@lezer/highlight";
import { python, pythonLanguage } from "@codemirror/lang-python";
import { autocompletion, closeBrackets, closeBracketsKeymap, closeCompletion, startCompletion } from "@codemirror/autocomplete";
import { lintGutter, setDiagnostics as diagnosticsEffect } from "@codemirror/lint";
import { vim as vimBindings } from "@replit/codemirror-vim";
import { strToU8, zipSync } from "fflate";
import { fileEntries } from "./files.js";
export { findMethod, applyMethodEdit, replaceMethod } from "./methods.js";
export { normalizeSavedImports } from "./imports.js";

const courseTheme = EditorView.theme({
  "&": {
    fontSize: "14px", fontWeight: "400", lineHeight: "1.6", minHeight: "12rem", border: "1px solid var(--line)",
    backgroundColor: "var(--paper)", color: "var(--ink)",
  },
  ".cm-scroller": { fontFamily: "var(--font-mono, ui-monospace, monospace)", overflow: "auto" },
  ".cm-content": { padding: "0.75rem 0", caretColor: "var(--ink)" },
  ".cm-gutters": { flexShrink: "0" },
  ".cm-lineNumbers .cm-gutterElement": { fontVariantNumeric: "tabular-nums" },
  "&.cm-focused": { outline: "2px solid var(--accent)" },
  ".cm-cursor, .cm-dropCursor": { borderLeftColor: "var(--ink)" },
  ".cm-gutters, .cm-panels, .cm-tooltip": {
    backgroundColor: "var(--surface, var(--paper))", color: "var(--ink)", borderColor: "var(--line)",
  },
  ".cm-lineNumbers": { color: "var(--muted, var(--ink))" },
  ".cm-activeLine, .cm-activeLineGutter": { backgroundColor: "var(--surface, var(--line))" },
  "&.cm-focused .cm-selectionBackground, .cm-selectionBackground, .cm-content ::selection": {
    backgroundColor: "color-mix(in srgb, var(--accent) 30%, var(--paper))",
  },
  ".cm-searchMatch": { backgroundColor: "var(--line)" },
  ".cm-searchMatch-selected": { backgroundColor: "color-mix(in srgb, var(--accent) 40%, var(--paper))" },
  ".cm-textfield, .cm-button": {
    background: "var(--paper)", color: "var(--ink)", border: "1px solid var(--line)",
  },
});
const courseHighlight = HighlightStyle.define([
  { tag: [tags.keyword, tags.operatorKeyword], color: "var(--syntax-keyword)" },
  { tag: [tags.string, tags.special(tags.string), tags.regexp], color: "var(--syntax-string)" },
  { tag: tags.function(tags.variableName), color: "var(--syntax-function)" },
  { tag: [tags.typeName, tags.className, tags.namespace], color: "var(--syntax-type)" },
  { tag: [tags.number, tags.bool, tags.null], color: "var(--syntax-number)" },
  { tag: tags.operator, color: "var(--syntax-operator)" },
  { tag: tags.comment, color: "var(--muted, var(--ink))", fontStyle: "italic" },
]);
const pythonSupport = new LanguageSupport(pythonLanguage.configure({props: [styleTags({
  "TypeDef/...": tags.typeName,
  "ClassDefinition/VariableName": tags.className,
})]}), python().support);
const colorMode = (dark) => EditorView.theme({
  "&": {
    "--syntax-keyword": dark ? "#ea6962" : "#c14a4a",
    "--syntax-string": dark ? "#a9b665" : "#6c782e",
    "--syntax-function": dark ? "#7daea3" : "#45707a",
    "--syntax-type": dark ? "#d8a657" : "#b47109",
    "--syntax-number": dark ? "#d3869b" : "#945e80",
    "--syntax-operator": dark ? "#89b482" : "#4c7a5d",
  },
}, { dark });

const inlineTheme = EditorView.theme({
  "&": { minHeight: "0", height: "auto" },
  ".cm-scroller": { overflow: "visible" },
});

export const supportsVim = () => !matchMedia("(pointer: coarse) and (hover: none)").matches;

export function createEditor({ parent, doc = "", onChange = () => {}, onRun = () => {}, onFocus = () => {}, vim = false, dark = false, inline = false, readOnly = false }) {
  const mode = new Compartment();
  const theme = new Compartment();
  const access = new Compartment();
  const readOnlyExtensions = () => [EditorState.readOnly.of(readOnly), EditorView.editable.of(!readOnly)];
  const makeState = (doc) => EditorState.create({
    doc,
    extensions: [
      // Keep run and standard search shortcuts ahead of Vim's key handler.
      Prec.highest(keymap.of([
        ...["Ctrl-Enter", "Meta-Enter"].map((key) => ({ key, run: () => { onRun(); return true; } })),
        ...["Ctrl-f", "Meta-f"].map((key) => ({ key, run: openSearchPanel, scope: "editor search-panel" })),
        { key: "Ctrl-Space", run: startCompletion },
      ])),
      // Observers run even when Vim handles Escape. Public tab-focus mode
      // bypasses ALL key handlers on the following Tab, allowing native focus.
      EditorView.domEventObservers({
        keydown(event, view) {
          if (event.key === "Escape") {
            // Dismiss suggestions without consuming Escape before Vim can
            // leave insert mode. One Escape must still prepare Tab to exit.
            closeCompletion(view);
            view.setTabFocusMode(true);
          }
          else if (!["Tab", "Shift", "Control", "Alt", "Meta"].includes(event.key)) view.setTabFocusMode(false);
        },
        blur(_event, view) { view.setTabFocusMode(false); },
      }),
      mode.of(vim && supportsVim() ? vimBindings() : []),
      lineNumbers(), history(), drawSelection(), highlightActiveLine(), EditorView.lineWrapping,
      pythonSupport, autocompletion(), closeBrackets(), indentUnit.of("    "), indentOnInput(),
      syntaxHighlighting(courseHighlight), search(),
      keymap.of([...closeBracketsKeymap, indentWithTab, ...defaultKeymap, ...historyKeymap, ...searchKeymap]),
      lintGutter(), courseTheme, inline ? inlineTheme : [], theme.of(colorMode(dark)),
      access.of(readOnlyExtensions()),
      EditorView.contentAttributes.of({
        "tabindex": "0",
        "autocapitalize": "off",
        "autocorrect": "off",
        "autocomplete": "off",
        "spellcheck": "false",
        "aria-label": "Python source editor",
        "aria-description": "Press Control or Command Enter to run. Press Escape then Tab to leave the editor.",
      }),
      EditorView.updateListener.of((update) => {
        if (update.docChanged) onChange(update.state.doc.toString());
        if (update.focusChanged && update.view.hasFocus) onFocus();
      }),
    ],
  });
  const view = new EditorView({ parent, state: makeState(doc) });
  const revealLine = (line) => {
    const number = Number.isFinite(line) ? Math.trunc(line) : 1;
    const row = view.state.doc.line(Math.max(1, Math.min(view.state.doc.lines, number)));
    view.dispatch({ selection: { anchor: row.from }, effects: EditorView.scrollIntoView(row.from, { y: "center" }) });
    view.focus();
  };
  return {
    getValue: () => view.state.doc.toString(),
    setValue(value) {
      // A file switch needs a fresh history, including when both files have
      // identical text. setState does not call the change listener.
      view.setState(makeState(value));
      view.setTabFocusMode(false);
    },
    focus: (line) => line === undefined ? view.focus() : revealLine(line),
    revealLine,
    setVim(enabled) {
      vim = enabled && supportsVim();
      view.dispatch({ effects: mode.reconfigure(vim ? vimBindings() : []) });
    },
    setDark(enabled) {
      dark = enabled;
      view.dispatch({ effects: theme.reconfigure(colorMode(enabled)) });
    },
    setReadOnly(enabled) {
      readOnly = enabled;
      view.dispatch({ effects: access.reconfigure(readOnlyExtensions()) });
    },
    setDiagnostics(diagnostics) {
      const position = (line, column) => {
        const row = view.state.doc.line(Math.max(1, Math.min(view.state.doc.lines, line ?? 1)));
        return row.from + Math.max(0, Math.min(row.length, (column ?? 1) - 1));
      };
      view.dispatch(diagnosticsEffect(view.state, diagnostics.map((item) => {
        const from = position(item.line, item.column);
        return {
          from,
          to: Math.max(from, position(item.endLine ?? item.line, item.endColumn ?? item.column)),
          message: item.message,
          severity: item.severity === "warning" ? "warning" : item.severity === "info" ? "info" : "error",
          source: item.source,
        };
      })));
    },
    destroy: () => view.destroy(),
  };
}

export function zipFiles(files) {
  const archive = Object.create(null);
  for (const { relative, content } of fileEntries(files)) archive[relative] = strToU8(content);
  return zipSync(archive);
}
