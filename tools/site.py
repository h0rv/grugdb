import argparse
import ast
import re
import shutil
import sys
import webbrowser
from collections.abc import Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass
from functools import partial
from hashlib import sha256
from html import escape
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from inspect import getdoc, getmro, getsource
from pathlib import Path
from textwrap import dedent
from typing import NewType
from urllib.parse import unquote, urlsplit

from fastpylight import guess, highlight_spans, theme_colors, theme_css
from markdown_it import MarkdownIt
from markdown_it.renderer import RendererHTML
from markdown_it.token import Token

from grugdb import (
    Column,
    Count,
    Database,
    Expr,
    Field,
    Query,
    Row,
    RowId,
    Sum,
    Table,
    Unique,
    column,
)

type APISymbol = type | Callable[..., object] | NewType

SITE_URL = "https://grugdb.horv.co"
REPO_URL = "https://github.com/h0rv/grugdb"
DESCRIPTION = (
    "Build a relational database in pure, typed Python: an iterator query engine, joins, "
    "indexes, a B+ tree, a planner, transactions, and a write-ahead log."
)
FAVICON = (
    "data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'>"
    "<text y='.9em' font-size='90'>🪨</text></svg>"
)


@dataclass(frozen=True, slots=True)
class Page:
    source: Path
    slug: str
    title: str
    markdown: str
    chapter: bool = False

    @classmethod
    def read(cls, source: Path, slug: str, *, chapter: bool = False) -> Page:
        markdown = source.read_text(encoding="utf-8")
        if markdown.startswith("---\n"):
            _, separator, markdown = markdown[4:].partition("\n---\n")
            if not separator:
                raise ValueError(f"Unclosed frontmatter in {source}")
        heading = re.search(r"^# (.+)$", markdown, re.MULTILINE)
        if heading is None:
            raise ValueError(f"Missing title in {source}")
        return cls(source.resolve(), slug, heading[1], markdown, chapter)

    @property
    def filename(self) -> str:
        return f"{self.slug}.html"

    @property
    def summary(self) -> str:
        """The first paragraph of prose, as plain text, for link previews."""
        for block in re.split(r"\n\s*\n", self.markdown):
            text = block.strip()
            if text and not text.startswith(("#", "```", "-", "|", ">", "<")):
                text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
                return re.sub(r"\s+", " ", text.replace("`", "")).strip()
        return DESCRIPTION


@dataclass(frozen=True, slots=True)
class Term:
    name: str
    summary: str
    example: str
    href: str
    documentation: str
    source: str

    def link(self, label: str) -> str:
        title = f"{self.summary}\n\n{self.example}"
        return (
            f'<a class="api-term" href="{escape(self.href)}" title="{escape(title)}"'
            f' data-term="{escape(self.name)}" data-summary="{escape(self.summary)}">'
            f"{escape(label)}</a>"
        )


def source_snippet(definition: APISymbol) -> str:
    """Return source with docstrings omitted."""
    if isinstance(definition, NewType):
        module_source = getsource(sys.modules[definition.__module__])
        for node in ast.parse(module_source).body:
            if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == definition.__name__
                for target in node.targets
            ):
                return "\n".join(module_source.splitlines()[node.lineno - 1 : node.end_lineno])
        raise ValueError(f"Missing type declaration: {definition.__name__}")
    source = dedent(getsource(definition))
    lines = source.splitlines()
    omitted: set[int] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            first = node.body[0]
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
                and first.end_lineno is not None
            ):
                omitted.update(range(first.lineno - 1, first.end_lineno))
                if first.end_lineno < len(lines) and not lines[first.end_lineno].strip():
                    omitted.add(first.end_lineno)
    return "\n".join(line for index, line in enumerate(lines) if index not in omitted).strip()


def api_reference(root: Path) -> Page:
    definitions: tuple[tuple[str, APISymbol | property], ...] = (
        ("Row", Row),
        ("RowId", RowId),
        ("Column", Column),
        ("column", column),
        ("Unique", Unique),
        ("Field", Field),
        ("Expr", Expr),
        ("Table", Table),
        ("Database", Database),
        ("Query", Query),
        ("Count", Count),
        ("Sum", Sum),
        ("lookup", Table.lookup),
        ("scan", Table.scan),
    )
    sections = [
        "# API reference",
        "Examples use imports from `grugdb` and the row classes shown below.",
    ]
    for name, definition in definitions:
        if isinstance(definition, property):
            getter = definition.fget
            if getter is None:
                raise ValueError(f"Missing API getter: {name}")
            definition = getter
        documentation = getdoc(definition)
        if not documentation:
            raise ValueError(f"Missing API docstring: {name}")
        implementations = [definition]
        if isinstance(definition, type):
            implementations.extend(
                base for base in getmro(definition)[1:] if base.__module__.startswith("grugdb.")
            )
        source = "\n\n".join(source_snippet(implementation) for implementation in implementations)
        sections.append(f"## {name}\n\n{documentation}\n\n### Source\n\n```python\n{source}\n```")
    return Page(root / "REFERENCE.md", "reference", "API reference", "\n\n".join(sections) + "\n")


def reference_terms(page: Page) -> dict[str, Term]:
    tokens = MarkdownIt("commonmark", {"html": False}).parse(page.markdown)
    terms: dict[str, Term] = {}
    counts: dict[str, int] = {}
    name = summary = example = href = source = ""
    lines = page.markdown.splitlines()
    documentation_start = documentation_end = 0
    in_source = False

    def finish(end: int) -> None:
        if name and summary and example:
            documentation = "\n".join(lines[documentation_start : documentation_end or end]).strip()
            terms[name] = Term(name, summary, example, href, documentation, source)

    for index, token in enumerate(tokens):
        if token.type == "heading_open":
            slug = (
                re.sub(r"[^a-z0-9]+", "-", tokens[index + 1].content.lower()).strip("-")
                or "section"
            )
            counts[slug] = counts.get(slug, 0) + 1
            if token.tag == "h2" and token.map is not None:
                finish(token.map[0])
                name, summary, example, source = tokens[index + 1].content, "", "", ""
                documentation_start, documentation_end = token.map[1], 0
                in_source = False
                suffix = f"-{counts[slug]}" if counts[slug] > 1 else ""
                href = f"{page.filename}#{page.slug}-{slug}{suffix}"
            elif token.tag == "h3" and tokens[index + 1].content == "Source":
                if token.map is not None:
                    documentation_end = token.map[0]
                in_source = True
        elif name and not summary and token.type == "paragraph_open":
            children = tokens[index + 1].children or []
            summary = "".join(
                " " if child.type in ("softbreak", "hardbreak") else child.content
                for child in children
                if child.type in ("text", "code_inline", "softbreak", "hardbreak")
            )
        elif name and token.type == "fence":
            if in_source:
                source = token.content.rstrip("\n")
            elif not example:
                example = token.content.rstrip("\n")
    finish(len(lines))
    return terms


def annotate_names(rendered: str, terms: dict[str, Term]) -> str:
    # Link identifier scopes, never strings, comments, or arbitrary HTML.
    pattern = (
        r'<span class="(hl-(?:constructor|type(?:-[a-z]+)*|function(?:-[a-z]+)*|'
        r'variable(?:-[a-z]+)*|property))">([A-Za-z_]\w*)</span>'
    )

    def replace(match: re.Match[str]) -> str:
        name = match[2]
        term = terms.get(name)
        if term is None or name == "row":
            return match[0]
        before = re.sub(r"<[^>]+>", "", rendered[: match.start()]).rstrip()
        after = re.sub(r"<[^>]+>", "", rendered[match.end() :]).lstrip()
        importing = re.search(r"\bfrom grugdb(?:\.\w+)* import\s*(?:[^()\n]*|\([^)]*)$", before)
        if (
            name in ("column", "scan")
            and not importing
            and (not after.startswith("(") or re.search(r"\bdef$", before))
        ):
            return match[0]
        if name in ("lookup", "scan") and not before.endswith("."):
            return match[0]
        return f'<span class="{match[1]}">{term.link(name)}</span>'

    return re.sub(pattern, replace, rendered)


def highlight_block(code: str, language: str, attributes: str) -> str:
    language = (  # ty: ignore[unsound-assignment]
        "python"
        if language.lower() in ("py", "pycon", "python")
        else guess("", language or "plaintext")
    )
    return highlight_spans(code, language).replace("<pre>", '<pre class="highlight">', 1)  # ty: ignore[unsound-return-statement]


def site_theme() -> str:
    def theme(mode: str, selector: str) -> str:
        name = f"gruvbox_material_{mode}"
        colors = theme_colors(name)
        values = {
            "paper": colors["normal"]["bg"],
            "ink": colors["normal"]["fg"],
            "surface": colors["highlighted"]["bg"],
            "code": colors["highlighted"]["bg"],
            "accent": colors["function"]["fg"],
            "muted": colors["comment"]["fg"],
        }
        variables = (
            f"color-scheme: {mode}; --line: color-mix(in srgb, var(--ink) 20%, var(--paper));"
        )
        for key, value in values.items():
            if value is None:
                raise ValueError(f"Missing {key} color in {name}")
            variables += f" --{key}: {value};"
        return f"{selector} {{ {variables} }}\n" + theme_css(name, f"{selector} code")  # ty: ignore[unsound-return-statement]

    return (
        theme("light", ":root")
        + "\n@media (prefers-color-scheme: dark) {\n"
        + theme("dark", ':root:not([data-theme="light"])')
        + "\n}\n"
        + theme("dark", ':root[data-theme="dark"]')
    )


def test_reference(path: Path, root: Path) -> tuple[Page, dict[str, str]]:
    source = path.read_text(encoding="utf-8")
    relative = path.relative_to(root).as_posix()
    sections = [f"# Tests in {relative}"]
    descriptions: dict[str, str] = {}
    for case in ast.parse(source).body:
        if isinstance(case, ast.ClassDef):
            for method in case.body:
                if isinstance(
                    method, (ast.FunctionDef, ast.AsyncFunctionDef)
                ) and method.name.startswith("test_"):
                    name = f"{case.name}.{method.name}"
                    description = ast.get_docstring(method) or name
                    descriptions[name] = " ".join(description.split("\n\n")[0].split())
                    code = "\n".join(source.splitlines()[method.lineno - 1 : method.end_lineno])
                    command = f"uv run python -m unittest {relative[:-3].replace('/', '.')}.{name}"
                    sections.append(
                        f"## {name}\n\n{description}\n\n```sh\n{command}\n```\n\n"
                        f"```python\n{dedent(code)}\n```"
                    )
    return Page(
        path.resolve(), path.stem.replace("_", "-"), f"Tests in {relative}", "\n\n".join(sections)
    ), descriptions


# Navigation headings, keyed by the chapter number where each part begins.
PARTS = {
    1: "Part 1 · A query engine",
    5: "Part 2 · Make it fast",
    9: "Part 3 · Make it safe",
    13: "Appendix",
}


class Site:
    def __init__(self, root: Path, output: Path) -> None:
        self.root = root.resolve()
        self.output = output
        introduction = self.root / "chapters/00-intro.md"
        self.pages = (
            [Page.read(introduction, "index"), Page.read(self.root / "README.md", "project")]
            if introduction.exists()
            else [Page.read(self.root / "README.md", "index")]
        )
        self.pages.extend(
            Page.read(path, path.stem, chapter=True)
            for path in sorted((self.root / "chapters").glob("*.md"))
            if path != introduction
        )
        reference = api_reference(self.root)
        self.pages.append(reference)
        for relative, slug in (
            (".agents/skills/tutor/SKILL.md", "tutor"),
            (".agents/skills/tutor/references/teaching.md", "teaching"),
        ):
            source = self.root / relative
            if source.exists():
                self.pages.append(Page.read(source, slug))
        self.test_descriptions: dict[tuple[Path, str], str] = {}
        for path in sorted((self.root / "tests").glob("test_*.py")):
            if path.name in {"test_course.py", "test_site.py"}:
                continue
            test_page, descriptions = test_reference(path, self.root)
            self.pages.append(test_page)
            self.test_descriptions.update(
                ((test_page.source, name), description)
                for name, description in descriptions.items()
            )
        self.by_source = {page.source: page for page in self.pages}
        self.terms = reference_terms(reference)
        self.renderer = RendererHTML()
        self.markdown = MarkdownIt(
            "commonmark",
            {"html": False, "highlight": self.highlight},
            renderer_cls=lambda _: self.renderer,
        )
        self.markdown.enable("table")

    def highlight(self, code: str, language: str, attributes: str) -> str:
        rendered = highlight_block(code, language, attributes)
        if language.lower() in ("python", "py", "pycon"):
            return annotate_names(rendered, self.terms)
        return rendered

    @property
    def chapters(self) -> list[Page]:
        return [page for page in self.pages if page.chapter]

    @property
    def course(self) -> list[Page]:
        introduction = self.by_source.get(self.root / "chapters/00-intro.md")
        return [introduction, *self.chapters] if introduction else self.chapters

    def link(self, href: str, source: Page) -> str:
        url = urlsplit(href)
        if url.scheme or url.netloc:
            return href
        destination = (
            (source.source.parent / unquote(url.path)).resolve() if url.path else source.source
        )
        target = self.by_source.get(destination)
        if target is None:
            raise ValueError(f"Unknown local link in {source.source}: {href}")
        fragment = unquote(url.fragment)
        if destination.suffix == ".py" and fragment:
            if (destination, fragment) not in self.test_descriptions:
                raise ValueError(f"Unknown test in {source.source}: {href}")
            fragment = re.sub(r"[^a-z0-9]+", "-", fragment.lower()).strip("-")
        anchor = f"{target.slug}-{fragment}" if fragment else target.slug
        fragment = f"#{anchor}" if url.fragment else ""
        query = f"?{url.query}" if url.query else ""
        return f"{target.filename}{query}{fragment}"

    def prepare(self, tokens: Sequence[Token], page: Page, *, linked: bool = False) -> None:
        for index, token in enumerate(tokens):
            if token.type == "link_open":
                linked = True
                href = token.attrGet("href")
                if href is not None:
                    if not isinstance(href, str):
                        raise ValueError("Link href must be text")
                    url = urlsplit(href)
                    if not url.scheme and not url.netloc:
                        destination = (page.source.parent / unquote(url.path)).resolve()
                        description = self.test_descriptions.get(
                            (destination, unquote(url.fragment))
                        )
                        if description and index + 1 < len(tokens):
                            tokens[index + 1].type = "text"
                            tokens[index + 1].content = description
                    token.attrSet("href", self.link(href, page))
            elif token.type == "link_close":
                linked = False
            elif token.type == "inline" and token.children:
                marker = re.match(r"^\[([ xX])\] ", token.content)
                if marker and token.children[0].type == "text":
                    task = " ".join(token.content[marker.end() :].split())
                    key = f"{page.slug}--{sha256(task.encode()).hexdigest()[:16]}"
                    checked = " checked" if marker[1].lower() == "x" else ""
                    token.children[0].content = token.children[0].content[marker.end() :]
                    opening = Token("html_inline", "", 0)
                    opening.content = (
                        f'<label class="task-item"><input type="checkbox"'
                        f' data-task="{escape(key)}"{checked}><span>'
                    )
                    closing = Token("html_inline", "", 0)
                    closing.content = "</span></label>"
                    token.children.insert(0, opening)
                    token.children.append(closing)
            elif token.type == "code_inline":
                path = token.content.partition("::")[0]
                is_path = bool(
                    re.fullmatch(
                        r"(?:[~./\w-]+/)?[\w.-]+\.(?:py|pyi|md|toml|json|yaml|yml|txt|html|css|js|lock)",
                        path,
                    )
                    or re.fullmatch(r"(?:\.{1,2}/|~/|/)[\w./-]+", path)
                    or re.fullmatch(
                        r"(?:src|tests|tools|chapters|bench|\.agents)(?:/[\w.-]+)+/?",
                        path,
                    )
                )
                code = (
                    highlight_spans(token.content, "plaintext" if is_path else "python")
                    .removeprefix("<pre><code>")
                    .removesuffix("</code></pre>")
                    .rstrip("\n")
                )
                if not linked and not is_path:
                    code = annotate_names(code, self.terms)
                token.type = "html_inline"
                token.content = f'<code class="inline-code">{code}</code>'
                if is_path and not linked and (href := self.github_link(path)):
                    token.content = f'<a class="file-link" href="{href}">{token.content}</a>'
            if token.children:
                self.prepare(token.children, page, linked=linked)

    def github_link(self, path: str) -> str | None:
        """Link a repository path to GitHub, if that file or folder exists."""
        target = (self.root / path.rstrip("/")).resolve()
        if not path or path.startswith(("/", "~", "..")) or not target.exists():
            return None
        if not target.is_relative_to(self.root):
            return None
        kind = "tree" if target.is_dir() else "blob"
        return f"{REPO_URL}/{kind}/main/{target.relative_to(self.root).as_posix()}"

    def render(self, page: Page) -> str:
        tokens = self.markdown.parse(page.markdown)
        self.prepare(tokens, page)
        counts: dict[str, int] = {}
        for index, token in enumerate(tokens):
            if token.type == "heading_open":
                text = tokens[index + 1].content
                slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "section"
                counts[slug] = counts.get(slug, 0) + 1
                suffix = f"-{counts[slug]}" if counts[slug] > 1 else ""
                anchor = page.slug if token.tag == "h1" else f"{page.slug}-{slug}{suffix}"
                token.attrSet("id", anchor)
        return self.renderer.render(tokens, self.markdown.options, {})

    def navigation(self, current: str) -> str:
        links = []
        introduction = self.by_source.get(self.root / "chapters/00-intro.md")
        if introduction:
            href = introduction.filename
            active = ' aria-current="page"' if current == "index" else ""
            links.append(f'<a href="{href}"{active}>Introduction</a>')
        for number, page in enumerate(self.chapters, start=1):
            if number in PARTS:
                links.append(f'<span class="nav-group">{escape(PARTS[number])}</span>')
            active = ' aria-current="page"' if current == page.slug else ""
            title = re.sub(r"^\d+\.\s*", "", page.title)
            href = page.filename
            links.append(
                f'<a href="{href}"{active}><span class="number">{number:02}</span>'
                f"<span>{escape(title)}</span></a>"
            )
        reference = self.by_source.get(self.root / "REFERENCE.md")
        reference_link = (
            '<a class="side-link" href="reference.html">API reference</a>' if reference else ""
        )
        return (
            '<a class="brand" href="index.html">grugdb<span>A database in Python</span></a>'
            '<details class="contents" open><summary>Chapters</summary><nav aria-label="Chapters">'
            + "".join(links)
            + "</nav></details>"
            + reference_link
            + f'<a class="side-link" href="{REPO_URL}">Source on GitHub</a>'
            + '<button id="theme" type="button" hidden>Theme</button>'
        )

    def page_links(self, page: Page) -> str:
        course = self.course
        if page not in course:
            return ""
        index = course.index(page)
        links = ""
        if index or page.chapter:
            previous = course[index - 1] if index else self.pages[0]
            links = (
                f'<a href="{previous.filename}">Previous<span>{escape(previous.title)}</span></a>'
            )
        if index + 1 < len(course):
            following = course[index + 1]
            links += (
                f'<a href="{following.filename}">Next<span>{escape(following.title)}</span></a>'
            )
        return f'<footer class="page-links">{links}</footer>'

    def edit_link(self, page: Page) -> str:
        if not page.source.exists() or not page.source.is_relative_to(self.root):
            return ""
        href = f"{REPO_URL}/blob/main/{page.source.relative_to(self.root).as_posix()}"
        return f'<p class="edit-link"><a href="{href}">Edit this page on GitHub</a></p>'

    def document(
        self,
        title: str,
        body: str,
        current: str,
        footer: str = "",
        *,
        description: str = DESCRIPTION,
        filename: str = "index.html",
        base: str = "",
    ) -> str:
        previews = []
        docs = MarkdownIt("commonmark", {"html": False, "highlight": highlight_block})
        for name, term in self.terms.items():
            if name == term.name:
                source = highlight_block(term.source, "python", "")
                documentation = docs.render(term.documentation)
                previews.append(
                    f'<template id="api-preview-{escape(name)}">'
                    f'<section data-view="source">{source}</section>'
                    f'<section data-view="docs">{documentation}</section></template>'
                )
        canonical = f"{SITE_URL}/" if filename == "index.html" else f"{SITE_URL}/{filename}"
        return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>{escape(title)} · grugdb</title>
{base}<meta name="description" content="{escape(description)}">
<link rel="canonical" href="{canonical}">
<meta property="og:type" content="article">
<meta property="og:site_name" content="grugdb">
<meta property="og:title" content="{escape(title)} · grugdb">
<meta property="og:description" content="{escape(description)}">
<meta property="og:url" content="{canonical}">
<meta name="twitter:card" content="summary">
<link rel="icon" href="{escape(FAVICON)}">
<link rel="stylesheet" href="style.css">
<script src="theme.js"></script>
</head>
<body>
<a class="skip-link" href="#content">Skip to content</a>
{"".join(previews)}
<div class="shell">
<aside>{self.navigation(current)}</aside>
<div class="reading">
<main id="content" class="prose">{body}</main>{footer}
</div>
</div>
</body>
</html>
"""

    def build(self) -> None:
        self.output.mkdir(parents=True, exist_ok=True)
        for page in self.pages:
            document = self.document(
                page.title,
                self.render(page) + self.edit_link(page),
                page.slug,
                self.page_links(page),
                description=page.summary,
                filename=page.filename,
            )
            (self.output / page.filename).write_text(document, encoding="utf-8")
        missing = self.document(
            "Page not found",
            "<h1>Page not found</h1><p>That page does not exist. "
            'Start from the <a href="index.html">introduction</a>.</p>',
            "404",
            filename="404.html",
            base='<base href="/">\n',
        )
        (self.output / "404.html").write_text(missing, encoding="utf-8")
        assets = Path(__file__).with_name("site")
        (self.output / "style.css").write_text(
            site_theme() + "\n" + (assets / "style.css").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        shutil.copyfile(assets / "theme.js", self.output / "theme.js")
        expected = {page.filename for page in self.pages} | {"404.html"}
        for old_page in self.output.glob("*.html"):
            if old_page.name not in expected:
                old_page.unlink()


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the grugdb course website.")
    parser.add_argument("--serve", action="store_true", help="serve locally after building")
    parser.add_argument("--open", action="store_true", help="open the browser with --serve")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    if args.open and not args.serve:
        parser.error("--open requires --serve")
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    root = Path(__file__).resolve().parents[1]
    site = Site(root, root / "site")
    site.build()
    print(f"Built {(site.output / 'index.html').as_uri()}")
    if args.serve:
        handler = partial(SimpleHTTPRequestHandler, directory=str(site.output))
        with ThreadingHTTPServer(("127.0.0.1", args.port), handler) as server:
            url = f"http://127.0.0.1:{args.port}"
            print(
                f"Open {url}. Rebuild after editing course files. Ctrl+C stops the server.",
                flush=True,
            )
            if args.open:
                webbrowser.open(url)
            with suppress(KeyboardInterrupt):
                server.serve_forever()


if __name__ == "__main__":
    main()
