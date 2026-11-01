import { parser } from "@lezer/python";

const helpers = new Set(["itertools.islice", "grugdb.expr.Desc", "grugdb.query.Scan"]);
const opaque = new Set(["String", "FormatString", "Comment"]);

function hasError(node) {
  if (node.type.isError) return true;
  for (let child = node.firstChild; child; child = child.nextSibling) {
    if (hasError(child)) return true;
  }
  return false;
}

function importsIn(source) {
  const tree = parser.parse(source);
  // Recovery can make an apparent import part of an unfinished expression.
  if (hasError(tree.topNode)) return null;
  const imports = [];
  function visit(node) {
    if (opaque.has(node.name)) return;
    if (node.name === "ImportStatement") {
      const tokens = [];
      for (let child = node.firstChild; child; child = child.nextSibling) {
        if (child.name !== "Comment") tokens.push(child);
      }
      if (tokens[0]?.name !== "from") return;
      const keyword = tokens.findIndex((token) => token.name === "import");
      const path = tokens.slice(1, keyword);
      const relative = path[0]?.name === ".";
      // Only one-dot imports refer to this package, not its parent.
      const local = relative && path[1]?.name !== ".";
      const module = local && path.length === 1 ? "grugdb"
        : (local ? "grugdb" : "") + path.map((token) => source.slice(token.from, token.to)).join("");
      const names = [];
      const items = tokens.slice(keyword + 1);
      const parenthesized = items[0]?.name === "(";
      if (parenthesized) {
        if (items.at(-1)?.name !== ")") return;
        items.pop();
        items.shift();
      }
      if (items.length === 1 && items[0].name === "*") {
        imports.push({ node, path, local, module, names, parenthesized });
        return;
      }
      while (items.length) {
        const name = items.shift();
        if (name.name !== "VariableName") return;
        let end = name;
        if (items[0]?.name === "as") {
          items.shift();
          end = items.shift();
          if (end?.name !== "VariableName") return;
        }
        names.push({ name: source.slice(name.from, name.to), from: name.from, to: end.to });
        if (!items.length) break;
        if (items.shift().name !== "," || (!items.length && !parenthesized)) return;
      }
      if (names.length) imports.push({ node, path, local, module, names, parenthesized });
      return;
    }
    for (let child = node.firstChild; child; child = child.nextSibling) visit(child);
  }
  visit(tree.topNode);
  return imports;
}

function lineEnd(source, position) {
  const offset = source.slice(position).search(/[\r\n]/);
  return offset < 0 ? source.length : position + offset;
}

/**
 * Maintain saved src/grugdb/*.py without replacing learner code. providedSource
 * is the original starter file. It allows a helper's noqa to share a physical
 * line with other supplied names, but never with a new learner import. Without
 * it, only lines importing exclusively the three known helpers are marked.
 */
export function normalizeSavedImports(source, providedSource = "") {
  const imports = importsIn(source);
  if (!imports) return source;
  const supplied = new Set();
  for (const statement of importsIn(providedSource) ?? []) {
    for (const item of statement.names) supplied.add(`${statement.module}.${item.name}`);
  }
  const edits = [];
  const marked = new Set();
  for (const statement of imports) {
    if (statement.local) {
      // `from . import X` needs no dot after the absolute package name.
      edits.push({ from: statement.path[0].from,
        to: statement.path.length === 1 ? statement.path[0].to : statement.path[0].from,
        text: "grugdb" });
    }
    // A comment on a semicolon-separated statement can suppress other imports.
    if (statement.node.parent?.name === "StatementGroup") continue;
    for (const item of statement.names) {
      if (!helpers.has(`${statement.module}.${item.name}`)) continue;
      const end = lineEnd(source, item.to);
      if (marked.has(end)) continue;
      // Backslash continuations have statement-wide noqa semantics; do not
      // annotate them. Parenthesized imports have per-name line semantics.
      if (!statement.parenthesized && /[\r\n]/.test(source.slice(statement.node.from, statement.node.to))) continue;
      const start = Math.max(source.lastIndexOf("\n", item.from - 1), source.lastIndexOf("\r", item.from - 1)) + 1;
      const sharing = statement.parenthesized && start > statement.node.from
        ? statement.names.filter((name) => name.from < end && name.to > start)
        : statement.names;
      if (sharing.some((name) => !helpers.has(`${statement.module}.${name.name}`)
          && !supplied.has(`${statement.module}.${name.name}`))) continue;
      // Do not insert a comment in a continued alias or before more code.
      const remainder = source.slice(item.to, end);
      if (/[\r\n]/.test(source.slice(item.from, item.to))
          || statement.names.some((name) => name.from < end && name.to > end)
          || /\\[\t ]*$/.test(remainder)) continue;
      const comment = source.slice(start, end).indexOf("#");
      const text = comment < 0 ? "" : source.slice(start + comment, end);
      const noqa = /#\s*noqa\b(?::[\t ]*([A-Z]\d+(?:[\t ]*,[\t ]*[A-Z]\d+)*))?/i.exec(text);
      if (noqa && (!noqa[1] || noqa[1].split(/\s*,\s*/).includes("F401"))) continue;
      if (noqa) {
        const at = start + comment + noqa.index + noqa[0].length;
        edits.push({ from: at, to: at, text: ", F401" });
        edits.push({ from: end, to: end, text: "  # supplied for exercises" });
      } else {
        edits.push({ from: end, to: end, text: "  # noqa: F401  # supplied for exercises" });
      }
      marked.add(end);
    }
  }
  // Applying right to left leaves all untouched source bytes in place.
  for (const edit of edits.sort((a, b) => b.from - a.from || b.to - a.to)) {
    source = source.slice(0, edit.from) + edit.text + source.slice(edit.to);
  }
  return source;
}
