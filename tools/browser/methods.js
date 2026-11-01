import { parser } from "@lezer/python";

const opaque = new Set(["String", "FormatString", "Comment"]);
const nameOf = (source, node) => {
  const name = node.getChild("VariableName");
  return name ? source.slice(name.from, name.to) : null;
};
const normalize = (text) => text.replace(/\r\n?|\n/g, "\n");
const width = (indent) => [...indent].reduce((column, char) => char === "\t" ? column + 8 - column % 8 : column + 1, 0);
const unindent = (text, indent) => normalize(text).split("\n")
  .map((line) => line.startsWith(indent) ? line.slice(indent.length) : line).join("\n");

function linesOf(source) {
  const lines = [];
  const breaks = /\r\n|\n|\r/g;
  let from = 0;
  for (let match; (match = breaks.exec(source));) {
    lines.push({ from, to: match.index, text: source.slice(from, match.index) });
    from = breaks.lastIndex;
  }
  lines.push({ from, to: source.length, text: source.slice(from) });
  for (const line of lines) line.indent = /^[\t ]*/.exec(line.text)[0];
  return lines;
}

function lineAt(lines, position) {
  let low = 0, high = lines.length;
  while (low + 1 < high) {
    const middle = (low + high) >> 1;
    if (lines[middle].from <= position) low = middle;
    else high = middle;
  }
  return low;
}

function hasError(node) {
  if (node.type.isError) return true;
  for (let child = node.firstChild; child; child = child.nextSibling) {
    if (hasError(child)) return true;
  }
  return false;
}

function inspect(source) {
  const nodes = [], tokens = [], protectedRanges = [], validSpans = [];
  function visit(node) {
    nodes.push(node);
    // Do not interpret keywords inside strings, comments, or f-string text.
    if (opaque.has(node.name)) {
      protectedRanges.push(node);
      return !hasError(node);
    }
    let valid = !node.type.isError;
    for (let child = node.firstChild; child; child = child.nextSibling) {
      if (!visit(child)) valid = false;
    }
    if (!node.firstChild) tokens.push(node);
    if (valid && node.to > node.from) validSpans.push(node);
    return valid;
  }
  visit(parser.parse(source).topNode);
  return { nodes, tokens, protectedRanges, validSpans };
}

/**
 * Find a direct class method, including its decorators. Offsets are UTF-16,
 * like CodeMirror. The range starts before class indentation and ends before
 * the last line's newline. Separating blank lines belong to the full file.
 * Ambiguous definitions or strings that hide the boundary return null.
 */
export function findMethod(source, className, methodName) {
  const lines = linesOf(source);
  const { nodes, tokens, protectedRanges, validSpans } = inspect(source);
  const classes = nodes.filter((node) => node.name === "ClassDefinition" && nameOf(source, node) === className);
  if (classes.length !== 1) return null;
  const owner = classes[0], body = owner.getChild("Body");
  if (!body) return null;
  const classLine = lineAt(lines, owner.from);
  let indent;
  for (let child = body.firstChild; child; child = child.nextSibling) {
    const row = lines[lineAt(lines, child.from)];
    if (row.from > lines[classLine].from && width(row.indent) > width(lines[classLine].indent) && child.name !== "Comment") {
      indent = row.indent;
      break;
    }
  }
  if (!indent) return null;

  const definitions = tokens.filter((node) => {
    if (node.name !== "def" || node.from <= body.from || node.from >= body.to) return false;
    const row = lines[lineAt(lines, node.from)];
    return row.indent === indent && /^(?:async[\t ]+)?def[\t ]/.test(row.text.slice(indent.length));
  });
  const matches = definitions.filter((node) => {
    const name = /^[\t ]+([\p{ID_Start}_][\p{ID_Continue}_]*)/u.exec(source.slice(node.to));
    return name?.[1] === methodName;
  });
  if (matches.length !== 1) return null;
  const keyword = matches[0];
  const definitionLine = lineAt(lines, keyword.from);
  const row = lines[definitionLine];
  const start = row.from + indent.length;
  // Parse the header separately too. Recovery in an earlier method can absorb
  // this def into an expression instead of producing a FunctionDefinition.
  const definition = parser.parse(source.slice(start, body.to)).topNode.getChild("FunctionDefinition");
  if (!definition) return null;
  const headerBody = definition.getChild("Body");
  const headerEnd = start + (headerBody?.from ?? definition.to);

  let firstLine = definitionLine;
  const previous = definitions.filter((node) => node.from < keyword.from).at(-1)?.from ?? body.from;
  for (const token of tokens) {
    if (!["At", "@"].includes(token.name) || token.from <= previous || token.from >= keyword.from) continue;
    const decoratorLine = lineAt(lines, token.from);
    const decoratorRow = lines[decoratorLine];
    if (decoratorRow.indent !== indent || decoratorRow.from + indent.length !== token.from) continue;
    const prefix = unindent(source.slice(decoratorRow.from, row.to), indent);
    const decorated = parser.parse(prefix).topNode.firstChild;
    const fn = decorated?.name === "DecoratedStatement" ? decorated.getChild("FunctionDefinition") : null;
    if (fn && nameOf(prefix, fn) === methodName && lineAt(linesOf(prefix), fn.from) === definitionLine - decoratorLine) {
      firstLine = decoratorLine;
      break;
    }
  }

  let lastLine = definitionLine;
  for (let index = definitionLine + 1; index < lines.length; index++) {
    const line = lines[index], content = line.from + line.indent.length;
    if (line.from >= body.to) break;
    if (!line.text.trim()) continue;
    const containing = protectedRanges.find((node) => node.name !== "Comment" && node.from < line.from && node.to > content);
    if (containing && hasError(containing)) return null;
    const inHeader = line.from <= headerEnd;
    const continuation = validSpans.some((node) => node.from < line.from && node.to > content
      && width(lines[lineAt(lines, node.from)].indent) > width(indent));
    const nextDefinition = tokens.some((node) => ["def", "class"].includes(node.name)
      && node.from >= content && node.from < line.to);
    // An incomplete parameter list may absorb the following decorator during
    // recovery. An @ at the start of a line cannot continue that header unless
    // it is part of a syntactically valid expression.
    const nextDecorator = tokens.some((node) => ["At", "@"].includes(node.name) && node.from === content)
      && !validSpans.some((node) => node.from >= start && node.from < line.from && node.to > content);
    if (!containing && width(line.indent) <= width(indent)
        && (nextDefinition || nextDecorator || (!inHeader && !continuation))) break;
    lastLine = index;
  }
  const from = lines[firstLine].from, to = lines[lastLine].to;
  return { from, to, length: to - from, indent, code: unindent(source.slice(from, to), indent), startLine: firstLine + 1 };
}

/**
 * Splice a previously located range without parsing the draft. Keep the returned
 * range for the next keystroke, even after a rename, deletion, or syntax error.
 * Other active ranges after this one must shift by new.length - old.length.
 */
export function applyMethodEdit(source, range, snippet) {
  if (!range || !Number.isInteger(range.from) || !Number.isInteger(range.to)
      || range.from < 0 || range.to < range.from || range.to > source.length
      || typeof range.indent !== "string" || typeof snippet !== "string"
      || unindent(source.slice(range.from, range.to), range.indent) !== range.code) {
    throw new Error("Invalid or stale method range. Keep the draft and reopen the full file.");
  }
  const code = normalize(snippet);
  const original = source.slice(range.from, range.to);
  const before = linesOf(original);
  const oldLines = range.code.split("\n"), newLines = code.split("\n");
  let prefix = 0, suffix = 0;
  while (prefix < oldLines.length && prefix < newLines.length && oldLines[prefix] === newLines[prefix]) prefix++;
  while (suffix < oldLines.length - prefix && suffix < newLines.length - prefix
      && oldLines.at(-1 - suffix) === newLines.at(-1 - suffix)) suffix++;
  const newline = /\r\n|\n|\r/.exec(source.slice(range.from, range.to))?.[0]
    ?? /\r\n|\n|\r/.exec(source)?.[0] ?? "\n";
  const text = newLines.map((line, index) => {
    // Preserve unchanged lines byte-for-byte, including whitespace-only lines
    // and string contents that originally had no class indentation.
    const oldIndex = index < prefix ? index
      : index >= newLines.length - suffix ? oldLines.length - newLines.length + index : -1;
    const value = oldIndex >= 0 ? before[oldIndex].text : line ? range.indent + line : "";
    const ending = oldIndex >= 0 && oldIndex + 1 < before.length
      ? original.slice(before[oldIndex].to, before[oldIndex + 1].from) : newline;
    return value + (index + 1 < newLines.length ? ending : "");
  }).join("");
  const to = range.from + text.length;
  return {
    source: source.slice(0, range.from) + text + source.slice(range.to),
    range: { from: range.from, to, length: text.length, indent: range.indent, code, startLine: lineAt(linesOf(source), range.from) + 1 },
  };
}

/** One-shot replacement. Target-loss errors carry the complete edited draft. */
export function replaceMethod(source, className, methodName, snippet) {
  const range = findMethod(source, className, methodName);
  if (!range) throw new Error(`Cannot locate ${className}.${methodName}. Keep the draft and use the full-file editor.`);
  const result = applyMethodEdit(source, range, snippet);
  const found = findMethod(result.source, className, methodName);
  if (!found || found.from < result.range.from || found.to > result.range.to) {
    const error = new Error(`Cannot locate ${className}.${methodName} after this edit. The complete edited file is available in error.source.`);
    error.code = "METHOD_TARGET_LOST";
    error.source = result.source;
    error.range = result.range;
    throw error;
  }
  return result;
}
